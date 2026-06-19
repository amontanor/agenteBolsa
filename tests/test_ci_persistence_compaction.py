from __future__ import annotations

import json

from agente_bolsa.continuous_improvement.persistence_compaction import (
    compact_cycle_context,
    compact_cycle_report,
)


def test_cycle_context_compaction_preserves_audit_references_and_is_bounded():
    huge_payload = "x" * 1_000_000
    context = {
        "cycle_id": "cycle-1",
        "collected_at": "2026-06-20T00:00:00+00:00",
        "settings": {"allow_live_trading": False},
        "evaluation": {"summary": {"expectancy": 0.01}},
        "reports": {
            "learning": {
                "available": True,
                "path": "latest.json",
                "payload": {"summary": {"wins": 4}, "raw": huge_payload},
            }
        },
        "events": {"latest": [{"event_id": "event-1", "payload": huge_payload}]},
        "learning": {
            "signals": [{"signal_id": "signal-1", "features": huge_payload}],
            "observations": [{"observation_id": "observation-1", "features": huge_payload}],
        },
        "existing_proposals": [{"proposal_id": "proposal-1", "payload": huge_payload}],
    }

    compacted = compact_cycle_context(context)

    assert compacted["_persistence"]["compacted"] is True
    assert compacted["settings"]["allow_live_trading"] is False
    assert compacted["evaluation"]["summary"]["expectancy"] == 0.01
    assert compacted["reports"]["learning"]["summary"] == {"wins": 4}
    assert compacted["references"]["events"]["ids"] == ["event-1"]
    assert compacted["references"]["signals"]["ids"] == ["signal-1"]
    assert compacted["references"]["observations"]["ids"] == ["observation-1"]
    assert compacted["references"]["proposals"]["ids"] == ["proposal-1"]
    assert len(json.dumps(compacted)) < 20_000
    assert compact_cycle_context(compacted) == compacted


def test_cycle_report_compaction_keeps_governance_and_proposal_summary():
    report = {
        "cycle_id": "cycle-1",
        "path": "latest_continuous_improvement_report.json",
        "real_data": {"summary": {"alpha": 0.02}},
        "governance": {"decision_counts": {"PROMOTE": 1}},
        "agent_summary": {"RiskGuardAgent": 2},
        "events": [{"event_id": "event-1", "payload": "x" * 500_000}],
        "tasks": [{"task_id": "task-1", "result": "x" * 500_000}],
        "proposals": [
            {
                "proposal_id": "proposal-1",
                "proposal_type": "PROMPT_CHANGE",
                "target_component": "decision",
                "status": "PENDING",
                "risk_level": "MEDIUM",
                "payload": {"artifact": "x" * 500_000},
            }
        ],
        "validations": [{"validation_id": "validation-1", "payload": "x" * 500_000}],
    }

    compacted = compact_cycle_report(report)

    assert compacted["real_data"]["summary"]["alpha"] == 0.02
    assert compacted["governance"]["decision_counts"]["PROMOTE"] == 1
    assert compacted["proposals"][0]["proposal_id"] == "proposal-1"
    assert "payload" not in compacted["proposals"][0]
    assert compacted["references"]["tasks"]["ids"] == ["task-1"]
    assert compacted["references"]["validations"]["ids"] == ["validation-1"]
    assert len(json.dumps(compacted)) < 20_000
    assert compact_cycle_report(compacted) == compacted
