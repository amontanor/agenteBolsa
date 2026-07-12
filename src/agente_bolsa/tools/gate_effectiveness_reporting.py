"""Post-market publication for the immutable P-L32 gate ledger.

This module only reads already sealed snapshots and outcomes.  It never runs a
gate, changes an order, or mutates a snapshot.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gate_evaluation import SCHEMA_VERSION, build_gate_effectiveness_quality
from .reporting import write_json_report

REPORT_SCHEMA_VERSION = "p-l34b.gate-effectiveness-quality.v1"
RUNTIME_KEY = "gate_effectiveness_quality_runtime"
WINDOW_LIMIT = 5000


def _hash(value: dict[str, Any]) -> str:
    stable = {key: item for key, item in value.items() if key not in {"generated_at", "content_hash", "duration_seconds"}}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()).hexdigest()


def _snapshots(store: Any, *, limit: int = WINDOW_LIMIT) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Read only prospective rows; legacy gate_json is deliberately ignored."""
    snapshots: list[dict[str, Any]] = []
    outcomes: dict[str, dict[str, Any]] = {}
    with store.connect() as conn:
        rows = conn.execute(
            """SELECT signal_id, features_json, outcome_json FROM signal_outcomes
               WHERE features_json LIKE '%\"gate_evaluation_snapshot\"%'
               ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    for row in rows:
        features = json.loads(row["features_json"] or "{}")
        snapshot = features.get("gate_evaluation_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEMA_VERSION:
            continue
        snapshots.append(snapshot)
        outcome = json.loads(row["outcome_json"] or "{}")
        outcomes[str(row["signal_id"])] = outcome if isinstance(outcome, dict) else {}
    return snapshots, outcomes


def build_gate_effectiveness_postmarket_report(store: Any, *, session_date: str, now: datetime | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    snapshots, outcomes = _snapshots(store)
    quality = build_gate_effectiveness_quality(snapshots, outcomes_by_signal=outcomes)
    maturity = dict(quality.get("maturity") or {})
    status = str(quality.get("status") or "unavailable")
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_session": session_date,
        "generated_at": now.isoformat(),
        "status": status,
        "freshness": {"market_session": session_date, "age_sessions": 0, "status": "fresh"},
        "coverage": {
            "snapshots": len(snapshots),
            "identity_weak": quality.get("identity_weak", 0),
            "identity_unavailable": quality.get("identity_unavailable", 0),
            "identity_coverage": quality.get("identity_coverage"),
            "context_coverage": quality.get("context_coverage"),
        },
        "maturity": maturity,
        "gates": quality.get("gates") or {},
        "categories": quality.get("categories") or {},
        "unavailable_by_reason": quality.get("unavailable_by_reason") or {},
        "warnings": list(quality.get("warnings") or []),
        "window": {"limit": WINDOW_LIMIT, "snapshots_processed": len(snapshots), "legacy_gate_json_excluded": True},
        "next_evaluable_after": "10 XNYS sessions after captured signals",
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    if report["duration_seconds"] > 30:
        report["warnings"].append("duration_over_30_seconds")
    report["content_hash"] = _hash(report)
    return report


def publish_gate_effectiveness_postmarket(store: Any, reports_dir: Path, *, run_id: str, session_date: str) -> dict[str, Any]:
    report = build_gate_effectiveness_postmarket_report(store, session_date=session_date)
    persisted = write_json_report(report, reports_dir, "gate_effectiveness_quality", run_id, latest_filename="latest_gate_effectiveness_quality.json")
    store.set_runtime_value(RUNTIME_KEY, {
        "status": persisted["status"], "last_started_at": persisted["generated_at"], "last_completed_at": persisted["generated_at"],
        "last_success_at": persisted["generated_at"], "last_failure_at": None, "last_report_session": session_date,
        "duration_seconds": persisted["duration_seconds"], "freshness": persisted["freshness"], "consecutive_failures": 0,
        "current_overlap": False, "last_error_code": None, "content_hash": persisted["content_hash"], "path": persisted.get("path"),
    })
    return persisted
