from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.agents import (
    SELF_SAFETY_REJECTION_REASON,
    ValidationAgent,
    self_safety_modification_violation,
)
from agente_bolsa.continuous_improvement.aggressiveness_gate import (
    AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE,
    aggressiveness_parameter_criteria,
    reject_ready_aggressiveness_without_evidence,
)
from agente_bolsa.storage import Store


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
        IMPROVEMENT_DRY_RUN=True,
    )


def _store(settings: Settings) -> Store:
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _proposal(proposal_id: str = "ci_prop_aggressive") -> dict:
    return {
        "proposal_id": proposal_id,
        "cycle_id": "ci_cycle_gate",
        "fingerprint": f"fp_{proposal_id}",
        "proposal_type": "PARAMETER_CHANGE",
        "target_component": "settings",
        "target_identifier": "max_orders_per_cycle",
        "status": "PENDING",
        "priority": "MEDIUM",
        "risk_level": "MEDIUM",
        "payload": {
            "current_value": "4",
            "proposed_value": "8",
            "rollback_plan": "Restore max_orders_per_cycle to 4.",
            "rationale": "Increase order throughput after evidence review.",
        },
        "guard": {"status": "PENDING", "reasons": []},
    }


def test_aggressiveness_proposal_without_edge_evidence_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    proposal = _proposal()

    result = ValidationAgent().validate(proposal, {"evaluation": {"summary": {}}}, settings, store=store)

    assert result["status"] == "REJECTED"
    check = result["payload"]["checks"][0]
    assert check["name"] == AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE
    assert check["evidence"]["target_identifier"] == "max_orders_per_cycle"


def test_aggressiveness_proposal_with_passed_edge_experiment_can_reach_human_queue(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    proposal = _proposal("ci_prop_evidence")
    store.save_continuous_improvement_experiment(
        {
            "experiment_id": "ci_exp_edge",
            "proposal_id": "ci_prop_evidence",
            "cycle_id": "ci_cycle_gate",
            "experiment_type": "shadow_forward",
            "status": "PASSED",
            "metrics": {"forward_expectancy_net": 0.018},
        }
    )
    context = {
        "evaluation": {"summary": {"observations": 10}},
        "reports": {
            "strategy_edge_compare": {
                "available": True,
                "payload": {
                    "robust_improvement": True,
                    "summary": {"deduped_rows": 25},
                    "metrics": {"forward_expectancy_net": 0.018},
                },
            },
            "operational_learning": {
                "available": True,
                "payload": {"shadow_evaluation": {"metrics_by_rule": {"candidate": {"trades": 20}}}},
            },
            "live_readiness": {"available": True, "payload": {"summary": {"mode": "paper"}}},
        },
    }

    result = ValidationAgent().validate(proposal, context, settings, store=store)

    assert result["status"] == "READY_TO_APPLY"
    assert AGGRESSIVENESS_REQUIRES_EDGE_EVIDENCE not in {item["name"] for item in result["payload"]["checks"]}


def test_retroactive_ready_aggressiveness_without_evidence_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    proposal = _proposal("ci_prop_retro")
    proposal["status"] = "READY_TO_APPLY"
    store.upsert_continuous_improvement_proposal(proposal)

    rejected = reject_ready_aggressiveness_without_evidence(store, settings=settings)

    assert [item["proposal_id"] for item in rejected] == ["ci_prop_retro"]
    stored = store.continuous_improvement_proposal("ci_prop_retro")
    assert stored is not None
    assert stored["status"] == "REJECTED"


def test_deterministic_gate_error_severity_is_constitutionally_covered():
    violation = self_safety_modification_violation(
        target_component="settings",
        target_identifier="deterministic_gate_error_severity",
        payload={},
    )

    assert violation is not None
    assert violation["reason"] == SELF_SAFETY_REJECTION_REASON


def test_settings_aggressiveness_analogs_are_documented(tmp_path):
    criteria = aggressiveness_parameter_criteria(_settings(tmp_path))

    assert criteria["max_daily_buy_orders"] == "increase"
    assert criteria["max_orders_per_cycle"] == "increase"
    assert criteria["trade_selection_top_n"] == "increase"
    assert criteria["entry_quality_min_score"] == "decrease"
    assert criteria["entry_quality_max_rsi"] == "increase"
    assert criteria["entry_quality_max_sma20_distance"] == "increase"
    assert criteria["entry_quality_fallback_momentum_extension_min_score"] == "decrease"
    assert criteria["entry_quality_fallback_momentum_extension_max_selection_rank"] == "increase"
