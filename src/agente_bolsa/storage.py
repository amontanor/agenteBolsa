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
    created_at TEXT NOT NULL,
    role TEXT
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

CREATE TABLE IF NOT EXISTS opportunity_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    session_date TEXT NOT NULL,
    slot_time TEXT NOT NULL,
    run_id TEXT,
    report_path TEXT,
    opportunities_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_snapshots_unique
ON opportunity_snapshots(session_date, slot_time);

CREATE INDEX IF NOT EXISTS idx_opportunity_snapshots_date_time
ON opportunity_snapshots(session_date DESC, slot_time DESC);

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

CREATE TABLE IF NOT EXISTS continuous_improvement_cycles (
    cycle_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    dedupe_key TEXT UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    context_json TEXT NOT NULL,
    evaluation_json TEXT NOT NULL,
    llm_call_id TEXT,
    llm_status TEXT,
    error_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ci_cycles_status_updated
ON continuous_improvement_cycles(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_llm_responses (
    llm_call_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    raw_response TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS continuous_improvement_proposals (
    proposal_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    proposal_type TEXT NOT NULL,
    target_component TEXT NOT NULL,
    target_identifier TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    guard_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_proposals_status_updated
ON continuous_improvement_proposals(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_validations (
    validation_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    status TEXT NOT NULL,
    validation_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(proposal_id) REFERENCES continuous_improvement_proposals(proposal_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS continuous_improvement_decisions (
    decision_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(proposal_id) REFERENCES continuous_improvement_proposals(proposal_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS continuous_improvement_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    priority TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    cooldown_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ci_events_status_updated
ON continuous_improvement_events(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_agent_tasks (
    task_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    event_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    dependency_ids_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    error_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(event_id) REFERENCES continuous_improvement_events(event_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_tasks_status_updated
ON continuous_improvement_agent_tasks(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_memories (
    memory_key TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_event_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_event_id) REFERENCES continuous_improvement_events(event_id)
);

CREATE TABLE IF NOT EXISTS continuous_improvement_hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    event_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    summary_text TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    source_task_ids_json TEXT NOT NULL,
    proposal_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES continuous_improvement_events(event_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_hypotheses_status_updated
ON continuous_improvement_hypotheses(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_proposal_artifacts (
    artifact_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    content_text TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(proposal_id) REFERENCES continuous_improvement_proposals(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_artifacts_proposal
ON continuous_improvement_proposal_artifacts(proposal_id, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_runtime_state (
    runtime_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS continuous_improvement_initiatives (
    initiative_id TEXT PRIMARY KEY,
    initiative_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_agent TEXT NOT NULL,
    priority TEXT NOT NULL,
    target_metric TEXT NOT NULL,
    baseline_value REAL,
    current_value REAL,
    expected_impact TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    linked_event_ids_json TEXT NOT NULL,
    linked_task_ids_json TEXT NOT NULL,
    linked_hypothesis_ids_json TEXT NOT NULL,
    linked_proposal_ids_json TEXT NOT NULL,
    linked_validation_ids_json TEXT NOT NULL,
    latest_decision_json TEXT NOT NULL,
    next_action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ci_initiatives_status_updated
ON continuous_improvement_initiatives(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_initiative_messages (
    message_id TEXT PRIMARY KEY,
    initiative_id TEXT NOT NULL,
    cycle_id TEXT,
    event_id TEXT,
    task_id TEXT,
    agent_name TEXT NOT NULL,
    role TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(initiative_id) REFERENCES continuous_improvement_initiatives(initiative_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_initiative_messages_initiative_created
ON continuous_improvement_initiative_messages(initiative_id, created_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_experiments (
    experiment_id TEXT PRIMARY KEY,
    initiative_id TEXT,
    proposal_id TEXT,
    cycle_id TEXT,
    experiment_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_json TEXT NOT NULL,
    period_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    artifact_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(initiative_id) REFERENCES continuous_improvement_initiatives(initiative_id),
    FOREIGN KEY(proposal_id) REFERENCES continuous_improvement_proposals(proposal_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_experiments_status_updated
ON continuous_improvement_experiments(status, updated_at);

CREATE TABLE IF NOT EXISTS continuous_improvement_applied_changes (
    applied_change_id TEXT PRIMARY KEY,
    initiative_id TEXT,
    proposal_id TEXT,
    cycle_id TEXT,
    status TEXT NOT NULL,
    change_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    rollback_json TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    validation_ids_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(initiative_id) REFERENCES continuous_improvement_initiatives(initiative_id),
    FOREIGN KEY(proposal_id) REFERENCES continuous_improvement_proposals(proposal_id),
    FOREIGN KEY(cycle_id) REFERENCES continuous_improvement_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_ci_applied_changes_status_updated
ON continuous_improvement_applied_changes(status, updated_at);

CREATE TABLE IF NOT EXISTS performance_daily (
    session_date TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    equity REAL,
    pnl_pct REAL,
    spy_pct REAL,
    alpha REAL,
    hit_rate_20 REAL,
    sharpe_60 REAL,
    max_dd REAL,
    iq_score REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_performance_daily_date
ON performance_daily(session_date);

CREATE TABLE IF NOT EXISTS promotion_windows (
    window_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    version TEXT NOT NULL,
    slot TEXT,
    started_at TEXT NOT NULL,
    min_sessions INTEGER NOT NULL,
    min_signals INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_promotion_windows_status
ON promotion_windows(status, updated_at);

CREATE TABLE IF NOT EXISTS prompt_versions (
    prompt_id TEXT PRIMARY KEY,
    prompt_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    template TEXT NOT NULL,
    status TEXT NOT NULL,
    parent_version INTEGER,
    created_by TEXT,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_key_status
ON prompt_versions(prompt_key, status);

CREATE TABLE IF NOT EXISTS agent_definitions (
    agent_key TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    goal TEXT NOT NULL,
    prompt_key TEXT,
    inputs_json TEXT NOT NULL,
    output_schema_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT,
    performance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS distilled_lessons (
    lesson_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    statement TEXT NOT NULL,
    supporting_cases INTEGER NOT NULL,
    contradicting_cases INTEGER NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    last_validated_at TEXT,
    source_refs_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_distilled_lessons_status
ON distilled_lessons(status, scope);

CREATE TABLE IF NOT EXISTS market_thesis (
    thesis_date TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    stance TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_evidence (
    evidence_id TEXT PRIMARY KEY,
    symbol TEXT,
    scope TEXT NOT NULL,
    topic TEXT,
    source_type TEXT NOT NULL,
    source_name TEXT,
    provider TEXT,
    url TEXT,
    title TEXT,
    summary TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    reliability_score REAL NOT NULL,
    freshness_hours REAL,
    staleness_status TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_evidence_symbol_updated
ON research_evidence(symbol, updated_at);

CREATE INDEX IF NOT EXISTS idx_research_evidence_scope_updated
ON research_evidence(scope, updated_at);

CREATE TABLE IF NOT EXISTS factory_runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    variants INTEGER NOT NULL,
    survivors INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_factory_runs_date
ON factory_runs(run_date);

CREATE TABLE IF NOT EXISTS pattern_stats (
    pattern_key TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    regime TEXT NOT NULL,
    occurrences INTEGER NOT NULL,
    hit_rate REAL,
    expectancy REAL,
    lift REAL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _loads_list(value: str | None) -> list[Any]:
    loaded = json.loads(value or "[]")
    return loaded if isinstance(loaded, list) else []


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bullish_confirmed_count(features: dict[str, Any]) -> int:
    chart_patterns = features.get("chart_patterns", {}) or {}
    if isinstance(chart_patterns, dict):
        return int(chart_patterns.get("bullish_confirmed_count") or 0)
    if isinstance(chart_patterns, list):
        return sum(
            1
            for item in chart_patterns
            if item.get("bias") == "bullish" and item.get("status") == "confirmed"
        )
    return 0


class Store:
    def __init__(self, database_path: Path, agent_logs_dir: Path) -> None:
        self.database_path = database_path
        self.agent_history = AgentHistoryLogger(agent_logs_dir)
        self._db_dir_ready = False

    def _ensure_db_dir(self) -> None:
        # D4: crear el directorio una sola vez, no en cada connect() (camino caliente).
        if not self._db_dir_ready:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_dir_ready = True

    def connect(self) -> sqlite3.Connection:
        self._ensure_db_dir()
        conn = sqlite3.connect(self.database_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            # Migraciones defensivas e idempotentes para bases preexistentes.
            self._ensure_column(conn, "llm_usage", "role", "TEXT")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
        role: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_usage (
                    usage_id, source, model, request_count, prompt_tokens,
                    completion_tokens, total_tokens, payload_json, created_at, role
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    role,
                ),
            )

    def llm_usage_by_role(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(role, 'unspecified') AS role,
                       COUNT(*) AS requests,
                       SUM(prompt_tokens) AS prompt_tokens,
                       SUM(completion_tokens) AS completion_tokens,
                       SUM(total_tokens) AS total_tokens
                FROM (SELECT * FROM llm_usage ORDER BY created_at DESC LIMIT ?)
                GROUP BY COALESCE(role, 'unspecified')
                ORDER BY total_tokens DESC
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "role": row["role"],
                "requests": int(row["requests"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
            }
            for row in rows
        ]

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
                       completion_tokens, total_tokens, payload_json, created_at, role
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

    def upsert_opportunity_snapshot(
        self,
        *,
        snapshot_id: str,
        session_date: str,
        slot_time: str,
        run_id: str | None,
        report_path: str | None,
        opportunities: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO opportunity_snapshots (
                    snapshot_id, session_date, slot_time, run_id, report_path,
                    opportunities_json, summary_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_date, slot_time) DO UPDATE SET
                    snapshot_id=excluded.snapshot_id,
                    run_id=excluded.run_id,
                    report_path=excluded.report_path,
                    opportunities_json=excluded.opportunities_json,
                    summary_json=excluded.summary_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot_id,
                    session_date,
                    slot_time,
                    run_id,
                    report_path,
                    _dumps(opportunities),
                    _dumps(summary),
                    now,
                    now,
                ),
            )

    def opportunity_snapshots(
        self,
        *,
        session_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT snapshot_id, session_date, slot_time, run_id, report_path,
                   opportunities_json, summary_json, created_at, updated_at
            FROM opportunity_snapshots
            WHERE 1 = 1
        """
        params: list[Any] = []
        if session_date:
            query += " AND session_date = ?"
            params.append(session_date)
        query += " ORDER BY session_date DESC, slot_time DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "snapshot_id": row["snapshot_id"],
                "session_date": row["session_date"],
                "slot_time": row["slot_time"],
                "run_id": row["run_id"],
                "report_path": row["report_path"],
                "opportunities": json.loads(row["opportunities_json"] or "[]"),
                "summary": json.loads(row["summary_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def latest_opportunity_snapshot(self) -> dict[str, Any] | None:
        rows = self.opportunity_snapshots(limit=1)
        return rows[0] if rows else None

    def opportunity_snapshot_dates(self, limit: int = 60) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT session_date
                FROM opportunity_snapshots
                ORDER BY session_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [str(row["session_date"]) for row in rows]

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

    def save_signal_outcomes_bulk(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        now = _utc_iso()
        payload = [
            (
                item["signal_id"],
                item["source_run_id"],
                item["source"],
                str(item["symbol"]).upper(),
                item["signal_date"],
                item["decision"],
                _dumps(item["features"]),
                _dumps(item.get("gate") or {}),
                _dumps(item.get("outcome") or {}),
                now,
                now,
            )
            for item in items
        ]
        with self.connect() as conn:
            conn.executemany(
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
                payload,
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

    def update_signal_gate(
        self,
        *,
        source_run_id: str,
        symbol: str,
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
                SET gate_json = ?, updated_at = ?
                WHERE source_run_id = ? AND symbol = ?
                """,
                (_dumps(existing_gate), _utc_iso(), source_run_id, symbol.upper()),
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

    def upsert_promotion_window(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO promotion_windows (
                    window_id, strategy, version, slot, started_at, min_sessions,
                    min_signals, status, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(window_id) DO UPDATE SET
                    status=excluded.status,
                    started_at=excluded.started_at,
                    result_json=excluded.result_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(item["window_id"]),
                    str(item["strategy"]),
                    str(item.get("version", "1")),
                    item.get("slot"),
                    item.get("started_at") or now,
                    int(item.get("min_sessions", 10)),
                    int(item.get("min_signals", 20)),
                    str(item.get("status", "OPEN")),
                    _dumps(item.get("result", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def promotion_windows(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM promotion_windows WHERE 1 = 1"
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
                "window_id": row["window_id"],
                "strategy": row["strategy"],
                "version": row["version"],
                "slot": row["slot"],
                "started_at": row["started_at"],
                "min_sessions": row["min_sessions"],
                "min_signals": row["min_signals"],
                "status": row["status"],
                "result": json.loads(row["result_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # -- market_thesis (T3.1) ---------------------------------------------
    def upsert_market_thesis(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_thesis (thesis_date, payload_json, stance, confidence, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thesis_date) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    stance=excluded.stance,
                    confidence=excluded.confidence
                """,
                (
                    str(item["thesis_date"]),
                    _dumps(item.get("payload", {})),
                    item.get("stance"),
                    _num(item.get("confidence")),
                    _utc_iso(),
                ),
            )

    def latest_market_thesis(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_thesis ORDER BY thesis_date DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {
            "thesis_date": row["thesis_date"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "stance": row["stance"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
        }

    # -- research_evidence -----------------------------------------------
    def upsert_research_evidence(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_evidence (
                    evidence_id, symbol, scope, topic, source_type, source_name, provider,
                    url, title, summary, published_at, fetched_at, reliability_score,
                    freshness_hours, staleness_status, quality_status, content_hash,
                    payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    scope=excluded.scope,
                    topic=excluded.topic,
                    source_type=excluded.source_type,
                    source_name=excluded.source_name,
                    provider=excluded.provider,
                    url=excluded.url,
                    title=excluded.title,
                    summary=excluded.summary,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    reliability_score=excluded.reliability_score,
                    freshness_hours=excluded.freshness_hours,
                    staleness_status=excluded.staleness_status,
                    quality_status=excluded.quality_status,
                    content_hash=excluded.content_hash,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(item["evidence_id"]),
                    item.get("symbol"),
                    str(item.get("scope", "market")),
                    item.get("topic"),
                    str(item.get("source_type", "unknown")),
                    item.get("source_name"),
                    item.get("provider"),
                    item.get("url"),
                    item.get("title"),
                    item.get("summary"),
                    item.get("published_at"),
                    item.get("fetched_at") or now,
                    float(item.get("reliability_score", 0.0)),
                    _num(item.get("freshness_hours")),
                    str(item.get("staleness_status", "fresh")),
                    str(item.get("quality_status", "available")),
                    str(item.get("content_hash", "")),
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def research_evidence(
        self,
        *,
        symbol: str | None = None,
        scope: str | None = None,
        quality_status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM research_evidence WHERE 1 = 1"
        params: list[Any] = []
        if symbol:
            query += " AND upper(coalesce(symbol, '')) = ?"
            params.append(str(symbol).upper())
        if scope:
            query += " AND scope = ?"
            params.append(scope)
        if quality_status:
            query += " AND quality_status = ?"
            params.append(quality_status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "evidence_id": row["evidence_id"],
                "symbol": row["symbol"],
                "scope": row["scope"],
                "topic": row["topic"],
                "source_type": row["source_type"],
                "source_name": row["source_name"],
                "provider": row["provider"],
                "url": row["url"],
                "title": row["title"],
                "summary": row["summary"],
                "published_at": row["published_at"],
                "fetched_at": row["fetched_at"],
                "reliability_score": row["reliability_score"],
                "freshness_hours": row["freshness_hours"],
                "staleness_status": row["staleness_status"],
                "quality_status": row["quality_status"],
                "content_hash": row["content_hash"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # -- factory_runs (T3.2) ----------------------------------------------
    def save_factory_run(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO factory_runs (run_id, run_date, variants, survivors, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item["run_id"]),
                    str(item.get("run_date")),
                    int(item.get("variants", 0)),
                    int(item.get("survivors", 0)),
                    _dumps(item.get("payload", {})),
                    _utc_iso(),
                ),
            )

    def factory_runs(self, *, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM factory_runs ORDER BY run_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "run_date": row["run_date"],
                "variants": row["variants"],
                "survivors": row["survivors"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # -- pattern_stats (T3.3) ---------------------------------------------
    def upsert_pattern_stat(self, item: dict[str, Any]) -> None:
        pattern_key = str(item.get("pattern_key") or f"{item['pattern']}:{item.get('regime', 'all')}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pattern_stats (
                    pattern_key, pattern, regime, occurrences, hit_rate, expectancy, lift, status, payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_key) DO UPDATE SET
                    occurrences=excluded.occurrences,
                    hit_rate=excluded.hit_rate,
                    expectancy=excluded.expectancy,
                    lift=excluded.lift,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    pattern_key,
                    str(item["pattern"]),
                    str(item.get("regime", "all")),
                    int(item.get("occurrences", 0)),
                    _num(item.get("hit_rate")),
                    _num(item.get("expectancy")),
                    _num(item.get("lift")),
                    str(item.get("status", "ACTIVE")),
                    _dumps(item.get("payload", {})),
                    _utc_iso(),
                ),
            )

    def pattern_stats(self, *, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM pattern_stats WHERE 1 = 1"
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
                "pattern_key": row["pattern_key"],
                "pattern": row["pattern"],
                "regime": row["regime"],
                "occurrences": row["occurrences"],
                "hit_rate": row["hit_rate"],
                "expectancy": row["expectancy"],
                "lift": row["lift"],
                "status": row["status"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # -- prompt_versions (T2.1) -------------------------------------------
    def next_prompt_version(self, prompt_key: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM prompt_versions WHERE prompt_key = ?",
                (prompt_key,),
            ).fetchone()
        return int(row["v"] or 0) + 1

    def upsert_prompt_version(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        prompt_id = str(item.get("prompt_id") or f"{item['prompt_key']}:{item['version']}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_versions (
                    prompt_id, prompt_key, version, template, status, parent_version,
                    created_by, metrics_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_id) DO UPDATE SET
                    template=excluded.template,
                    status=excluded.status,
                    metrics_json=excluded.metrics_json
                """,
                (
                    prompt_id,
                    str(item["prompt_key"]),
                    int(item["version"]),
                    str(item["template"]),
                    str(item.get("status", "CANDIDATE")),
                    item.get("parent_version"),
                    item.get("created_by"),
                    _dumps(item.get("metrics", {})),
                    item.get("created_at") or now,
                ),
            )

    def prompt_versions(self, *, prompt_key: str | None = None, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM prompt_versions WHERE 1 = 1"
        params: list[Any] = []
        if prompt_key:
            query += " AND prompt_key = ?"
            params.append(prompt_key)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY prompt_key ASC, version DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "prompt_id": row["prompt_id"],
                "prompt_key": row["prompt_key"],
                "version": row["version"],
                "template": row["template"],
                "status": row["status"],
                "parent_version": row["parent_version"],
                "created_by": row["created_by"],
                "metrics": json.loads(row["metrics_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def active_prompt(self, prompt_key: str) -> dict[str, Any] | None:
        rows = self.prompt_versions(prompt_key=prompt_key, status="ACTIVE", limit=1)
        return rows[0] if rows else None

    def set_prompt_status(self, prompt_key: str, version: int, status: str) -> None:
        with self.connect() as conn:
            if status == "ACTIVE":
                conn.execute(
                    "UPDATE prompt_versions SET status='RETIRED' WHERE prompt_key=? AND status='ACTIVE'",
                    (prompt_key,),
                )
            conn.execute(
                "UPDATE prompt_versions SET status=? WHERE prompt_key=? AND version=?",
                (status, prompt_key, int(version)),
            )

    # -- agent_definitions (T2.2) -----------------------------------------
    def upsert_agent_definition(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_definitions (
                    agent_key, role, goal, prompt_key, inputs_json, output_schema_json,
                    status, created_by, performance_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_key) DO UPDATE SET
                    role=excluded.role,
                    goal=excluded.goal,
                    prompt_key=excluded.prompt_key,
                    inputs_json=excluded.inputs_json,
                    output_schema_json=excluded.output_schema_json,
                    status=excluded.status,
                    performance_json=excluded.performance_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(item["agent_key"]),
                    str(item.get("role", "")),
                    str(item.get("goal", "")),
                    item.get("prompt_key"),
                    _dumps(item.get("inputs", [])),
                    _dumps(item.get("output_schema", {})),
                    str(item.get("status", "ACTIVE")),
                    item.get("created_by"),
                    _dumps(item.get("performance", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def agent_definitions(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_definitions WHERE 1 = 1"
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
                "agent_key": row["agent_key"],
                "role": row["role"],
                "goal": row["goal"],
                "prompt_key": row["prompt_key"],
                "inputs": json.loads(row["inputs_json"] or "[]"),
                "output_schema": json.loads(row["output_schema_json"] or "{}"),
                "status": row["status"],
                "created_by": row["created_by"],
                "performance": json.loads(row["performance_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def set_agent_status(self, agent_key: str, status: str, *, performance: dict[str, Any] | None = None) -> int:
        with self.connect() as conn:
            if performance is not None:
                cursor = conn.execute(
                    "UPDATE agent_definitions SET status=?, performance_json=?, updated_at=? WHERE agent_key=?",
                    (status, _dumps(performance), _utc_iso(), agent_key),
                )
            else:
                cursor = conn.execute(
                    "UPDATE agent_definitions SET status=?, updated_at=? WHERE agent_key=?",
                    (status, _utc_iso(), agent_key),
                )
            return cursor.rowcount

    # -- distilled_lessons (T2.4) -----------------------------------------
    def upsert_distilled_lesson(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO distilled_lessons (
                    lesson_id, scope, statement, supporting_cases, contradicting_cases,
                    confidence, status, last_validated_at, source_refs_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lesson_id) DO UPDATE SET
                    scope=excluded.scope,
                    statement=excluded.statement,
                    supporting_cases=excluded.supporting_cases,
                    contradicting_cases=excluded.contradicting_cases,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    last_validated_at=excluded.last_validated_at,
                    source_refs_json=excluded.source_refs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(item["lesson_id"]),
                    str(item.get("scope", "process")),
                    str(item.get("statement", "")),
                    int(item.get("supporting_cases", 0)),
                    int(item.get("contradicting_cases", 0)),
                    float(item.get("confidence", 0.0)),
                    str(item.get("status", "ACTIVE")),
                    item.get("last_validated_at") or now,
                    _dumps(item.get("source_refs", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def distilled_lessons(self, *, status: str | None = None, scope: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM distilled_lessons WHERE 1 = 1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if scope:
            query += " AND scope = ?"
            params.append(scope)
        query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "lesson_id": row["lesson_id"],
                "scope": row["scope"],
                "statement": row["statement"],
                "supporting_cases": row["supporting_cases"],
                "contradicting_cases": row["contradicting_cases"],
                "confidence": row["confidence"],
                "status": row["status"],
                "last_validated_at": row["last_validated_at"],
                "source_refs": json.loads(row["source_refs_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def set_lesson_status(self, lesson_id: str, status: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE distilled_lessons SET status=?, updated_at=? WHERE lesson_id=?",
                (status, _utc_iso(), lesson_id),
            )
            return cursor.rowcount

    def upsert_strategy_version(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        strategy_id = str(item.get("strategy_id") or f"{item['name']}:{item.get('version', '1')}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_versions (
                    strategy_id, name, version, status, source_path, metrics_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name=excluded.name,
                    version=excluded.version,
                    status=excluded.status,
                    source_path=excluded.source_path,
                    metrics_json=excluded.metrics_json,
                    updated_at=excluded.updated_at
                """,
                (
                    strategy_id,
                    str(item["name"]),
                    str(item.get("version", "1")),
                    str(item.get("status", "ACTIVE")),
                    item.get("source_path"),
                    _dumps(item.get("metrics", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def strategy_versions(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM strategy_versions WHERE 1 = 1"
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
                "strategy_id": row["strategy_id"],
                "name": row["name"],
                "version": row["version"],
                "status": row["status"],
                "source_path": row["source_path"],
                "metrics": json.loads(row["metrics_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def set_strategy_status(self, name: str, status: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE strategy_versions SET status = ?, updated_at = ? WHERE name = ?",
                (status, _utc_iso(), name),
            )
            return cursor.rowcount

    def upsert_performance_daily(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO performance_daily (
                    session_date, payload_json, equity, pnl_pct, spy_pct, alpha,
                    hit_rate_20, sharpe_60, max_dd, iq_score, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    equity=excluded.equity,
                    pnl_pct=excluded.pnl_pct,
                    spy_pct=excluded.spy_pct,
                    alpha=excluded.alpha,
                    hit_rate_20=excluded.hit_rate_20,
                    sharpe_60=excluded.sharpe_60,
                    max_dd=excluded.max_dd,
                    iq_score=excluded.iq_score
                """,
                (
                    str(item.get("session_date")),
                    _dumps(item.get("payload", {})),
                    _num(item.get("equity")),
                    _num(item.get("pnl_pct")),
                    _num(item.get("spy_pct")),
                    _num(item.get("alpha")),
                    _num(item.get("hit_rate_20")),
                    _num(item.get("sharpe_60")),
                    _num(item.get("max_dd")),
                    _num(item.get("iq_score")),
                    _utc_iso(),
                ),
            )

    def performance_daily(
        self,
        *,
        limit: int = 90,
        since_date: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM performance_daily WHERE 1 = 1"
        params: list[Any] = []
        if since_date:
            query += " AND session_date >= ?"
            params.append(since_date)
        query += " ORDER BY session_date ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "session_date": row["session_date"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "equity": row["equity"],
                "pnl_pct": row["pnl_pct"],
                "spy_pct": row["spy_pct"],
                "alpha": row["alpha"],
                "hit_rate_20": row["hit_rate_20"],
                "sharpe_60": row["sharpe_60"],
                "max_dd": row["max_dd"],
                "iq_score": row["iq_score"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def latest_performance_daily(self) -> dict[str, Any] | None:
        rows = self.performance_daily(limit=0)
        return rows[-1] if rows else None

    def same_session_intraday_signal_summary(
        self,
        *,
        session_date: str,
        symbols: list[str] | None = None,
        source: str = "intraday_scan",
    ) -> dict[str, dict[str, Any]]:
        query = """
            SELECT symbol, decision, features_json, created_at
            FROM signal_outcomes
            WHERE signal_date = ?
              AND source = ?
        """
        params: list[Any] = [session_date, source]
        normalized_symbols = sorted({str(symbol).upper() for symbol in (symbols or []) if str(symbol).strip()})
        if normalized_symbols:
            placeholders = ",".join("?" for _ in normalized_symbols)
            query += f" AND symbol IN ({placeholders})"
            params.extend(normalized_symbols)
        query += " ORDER BY symbol ASC, created_at ASC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            grouped.setdefault(symbol, []).append(
                {
                    "decision": row["decision"],
                    "features": json.loads(row["features_json"] or "{}"),
                    "created_at": row["created_at"],
                }
            )

        result: dict[str, dict[str, Any]] = {}
        for symbol, items in grouped.items():
            if not items:
                continue
            first = items[0]
            latest = items[-1]
            first_features = first.get("features", {}) or {}
            latest_features = latest.get("features", {}) or {}
            direction = str(latest_features.get("direction") or first_features.get("direction") or "long").lower()
            first_entry = _num(first_features.get("entry_price") or first_features.get("close"))
            latest_entry = _num(latest_features.get("entry_price") or latest_features.get("close"))
            same_session_return = None
            if first_entry and latest_entry:
                if direction == "short":
                    same_session_return = (first_entry - latest_entry) / first_entry
                else:
                    same_session_return = (latest_entry - first_entry) / first_entry
            result[symbol] = {
                "symbol": symbol,
                "observations": len(items),
                "same_session_return": round(same_session_return, 4) if same_session_return is not None else None,
                "selected_for_llm": any(bool((item.get("features", {}) or {}).get("selected_for_llm")) for item in items),
                "latest_decision": latest.get("decision"),
                "latest_score": _num(latest_features.get("score")),
                "latest_rsi_14": _num(latest_features.get("rsi_14")),
                "latest_volume_zscore_20": _num(latest_features.get("volume_zscore_20")),
                "latest_distance_sma20": _num(latest_features.get("distance_sma20")),
                "latest_bullish_confirmed_patterns": _bullish_confirmed_count(latest_features),
                "first_seen_at": first.get("created_at"),
                "last_seen_at": latest.get("created_at"),
            }
        return result

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

    def create_continuous_improvement_cycle(self, item: dict[str, Any]) -> None:
        from .continuous_improvement.persistence_compaction import (
            compact_cycle_context,
            compact_cycle_report,
        )

        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO continuous_improvement_cycles (
                    cycle_id, trace_id, job_id, status, mode, dry_run, dedupe_key,
                    started_at, finished_at, context_json, evaluation_json, llm_call_id,
                    llm_status, error_json, report_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["cycle_id"],
                    item["trace_id"],
                    item["job_id"],
                    item.get("status", "PENDING"),
                    item.get("mode", "manual"),
                    int(bool(item.get("dry_run", True))),
                    item.get("dedupe_key"),
                    item.get("started_at") or now,
                    item.get("finished_at"),
                    _dumps(compact_cycle_context(item.get("context", {}))),
                    _dumps(item.get("evaluation", {})),
                    item.get("llm_call_id"),
                    item.get("llm_status"),
                    _dumps(item.get("error", {})),
                    _dumps(compact_cycle_report(item.get("report", {}))),
                    now,
                    now,
                ),
            )

    def update_continuous_improvement_cycle(self, cycle_id: str, **updates: Any) -> None:
        from .continuous_improvement.persistence_compaction import (
            compact_cycle_context,
            compact_cycle_report,
        )

        allowed = {
            "status": "status",
            "finished_at": "finished_at",
            "dedupe_key": "dedupe_key",
            "context": "context_json",
            "evaluation": "evaluation_json",
            "llm_call_id": "llm_call_id",
            "llm_status": "llm_status",
            "error": "error_json",
            "report": "report_json",
        }
        assignments = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            assignments.append(f"{column} = ?")
            value = updates[key]
            if column.endswith("_json"):
                if key == "context":
                    value = compact_cycle_context(value)
                elif key == "report":
                    value = compact_cycle_report(value)
                value = _dumps(value if value is not None else ([] if key.startswith("linked_") else {}))
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = ?")
        values.append(_utc_iso())
        values.append(cycle_id)
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE continuous_improvement_cycles
                SET {", ".join(assignments)}
                WHERE cycle_id = ?
                """,
                values,
            )

    def continuous_improvement_cycle_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT cycle_id, trace_id, job_id, status, mode, dry_run, dedupe_key,
                       started_at, finished_at, context_json, evaluation_json,
                       llm_call_id, llm_status, error_json, report_json, created_at, updated_at
                FROM continuous_improvement_cycles
                WHERE dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchone()
        return self._continuous_improvement_cycle_from_row(row) if row else None

    def latest_continuous_improvement_cycle(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT cycle_id, trace_id, job_id, status, mode, dry_run, dedupe_key,
                       started_at, finished_at, context_json, evaluation_json,
                       llm_call_id, llm_status, error_json, report_json, created_at, updated_at
                FROM continuous_improvement_cycles
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._continuous_improvement_cycle_from_row(row) if row else None

    def continuous_improvement_cycles(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT cycle_id, trace_id, job_id, status, mode, dry_run, dedupe_key,
                       started_at, finished_at, context_json, evaluation_json,
                       llm_call_id, llm_status, error_json, report_json, created_at, updated_at
                FROM continuous_improvement_cycles
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._continuous_improvement_cycle_from_row(row) for row in rows]

    def continuous_improvement_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT cycle_id, trace_id, job_id, status, mode, dry_run, dedupe_key,
                       started_at, finished_at, context_json, evaluation_json,
                       llm_call_id, llm_status, error_json, report_json, created_at, updated_at
                FROM continuous_improvement_cycles
                WHERE cycle_id = ?
                """,
                (cycle_id,),
            ).fetchone()
        if not row:
            return None
        cycle = self._continuous_improvement_cycle_from_row(row)
        cycle["proposals"] = self.continuous_improvement_proposals(cycle_id=cycle_id, limit=500)
        cycle["validations"] = self.continuous_improvement_validations(cycle_id=cycle_id)
        return cycle

    def _continuous_improvement_cycle_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "cycle_id": row["cycle_id"],
            "trace_id": row["trace_id"],
            "job_id": row["job_id"],
            "status": row["status"],
            "mode": row["mode"],
            "dry_run": bool(row["dry_run"]),
            "dedupe_key": row["dedupe_key"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "context": json.loads(row["context_json"] or "{}"),
            "evaluation": json.loads(row["evaluation_json"] or "{}"),
            "llm_call_id": row["llm_call_id"],
            "llm_status": row["llm_status"],
            "error": json.loads(row["error_json"] or "{}"),
            "report": json.loads(row["report_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_continuous_improvement_llm_response(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_llm_responses (
                    llm_call_id, cycle_id, provider, model, status, request_json,
                    response_json, raw_response, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["llm_call_id"],
                    item["cycle_id"],
                    item.get("provider", ""),
                    item.get("model", ""),
                    item.get("status", "unknown"),
                    _dumps(item.get("request", {})),
                    _dumps(item.get("response", {})),
                    item.get("raw_response"),
                    item.get("error"),
                    item.get("created_at") or _utc_iso(),
                ),
            )

    def upsert_continuous_improvement_proposal(self, item: dict[str, Any]) -> tuple[str, bool]:
        now = _utc_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT proposal_id
                FROM continuous_improvement_proposals
                WHERE fingerprint = ?
                """,
                (item["fingerprint"],),
            ).fetchone()
            if existing:
                return str(existing["proposal_id"]), False
            conn.execute(
                """
                INSERT INTO continuous_improvement_proposals (
                    proposal_id, cycle_id, fingerprint, proposal_type, target_component,
                    target_identifier, status, priority, risk_level, payload_json,
                    guard_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["proposal_id"],
                    item["cycle_id"],
                    item["fingerprint"],
                    item.get("proposal_type", "MONITORING_CHANGE"),
                    item.get("target_component", ""),
                    item.get("target_identifier", ""),
                    item.get("status", "PENDING"),
                    item.get("priority", "MEDIUM"),
                    item.get("risk_level", "MEDIUM"),
                    _dumps(item.get("payload", {})),
                    _dumps(item.get("guard", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )
        return item["proposal_id"], True

    def update_continuous_improvement_proposal_status(
        self,
        proposal_id: str,
        *,
        status: str,
        actor: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT cycle_id FROM continuous_improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if not row:
                raise KeyError(proposal_id)
            conn.execute(
                """
                UPDATE continuous_improvement_proposals
                SET status = ?, updated_at = ?
                WHERE proposal_id = ?
                """,
                (status, now, proposal_id),
            )
            conn.execute(
                """
                INSERT INTO continuous_improvement_decisions (
                    decision_id, proposal_id, cycle_id, decision, reason, actor,
                    payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"ci_decision_{proposal_id}_{now}",
                    proposal_id,
                    row["cycle_id"],
                    status,
                    reason,
                    actor,
                    _dumps(payload or {}),
                    now,
                ),
            )

    def save_continuous_improvement_decision(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_decisions (
                    decision_id, proposal_id, cycle_id, decision, reason, actor,
                    payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("decision_id") or f"ci_decision_{item['proposal_id']}_{now}",
                    item["proposal_id"],
                    item["cycle_id"],
                    item["decision"],
                    item.get("reason") or "",
                    item.get("actor") or "system",
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or now,
                ),
            )

    def continuous_improvement_decisions(
        self,
        *,
        proposal_id: str | None = None,
        cycle_id: str | None = None,
        actor: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT decision_id, proposal_id, cycle_id, decision, reason, actor,
                   payload_json, created_at
            FROM continuous_improvement_decisions
            WHERE 1 = 1
        """
        params: list[Any] = []
        if proposal_id:
            query += " AND proposal_id = ?"
            params.append(proposal_id)
        if cycle_id:
            query += " AND cycle_id = ?"
            params.append(cycle_id)
        if actor:
            query += " AND actor = ?"
            params.append(actor)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "decision_id": row["decision_id"],
                "proposal_id": row["proposal_id"],
                "cycle_id": row["cycle_id"],
                "decision": row["decision"],
                "reason": row["reason"],
                "actor": row["actor"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def continuous_improvement_proposals(
        self,
        *,
        cycle_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT proposal_id, cycle_id, fingerprint, proposal_type, target_component,
                   target_identifier, status, priority, risk_level, payload_json,
                   guard_json, created_at, updated_at
            FROM continuous_improvement_proposals
            WHERE 1 = 1
        """
        params: list[Any] = []
        if cycle_id:
            query += " AND cycle_id = ?"
            params.append(cycle_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "proposal_id": row["proposal_id"],
                "cycle_id": row["cycle_id"],
                "fingerprint": row["fingerprint"],
                "proposal_type": row["proposal_type"],
                "target_component": row["target_component"],
                "target_identifier": row["target_identifier"],
                "status": row["status"],
                "priority": row["priority"],
                "risk_level": row["risk_level"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "guard": json.loads(row["guard_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def continuous_improvement_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        rows = self.continuous_improvement_proposals(limit=10000)
        for row in rows:
            if row["proposal_id"] == proposal_id:
                row["validations"] = self.continuous_improvement_validations(proposal_id=proposal_id)
                return row
        return None

    def save_continuous_improvement_validation(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_validations (
                    validation_id, proposal_id, cycle_id, status, validation_type,
                    payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["validation_id"],
                    item["proposal_id"],
                    item["cycle_id"],
                    item.get("status", "PENDING"),
                    item.get("validation_type", "deterministic"),
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or _utc_iso(),
                ),
            )

    def continuous_improvement_validations(
        self,
        *,
        proposal_id: str | None = None,
        cycle_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT validation_id, proposal_id, cycle_id, status, validation_type,
                   payload_json, created_at
            FROM continuous_improvement_validations
            WHERE 1 = 1
        """
        params: list[Any] = []
        if proposal_id:
            query += " AND proposal_id = ?"
            params.append(proposal_id)
        if cycle_id:
            query += " AND cycle_id = ?"
            params.append(cycle_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "validation_id": row["validation_id"],
                "proposal_id": row["proposal_id"],
                "cycle_id": row["cycle_id"],
                "status": row["status"],
                "validation_type": row["validation_type"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def upsert_continuous_improvement_event(self, item: dict[str, Any]) -> tuple[str, bool]:
        now = _utc_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT event_id
                FROM continuous_improvement_events
                WHERE fingerprint = ?
                """,
                (item["fingerprint"],),
            ).fetchone()
            if existing:
                return str(existing["event_id"]), False
            conn.execute(
                """
                INSERT INTO continuous_improvement_events (
                    event_id, event_type, domain, status, source, priority, fingerprint,
                    payload_json, cooldown_until, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["event_id"],
                    item["event_type"],
                    item.get("domain", "software"),
                    item.get("status", "DISCOVERED"),
                    item.get("source", "runtime"),
                    item.get("priority", "MEDIUM"),
                    item["fingerprint"],
                    _dumps(item.get("payload", {})),
                    item.get("cooldown_until"),
                    item.get("created_at") or now,
                    now,
                ),
            )
        return item["event_id"], True

    def update_continuous_improvement_event(self, event_id: str, **updates: Any) -> None:
        allowed = {
            "status": "status",
            "cooldown_until": "cooldown_until",
            "payload": "payload_json",
        }
        assignments = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            assignments.append(f"{column} = ?")
            value = updates[key]
            if column.endswith("_json"):
                value = _dumps(value if value is not None else ([] if key.startswith("linked_") else {}))
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = ?")
        values.append(_utc_iso())
        values.append(event_id)
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE continuous_improvement_events
                SET {", ".join(assignments)}
                WHERE event_id = ?
                """,
                values,
            )

    def continuous_improvement_events(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT event_id, event_type, domain, status, source, priority, fingerprint,
                   payload_json, cooldown_until, created_at, updated_at
            FROM continuous_improvement_events
            WHERE 1 = 1
        """
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "domain": row["domain"],
                "status": row["status"],
                "source": row["source"],
                "priority": row["priority"],
                "fingerprint": row["fingerprint"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "cooldown_until": row["cooldown_until"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def continuous_improvement_event(self, event_id: str) -> dict[str, Any] | None:
        rows = self.continuous_improvement_events(limit=10000)
        for row in rows:
            if row["event_id"] == event_id:
                return row
        return None

    def create_continuous_improvement_task(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO continuous_improvement_agent_tasks (
                    task_id, cycle_id, event_id, agent_name, domain, status, priority,
                    dependency_ids_json, payload_json, result_json, error_json,
                    attempt_count, created_at, updated_at, started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["task_id"],
                    item.get("cycle_id"),
                    item["event_id"],
                    item["agent_name"],
                    item.get("domain", "software"),
                    item.get("status", "DISCOVERED"),
                    item.get("priority", "MEDIUM"),
                    _dumps(item.get("dependency_ids", [])),
                    _dumps(item.get("payload", {})),
                    _dumps(item.get("result", {})),
                    _dumps(item.get("error", {})),
                    int(item.get("attempt_count") or 0),
                    item.get("created_at") or now,
                    now,
                    item.get("started_at"),
                    item.get("finished_at"),
                ),
            )

    def update_continuous_improvement_task(self, task_id: str, **updates: Any) -> None:
        allowed = {
            "cycle_id": "cycle_id",
            "status": "status",
            "payload": "payload_json",
            "result": "result_json",
            "error": "error_json",
            "attempt_count": "attempt_count",
            "started_at": "started_at",
            "finished_at": "finished_at",
        }
        assignments = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            assignments.append(f"{column} = ?")
            value = updates[key]
            if column.endswith("_json"):
                value = _dumps(value if value is not None else ([] if key.startswith("linked_") else {}))
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = ?")
        values.append(_utc_iso())
        values.append(task_id)
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE continuous_improvement_agent_tasks
                SET {", ".join(assignments)}
                WHERE task_id = ?
                """,
                values,
            )

    def continuous_improvement_tasks(
        self,
        *,
        event_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT task_id, cycle_id, event_id, agent_name, domain, status, priority,
                   dependency_ids_json, payload_json, result_json, error_json,
                   attempt_count, created_at, updated_at, started_at, finished_at
            FROM continuous_improvement_agent_tasks
            WHERE 1 = 1
        """
        params: list[Any] = []
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "cycle_id": row["cycle_id"],
                "event_id": row["event_id"],
                "agent_name": row["agent_name"],
                "domain": row["domain"],
                "status": row["status"],
                "priority": row["priority"],
                "dependency_ids": json.loads(row["dependency_ids_json"] or "[]"),
                "payload": json.loads(row["payload_json"] or "{}"),
                "result": json.loads(row["result_json"] or "{}"),
                "error": json.loads(row["error_json"] or "{}"),
                "attempt_count": int(row["attempt_count"] or 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]

    def continuous_improvement_task(self, task_id: str) -> dict[str, Any] | None:
        rows = self.continuous_improvement_tasks(limit=10000)
        for row in rows:
            if row["task_id"] == task_id:
                return row
        return None

    def upsert_continuous_improvement_memory(
        self,
        *,
        memory_key: str,
        domain: str,
        summary_text: str,
        payload: dict[str, Any],
        source_event_id: str | None = None,
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO continuous_improvement_memories (
                    memory_key, domain, summary_text, payload_json, source_event_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_key) DO UPDATE SET
                    domain=excluded.domain,
                    summary_text=excluded.summary_text,
                    payload_json=excluded.payload_json,
                    source_event_id=excluded.source_event_id,
                    updated_at=excluded.updated_at
                """,
                (
                    memory_key,
                    domain,
                    summary_text,
                    _dumps(payload),
                    source_event_id,
                    now,
                ),
            )

    def continuous_improvement_memories(self, domain: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT memory_key, domain, summary_text, payload_json, source_event_id, updated_at
            FROM continuous_improvement_memories
            WHERE 1 = 1
        """
        params: list[Any] = []
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY updated_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "memory_key": row["memory_key"],
                "domain": row["domain"],
                "summary_text": row["summary_text"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "source_event_id": row["source_event_id"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def upsert_continuous_improvement_hypothesis(self, item: dict[str, Any]) -> tuple[str, bool]:
        now = _utc_iso()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT hypothesis_id
                FROM continuous_improvement_hypotheses
                WHERE fingerprint = ?
                """,
                (item["fingerprint"],),
            ).fetchone()
            if existing:
                return str(existing["hypothesis_id"]), False
            conn.execute(
                """
                INSERT INTO continuous_improvement_hypotheses (
                    hypothesis_id, cycle_id, event_id, domain, subject, status, confidence,
                    fingerprint, summary_text, evidence_json, source_task_ids_json,
                    proposal_ids_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["hypothesis_id"],
                    item.get("cycle_id"),
                    item["event_id"],
                    item.get("domain", "software"),
                    item["subject"],
                    item.get("status", "OPEN"),
                    item.get("confidence", "LOW"),
                    item["fingerprint"],
                    item.get("summary_text", ""),
                    _dumps(item.get("evidence", [])),
                    _dumps(item.get("source_task_ids", [])),
                    _dumps(item.get("proposal_ids", [])),
                    item.get("created_at") or now,
                    now,
                ),
            )
        return item["hypothesis_id"], True

    def continuous_improvement_hypotheses(
        self,
        *,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT hypothesis_id, cycle_id, event_id, domain, subject, status, confidence,
                   fingerprint, summary_text, evidence_json, source_task_ids_json,
                   proposal_ids_json, created_at, updated_at
            FROM continuous_improvement_hypotheses
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
                "hypothesis_id": row["hypothesis_id"],
                "cycle_id": row["cycle_id"],
                "event_id": row["event_id"],
                "domain": row["domain"],
                "subject": row["subject"],
                "status": row["status"],
                "confidence": row["confidence"],
                "fingerprint": row["fingerprint"],
                "summary_text": row["summary_text"],
                "evidence": json.loads(row["evidence_json"] or "[]"),
                "source_task_ids": json.loads(row["source_task_ids_json"] or "[]"),
                "proposal_ids": json.loads(row["proposal_ids_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_continuous_improvement_proposal_artifact(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO continuous_improvement_proposal_artifacts (
                    artifact_id, proposal_id, artifact_type, content_text, payload_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["artifact_id"],
                    item["proposal_id"],
                    item.get("artifact_type", "text"),
                    item.get("content_text", ""),
                    _dumps(item.get("payload", {})),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def continuous_improvement_proposal_artifact(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT artifact_id, proposal_id, artifact_type, content_text, payload_json,
                       created_at, updated_at
                FROM continuous_improvement_proposal_artifacts
                WHERE proposal_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "artifact_id": row["artifact_id"],
            "proposal_id": row["proposal_id"],
            "artifact_type": row["artifact_type"],
            "content_text": row["content_text"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_continuous_improvement_runtime_state(
        self,
        *,
        runtime_name: str,
        status: str,
        heartbeat_at: str,
        payload: dict[str, Any],
    ) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO continuous_improvement_runtime_state (
                    runtime_name, status, heartbeat_at, payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(runtime_name) DO UPDATE SET
                    status=excluded.status,
                    heartbeat_at=excluded.heartbeat_at,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    runtime_name,
                    status,
                    heartbeat_at,
                    _dumps(payload),
                    now,
                ),
            )

    def continuous_improvement_runtime_state(self, runtime_name: str = "lab") -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT runtime_name, status, heartbeat_at, payload_json, updated_at
                FROM continuous_improvement_runtime_state
                WHERE runtime_name = ?
                """,
                (runtime_name,),
            ).fetchone()
        if not row:
            return None
        return {
            "runtime_name": row["runtime_name"],
            "status": row["status"],
            "heartbeat_at": row["heartbeat_at"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "updated_at": row["updated_at"],
        }

    def upsert_continuous_improvement_initiative(self, item: dict[str, Any]) -> tuple[str, bool]:
        now = _utc_iso()
        evidence = item.get("evidence", []) or []
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT initiative_id, evidence_json, linked_event_ids_json, linked_task_ids_json,
                       linked_hypothesis_ids_json, linked_proposal_ids_json, linked_validation_ids_json
                FROM continuous_improvement_initiatives
                WHERE initiative_key = ?
                """,
                (item["initiative_key"],),
            ).fetchone()
            if existing:
                merged_evidence = self._merge_json_list(existing["evidence_json"], evidence)
                linked_event_ids = self._merge_json_list(existing["linked_event_ids_json"], item.get("linked_event_ids", []))
                linked_task_ids = self._merge_json_list(existing["linked_task_ids_json"], item.get("linked_task_ids", []))
                linked_hypothesis_ids = self._merge_json_list(existing["linked_hypothesis_ids_json"], item.get("linked_hypothesis_ids", []))
                linked_proposal_ids = self._merge_json_list(existing["linked_proposal_ids_json"], item.get("linked_proposal_ids", []))
                linked_validation_ids = self._merge_json_list(existing["linked_validation_ids_json"], item.get("linked_validation_ids", []))
                conn.execute(
                    """
                    UPDATE continuous_improvement_initiatives
                    SET title = ?,
                        domain = ?,
                        status = ?,
                        owner_agent = ?,
                        priority = ?,
                        target_metric = ?,
                        baseline_value = ?,
                        current_value = ?,
                        expected_impact = ?,
                        risk_level = ?,
                        evidence_json = ?,
                        linked_event_ids_json = ?,
                        linked_task_ids_json = ?,
                        linked_hypothesis_ids_json = ?,
                        linked_proposal_ids_json = ?,
                        linked_validation_ids_json = ?,
                        latest_decision_json = ?,
                        next_action = ?,
                        updated_at = ?
                    WHERE initiative_id = ?
                    """,
                    (
                        item.get("title", ""),
                        item.get("domain", "trading"),
                        item.get("status", "OPEN"),
                        item.get("owner_agent", ""),
                        item.get("priority", "MEDIUM"),
                        item.get("target_metric", ""),
                        item.get("baseline_value"),
                        item.get("current_value"),
                        item.get("expected_impact", ""),
                        item.get("risk_level", "MEDIUM"),
                        _dumps(merged_evidence),
                        _dumps(linked_event_ids),
                        _dumps(linked_task_ids),
                        _dumps(linked_hypothesis_ids),
                        _dumps(linked_proposal_ids),
                        _dumps(linked_validation_ids),
                        _dumps(item.get("latest_decision", {})),
                        item.get("next_action", ""),
                        now,
                        existing["initiative_id"],
                    ),
                )
                return str(existing["initiative_id"]), False
            conn.execute(
                """
                INSERT INTO continuous_improvement_initiatives (
                    initiative_id, initiative_key, title, domain, status, owner_agent,
                    priority, target_metric, baseline_value, current_value, expected_impact,
                    risk_level, evidence_json, linked_event_ids_json, linked_task_ids_json,
                    linked_hypothesis_ids_json, linked_proposal_ids_json, linked_validation_ids_json,
                    latest_decision_json, next_action, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["initiative_id"],
                    item["initiative_key"],
                    item.get("title", ""),
                    item.get("domain", "trading"),
                    item.get("status", "OPEN"),
                    item.get("owner_agent", ""),
                    item.get("priority", "MEDIUM"),
                    item.get("target_metric", ""),
                    item.get("baseline_value"),
                    item.get("current_value"),
                    item.get("expected_impact", ""),
                    item.get("risk_level", "MEDIUM"),
                    _dumps(evidence),
                    _dumps(item.get("linked_event_ids", [])),
                    _dumps(item.get("linked_task_ids", [])),
                    _dumps(item.get("linked_hypothesis_ids", [])),
                    _dumps(item.get("linked_proposal_ids", [])),
                    _dumps(item.get("linked_validation_ids", [])),
                    _dumps(item.get("latest_decision", {})),
                    item.get("next_action", ""),
                    item.get("created_at") or now,
                    now,
                ),
            )
        return item["initiative_id"], True

    def update_continuous_improvement_initiative(self, initiative_id: str, **updates: Any) -> None:
        allowed = {
            "title": "title",
            "domain": "domain",
            "status": "status",
            "owner_agent": "owner_agent",
            "priority": "priority",
            "target_metric": "target_metric",
            "baseline_value": "baseline_value",
            "current_value": "current_value",
            "expected_impact": "expected_impact",
            "risk_level": "risk_level",
            "evidence": "evidence_json",
            "linked_event_ids": "linked_event_ids_json",
            "linked_task_ids": "linked_task_ids_json",
            "linked_hypothesis_ids": "linked_hypothesis_ids_json",
            "linked_proposal_ids": "linked_proposal_ids_json",
            "linked_validation_ids": "linked_validation_ids_json",
            "latest_decision": "latest_decision_json",
            "next_action": "next_action",
        }
        assignments = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            assignments.append(f"{column} = ?")
            value = updates[key]
            if column.endswith("_json"):
                value = _dumps(value if value is not None else ([] if key.startswith("linked_") else {}))
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = ?")
        values.append(_utc_iso())
        values.append(initiative_id)
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE continuous_improvement_initiatives
                SET {", ".join(assignments)}
                WHERE initiative_id = ?
                """,
                values,
            )

    def continuous_improvement_initiatives(
        self,
        *,
        statuses: list[str] | None = None,
        domain: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT initiative_id, initiative_key, title, domain, status, owner_agent,
                   priority, target_metric, baseline_value, current_value, expected_impact,
                   risk_level, evidence_json, linked_event_ids_json, linked_task_ids_json,
                   linked_hypothesis_ids_json, linked_proposal_ids_json, linked_validation_ids_json,
                   latest_decision_json, next_action, created_at, updated_at
            FROM continuous_improvement_initiatives
            WHERE 1 = 1
        """
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._continuous_improvement_initiative_from_row(row) for row in rows]

    def continuous_improvement_initiative(self, initiative_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT initiative_id, initiative_key, title, domain, status, owner_agent,
                       priority, target_metric, baseline_value, current_value, expected_impact,
                       risk_level, evidence_json, linked_event_ids_json, linked_task_ids_json,
                       linked_hypothesis_ids_json, linked_proposal_ids_json, linked_validation_ids_json,
                       latest_decision_json, next_action, created_at, updated_at
                FROM continuous_improvement_initiatives
                WHERE initiative_id = ?
                """,
                (initiative_id,),
            ).fetchone()
        if not row:
            return None
        initiative = self._continuous_improvement_initiative_from_row(row)
        initiative["messages"] = self.continuous_improvement_initiative_messages(initiative_id=initiative_id)
        return initiative

    def continuous_improvement_initiative_by_key(self, initiative_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT initiative_id, initiative_key, title, domain, status, owner_agent,
                       priority, target_metric, baseline_value, current_value, expected_impact,
                       risk_level, evidence_json, linked_event_ids_json, linked_task_ids_json,
                       linked_hypothesis_ids_json, linked_proposal_ids_json, linked_validation_ids_json,
                       latest_decision_json, next_action, created_at, updated_at
                FROM continuous_improvement_initiatives
                WHERE initiative_key = ?
                """,
                (initiative_key,),
            ).fetchone()
        return self._continuous_improvement_initiative_from_row(row) if row else None

    def _continuous_improvement_initiative_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "initiative_id": row["initiative_id"],
            "initiative_key": row["initiative_key"],
            "title": row["title"],
            "domain": row["domain"],
            "status": row["status"],
            "owner_agent": row["owner_agent"],
            "priority": row["priority"],
            "target_metric": row["target_metric"],
            "baseline_value": row["baseline_value"],
            "current_value": row["current_value"],
            "expected_impact": row["expected_impact"],
            "risk_level": row["risk_level"],
            "evidence": json.loads(row["evidence_json"] or "[]"),
            "linked_event_ids": json.loads(row["linked_event_ids_json"] or "[]"),
            "linked_task_ids": json.loads(row["linked_task_ids_json"] or "[]"),
            "linked_hypothesis_ids": json.loads(row["linked_hypothesis_ids_json"] or "[]"),
            "linked_proposal_ids": json.loads(row["linked_proposal_ids_json"] or "[]"),
            "linked_validation_ids": json.loads(row["linked_validation_ids_json"] or "[]"),
            "latest_decision": json.loads(row["latest_decision_json"] or "{}"),
            "next_action": row["next_action"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_continuous_improvement_initiative_message(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_initiative_messages (
                    message_id, initiative_id, cycle_id, event_id, task_id, agent_name,
                    role, message_type, content_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["message_id"],
                    item["initiative_id"],
                    item.get("cycle_id"),
                    item.get("event_id"),
                    item.get("task_id"),
                    item.get("agent_name", ""),
                    item.get("role", "agent"),
                    item.get("message_type", "note"),
                    _dumps(item.get("content", {})),
                    item.get("created_at") or _utc_iso(),
                ),
            )

    def continuous_improvement_initiative_messages(
        self,
        *,
        initiative_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT message_id, initiative_id, cycle_id, event_id, task_id, agent_name,
                   role, message_type, content_json, created_at
            FROM continuous_improvement_initiative_messages
            WHERE 1 = 1
        """
        params: list[Any] = []
        if initiative_id:
            query += " AND initiative_id = ?"
            params.append(initiative_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "initiative_id": row["initiative_id"],
                "cycle_id": row["cycle_id"],
                "event_id": row["event_id"],
                "task_id": row["task_id"],
                "agent_name": row["agent_name"],
                "role": row["role"],
                "message_type": row["message_type"],
                "content": json.loads(row["content_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def append_continuous_improvement_initiative_links(
        self,
        initiative_id: str,
        *,
        event_ids: list[str] | None = None,
        task_ids: list[str] | None = None,
        hypothesis_ids: list[str] | None = None,
        proposal_ids: list[str] | None = None,
        validation_ids: list[str] | None = None,
    ) -> None:
        initiative = self.continuous_improvement_initiative(initiative_id)
        if not initiative:
            return
        self.update_continuous_improvement_initiative(
            initiative_id,
            linked_event_ids=self._merge_list_values(initiative.get("linked_event_ids", []), event_ids or []),
            linked_task_ids=self._merge_list_values(initiative.get("linked_task_ids", []), task_ids or []),
            linked_hypothesis_ids=self._merge_list_values(initiative.get("linked_hypothesis_ids", []), hypothesis_ids or []),
            linked_proposal_ids=self._merge_list_values(initiative.get("linked_proposal_ids", []), proposal_ids or []),
            linked_validation_ids=self._merge_list_values(initiative.get("linked_validation_ids", []), validation_ids or []),
        )

    def save_continuous_improvement_experiment(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_experiments (
                    experiment_id, initiative_id, proposal_id, cycle_id, experiment_type, status,
                    input_json, period_json, metrics_json, result_json, artifact_path, error,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["experiment_id"],
                    item.get("initiative_id"),
                    item.get("proposal_id"),
                    item.get("cycle_id"),
                    item.get("experiment_type", "unknown"),
                    item.get("status", "PENDING"),
                    _dumps(item.get("input", {})),
                    _dumps(item.get("period", {})),
                    _dumps(item.get("metrics", {})),
                    _dumps(item.get("result", {})),
                    item.get("artifact_path"),
                    item.get("error"),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def continuous_improvement_experiments(
        self,
        *,
        initiative_id: str | None = None,
        proposal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT experiment_id, initiative_id, proposal_id, cycle_id, experiment_type, status,
                   input_json, period_json, metrics_json, result_json, artifact_path, error,
                   created_at, updated_at
            FROM continuous_improvement_experiments
            WHERE 1 = 1
        """
        params: list[Any] = []
        if initiative_id:
            query += " AND initiative_id = ?"
            params.append(initiative_id)
        if proposal_id:
            query += " AND proposal_id = ?"
            params.append(proposal_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "experiment_id": row["experiment_id"],
                "initiative_id": row["initiative_id"],
                "proposal_id": row["proposal_id"],
                "cycle_id": row["cycle_id"],
                "experiment_type": row["experiment_type"],
                "status": row["status"],
                "input": json.loads(row["input_json"] or "{}"),
                "period": json.loads(row["period_json"] or "{}"),
                "metrics": json.loads(row["metrics_json"] or "{}"),
                "result": json.loads(row["result_json"] or "{}"),
                "artifact_path": row["artifact_path"],
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_continuous_improvement_applied_change(self, item: dict[str, Any]) -> None:
        now = _utc_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO continuous_improvement_applied_changes (
                    applied_change_id, initiative_id, proposal_id, cycle_id, status, change_type,
                    target_key, before_json, after_json, rollback_json, decision_json,
                    validation_ids_json, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["applied_change_id"],
                    item.get("initiative_id"),
                    item.get("proposal_id"),
                    item.get("cycle_id"),
                    item.get("status", "PENDING"),
                    item.get("change_type", "CONFIG_CHANGE"),
                    item.get("target_key", ""),
                    _dumps(item.get("before", {})),
                    _dumps(item.get("after", {})),
                    _dumps(item.get("rollback", {})),
                    _dumps(item.get("decision", {})),
                    _dumps(item.get("validation_ids", [])),
                    item.get("error"),
                    item.get("created_at") or now,
                    now,
                ),
            )

    def continuous_improvement_applied_changes(
        self,
        *,
        initiative_id: str | None = None,
        proposal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT applied_change_id, initiative_id, proposal_id, cycle_id, status, change_type,
                   target_key, before_json, after_json, rollback_json, decision_json,
                   validation_ids_json, error, created_at, updated_at
            FROM continuous_improvement_applied_changes
            WHERE 1 = 1
        """
        params: list[Any] = []
        if initiative_id:
            query += " AND initiative_id = ?"
            params.append(initiative_id)
        if proposal_id:
            query += " AND proposal_id = ?"
            params.append(proposal_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "applied_change_id": row["applied_change_id"],
                "initiative_id": row["initiative_id"],
                "proposal_id": row["proposal_id"],
                "cycle_id": row["cycle_id"],
                "status": row["status"],
                "change_type": row["change_type"],
                "target_key": row["target_key"],
                "before": json.loads(row["before_json"] or "{}"),
                "after": json.loads(row["after_json"] or "{}"),
                "rollback": json.loads(row["rollback_json"] or "{}"),
                "decision": json.loads(row["decision_json"] or "{}"),
                "validation_ids": json.loads(row["validation_ids_json"] or "[]"),
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def rollback_continuous_improvement_applied_change(self, applied_change_id: str, *, actor: str = "api") -> dict[str, Any] | None:
        changes = self.continuous_improvement_applied_changes(limit=10000)
        change = next((item for item in changes if item["applied_change_id"] == applied_change_id), None)
        if not change:
            return None
        rollback = change.get("rollback") or {}
        self.save_continuous_improvement_applied_change(
            {
                **change,
                "status": "ROLLED_BACK",
                "decision": {
                    **(change.get("decision") or {}),
                    "rollback_actor": actor,
                    "rollback_at": _utc_iso(),
                },
                "after": rollback.get("restore", change.get("before", {})),
            }
        )
        return self.continuous_improvement_applied_changes(limit=1)[0]

    def _merge_json_list(self, current_json: str, extra_values: list[Any]) -> list[Any]:
        return self._merge_list_values(json.loads(current_json or "[]"), extra_values)

    def _merge_list_values(self, current: list[Any], extra: list[Any]) -> list[Any]:
        merged: list[Any] = []
        for value in [*current, *extra]:
            if value is None:
                continue
            if value not in merged:
                merged.append(value)
        return merged

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
                "opportunity_snapshots",
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
                "continuous_improvement_cycles",
                "continuous_improvement_llm_responses",
                "continuous_improvement_proposals",
                "continuous_improvement_validations",
                "continuous_improvement_decisions",
                "continuous_improvement_events",
                "continuous_improvement_agent_tasks",
                "continuous_improvement_memories",
                "continuous_improvement_hypotheses",
                "continuous_improvement_proposal_artifacts",
                "continuous_improvement_runtime_state",
                "continuous_improvement_initiatives",
                "continuous_improvement_initiative_messages",
                "continuous_improvement_experiments",
                "continuous_improvement_applied_changes",
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
