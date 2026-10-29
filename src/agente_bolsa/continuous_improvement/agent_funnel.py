"""Read-only funnel report for the continuous improvement lab.

Answers one question with auditable denominators: what do the agents plan, what
do they propose, what gets admitted, what gets applied, and why does the rest
die.

Rules:

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`. This module never
  writes, repairs, vacuums or checkpoints anything.
- Denominators are reported separately: cycles, proposals, decisions, tasks and
  initiatives are not the same unit.
- `0`, `null` and `unavailable` mean different things and stay distinct.
- Attribution is by initiative owner, not by free text. Proposals do not store a
  producer agent, so the report says so in `limits`.
- Measurement only: nothing here decides readiness or changes a policy.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
INFORMATIONAL_REASONS = frozenset({"autonomous_apply_enabled"})
ADMITTED_STATUSES = frozenset({"READY_TO_APPLY", "PASSED", "APPLIED"})
GUARD_REJECTED = frozenset({"REJECTED"})
GUARD_LIVE = frozenset({"PENDING", "REQUIRES_HUMAN_REVIEW", "WAITING_HUMAN_REVIEW"})
GUARD_ADMITTED = frozenset({"READY_TO_APPLY", "PASSED", "APPLIED"})
TERMINAL_CYCLE_STATUSES = frozenset({"COMPLETED", "FAILED", "PARTIAL", "SKIPPED"})


def resolve_data_dir(value: str | None) -> Path:
    if value:
        return Path(value)
    import os

    return Path(os.environ.get("DATA_DIR") or "data")


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open one SQLite file strictly read-only."""

    uri = f"file:{db_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    try:
        return list(connection.execute(sql, params))
    except sqlite3.Error:
        return []


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def classify_rejection(status: str, guard: dict[str, Any]) -> str:
    """Classify one rejected proposal by the gate that actually rejected it.

    `own_gate` means the proposal's own guard rejected it. `inherited_batch`
    means the row is REJECTED while its own guard approved or left it pending:
    the rejection came from a group decision, not from that proposal's evidence.
    `invalid_transition` means the row was REJECTED while its guard had already
    admitted it. Anything else stays `unclassified` on purpose.
    """

    if str(status or "").upper() != "REJECTED":
        return ""
    guard_status = str(guard.get("status") or "").upper()
    if guard_status in GUARD_REJECTED:
        return "own_gate"
    if guard_status in GUARD_LIVE:
        return "inherited_batch"
    if guard_status in GUARD_ADMITTED:
        return "invalid_transition"
    return "unclassified"


def _owner_for_initiative_key(key: str) -> str:
    from .agents import initiative_owner_from_key

    return initiative_owner_from_key(key) if key else "unavailable"


def _age_days(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round((now - parsed.astimezone(timezone.utc)).total_seconds() / 86400.0, 2)


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter = Counter(str(row.get(field) or "unavailable") for row in rows)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def build_report(
    data_dir: str | Path,
    *,
    scoreboard: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the whole report from one read-only snapshot."""

    from .agent_objectives import evaluate_agent_objectives, load_agent_objectives

    data_path = Path(data_dir)
    db_path = data_path / "state" / "agente_bolsa.sqlite3"
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": "sqlite_read_only",
        "generated_at": generated_at.isoformat(),
        "database": {
            "path": str(db_path),
            "exists": db_path.exists(),
            "mode": "ro",
            "query_only": True,
        },
        "status": "unavailable",
        "reason": "",
    }
    if not db_path.exists():
        report["reason"] = "database_missing"
        report["objectives"] = evaluate_agent_objectives(
            None, load_agent_objectives(data_path), now=generated_at
        )
        return report

    objectives_config = load_agent_objectives(data_path)
    connection = connect_readonly(db_path)
    try:
        cycles = [
            dict(row)
            for row in _rows(
                connection,
                "SELECT cycle_id, status, mode, started_at, finished_at, created_at "
                "FROM continuous_improvement_cycles ORDER BY created_at",
            )
        ]
        initiatives = [
            dict(row)
            for row in _rows(
                connection,
                "SELECT initiative_id, initiative_key, domain, status, owner_agent, "
                "target_metric, created_at, updated_at FROM continuous_improvement_initiatives",
            )
        ]
        proposals = [
            dict(row)
            for row in _rows(
                connection,
                "SELECT proposal_id, cycle_id, status, proposal_type, target_component, "
                "target_identifier, payload_json, guard_json, created_at, updated_at "
                "FROM continuous_improvement_proposals",
            )
        ]
        tasks = [
            dict(row)
            for row in _rows(
                connection,
                "SELECT task_id, agent_name, domain, status, created_at, finished_at "
                "FROM continuous_improvement_agent_tasks",
            )
        ]
        decisions_total = 0
        if _table_exists(connection, "continuous_improvement_decisions"):
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM continuous_improvement_decisions"
            ).fetchone()
            decisions_total = int(row["total"] if row else 0)
        window_blocked = 0
        cooldown = 0
        if _table_exists(connection, "agent_events"):
            for event_type, target in (
                ("lab_market_window_blocked", "window_blocked"),
                ("lab_group_cooldown_active", "cooldown"),
            ):
                row = connection.execute(
                    "SELECT COUNT(*) AS total FROM agent_events WHERE event_type=?",
                    (event_type,),
                ).fetchone()
                value = int(row["total"] if row else 0)
                if target == "window_blocked":
                    window_blocked = value
                else:
                    cooldown = value
    finally:
        connection.close()

    owner_by_initiative = {
        str(item.get("initiative_key") or ""): str(item.get("owner_agent") or "unavailable")
        for item in initiatives
        if item.get("initiative_key")
    }
    proposal_rows: list[dict[str, Any]] = []
    rejection_classes: Counter[str] = Counter()
    blocking_reasons: Counter[str] = Counter()
    informational_reasons: Counter[str] = Counter()
    for item in proposals:
        payload = _json_dict(item.get("payload_json"))
        guard = _json_dict(item.get("guard_json"))
        initiative_key = str(payload.get("initiative_key") or "")
        owner = owner_by_initiative.get(initiative_key) or _owner_for_initiative_key(initiative_key)
        status = str(item.get("status") or "unavailable").upper()
        reasons = [str(reason) for reason in (guard.get("reasons") or []) if reason]
        for reason in reasons:
            if reason in INFORMATIONAL_REASONS:
                informational_reasons[reason] += 1
            else:
                blocking_reasons[reason] += 1
        rejection_class = classify_rejection(status, guard)
        if rejection_class:
            rejection_classes[rejection_class] += 1
        proposal_rows.append(
            {
                "proposal_id": item.get("proposal_id"),
                "status": status,
                "proposal_type": item.get("proposal_type") or "unavailable",
                "target_component": item.get("target_component") or "unavailable",
                "owner_agent": owner,
                "initiative_key": initiative_key or "unavailable",
                "guard_status": str(guard.get("status") or "unavailable").upper(),
                "rejection_class": rejection_class,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )

    statuses = Counter(row["status"] for row in proposal_rows)
    admitted = sum(count for status, count in statuses.items() if status in ADMITTED_STATUSES)
    applied = statuses.get("APPLIED", 0)
    ready_rows = [row for row in proposal_rows if row["status"] == "READY_TO_APPLY"]
    ready_ages = [
        (row["proposal_id"], _age_days(row["updated_at"] or row["created_at"], generated_at))
        for row in ready_rows
    ]
    ready_ages = [(pid, age) for pid, age in ready_ages if age is not None]
    ready_ages.sort(key=lambda item: (-item[1], str(item[0])))

    proposal_stats: dict[str, dict[str, Any]] = {}
    for row in proposal_rows:
        bucket = proposal_stats.setdefault(
            row["owner_agent"],
            {"proposals": 0, "admitted": 0, "applied": 0, "rejected": 0, "decisions": 0},
        )
        bucket["proposals"] += 1
        if row["status"] in ADMITTED_STATUSES:
            bucket["admitted"] += 1
        if row["status"] == "APPLIED":
            bucket["applied"] += 1
        if row["status"] == "REJECTED":
            bucket["rejected"] += 1
    # Decisions are not attributable per proposal here; the funnel total is the
    # only honest denominator, and it is reported once.
    if proposal_stats:
        for bucket in proposal_stats.values():
            bucket["decisions"] = decisions_total

    cycle_status = Counter(str(row.get("status") or "unavailable") for row in cycles)
    cycle_mode = Counter(str(row.get("mode") or "unavailable") for row in cycles)
    first_cycle = str(cycles[0].get("created_at") or "") if cycles else ""
    last_cycle = str(cycles[-1].get("created_at") or "") if cycles else ""

    report.update(
        {
            "status": "available" if proposals or cycles else "collecting",
            "denominators": {
                "cycles": len(cycles),
                "proposals": len(proposal_rows),
                "decisions": decisions_total,
                "tasks": len(tasks),
                "initiatives": len(initiatives),
            },
            "cycles": {
                "total": len(cycles),
                "by_status": dict(sorted(cycle_status.items())),
                "by_mode": dict(sorted(cycle_mode.items())),
                "first_created_at": first_cycle,
                "last_created_at": last_cycle,
                "last_age_days": _age_days(last_cycle, generated_at),
                "terminal": sum(
                    count
                    for status, count in cycle_status.items()
                    if status in TERMINAL_CYCLE_STATUSES
                ),
                "market_window_blocked_events": window_blocked,
                "group_cooldown_events": cooldown,
            },
            "proposals": {
                "total": len(proposal_rows),
                "by_status": dict(sorted(statuses.items())),
                "by_type": _count_by(proposal_rows, "proposal_type"),
                "by_target_component": _count_by(proposal_rows, "target_component"),
                "by_owner_agent": _count_by(proposal_rows, "owner_agent"),
                "funnel": {
                    "generated": len(proposal_rows),
                    "admitted": admitted,
                    "ready_to_apply": statuses.get("READY_TO_APPLY", 0),
                    "applied": applied,
                    "rejected": statuses.get("REJECTED", 0),
                    "admission_rate": round(admitted / len(proposal_rows), 4)
                    if proposal_rows
                    else None,
                },
                "rejection_attribution": {
                    "own_gate": rejection_classes.get("own_gate", 0),
                    "inherited_batch": rejection_classes.get("inherited_batch", 0),
                    "invalid_transition": rejection_classes.get("invalid_transition", 0),
                    "unclassified": rejection_classes.get("unclassified", 0),
                },
                "blocking_reasons": dict(blocking_reasons.most_common(20)),
                "informational_reasons": dict(informational_reasons.most_common(10)),
                "ready_to_apply_aging": {
                    "count": len(ready_rows),
                    "with_timestamp": len(ready_ages),
                    "max_age_days": ready_ages[0][1] if ready_ages else None,
                    "oldest": [
                        {"proposal_id": pid, "age_days": age} for pid, age in ready_ages[:10]
                    ],
                },
            },
            "tasks": {
                "total": len(tasks),
                "by_agent": _count_by(tasks, "agent_name"),
                "by_status": _count_by(tasks, "status"),
                "by_domain": _count_by(tasks, "domain"),
            },
            "initiatives": {
                "total": len(initiatives),
                "by_domain": _count_by(initiatives, "domain"),
                "by_status": _count_by(initiatives, "status"),
                "by_owner_agent": _count_by(initiatives, "owner_agent"),
            },
            "objectives": evaluate_agent_objectives(
                scoreboard,
                objectives_config,
                proposal_stats=proposal_stats,
                now=generated_at,
            ),
            "limits": {
                "attribution_unit": "initiative_owner_agent",
                "producer_agent_recorded": False,
                "cycle_status_partial_counts_as_terminal": True,
                "decisions_per_agent": "unavailable",
                "note": "Las propuestas no guardan el agente productor; el dueno es el de la iniciativa.",
            },
        }
    )
    return report


def load_scoreboard(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("agent_learning"), dict):
        return payload["agent_learning"]
    return payload if isinstance(payload, dict) else None


def format_summary(report: dict[str, Any]) -> str:
    lines = [f"estado: {report.get('status')} ({report.get('reason') or 'ok'})"]
    denominators = report.get("denominators") or {}
    lines.append(
        "denominadores: " + ", ".join(f"{key}={value}" for key, value in denominators.items())
    )
    cycles = report.get("cycles") or {}
    lines.append(
        f"ciclos: {cycles.get('total')} ultimo={cycles.get('last_created_at') or 'unavailable'} "
        f"edad_dias={cycles.get('last_age_days')} "
        f"bloqueos_ventana={cycles.get('market_window_blocked_events')}"
    )
    proposals = report.get("proposals") or {}
    funnel = proposals.get("funnel") or {}
    lines.append(
        f"propuestas: {funnel.get('generated')} admitidas={funnel.get('admitted')} "
        f"listas={funnel.get('ready_to_apply')} aplicadas={funnel.get('applied')} "
        f"rechazadas={funnel.get('rejected')} tasa_admision={funnel.get('admission_rate')}"
    )
    attribution = proposals.get("rejection_attribution") or {}
    lines.append("rechazos: " + ", ".join(f"{key}={value}" for key, value in attribution.items()))
    objectives = report.get("objectives") or {}
    lines.append(f"objetivos: {objectives.get('status')} {objectives.get('counts')}")
    return "\n".join(lines)
