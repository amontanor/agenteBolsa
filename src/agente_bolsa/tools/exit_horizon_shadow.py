"""Counterfactual exit-horizon comparison for reconciled paper buys."""

from __future__ import annotations

from collections import Counter
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .edge_analysis import _build_spy_forward_returns, linked_executed_buy_signals


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return round(gains / losses, 4) if losses > 0 else None


def _pick_return(row: dict[str, Any], horizons: tuple[int, ...]) -> tuple[int | None, float | None]:
    outcome = row.get("outcome") or {}
    for horizon in horizons:
        value = _num(outcome.get(f"return_{horizon}d"))
        if value is not None:
            return horizon, value
    return None, None


def _metrics(observations: list[dict[str, Any]]) -> dict[str, Any]:
    values = [item["return"] for item in observations]
    alphas = [item["alpha"] for item in observations if item.get("alpha") is not None]
    basis = Counter(f"{item['horizon']}d" for item in observations)
    return {
        "matured": len(values),
        "expectancy": round(sum(values) / len(values), 4) if values else None,
        "hit_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        "profit_factor": _profit_factor(values),
        "alpha": round(sum(alphas) / len(alphas), 4) if alphas else None,
        "benchmark_coverage": len(alphas),
        "basis": dict(sorted(basis.items())),
    }


def build_exit_horizon_shadow(
    settings: Settings,
    store: Store,
    *,
    since_date: str = "2026-04-01",
    linked_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare 1-3d and 5-10d observations without changing exit behavior."""

    if linked_rows is None:
        executed = linked_executed_buy_signals(settings, store, since_date=since_date)
        rows = list(executed.get("linked_rows") or [])
    else:
        rows = list(linked_rows)
    if rows:
        start = min(str(row.get("signal_date") or "")[:10] for row in rows)
        end = max(str(row.get("signal_date") or "")[:10] for row in rows)
    else:
        start = end = since_date
    benchmark = _build_spy_forward_returns(settings, start=start, end=end) if rows else {}

    definitions = {
        "current_1_3d": (3, 1),
        "shadow_5_10d": (10, 5),
    }
    observations: dict[str, list[dict[str, Any]]] = {key: [] for key in definitions}
    by_signal: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        signal_id = str(row.get("signal_id") or row.get("broker_order_id") or "")
        signal_date = str(row.get("signal_date") or "")[:10]
        by_signal[signal_id] = {}
        for policy, horizons in definitions.items():
            horizon, value = _pick_return(row, horizons)
            if horizon is None or value is None:
                continue
            spy_return = benchmark.get((signal_date, horizon))
            item = {
                "signal_id": signal_id,
                "symbol": row.get("symbol"),
                "signal_date": signal_date,
                "horizon": horizon,
                "return": value,
                "spy_return": spy_return,
                "alpha": round(value - spy_return, 6) if spy_return is not None else None,
            }
            observations[policy].append(item)
            by_signal[signal_id][policy] = item

    paired = []
    for signal_id, policies in by_signal.items():
        current = policies.get("current_1_3d")
        shadow = policies.get("shadow_5_10d")
        if not current or not shadow:
            continue
        paired.append(
            {
                "signal_id": signal_id,
                "symbol": shadow.get("symbol"),
                "current_horizon": current["horizon"],
                "shadow_horizon": shadow["horizon"],
                "return_delta": round(shadow["return"] - current["return"], 4),
                "alpha_delta": round(shadow["alpha"] - current["alpha"], 4)
                if shadow.get("alpha") is not None and current.get("alpha") is not None
                else None,
            }
        )
    return_deltas = [item["return_delta"] for item in paired]
    alpha_deltas = [item["alpha_delta"] for item in paired if item.get("alpha_delta") is not None]
    return {
        "mode": "SHADOW",
        "changes_trading_behavior": False,
        "since_date": since_date,
        "linked_executed_buys": len(rows),
        "current_1_3d": _metrics(observations["current_1_3d"]),
        "shadow_5_10d": _metrics(observations["shadow_5_10d"]),
        "paired_comparison": {
            "n": len(paired),
            "avg_return_delta": round(sum(return_deltas) / len(return_deltas), 4) if return_deltas else None,
            "avg_alpha_delta": round(sum(alpha_deltas) / len(alpha_deltas), 4) if alpha_deltas else None,
        },
        "promotion_eligible": False,
        "promotion_reason": "measurement_only; require a larger matured paper sample",
        "pairs": paired,
    }
