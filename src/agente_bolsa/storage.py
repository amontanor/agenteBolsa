"""SQLite persistence for hypotheses, events and validation results."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging_utils import AgentHistoryLogger
from .models import AgentEvent, Hypothesis


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS agent_events (
    event_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    event_type TEXT NOT NULL,
    cycle_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_events_agent_created
ON agent_events(agent, created_at);

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    entry_rule TEXT NOT NULL,
    exit_rule TEXT NOT NULL,
    invalidation_rule TEXT NOT NULL,
    horizon TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    hypothesis_id TEXT,
    strategy_name TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    passed INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    hypothesis_id TEXT,
    strategy_name TEXT,
    decision_type TEXT NOT NULL,
    approved INTEGER NOT NULL,
    reason TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    source_path TEXT,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_recommendations (
    recommendation_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_usage (
    usage_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    request_count INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created
ON llm_usage(created_at);

CREATE TABLE IF NOT EXISTS order_plans (
    plan_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    notional REAL NOT NULL,
    approved INTEGER NOT NULL,
    dry_run INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_orders (
    broker_order_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    signal_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    decision TEXT NOT NULL,
    features_json TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_symbol_date
ON signal_outcomes(symbol, signal_date);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_decision
ON signal_outcomes(decision);

CREATE TABLE IF NOT EXISTS trade_memory (
    memory_id TEXT PRIMARY KEY,
    trade_time TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    notional REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    realized_pl REAL,
    realized_plpc REAL,
    open_pl REAL,
    open_plpc REAL,
    verdict TEXT NOT NULL,
    features_json TEXT NOT NULL,
    thesis_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trade_memory_symbol_date
ON trade_memory(symbol, trade_date);

CREATE TABLE IF NOT EXISTS strategy_rules (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    condition_json TEXT NOT NULL,
    effect TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategy_rules_status
ON strategy_rules(status);

CREATE TABLE IF NOT EXISTS rule_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    would_block INTEGER NOT NULL,
    actual_outcome TEXT NOT NULL,
    avoided_loss REAL NOT NULL,
    missed_gain REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(rule_id) REFERENCES strategy_rules(rule_id),
    FOREIGN KEY(memory_id) REFERENCES trade_memory(memory_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_evaluations_unique
ON rule_evaluations(rule_id, memory_id);

CREATE TABLE IF NOT EXISTS learning_observations (
    observation_id TEXT PRIMARY KEY,
    signal_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    source_family TEXT NOT NULL,
    source_run_ids_json TEXT NOT NULL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    best_signal_id TEXT,
    best_score REAL,
    decision TEXT NOT NULL,
    explanation TEXT NOT NULL,
    llm_considered INTEGER NOT NULL,
    approved_buy INTEGER NOT NULL,
    blocked_entry_quality INTEGER NOT NULL,
    blocked_backtest INTEGER NOT NULL,
    executed_buy INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    rank_path_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_observations_unique
ON learning_observations(signal_date, symbol, source_family);

CREATE INDEX IF NOT EXISTS idx_learning_observations_date
ON learning_observations(signal_date);

CREATE TABLE IF NOT EXISTS learning_daily_summaries (
    summary_id TEXT PRIMARY KEY,
    session_date TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_daily_summaries_kind_date
ON learning_daily_summaries(kind, session_date);

CREATE TABLE IF NOT EXISTS learning_policy_candidates (
    policy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    policy_type TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    auto_activatable INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    notes TEXT NOT NULL,
    promoted_at TEXT,
    last_evaluated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_policy_candidates_status
ON learning_policy_candidates(status);

CREATE TABLE IF NOT EXISTS learning_policy_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    phase TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(policy_id) REFERENCES learning_policy_candidates(policy_id)
);

CREATE INDEX IF NOT EXISTS idx_learning_policy_evaluations_policy_date
ON learning_policy_evaluations(policy_id, session_date);

CREATE TABLE IF NOT EXISTS pre_earnings_predictions (
    prediction_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    prediction_date TEXT NOT NULL,
    session_date TEXT NOT NULL,
    earnings_datetime TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    score REAL NOT NULL,
    max_score REAL NOT NULL,
    reason TEXT NOT NULL,
    features_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pre_earnings_predictions_session
ON pre_earnings_predictions(session_date, symbol);

CREATE INDEX IF NOT EXISTS idx_pre_earnings_predictions_status
ON pre_earnings_predictions(status);

CREATE TABLE IF NOT EXISTS pre_earnings_analyst_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    eps_estimate REAL,
    revenue_estimate REAL,
    eps_count REAL,
    revenue_count REAL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pre_earnings_analyst_snapshots_symbol_date
ON pre_earnings_analyst_snapshots(symbol, snapshot_date);
"""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


class Store:
    def __init__(self, database_path: Path, agent_logs_dir: Path) -> None:
        self.database_path = database_path
        self.agent_history = AgentHistoryLogger(agent_logs_dir)

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def record_agent_event(self, event: AgentEvent) -> None:
        self.agent_history.log(event)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_events (
                    event_id, agent, event_type, cycle_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.agent,
                    event.event_type,
                    event.cycle_id,
                    _dumps(event.payload),
                    event.created_at.isoformat(),
                ),
            )

    def save_hypothesis(self, hypothesis: Hypothesis) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO hypotheses (
                    hypothesis_id, name, description, symbols_json, entry_rule,
                    exit_rule, invalidation_rule, horizon, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hypothesis_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    symbols_json=excluded.symbols_json,
                    entry_rule=excluded.entry_rule,
                    exit_rule=excluded.exit_rule,
                    invalidation_rule=excluded.invalidation_rule,
                    horizon=excluded.horizon,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    hypothesis.hypothesis_id,
                    hypothesis.name,
                    hypothesis.description,
                    _dumps(hypothesis.symbols),
                    hypothesis.entry_rule,
                    hypothesis.exit_rule,
                    hypothesis.invalidation_rule,
                    hypothesis.horizon,
                    hypothesis.status,
                    hypothesis.created_at.isoformat(),
                    now,
                ),
            )

    def save_backtest_run(
        self,
        run_id: str,
        hypothesis_id: str | None,
        strategy_name: str,
        metrics: dict[str, Any],
        passed: bool,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO backtest_runs (
                    run_id, hypothesis_id, strategy_name, metrics_json, passed, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    hypothesis_id,
                    strategy_name,
                    _dumps(metrics),
                    int(passed),
                    _utc_iso(),
                ),
            )

    def save_decision(
        self,
        decision_id: str,
        hypothesis_id: str | None,
        strategy_name: str | None,
        decision_type: str,
        approved: bool,
        reason: str,
        checks: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decisions (
                    decision_id, hypothesis_id, strategy_name, decision_type,
                    approved, reason, checks_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    hypothesis_id,
                    strategy_name,
                    decision_type,
                    int(approved),
                    reason,
                    _dumps(checks),
                    _utc_iso(),
                ),
            )

    def get_runtime_value(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM runtime_state WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["value_json"])

    def set_runtime_value(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at
                """,
                (key, _dumps(value), _utc_iso()),
            )

    def save_trade_recommendation(
        self,
        *,
        recommendation_id: str,
        cycle_id: str,
        symbol: str,
        action: str,
        confidence: float,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_recommendations (
                    recommendation_id, cycle_id, symbol, action, confidence,
                    payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    cycle_id,
                    symbol,
                    action,
                    confidence,
                    _dumps(payload),
                    _utc_iso(),
                ),
            )

    def save_order_plan(
        self,
        *,
        plan_id: str,
        cycle_id: str,
        symbol: str,
        side: str,
        notional: float,
        approved: bool,
        dry_run: bool,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO order_plans (
                    plan_id, cycle_id, symbol, side, notional, approved,
                    dry_run, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    cycle_id,
                    symbol,
                    side,
                    notional,
                    int(approved),
                    int(dry_run),
                    _dumps(payload),
                    _utc_iso(),
                ),
            )

    def record_llm_usage(
        self,
        *,
        usage_id: str,
        source: str,
        model: str | None,
        request_count: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_usage (
                    usage_id, source, model, request_count, prompt_tokens,
                    completion_tokens, total_tokens, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id,
                    source,
                    model,
                    int(request_count),
                    int(prompt_tokens),
                    int(completion_tokens),
                    int(total_tokens),
                    _dumps(payload or {}),
                    _utc_iso(),
                ),
            )

    def daily_llm_usage(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    substr(created_at, 1, 10) AS date,
                    SUM(request_count) AS requests,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM llm_usage
                GROUP BY substr(created_at, 1, 10)
                ORDER BY date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_llm_usage(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT usage_id, source, model, request_count, prompt_tokens,
                       completion_tokens, total_tokens, payload_json, created_at
                FROM llm_usage
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_order_plans(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT plan_id, cycle_id, symbol, side, notional, approved,
                   dry_run, payload_json, created_at
            FROM order_plans
            WHERE approved = 1
              AND dry_run = 1
              AND plan_id NOT IN (SELECT plan_id FROM broker_orders)
        """
        params: list[Any] = []
        if cycle_id:
            query += " AND cycle_id = ?"
            params.append(cycle_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "plan_id": row["plan_id"],
                "cycle_id": row["cycle_id"],
                "symbol": row["symbol"],
                "side": row["side"],
                "notional": row["notional"],
                "approved": bool(row["approved"]),
                "dry_run": bool(row["dry_run"]),
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_broker_order(
        self,
        *,
        broker_order_id: str,
        plan_id: str,
        cycle_id: str,
        symbol: str,
        side: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO broker_orders (
                    broker_order_id, plan_id, cycle_id, symbol, side,
                    status, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    broker_order_id,
                    plan_id,
                    cycle_id,
                    symbol,
                    side,
                    status,
                    _dumps(payload),
                    _utc_iso(),
                ),
            )

    def save_signal_outcome(
        self,
        *,
        signal_id: str,
        source_run_id: str,
        source: str,
        symbol: str,
        signal_date: str,
        decision: str,
        features: dict[str, Any],
        gate: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_outcomes (
                    signal_id, source_run_id, source, symbol, signal_date,
                    decision, features_json, gate_json, outcome_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    decision=excluded.decision,
                    features_json=excluded.features_json,
                    gate_json=excluded.gate_json,
                    outcome_json=excluded.outcome_json,
                    updated_at=excluded.updated_at
                """,
                (
                    signal_id,
                    source_run_id,
                    source,
                    symbol.upper(),
                    signal_date,
                    decision,
                    _dumps(features),
                    _dumps(gate or {}),
                    _dumps(outcome or {}),
                    now,
                    now,
                ),
            )

    def update_signal_decision(
        self,
        *,
        source_run_id: str,
        symbol: str,
        decision: str,
        gate: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT gate_json
                FROM signal_outcomes
                WHERE source_run_id = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (source_run_id, symbol.upper()),
            ).fetchone()
            if not row:
                return
            existing_gate = json.loads(row["gate_json"] or "{}")
            existing_gate.update(gate)
            conn.execute(
                """
                UPDATE signal_outcomes
                SET decision = ?, gate_json = ?, updated_at = ?
                WHERE source_run_id = ? AND symbol = ?
                """,
                (decision, _dumps(existing_gate), _utc_iso(), source_run_id, symbol.upper()),
            )

    def update_signal_outcome(self, signal_id: str, outcome: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE signal_outcomes
                SET outcome_json = ?, updated_at = ?
                WHERE signal_id = ?
                """,
                (_dumps(outcome), _utc_iso(), signal_id),
            )

    def update_signal_outcomes_bulk(self, outcomes: dict[str, dict[str, Any]]) -> None:
        if not outcomes:
            return
        now = _utc_iso()
        with self.connect() as conn:
            conn.executemany(
                """
                UPDATE signal_outcomes
                SET outcome_json = ?, updated_at = ?
                WHERE signal_id = ?
                """,
                [(_dumps(outcome), now, signal_id) for signal_id, outcome in outcomes.items()],
            )

    def save_pre_earnings_prediction(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pre_earnings_predictions (
                    prediction_id, source_run_id, symbol, prediction_date,
                    session_date, earnings_datetime, hypothesis, score, max_score,
                    reason, features_json, outcome_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id) DO UPDATE SET
                    source_run_id=excluded.source_run_id,
                    hypothesis=excluded.hypothesis,
                    score=excluded.score,
                    max_score=excluded.max_score,
                    reason=excluded.reason,
                    features_json=excluded.features_json,
                    outcome_json=excluded.outcome_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    item["prediction_id"],
                    item["source_run_id"],
                    item["symbol"].upper(),
                    item["prediction_date"],
                    item["session_date"],
                    item["earnings_datetime"],
                    item["hypothesis"],
                    float(item.get("score") or 0),
                    float(item.get("max_score") or 0),
                    item.get("reason") or "",
                    _dumps(item.get("features", {})),
                    _dumps(item.get("outcome", {})),
                    item.get("status", "pending"),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def update_pre_earnings_prediction_outcome(
        self,
        prediction_id: str,
        *,
        outcome: dict[str, Any],
        status: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE pre_earnings_predictions
                SET outcome_json = ?, status = ?, updated_at = ?
                WHERE prediction_id = ?
                """,
                (_dumps(outcome), status, _utc_iso(), prediction_id),
            )

    def pre_earnings_predictions(
        self,
        *,
        status: str | None = None,
        since_date: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT prediction_id, source_run_id, symbol, prediction_date,
                   session_date, earnings_datetime, hypothesis, score, max_score,
                   reason, features_json, outcome_json, status, created_at, updated_at
            FROM pre_earnings_predictions
            WHERE 1 = 1
        """
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if since_date:
            query += " AND prediction_date >= ?"
            params.append(since_date)
        query += " ORDER BY prediction_date DESC, session_date DESC, score DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if not key.endswith("_json")},
                "features": json.loads(row["features_json"] or "{}"),
                "outcome": json.loads(row["outcome_json"] or "{}"),
            }
            for row in rows
        ]

    def save_pre_earnings_analyst_snapshot(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        symbol = item["symbol"].upper()
        snapshot_date = item["snapshot_date"]
        snapshot_id = f"{snapshot_date}:{symbol}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pre_earnings_analyst_snapshots (
                    snapshot_id, symbol, snapshot_date, eps_estimate,
                    revenue_estimate, eps_count, revenue_count, payload_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    eps_estimate=excluded.eps_estimate,
                    revenue_estimate=excluded.revenue_estimate,
                    eps_count=excluded.eps_count,
                    revenue_count=excluded.revenue_count,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot_id,
                    symbol,
                    snapshot_date,
                    item.get("eps_estimate"),
                    item.get("revenue_estimate"),
                    item.get("eps_count"),
                    item.get("revenue_count"),
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def pre_earnings_analyst_snapshot_before(
        self,
        symbol: str,
        target_date: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot_id, symbol, snapshot_date, eps_estimate,
                       revenue_estimate, eps_count, revenue_count, payload_json,
                       created_at, updated_at
                FROM pre_earnings_analyst_snapshots
                WHERE symbol = ? AND snapshot_date <= ?
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (symbol.upper(), target_date),
            ).fetchone()
        if not row:
            return None
        return {
            **{key: row[key] for key in row.keys() if key != "payload_json"},
            "payload": json.loads(row["payload_json"] or "{}"),
        }

    def save_trade_memory(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_memory (
                    memory_id, trade_time, trade_date, symbol, side, qty, price,
                    notional, stop_loss, take_profit, realized_pl, realized_plpc,
                    open_pl, open_plpc, verdict, features_json, thesis_json,
                    outcome_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    stop_loss=excluded.stop_loss,
                    take_profit=excluded.take_profit,
                    realized_pl=excluded.realized_pl,
                    realized_plpc=excluded.realized_plpc,
                    open_pl=excluded.open_pl,
                    open_plpc=excluded.open_plpc,
                    verdict=excluded.verdict,
                    features_json=excluded.features_json,
                    thesis_json=excluded.thesis_json,
                    outcome_json=excluded.outcome_json,
                    updated_at=excluded.updated_at
                """,
                (
                    item["memory_id"],
                    item["trade_time"],
                    item["trade_date"],
                    item["symbol"],
                    item["side"],
                    item["qty"],
                    item["price"],
                    item["notional"],
                    item.get("stop_loss"),
                    item.get("take_profit"),
                    item.get("realized_pl"),
                    item.get("realized_plpc"),
                    item.get("open_pl"),
                    item.get("open_plpc"),
                    item["verdict"],
                    _dumps(item.get("features", {})),
                    _dumps(item.get("thesis", {})),
                    _dumps(item.get("outcome", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def trade_memory(self, *, limit: int = 500, since_date: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT memory_id, trade_time, trade_date, symbol, side, qty, price,
                   notional, stop_loss, take_profit, realized_pl, realized_plpc,
                   open_pl, open_plpc, verdict, features_json, thesis_json,
                   outcome_json, created_at, updated_at
            FROM trade_memory
            WHERE 1 = 1
        """
        params: list[Any] = []
        if since_date:
            query += " AND trade_date >= ?"
            params.append(since_date)
        query += " ORDER BY trade_time DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if not key.endswith("_json")},
                "features": json.loads(row["features_json"] or "{}"),
                "thesis": json.loads(row["thesis_json"] or "{}"),
                "outcome": json.loads(row["outcome_json"] or "{}"),
            }
            for row in rows
        ]

    def latest_signal_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT signal_id, source_run_id, source, symbol, signal_date,
                       decision, features_json, gate_json, outcome_json,
                       created_at, updated_at
                FROM signal_outcomes
                WHERE symbol = ?
                ORDER BY signal_date DESC, created_at DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            ).fetchone()
        if not row:
            return None
        return {
            "signal_id": row["signal_id"],
            "source_run_id": row["source_run_id"],
            "source": row["source"],
            "symbol": row["symbol"],
            "signal_date": row["signal_date"],
            "decision": row["decision"],
            "features": json.loads(row["features_json"] or "{}"),
            "gate": json.loads(row["gate_json"] or "{}"),
            "outcome": json.loads(row["outcome_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_strategy_rule(self, rule: dict[str, Any]) -> None:
        now = _utc_iso()
        existing = self.strategy_rule(rule["rule_id"])
        created_at = rule.get("created_at") or (existing or {}).get("created_at") or now
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_rules (
                    rule_id, name, description, condition_json, effect, status,
                    source, evidence_json, metrics_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    condition_json=excluded.condition_json,
                    effect=excluded.effect,
                    status=excluded.status,
                    source=excluded.source,
                    evidence_json=excluded.evidence_json,
                    metrics_json=excluded.metrics_json,
                    updated_at=excluded.updated_at
                """,
                (
                    rule["rule_id"],
                    rule["name"],
                    rule["description"],
                    _dumps(rule.get("condition", {})),
                    rule["effect"],
                    rule.get("status", "shadow"),
                    rule.get("source", "rule_miner"),
                    _dumps(rule.get("evidence", {})),
                    _dumps(rule.get("metrics", {})),
                    created_at,
                    now,
                ),
            )

    def strategy_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT rule_id, name, description, condition_json, effect, status,
                       source, evidence_json, metrics_json, created_at, updated_at
                FROM strategy_rules
                WHERE rule_id = ?
                """,
                (rule_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "rule_id": row["rule_id"],
            "name": row["name"],
            "description": row["description"],
            "condition": json.loads(row["condition_json"] or "{}"),
            "effect": row["effect"],
            "status": row["status"],
            "source": row["source"],
            "evidence": json.loads(row["evidence_json"] or "{}"),
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def strategy_rules(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = """
            SELECT rule_id, name, description, condition_json, effect, status,
                   source, evidence_json, metrics_json, created_at, updated_at
            FROM strategy_rules
            WHERE 1 = 1
        """
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "rule_id": row["rule_id"],
                "name": row["name"],
                "description": row["description"],
                "condition": json.loads(row["condition_json"] or "{}"),
                "effect": row["effect"],
                "status": row["status"],
                "source": row["source"],
                "evidence": json.loads(row["evidence_json"] or "{}"),
                "metrics": json.loads(row["metrics_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_rule_evaluation(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rule_evaluations (
                    evaluation_id, rule_id, memory_id, symbol, would_block,
                    actual_outcome, avoided_loss, missed_gain, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["evaluation_id"],
                    item["rule_id"],
                    item["memory_id"],
                    item["symbol"],
                    int(item.get("would_block", False)),
                    item.get("actual_outcome", "unknown"),
                    float(item.get("avoided_loss") or 0.0),
                    float(item.get("missed_gain") or 0.0),
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or _utc_iso(),
                ),
            )

    def rule_evaluations(self, *, rule_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = """
            SELECT evaluation_id, rule_id, memory_id, symbol, would_block,
                   actual_outcome, avoided_loss, missed_gain, payload_json, created_at
            FROM rule_evaluations
            WHERE 1 = 1
        """
        params: list[Any] = []
        if rule_id:
            query += " AND rule_id = ?"
            params.append(rule_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "evaluation_id": row["evaluation_id"],
                "rule_id": row["rule_id"],
                "memory_id": row["memory_id"],
                "symbol": row["symbol"],
                "would_block": bool(row["would_block"]),
                "actual_outcome": row["actual_outcome"],
                "avoided_loss": row["avoided_loss"],
                "missed_gain": row["missed_gain"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def upsert_learning_observation(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_observations (
                    observation_id, signal_date, symbol, source_family, source_run_ids_json,
                    first_seen_at, last_seen_at, best_signal_id, best_score, decision,
                    explanation, llm_considered, approved_buy, blocked_entry_quality,
                    blocked_backtest, executed_buy, duplicate_count, rank_path_json,
                    features_json, gate_json, outcome_json, execution_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    signal_date=excluded.signal_date,
                    symbol=excluded.symbol,
                    source_family=excluded.source_family,
                    source_run_ids_json=excluded.source_run_ids_json,
                    first_seen_at=excluded.first_seen_at,
                    last_seen_at=excluded.last_seen_at,
                    best_signal_id=excluded.best_signal_id,
                    best_score=excluded.best_score,
                    decision=excluded.decision,
                    explanation=excluded.explanation,
                    llm_considered=excluded.llm_considered,
                    approved_buy=excluded.approved_buy,
                    blocked_entry_quality=excluded.blocked_entry_quality,
                    blocked_backtest=excluded.blocked_backtest,
                    executed_buy=excluded.executed_buy,
                    duplicate_count=excluded.duplicate_count,
                    rank_path_json=excluded.rank_path_json,
                    features_json=excluded.features_json,
                    gate_json=excluded.gate_json,
                    outcome_json=excluded.outcome_json,
                    execution_json=excluded.execution_json,
                    updated_at=excluded.updated_at
                """,
                (
                    item["observation_id"],
                    item["signal_date"],
                    item["symbol"].upper(),
                    item["source_family"],
                    _dumps(item.get("source_run_ids", [])),
                    item.get("first_seen_at"),
                    item.get("last_seen_at"),
                    item.get("best_signal_id"),
                    item.get("best_score"),
                    item.get("decision", "candidate"),
                    item.get("explanation", ""),
                    int(bool(item.get("llm_considered"))),
                    int(bool(item.get("approved_buy"))),
                    int(bool(item.get("blocked_entry_quality"))),
                    int(bool(item.get("blocked_backtest"))),
                    int(bool(item.get("executed_buy"))),
                    int(item.get("duplicate_count") or 0),
                    _dumps(item.get("rank_path", [])),
                    _dumps(item.get("features", {})),
                    _dumps(item.get("gate", {})),
                    _dumps(item.get("outcome", {})),
                    _dumps(item.get("execution", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def learning_observations(
        self,
        *,
        since_date: str | None = None,
        end_date: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT observation_id, signal_date, symbol, source_family, source_run_ids_json,
                   first_seen_at, last_seen_at, best_signal_id, best_score, decision,
                   explanation, llm_considered, approved_buy, blocked_entry_quality,
                   blocked_backtest, executed_buy, duplicate_count, rank_path_json,
                   features_json, gate_json, outcome_json, execution_json, created_at, updated_at
            FROM learning_observations
            WHERE 1 = 1
        """
        params: list[Any] = []
        if since_date:
            query += " AND signal_date >= ?"
            params.append(since_date)
        if end_date:
            query += " AND signal_date <= ?"
            params.append(end_date)
        query += " ORDER BY signal_date DESC, symbol ASC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if not key.endswith("_json")},
                "source_run_ids": json.loads(row["source_run_ids_json"] or "[]"),
                "rank_path": json.loads(row["rank_path_json"] or "[]"),
                "features": json.loads(row["features_json"] or "{}"),
                "gate": json.loads(row["gate_json"] or "{}"),
                "outcome": json.loads(row["outcome_json"] or "{}"),
                "execution": json.loads(row["execution_json"] or "{}"),
                "llm_considered": bool(row["llm_considered"]),
                "approved_buy": bool(row["approved_buy"]),
                "blocked_entry_quality": bool(row["blocked_entry_quality"]),
                "blocked_backtest": bool(row["blocked_backtest"]),
                "executed_buy": bool(row["executed_buy"]),
            }
            for row in rows
        ]

    def upsert_learning_daily_summary(
        self,
        *,
        summary_id: str,
        session_date: str,
        kind: str,
        payload: dict[str, Any],
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_daily_summaries (
                    summary_id, session_date, kind, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    kind=excluded.kind,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    summary_id,
                    session_date,
                    kind,
                    _dumps(payload),
                    now,
                    now,
                ),
            )

    def latest_learning_daily_summary(self, *, kind: str | None = None) -> dict[str, Any] | None:
        query = """
            SELECT summary_id, session_date, kind, payload_json, created_at, updated_at
            FROM learning_daily_summaries
            WHERE 1 = 1
        """
        params: list[Any] = []
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY session_date DESC, updated_at DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return {
            "summary_id": row["summary_id"],
            "session_date": row["session_date"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_learning_policy_candidate(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_policy_candidates (
                    policy_id, name, policy_type, status, scope, auto_activatable,
                    evidence_json, metrics_json, notes, promoted_at, last_evaluated_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    name=excluded.name,
                    policy_type=excluded.policy_type,
                    status=excluded.status,
                    scope=excluded.scope,
                    auto_activatable=excluded.auto_activatable,
                    evidence_json=excluded.evidence_json,
                    metrics_json=excluded.metrics_json,
                    notes=excluded.notes,
                    promoted_at=excluded.promoted_at,
                    last_evaluated_at=excluded.last_evaluated_at,
                    updated_at=excluded.updated_at
                """,
                (
                    item["policy_id"],
                    item["name"],
                    item.get("policy_type", "shadow"),
                    item.get("status", "shadow"),
                    item.get("scope", "global"),
                    int(bool(item.get("auto_activatable"))),
                    _dumps(item.get("evidence", {})),
                    _dumps(item.get("metrics", {})),
                    item.get("notes", ""),
                    item.get("promoted_at"),
                    item.get("last_evaluated_at"),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def learning_policy_candidates(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = """
            SELECT policy_id, name, policy_type, status, scope, auto_activatable,
                   evidence_json, metrics_json, notes, promoted_at, last_evaluated_at,
                   created_at, updated_at
            FROM learning_policy_candidates
            WHERE 1 = 1
        """
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "policy_id": row["policy_id"],
                "name": row["name"],
                "policy_type": row["policy_type"],
                "status": row["status"],
                "scope": row["scope"],
                "auto_activatable": bool(row["auto_activatable"]),
                "evidence": json.loads(row["evidence_json"] or "{}"),
                "metrics": json.loads(row["metrics_json"] or "{}"),
                "notes": row["notes"],
                "promoted_at": row["promoted_at"],
                "last_evaluated_at": row["last_evaluated_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_learning_policy_evaluation(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO learning_policy_evaluations (
                    evaluation_id, policy_id, session_date, phase, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["evaluation_id"],
                    item["policy_id"],
                    item["session_date"],
                    item["phase"],
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or _utc_iso(),
                ),
            )

    def learning_policy_evaluations(
        self,
        *,
        policy_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT evaluation_id, policy_id, session_date, phase, payload_json, created_at
            FROM learning_policy_evaluations
            WHERE 1 = 1
        """
        params: list[Any] = []
        if policy_id:
            query += " AND policy_id = ?"
            params.append(policy_id)
        query += " ORDER BY session_date DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "evaluation_id": row["evaluation_id"],
                "policy_id": row["policy_id"],
                "session_date": row["session_date"],
                "phase": row["phase"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def signal_outcomes(
        self,
        *,
        limit: int = 500,
        since_date: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT signal_id, source_run_id, source, symbol, signal_date,
                   decision, features_json, gate_json, outcome_json,
                   created_at, updated_at
            FROM signal_outcomes
            WHERE 1 = 1
        """
        params: list[Any] = []
        if since_date:
            query += " AND signal_date >= ?"
            params.append(since_date)
        query += " ORDER BY signal_date DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "signal_id": row["signal_id"],
                "source_run_id": row["source_run_id"],
                "source": row["source"],
                "symbol": row["symbol"],
                "signal_date": row["signal_date"],
                "decision": row["decision"],
                "features": json.loads(row["features_json"] or "{}"),
                "gate": json.loads(row["gate_json"] or "{}"),
                "outcome": json.loads(row["outcome_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def latest_executed_buy_plans_by_symbol(self) -> dict[str, dict[str, Any]]:
        """Return latest locally registered buy order plan per symbol."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, payload_json, created_at
                FROM broker_orders
                WHERE lower(side) = 'buy'
                ORDER BY created_at DESC
                """
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            if symbol in result:
                continue
            payload = json.loads(row["payload_json"])
            plan = payload.get("plan", {}) or {}
            result[symbol] = {
                "symbol": symbol,
                "created_at": row["created_at"],
                "plan": plan,
                "broker_order": payload.get("broker_order", {}),
            }
        return result

    def count_broker_orders(
        self,
        *,
        side: str | None = None,
        since_iso: str | None = None,
    ) -> int:
        """Count locally registered broker orders, optionally filtered by side/date."""

        query = "SELECT COUNT(*) AS count FROM broker_orders WHERE 1 = 1"
        params: list[Any] = []
        if side:
            query += " AND lower(side) = ?"
            params.append(side.lower())
        if since_iso:
            query += " AND created_at >= ?"
            params.append(since_iso)

        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["count"] or 0)

    def status(self) -> dict[str, Any]:
        self.ensure_schema()
        with self.connect() as conn:
            tables = {}
            for table in (
                "agent_events",
                "hypotheses",
                "backtest_runs",
                "decisions",
                "trade_recommendations",
                "order_plans",
                "broker_orders",
                "signal_outcomes",
                "trade_memory",
                "strategy_rules",
                "rule_evaluations",
                "learning_observations",
                "learning_daily_summaries",
                "learning_policy_candidates",
                "learning_policy_evaluations",
                "pre_earnings_predictions",
                "pre_earnings_analyst_snapshots",
            ):
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                tables[table] = row["count"]
        return {
            "database": str(self.database_path),
            "tables": tables,
        }

    def latest_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, agent, event_type, cycle_id, payload_json, created_at
                FROM agent_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def event_from_dict(
    agent: str,
    event_type: str,
    payload: dict[str, Any],
    cycle_id: str | None,
) -> AgentEvent:
    return AgentEvent(agent=agent, event_type=event_type, payload=payload, cycle_id=cycle_id)


def hypothesis_to_dict(hypothesis: Hypothesis) -> dict[str, Any]:
    return asdict(hypothesis)
