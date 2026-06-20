"""Strict shadow promotion/readiness policy based on measured edge."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.edge_analysis import _build_spy_forward_context, _date_text, _metrics
from agente_bolsa.tools.execution_linking import match_signal_row_for_buy_order
from agente_bolsa.tools.profitability_scoreboard import build_profitability_scoreboard
from agente_bolsa.tools.signal_learning import _indicator_tags, _setup_key

PROMOTION_MIN_MATURED = 20
PROMOTION_MIN_DAYS = 10
PROMOTION_MIN_REGIMES = 2
PROMOTION_MIN_ALPHA = 0.01
PROMOTION_MIN_EXPECTANCY = 0.01
PROMOTION_MAX_TURNOVER_PER_SESSION = 5.0
RETIRE_MIN_MATURED = 5
RETIRE_MAX_ALPHA_5D = -0.02
RETIRE_MAX_PROFIT_FACTOR_5D = 0.60
PENDING_VALIDATION_TTL_DAYS = 14
RETIRE_ACTIONABLE_KEYS = {
    ("setup", "confirmed_pattern"),
    ("tag", "rsi:60_75"),
    ("tag", "volume_z:lt0"),
    ("tag", "sma20_dist:0_6pct"),
}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _loads(raw: str | None) -> dict[str, Any]:
    import json

    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _order_plan_created_at(payload: dict[str, Any]) -> str | None:
    return str(((payload.get("plan") or {}).get("created_at")) or "").strip() or None


def _executed_rows(settings: Settings, store: Store, *, since_date: str) -> list[dict[str, Any]]:
    import sqlite3

    with store.connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT broker_order_id, plan_id, symbol, side, status, created_at, payload_json
            FROM broker_orders
            WHERE lower(side) = 'buy'
              AND lower(status) = 'filled'
              AND created_at >= ?
            ORDER BY created_at ASC
            """,
            (f"{since_date}T00:00:00",),
        ).fetchall()
        linked: list[dict[str, Any]] = []
        for row in rows:
            payload = _loads(row["payload_json"])
            signal = match_signal_row_for_buy_order(
                conn,
                symbol=str(row["symbol"]),
                order_created_at=row["created_at"],
                plan_created_at=_order_plan_created_at(payload),
                broker_order_id=str(row["broker_order_id"]),
            )
            if signal:
                linked.append(signal)
    if not linked:
        return []
    start = min(_date_text(row.get("signal_date")) for row in linked)
    end = max(_date_text(row.get("signal_date")) for row in linked)
    benchmark_context = _build_spy_forward_context(settings, start=start, end=end)
    regimes = benchmark_context["regimes"]
    for row in linked:
        features = row.get("features") or {}
        row["setup_key"] = _setup_key(row)
        row["tags"] = _indicator_tags(row)
        row["regime"] = str(
            features.get("market_regime")
            or features.get("regime")
            or regimes.get(_date_text(row.get("signal_date")))
            or "unknown"
        )
    return linked


def _walk_forward_ok(rows: list[dict[str, Any]], benchmark: dict[tuple[str, int], float | None], *, horizon: int = 10) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("signal_date") or ""))
    if len(ordered) < PROMOTION_MIN_MATURED:
        return {"ok": False, "reason": "muestra insuficiente para walk-forward"}
    midpoint = len(ordered) // 2
    windows = [ordered[:midpoint], ordered[midpoint:]]
    checks = []
    for window in windows:
        metrics = _metrics(window, benchmark)
        checks.append(
            {
                "matured": metrics.get(f"matured_{horizon}d"),
                "expectancy": metrics.get(f"expectancy_{horizon}d"),
                "alpha": metrics.get(f"alpha_{horizon}d"),
                "ok": (_num(metrics.get(f"expectancy_{horizon}d")) or 0.0) >= PROMOTION_MIN_EXPECTANCY
                and (_num(metrics.get(f"alpha_{horizon}d")) or 0.0) >= PROMOTION_MIN_ALPHA,
            }
        )
    return {"ok": all(item["ok"] for item in checks), "windows": checks}


def _candidate_decision(
    *,
    kind: str,
    key: str,
    rows: list[dict[str, Any]],
    benchmark: dict[tuple[str, int], float | None],
) -> dict[str, Any]:
    metrics = _metrics(rows, benchmark)
    sessions = len({row.get("signal_date") for row in rows})
    regimes = Counter(str(row.get("regime") or "unknown") for row in rows)
    turnover = round(len(rows) / sessions, 4) if sessions else None
    matured_10d = int(metrics.get("matured_10d") or 0)
    alpha_10d = _num(metrics.get("alpha_10d"))
    expectancy_10d = _num(metrics.get("expectancy_10d"))
    stable_regimes = len([regime for regime, count in regimes.items() if regime != "unknown" and count >= 5])
    walk_forward = _walk_forward_ok(rows, benchmark, horizon=10)
    promote_checks = {
        "matured_sample": matured_10d >= PROMOTION_MIN_MATURED,
        "calendar_days": sessions >= PROMOTION_MIN_DAYS,
        "positive_expectancy_margin": (expectancy_10d or 0.0) >= PROMOTION_MIN_EXPECTANCY,
        "positive_alpha_margin": (alpha_10d or 0.0) >= PROMOTION_MIN_ALPHA,
        "regime_stability": stable_regimes >= PROMOTION_MIN_REGIMES,
        "walk_forward": bool(walk_forward.get("ok")),
        "turnover": turnover is not None and turnover <= PROMOTION_MAX_TURNOVER_PER_SESSION,
    }
    alpha_5d = _num(metrics.get("alpha_5d"))
    profit_factor_5d = _num(metrics.get("profit_factor_5d"))
    retire_checks = {
        "actionable_scope": (kind, key) in RETIRE_ACTIONABLE_KEYS,
        "matured_sample": int(metrics.get("matured_5d") or 0) >= RETIRE_MIN_MATURED,
        "negative_alpha": (alpha_5d if alpha_5d is not None else 0.0) <= RETIRE_MAX_ALPHA_5D,
        "weak_profit_factor": (profit_factor_5d if profit_factor_5d is not None else 999.0)
        <= RETIRE_MAX_PROFIT_FACTOR_5D,
    }
    if all(promote_checks.values()):
        verdict = "PROMOTE_CANDIDATE"
        action = "propose_shadow_to_active"
    elif all(retire_checks.values()):
        verdict = "RETIRE_CANDIDATE"
        action = "propose_active_to_shadow"
    else:
        verdict = "HOLD"
        action = "keep_collecting_evidence"
    return {
        "kind": kind,
        "key": key,
        "verdict": verdict,
        "action": action,
        "metrics": metrics,
        "sessions": sessions,
        "regimes": dict(regimes),
        "stable_regime_count": stable_regimes,
        "turnover_per_session": turnover,
        "promotion_checks": promote_checks,
        "retire_checks": retire_checks,
        "walk_forward": walk_forward,
    }


def _validation_backlog(store: Store) -> dict[str, Any]:
    validations = store.continuous_improvement_validations(limit=100000)
    now = datetime.now(timezone.utc)
    status_counts = Counter(str(item.get("status") or "UNKNOWN") for item in validations)
    stale_pending = []
    for item in validations:
        if str(item.get("status") or "") != "PENDING":
            continue
        try:
            created = datetime.fromisoformat(str(item.get("created_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        age_days = (now - created).days
        if age_days >= PENDING_VALIDATION_TTL_DAYS:
            stale_pending.append(
                {
                    "validation_id": item.get("validation_id"),
                    "proposal_id": item.get("proposal_id"),
                    "age_days": age_days,
                    "recommended_status": "EXPIRED_PENDING",
                    "reason": f"pending validation older than {PENDING_VALIDATION_TTL_DAYS} days",
                }
            )
    return {
        "total": len(validations),
        "status_counts": dict(status_counts),
        "pending": status_counts.get("PENDING", 0),
        "stale_pending": stale_pending,
        "recommended_closures": len(stale_pending),
    }


def evaluate_promotion_readiness(
    settings: Settings,
    store: Store,
    *,
    since_date: str = "2026-04-01",
) -> dict[str, Any]:
    rows = _executed_rows(settings, store, since_date=since_date)
    if rows:
        start = min(_date_text(row.get("signal_date")) for row in rows)
        end = max(_date_text(row.get("signal_date")) for row in rows)
    else:
        start = end = since_date
    benchmark = _build_spy_forward_context(settings, start=start, end=end)["returns"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(("setup", str(row.get("setup_key") or "unknown")), []).append(row)
        groups.setdefault(("regime", str(row.get("regime") or "unknown")), []).append(row)
        for tag in row.get("tags") or []:
            groups.setdefault(("tag", str(tag)), []).append(row)
    evaluations = [
        _candidate_decision(kind=kind, key=key, rows=items, benchmark=benchmark)
        for (kind, key), items in groups.items()
    ]
    evaluations.sort(
        key=lambda item: (
            {"PROMOTE_CANDIDATE": 2, "RETIRE_CANDIDATE": 1, "HOLD": 0}.get(str(item.get("verdict")), 0),
            item.get("metrics", {}).get("alpha_10d") or -999,
        ),
        reverse=True,
    )
    return {
        "since_date": since_date,
        "policy": {
            "promotion_min_matured": PROMOTION_MIN_MATURED,
            "promotion_min_days": PROMOTION_MIN_DAYS,
            "promotion_min_regimes": PROMOTION_MIN_REGIMES,
            "promotion_min_alpha_10d": PROMOTION_MIN_ALPHA,
            "promotion_min_expectancy_10d": PROMOTION_MIN_EXPECTANCY,
            "retire_min_matured_5d": RETIRE_MIN_MATURED,
            "retire_max_alpha_5d": RETIRE_MAX_ALPHA_5D,
            "retire_max_profit_factor_5d": RETIRE_MAX_PROFIT_FACTOR_5D,
            "mode": "proposal_only_no_state_change",
        },
        "scoreboard": build_profitability_scoreboard(settings, store, since_date=since_date),
        "evaluations": evaluations,
        "promotion_candidates": [item for item in evaluations if item["verdict"] == "PROMOTE_CANDIDATE"],
        "retire_candidates": [item for item in evaluations if item["verdict"] == "RETIRE_CANDIDATE"],
        "validation_backlog": _validation_backlog(store),
    }
