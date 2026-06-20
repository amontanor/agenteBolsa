"""Weekly measurement for C2 shadow policies without trading side effects."""

from __future__ import annotations

import json
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .signal_learning import HORIZONS, _setup_key


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _metrics(values: list[float]) -> dict[str, Any]:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return {
        "matured": len(values),
        "expectancy": round(sum(values) / len(values), 4) if values else None,
        "hit_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        "profit_factor": round(gains / losses, 4) if losses > 0 else None,
    }


def _candidate_rows(store: Store, since_date: str) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT signal_id, symbol, signal_date, features_json, outcome_json
            FROM signal_outcomes
            WHERE signal_date >= ?
              AND (
                json_extract(features_json, '$.setup_name') = 'confirmed_pattern'
                OR coalesce(json_extract(features_json, '$.chart_patterns.bullish_confirmed_count'), 0) > 0
                OR json_type(outcome_json, '$.exit_policy_v2') IS NOT NULL
              )
            ORDER BY created_at ASC
            """,
            (since_date,),
        ).fetchall()
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        item = {
            "signal_id": row["signal_id"],
            "symbol": row["symbol"],
            "signal_date": row["signal_date"],
            "features": json.loads(row["features_json"] or "{}"),
            "outcome": json.loads(row["outcome_json"] or "{}"),
        }
        key = (str(row["symbol"]), str(row["signal_date"]))
        existing = deduplicated.get(key)
        item_outcome = item["outcome"]
        existing_outcome = (existing or {}).get("outcome") or {}
        item_score = sum(item_outcome.get(f"return_{horizon}d") is not None for horizon in HORIZONS) + int(
            bool(item_outcome.get("exit_policy_v2"))
        )
        existing_score = sum(existing_outcome.get(f"return_{horizon}d") is not None for horizon in HORIZONS) + int(
            bool(existing_outcome.get("exit_policy_v2"))
        )
        if existing is None or item_score >= existing_score:
            deduplicated[key] = item
    return list(deduplicated.values())


def build_c2_shadow_report(
    settings: Settings,
    store: Store,
    *,
    since_date: str,
) -> dict[str, Any]:
    rows = _candidate_rows(store, since_date)
    confirmed = [row for row in rows if _setup_key(row) == "confirmed_pattern"]
    confirmed_metrics = {}
    for horizon in HORIZONS:
        values = [
            value
            for row in confirmed
            if (value := _num((row.get("outcome") or {}).get(f"return_{horizon}d"))) is not None
        ]
        confirmed_metrics[f"{horizon}d"] = _metrics(values)

    stale_current = []
    stale_shadow = []
    stale_triggered = 0
    stale_eligible = 0
    days = int(settings.exit_policy_v2_stale_guard_days)
    for row in rows:
        outcome = row.get("outcome") or {}
        policy = outcome.get("exit_policy_v2") or {}
        current_return = _num(policy.get("return_pct"))
        day_return = _num(outcome.get(f"return_{days}d"))
        peak_return = _num(policy.get("peak_return"))
        if current_return is None or day_return is None or peak_return is None:
            continue
        stale_eligible += 1
        stale_current.append(current_return)
        first_hit = outcome.get("first_hit") or {}
        protected_exit = (
            first_hit.get("type") in {"stop_loss", "take_profit"}
            and 0 < int(first_hit.get("days") or 0) <= days
        )
        triggered = (
            not protected_exit
            and peak_return <= float(settings.exit_policy_v2_stale_guard_max_peak_return)
            and day_return <= float(settings.exit_policy_v2_stale_guard_min_return)
        )
        stale_triggered += int(triggered)
        stale_shadow.append(day_return if triggered else current_return)

    return {
        "mode": "SHADOW",
        "changes_trading_behavior": False,
        "flags": {
            "stale_guard_behavior_enabled": bool(settings.exit_policy_v2_stale_guard_enabled),
            "confirmed_pattern_penalty_behavior_enabled": bool(settings.selection_negative_pocket_penalty_enabled),
        },
        "stale_guard": {
            "eligible": stale_eligible,
            "triggered": stale_triggered,
            "current": _metrics(stale_current),
            "shadow": _metrics(stale_shadow),
            "days": days,
        },
        "confirmed_pattern": {
            "signals": len(confirmed),
            "metrics": confirmed_metrics,
            "shadow_penalty": float(settings.selection_negative_pocket_confirmed_pattern_penalty),
            "applied": bool(settings.selection_negative_pocket_penalty_enabled),
        },
    }
