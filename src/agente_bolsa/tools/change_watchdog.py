"""Watchdog de cambios aplicados: rollback automatico por metricas (T0.5).

Todo cambio promovido (APPLIED por T0.3) queda en observacion. Tras cada sesion,
se compara la ventana de `performance_daily` (T0.2) posterior al cambio contra la
ventana equivalente previa. Si el `iq_score` cae demasiado, o el hit rate se
desploma con suficiente actividad, el cambio se marca `ROLLBACK_REQUESTED` y se
revierte con la maquinaria de T0.3 (`git revert` + suite), sin intervencion
humana.

El nucleo de calculo usa solo libreria estandar para ser barato y testeable.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

from ..continuous_improvement.proposal_contract import validate_origin
from ..logging_utils import log_system_event

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


def _mean(values: list[float]) -> float | None:
    clean = [value for value in values if isinstance(value, (int, float))]
    return statistics.fmean(clean) if clean else None


def _change_session_date(change: dict[str, Any]) -> str:
    return str(change.get("created_at") or "")[:10]


def _dominant_regime(rows: list[dict[str, Any]]) -> str | None:
    """Regimen de mercado mayoritario de una ventana (T5.2), o None si no consta."""

    counts: dict[str, int] = {}
    for row in rows:
        payload = row.get("payload") or {}
        regime = payload.get("regime") or (payload.get("market_state") or {}).get("market_regime")
        if regime:
            counts[str(regime)] = counts.get(str(regime), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _trades_in_window(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        payload = row.get("payload") or {}
        for key in ("buys", "sells"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                total += int(value)
    return total


def origin_attribution(change: dict[str, Any]) -> dict[str, Any]:
    """Expose contract origin without ever assigning authorship to the watchdog."""
    contract = ((change.get("decision") or {}).get("experiment_contract") or {})
    origin = contract.get("origin")
    if not origin:
        return {"attribution_status": "legacy_unattributed" if change.get("proposal_id") else "unavailable"}
    check = validate_origin(origin, change_class=str(contract.get("change_class") or ""))
    if not check["valid"]:
        return {"attribution_status": "invalid_origin"}
    return {
        "attribution_status": "attributed",
        "origin": check["origin"],
        "hypothesis_id": contract.get("hypothesis_id"),
        "evaluated_by": "change_watchdog",
    }


def evaluate_applied_changes(store: Store, settings: Settings) -> list[dict[str, Any]]:
    """Evalua los cambios APPLIED recientes y marca los daninos como ROLLBACK_REQUESTED.

    Devuelve una lista de decisiones (incluye los que esperan y los que se
    mantienen) para trazabilidad y tests.
    """

    window = int(getattr(settings, "change_watchdog_window_sessions", 5))
    max_iq_drop = float(getattr(settings, "change_watchdog_max_iq_drop", 10.0))
    max_hit_drop = float(getattr(settings, "change_watchdog_max_hit_rate_drop", 0.15))
    min_trades = int(getattr(settings, "change_watchdog_min_trades", 5))

    rows = store.performance_daily(limit=0)
    rows = sorted(rows, key=lambda item: item["session_date"])
    changes = store.continuous_improvement_applied_changes(statuses=["APPLIED"], limit=500)
    decisions: list[dict[str, Any]] = []

    for change in changes:
        if change.get("change_type") != "CODE_CHANGE":
            continue
        change_date = _change_session_date(change)
        decision = change.get("decision") or {}
        contract = decision.get("experiment_contract") or {}
        change_class = str(contract.get("change_class") or "trading").lower()
        if change_class == "docs":
            change["decision"] = {
                **decision,
                "impact_validation": {"status": "NON_QUALIFYING", "reason": "docs_change"},
            }
            store.save_continuous_improvement_applied_change(change)
            decisions.append(
                {
                    "applied_change_id": change.get("applied_change_id"),
                    "change_date": change_date,
                    "post_sessions": 0,
                    "verdict": "NON_QUALIFYING",
                    "change_class": change_class,
                    "attribution": origin_attribution(change),
                }
            )
            continue
        if change_class in {"reliability", "observability"}:
            decisions.append(_evaluate_operational_change(store, change, contract, change_class))
            continue
        post = [row for row in rows if row["session_date"] > change_date]
        prior = [row for row in rows if row["session_date"] <= change_date]

        antiquity = len(post)
        base = {
            "applied_change_id": change.get("applied_change_id"),
            "change_date": change_date,
            "post_sessions": antiquity,
        }

        # Aun fuera de la ventana de observacion: el cambio ya "gradua".
        if antiquity > window:
            decisions.append({**base, "verdict": "GRADUATED", "change_class": change_class, "attribution": origin_attribution(change)})
            continue
        # Datos insuficientes para juzgar: esperar.
        prior_window = prior[-antiquity:] if antiquity else []
        if antiquity < 2 or len(prior_window) < 2:
            decisions.append({**base, "verdict": "WAIT", "attribution": origin_attribution(change)})
            continue

        # No comparar ventanas de regimenes distintos (T5.2): extender en su lugar.
        regime_post = _dominant_regime(post)
        regime_prior = _dominant_regime(prior_window)
        if regime_post and regime_prior and regime_post != regime_prior:
            decisions.append({**base, "verdict": "WAIT", "reason": f"regime_mismatch:{regime_prior}->{regime_post}", "attribution": origin_attribution(change)})
            continue

        iq_post = _mean([row.get("iq_score") for row in post])
        iq_prior = _mean([row.get("iq_score") for row in prior_window])
        hit_post = _mean([row.get("hit_rate_20") for row in post])
        hit_prior = _mean([row.get("hit_rate_20") for row in prior_window])
        trades_post = _trades_in_window(post)

        iq_drop = (iq_prior - iq_post) if (iq_prior is not None and iq_post is not None) else None
        hit_drop = (hit_prior - hit_post) if (hit_prior is not None and hit_post is not None) else None

        iq_breach = iq_drop is not None and iq_drop > max_iq_drop
        hit_breach = hit_drop is not None and hit_drop > max_hit_drop and trades_post >= min_trades

        metrics = {
            "iq_prior": iq_prior,
            "iq_post": iq_post,
            "iq_drop": iq_drop,
            "hit_prior": hit_prior,
            "hit_post": hit_post,
            "hit_drop": hit_drop,
            "trades_post": trades_post,
            "max_iq_drop": max_iq_drop,
            "max_hit_rate_drop": max_hit_drop,
        }

        if iq_breach or hit_breach:
            reasons = []
            if iq_breach:
                reasons.append(f"iq_drop={iq_drop:.2f}>{max_iq_drop}")
            if hit_breach:
                reasons.append(f"hit_drop={hit_drop:.3f}>{max_hit_drop} con {trades_post} trades")
            change["status"] = "ROLLBACK_REQUESTED"
            change["decision"] = {
                **(change.get("decision") or {}),
                "watchdog": {"metrics": metrics, "reasons": reasons},
            }
            store.save_continuous_improvement_applied_change(change)
            decisions.append({**base, "verdict": "ROLLBACK_REQUESTED", "metrics": metrics, "reasons": reasons, "attribution": origin_attribution(change)})
        else:
            # HOLD: registrar si la ventana post mejoro, para la calidad de
            # promociones corregida del iq_score (T5.3).
            improved = bool(iq_drop is not None and iq_drop < 0)
            change["decision"] = {
                **(change.get("decision") or {}),
                "watchdog": {"metrics": metrics, "improved": improved},
                "impact_validation": {
                    "status": "PASSED" if improved and trades_post >= min_trades else "PENDING",
                    "metric_name": "iq_score",
                    "sample": trades_post,
                    "post": iq_post,
                    "baseline": iq_prior,
                },
            }
            store.save_continuous_improvement_applied_change(change)
            decisions.append({**base, "verdict": "HOLD", "metrics": metrics, "improved": improved, "attribution": origin_attribution(change)})

    return decisions


def _evaluate_operational_change(
    store: Store,
    change: dict[str, Any],
    contract: dict[str, Any],
    change_class: str,
) -> dict[str, Any]:
    """Evaluate non-trading classes only against their declared metric."""

    decision = change.get("decision") or {}
    metrics = decision.get("post_apply_metrics") or {}
    metric_name = str(contract.get("metric_name") or "")
    observed = metrics.get(metric_name) if isinstance(metrics, dict) else None
    baseline = contract.get("baseline")
    target = contract.get("target")
    sample = metrics.get("sample", 0) if isinstance(metrics, dict) else 0
    min_sample = int(contract.get("min_sample") or 1)
    passed = False
    if all(isinstance(value, (int, float)) for value in (observed, baseline, target)) and int(sample or 0) >= min_sample:
        passed = observed >= target if target >= baseline else observed <= target
    status = "PASSED" if passed else "PENDING"
    impact = {
        "status": status,
        "change_class": change_class,
        "metric_name": metric_name,
        "baseline": baseline,
        "target": target,
        "observed": observed,
        "sample": sample,
        "min_sample": min_sample,
    }
    change["decision"] = {**decision, "impact_validation": impact}
    store.save_continuous_improvement_applied_change(change)
    return {
        "applied_change_id": change.get("applied_change_id"),
        "change_date": _change_session_date(change),
        "post_sessions": 0,
        "verdict": "IMPACT_CONFIRMED" if passed else "WAIT",
        "change_class": change_class,
        "metrics": impact,
        "attribution": origin_attribution(change),
    }


def execute_rollbacks(store: Store, settings: Settings) -> list[dict[str, Any]]:
    """Revierte los cambios marcados ROLLBACK_REQUESTED (mas reciente primero)."""

    from ..continuous_improvement.experiments import AutoApplyCodeAgent

    requested = store.continuous_improvement_applied_changes(statuses=["ROLLBACK_REQUESTED"], limit=500)
    # Mas reciente primero: si dos cambios solapan ventana, revertir el ultimo.
    requested.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

    agent = AutoApplyCodeAgent()
    results: list[dict[str, Any]] = []
    for change in requested:
        applied_change_id = change.get("applied_change_id")
        metrics = ((change.get("decision") or {}).get("watchdog") or {}).get("metrics", {})
        try:
            result = agent.rollback(
                settings=settings,
                store=store,
                applied_change_id=applied_change_id,
                actor="change_watchdog",
            )
            status = (result or {}).get("status")
        except Exception as exc:  # noqa: BLE001 - el watchdog no debe tumbar el job.
            status = "ROLLBACK_ERROR"
            result = {"error": repr(exc)}
        log_system_event(
            settings.logs_dir,
            "change_rolled_back",
            {"applied_change_id": applied_change_id, "status": status, "metrics": metrics},
        )
        results.append({"applied_change_id": applied_change_id, "status": status, "metrics": metrics})
    return results


def run_change_watchdog(store: Store, settings: Settings) -> dict[str, Any]:
    """Punto de entrada del scheduler: evalua y luego ejecuta rollbacks."""

    if not getattr(settings, "change_watchdog_enabled", True):
        return {"enabled": False, "evaluated": [], "rolled_back": []}
    evaluated = evaluate_applied_changes(store, settings)
    rolled_back = execute_rollbacks(store, settings)
    throttle = None
    # Tras rollbacks (semana mala), recortar el presupuesto de riesgo -25% (T4.1).
    if rolled_back and getattr(settings, "risk_budget_enabled", False):
        try:
            from ..risk_budget import risk_budget_throttle

            throttle = risk_budget_throttle(store, settings, 0.75)
        except Exception:  # noqa: BLE001 - el throttle no debe tumbar el watchdog.
            throttle = None
    return {"enabled": True, "evaluated": evaluated, "rolled_back": rolled_back, "risk_budget_throttle": throttle}
