"""Replay historico de prompts (T2.1).

Re-ejecuta un prompt CANDIDATE sobre decisiones historicas y compara contra los
outcomes reales ya madurados: ¿el prompt nuevo habria comprado mas ganadoras y
menos perdedoras? Devuelve expectancy simulada, numero de cambios de decision y
violaciones de formato (deben ser 0). El "decider" es inyectable para tests.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


# decider(template, signal) -> {"action": "buy"|"hold"|..., "valid": bool}
Decider = Callable[[str, dict[str, Any]], dict[str, Any]]


def _is_matured(signal: dict[str, Any]) -> bool:
    verdict = str((signal.get("outcome") or {}).get("verdict", "") or "")
    return verdict not in {"", "pending"}


def _return_pct(signal: dict[str, Any]) -> float | None:
    value = (signal.get("outcome") or {}).get("return_pct")
    return float(value) if isinstance(value, (int, float)) else None


def _recorded_action(signal: dict[str, Any]) -> str:
    return str(signal.get("decision") or "").lower()


def replay_decisions(
    store: Store,
    settings: Settings,
    prompt_key: str,
    candidate_version: int,
    *,
    sessions: int = 10,
    decider: Decider | None = None,
) -> dict[str, Any]:
    """Re-ejecuta el prompt candidato sobre el historico y mide su efecto."""

    candidate = next(
        (
            row
            for row in store.prompt_versions(prompt_key=prompt_key, limit=500)
            if int(row["version"]) == int(candidate_version)
        ),
        None,
    )
    if candidate is None:
        return {"ok": False, "error": f"version {candidate_version} no encontrada para {prompt_key}"}
    template = str(candidate.get("template") or "")

    rows = [item for item in store.signal_outcomes(limit=5000) if _is_matured(item)]
    distinct_dates = sorted({item["signal_date"] for item in rows}, reverse=True)[:sessions]
    sample = [item for item in rows if item["signal_date"] in set(distinct_dates)]

    if decider is None:
        decider = _default_decider(settings)

    buy_returns: list[float] = []
    decision_changes = 0
    format_violations = 0
    evaluated = 0
    for signal in sample:
        try:
            decision = decider(template, signal)
        except Exception:  # noqa: BLE001 - una decision rota cuenta como violacion.
            format_violations += 1
            continue
        if not isinstance(decision, dict) or not decision.get("valid", True):
            format_violations += 1
            continue
        evaluated += 1
        action = str(decision.get("action") or "").lower()
        if action != _recorded_action(signal):
            decision_changes += 1
        if action == "buy":
            ret = _return_pct(signal)
            if ret is not None:
                buy_returns.append(ret)

    expectancy_sim = round(statistics.fmean(buy_returns), 6) if buy_returns else None
    return {
        "ok": True,
        "prompt_key": prompt_key,
        "candidate_version": candidate_version,
        "sessions": len(distinct_dates),
        "decisions_evaluated": evaluated,
        "expectancy_sim": expectancy_sim,
        "buys": len(buy_returns),
        "decision_changes": decision_changes,
        "format_violations": format_violations,
    }


def evaluate_prompt_promotion(
    candidate_metrics: dict[str, Any],
    active_expectancy: float | None,
    *,
    min_decisions: int = 30,
) -> dict[str, Any]:
    """Criterio: expectancy candidato >= ACTIVE y 0 violaciones en >= min_decisions."""

    expectancy = candidate_metrics.get("expectancy_sim")
    violations = int(candidate_metrics.get("format_violations") or 0)
    decisions = int(candidate_metrics.get("decisions_evaluated") or 0)
    reasons: list[str] = []
    if decisions < min_decisions:
        reasons.append(f"decisiones insuficientes ({decisions}<{min_decisions})")
    if violations > 0:
        reasons.append(f"{violations} violaciones de formato")
    if expectancy is None:
        reasons.append("sin expectancy simulada")
    elif active_expectancy is not None and expectancy < active_expectancy:
        reasons.append("expectancy < ACTIVE")
    promote = not reasons
    return {"promote": promote, "reasons": reasons, "expectancy_sim": expectancy}


def _default_decider(settings: Settings) -> Decider:
    """Decider real: usa el LLM (rol decision) con el template candidato.

    Por defecto es conservador: si no hay LLM disponible, marca la decision como
    invalida (cuenta como violacion) en vez de inventar resultados.
    """

    def decider(template: str, signal: dict[str, Any]) -> dict[str, Any]:
        try:
            import json

            from ..llm_router import chat_for_role

            messages = [
                {"role": "system", "content": template},
                {"role": "user", "content": json.dumps({"signal": signal.get("features", {})}, ensure_ascii=True)},
            ]
            response, _endpoint, _attempts = chat_for_role("decision", settings=settings, messages=messages)
            content = response.choices[0].message.content or "{}"
            data = json.loads(content[content.find("{") : content.rfind("}") + 1])
            return {"action": str(data.get("action") or "hold"), "valid": True}
        except Exception:  # noqa: BLE001
            return {"action": "hold", "valid": False}

    return decider
