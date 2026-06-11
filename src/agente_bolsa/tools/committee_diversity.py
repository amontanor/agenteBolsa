"""Diversidad real del comite de agentes (T5.11).

El comite no debe ser un solo modelo con doce sombreros. Aqui se mide la
correlacion de votos entre modelos (dos "expertos" que coinciden >95% son
redundantes) y se verifica el invariante de gobierno: ninguna compra puede
originarse sin un candidato determinista; el consenso LLM solo veta o reduce.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

REDUNDANT_AGREEMENT = 0.95
REDUNDANT_MIN_DICTAMENES = 50


def vote_correlation(votes_by_model: dict[str, list[Any]]) -> dict[str, Any]:
    """Calcula el acuerdo por par de modelos y marca redundancias (T5.11).

    `votes_by_model`: modelo -> lista de dictamenes (mismo orden por dictamen).
    """

    models = sorted(votes_by_model)
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(models, 2):
        va, vb = votes_by_model[a], votes_by_model[b]
        n = min(len(va), len(vb))
        if n == 0:
            continue
        matches = sum(1 for i in range(n) if va[i] == vb[i])
        agreement = matches / n
        pairs.append(
            {
                "a": a,
                "b": b,
                "n": n,
                "agreement": round(agreement, 4),
                "redundant": agreement > REDUNDANT_AGREEMENT and n >= REDUNDANT_MIN_DICTAMENES,
            }
        )
    return {"pairs": pairs, "redundant_pairs": [p for p in pairs if p["redundant"]]}


def model_id_from_llm_result(llm_result: dict[str, Any]) -> str | None:
    """Extrae el modelo que emitio un dictamen del resultado LLM registrado (T5.11).

    Lee las formas comunes del dump (`model`, `endpoint.model`, `provider`) sin
    necesidad de tocar el agente: el `model_id` ya viaja en el resultado.
    """

    if not isinstance(llm_result, dict):
        return None
    for key in ("model", "model_id", "model_name"):
        value = llm_result.get(key)
        if value:
            return str(value)
    endpoint = llm_result.get("endpoint") or {}
    if isinstance(endpoint, dict) and endpoint.get("model"):
        return str(endpoint["model"])
    return None


def votes_by_model(decisions: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Agrupa dictamenes por modelo a partir de registros del comite (T5.11).

    Cada decision: {"llm": <dump>, "vote": <valor>} o equivalente. Usa
    `model_id_from_llm_result` para resolver el modelo emisor.
    """

    grouped: dict[str, list[Any]] = {}
    for decision in decisions:
        model = model_id_from_llm_result(decision.get("llm") or decision)
        vote = decision.get("vote") or decision.get("decision")
        if model is None or vote is None:
            continue
        grouped.setdefault(model, []).append(vote)
    return grouped


def buy_requires_deterministic_candidate(
    recommendations: list[dict[str, Any]],
    candidate_symbols: set[str] | list[str],
) -> tuple[bool, list[str]]:
    """Invariante (T5.11): ninguna BUY sin candidato determinista.

    Devuelve (ok, offenders): simbolos comprados que no estaban entre los
    candidatos deterministas del estudio tecnico.
    """

    allowed = {str(s).upper() for s in candidate_symbols}
    offenders: list[str] = []
    for rec in recommendations:
        action = str(rec.get("action") or "").lower()
        if action != "buy":
            continue
        symbol = str(rec.get("symbol") or "").upper()
        if symbol and symbol not in allowed:
            offenders.append(symbol)
    return (not offenders), offenders
