"""Compact snapshots persisted for continuous-improvement cycles.

The lab keeps the canonical entities in normalized tables.  Cycle rows only
need an auditable snapshot; persisting complete reports, signals and backlogs
on every tick duplicates several megabytes per cycle.
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 1
MAX_REFERENCES = 200


def _references(items: Any, id_keys: tuple[str, ...]) -> dict[str, Any]:
    values = items if isinstance(items, list) else []
    references: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        value = next((item.get(key) for key in id_keys if item.get(key)), None)
        if value is not None:
            references.append(str(value))
        if len(references) >= MAX_REFERENCES:
            break
    return {"count": len(values), "ids": references}


def _report_summary(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"available": False}
    payload = report.get("payload") if isinstance(report.get("payload"), dict) else report
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "available": report.get("available", True),
        "path": report.get("path"),
        "generated_at": payload.get("generated_at") or payload.get("as_of") or payload.get("created_at"),
        "status": payload.get("status"),
        "summary": summary,
    }


def compact_cycle_context(context: Any) -> dict[str, Any]:
    """Return the bounded, auditable subset required for a historical cycle."""

    if not isinstance(context, dict):
        return {"_persistence": {"schema_version": SCHEMA_VERSION, "compacted": True}}
    if (context.get("_persistence") or {}).get("compacted") is True:
        return context
    events = context.get("events") if isinstance(context.get("events"), dict) else {}
    learning = context.get("learning") if isinstance(context.get("learning"), dict) else {}
    reports = context.get("reports") if isinstance(context.get("reports"), dict) else {}
    return {
        "_persistence": {"schema_version": SCHEMA_VERSION, "compacted": True},
        "cycle_id": context.get("cycle_id"),
        "collected_at": context.get("collected_at"),
        "source": context.get("source"),
        "settings": context.get("settings") or {},
        "database": context.get("database") or {},
        "runtime": context.get("runtime") or {},
        "evaluation": context.get("evaluation") or {},
        "lesson_curation": context.get("lesson_curation") or {},
        "reports": {name: _report_summary(value) for name, value in reports.items()},
        "references": {
            "events": _references(events.get("latest"), ("event_id",)),
            "recent_errors": _references(events.get("recent_errors"), ("event_id",)),
            "signals": _references(learning.get("signals"), ("signal_id",)),
            "observations": _references(learning.get("observations"), ("observation_id", "signal_id")),
            "policy_candidates": _references(learning.get("policy_candidates"), ("candidate_id", "policy_key")),
            "distilled_lessons": _references(learning.get("distilled_lessons"), ("lesson_id", "lesson_key")),
            "proposals": _references(context.get("existing_proposals"), ("proposal_id",)),
            "initiatives": _references(context.get("initiatives"), ("initiative_id",)),
            "initiative_messages": _references(context.get("initiative_messages"), ("message_id",)),
            "hypotheses": _references(context.get("hypotheses"), ("hypothesis_id",)),
            "memories": _references(context.get("memories"), ("memory_id", "memory_key")),
        },
    }


def _proposal_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "proposal_id": item.get("proposal_id"),
        "proposal_type": item.get("proposal_type"),
        "target_component": item.get("target_component"),
        "target_identifier": item.get("target_identifier"),
        "status": item.get("status"),
        "risk_level": item.get("risk_level"),
        "duplicate_existing": item.get("duplicate_existing"),
    }


def compact_cycle_report(report: Any) -> dict[str, Any]:
    """Keep cycle results and governance without embedding normalized rows."""

    if not isinstance(report, dict):
        return {"_persistence": {"schema_version": SCHEMA_VERSION, "compacted": True}}
    if (report.get("_persistence") or {}).get("compacted") is True:
        return report
    proposals = report.get("proposals") if isinstance(report.get("proposals"), list) else []
    return {
        "_persistence": {"schema_version": SCHEMA_VERSION, "compacted": True},
        "cycle_id": report.get("cycle_id"),
        "generated_at": report.get("generated_at"),
        "path": report.get("path"),
        "real_data": report.get("real_data") or {},
        "governance": report.get("governance") or {},
        "agent_summary": report.get("agent_summary") or {},
        "proposals": [_proposal_summary(item) for item in proposals[:MAX_REFERENCES]],
        "references": {
            "events": _references(report.get("events"), ("event_id",)),
            "tasks": _references(report.get("tasks"), ("task_id",)),
            "hypotheses": _references(report.get("hypotheses"), ("hypothesis_id",)),
            "proposals": _references(proposals, ("proposal_id",)),
            "validations": _references(report.get("validations"), ("validation_id",)),
            "initiatives": _references(report.get("initiatives"), ("initiative_id",)),
            "pending": _references(report.get("pending"), ("proposal_id",)),
        },
    }
