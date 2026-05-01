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
