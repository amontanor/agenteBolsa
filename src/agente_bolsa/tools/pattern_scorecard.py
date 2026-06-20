"""Scorecard de figuras auto-evaluado y pesos dinamicos (T3.3).

El reconocimiento de figuras (velas y chartismo) se mide a si mismo: por patron y
regimen calcula hit rate, expectancy y lift vs senales sin el patron, sobre
outcomes madurados. El peso de cada patron en el scoring pasa de fijo a dinamico
(base x lift, acotado), con fallback al peso fijo si hay pocas ocurrencias. Los
patrones que dejan de funcionar (lift < 0.8 con suficientes casos) se degradan a
peso 0 (reversible si el lift se recupera).
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


RETIRE_LIFT_THRESHOLD = 0.8
RETIRE_MIN_OCCURRENCES = 50


def _verdict(signal: dict[str, Any]) -> str:
    return str((signal.get("outcome") or {}).get("verdict", "") or "")


def _is_matured(signal: dict[str, Any]) -> bool:
    return _verdict(signal) not in {"", "pending"}


def _is_winner(signal: dict[str, Any]) -> bool:
    return _verdict(signal).startswith("winner")


def _return_pct(signal: dict[str, Any]) -> float | None:
    value = (signal.get("outcome") or {}).get("return_pct")
    return float(value) if isinstance(value, (int, float)) else None


def _patterns_of(signal: dict[str, Any]) -> list[str]:
    features = signal.get("features") or {}
    labels: list[str] = []
    chart = features.get("chart_patterns") or {}
    if isinstance(chart, dict):
        labels.extend(str(item) for item in (chart.get("labels") or []))
    candles = features.get("candle_patterns") or []
    if isinstance(candles, list):
        labels.extend(str(item) for item in candles)
    return [label for label in labels if label]


def _regime_of(signal: dict[str, Any]) -> str:
    features = signal.get("features") or {}
    return str(features.get("market_regime") or features.get("regime") or "all")


def _win_rate(signals: list[dict[str, Any]]) -> float | None:
    decided = [s for s in signals if _verdict(s).startswith(("winner", "loser"))]
    if not decided:
        return None
    return sum(1 for s in decided if _is_winner(s)) / len(decided)


def build_pattern_scorecard(store: Store, *, min_occurrences: int = 30) -> dict[str, Any]:
    """Calcula y persiste lift por patron sobre outcomes madurados."""

    signals = [item for item in store.signal_outcomes(limit=10000) if _is_matured(item)]
    all_patterns: set[str] = set()
    for signal in signals:
        all_patterns.update(_patterns_of(signal))

    scorecard: list[dict[str, Any]] = []
    for pattern in sorted(all_patterns):
        with_pattern = [s for s in signals if pattern in _patterns_of(s)]
        without_pattern = [s for s in signals if pattern not in _patterns_of(s)]
        wr_with = _win_rate(with_pattern)
        wr_without = _win_rate(without_pattern)
        lift = round(wr_with / wr_without, 4) if (wr_with is not None and wr_without) else None
        returns = [r for r in (_return_pct(s) for s in with_pattern) if r is not None]
        expectancy = round(statistics.fmean(returns), 6) if returns else None
        occurrences = len(with_pattern)
        status = "ACTIVE"
        if occurrences >= RETIRE_MIN_OCCURRENCES and lift is not None and lift < RETIRE_LIFT_THRESHOLD:
            status = "RETIRED"
        stat = {
            "pattern": pattern,
            "regime": "all",
            "occurrences": occurrences,
            "hit_rate": round(wr_with, 4) if wr_with is not None else None,
            "expectancy": expectancy,
            "lift": lift,
            "status": status,
            "payload": {"min_occurrences": min_occurrences},
        }
        store.upsert_pattern_stat(stat)
        scorecard.append(stat)
    return {"patterns": scorecard, "count": len(scorecard)}


def pattern_weight(
    store: Store,
    settings: Settings,
    pattern: str,
    base_weight: float,
    *,
    regime: str = "all",
) -> float:
    """Peso dinamico de un patron: base x lift, acotado [0, 2x base].

    Si los pesos dinamicos estan desactivados o hay pocas ocurrencias, devuelve el
    peso fijo. Un patron RETIRED pesa 0.
    """

    if not getattr(settings, "pattern_dynamic_weights_enabled", False):
        return base_weight
    min_occ = int(getattr(settings, "pattern_min_occurrences", 30))
    stats = {f"{row['pattern']}:{row['regime']}": row for row in store.pattern_stats(limit=1000)}
    row = stats.get(f"{pattern}:{regime}") or stats.get(f"{pattern}:all")
    if not row:
        return base_weight
    if str(row.get("status")) == "RETIRED":
        return 0.0
    occurrences = int(row.get("occurrences") or 0)
    lift = row.get("lift")
    if occurrences < min_occ or not isinstance(lift, (int, float)):
        return base_weight
    weight = base_weight * float(lift)
    return max(0.0, min(weight, 2.0 * base_weight))


def dynamic_pattern_weights(store: Store, settings: Settings, base_weight: float = 1.0) -> dict[str, float]:
    """Mapa patron -> peso dinamico (para inspeccion/uso por el laboratorio)."""

    return {row["pattern"]: pattern_weight(store, settings, row["pattern"], base_weight) for row in store.pattern_stats(limit=1000)}
