from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.agents import (
    ValidationAgent,
    self_governance_modification_violation,
)
from agente_bolsa.continuous_improvement.cast_governance import (
    CAST_CAP_REASON,
    CONTRACT_VIOLATION_REASON,
    DEFAULT_CAST_GOVERNANCE_CONFIG,
    NOT_A_PROPOSER_REASON,
    assess_cast_governance,
    load_cast_governance_config,
    measured_evidence_present,
)
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _store(settings) -> Store:
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _proposal(payload: dict, *, proposal_type: str = "MONITORING_CHANGE") -> dict:
    return {
        "proposal_id": new_id("ci_prop_test"),
        "cycle_id": new_id("ci_cycle_test"),
        "proposal_type": proposal_type,
        "target_component": "docs",
        "target_identifier": "docs/nota_test.md",
        "status": "PENDING",
        "priority": "LOW",
        "risk_level": "LOW",
        "payload": payload,
    }


def test_load_creates_default_config(tmp_path):
    path = tmp_path / "config" / "cast_governance.json"
    config = load_cast_governance_config(path)
    assert path.exists()
    assert config["enabled"] is True
    assert config["human_gated"] is True
    assert config["weekly_cap_no_evidence"] == {"OrchestratorAgent": 10}
    assert "StrategyEvaluatorAgent" in config["retired_proposers"]


def test_metrics_alone_are_not_evidence():
    prose = {
        "proposed_value": "Aumentar ejecuciones para recolectar outcomes.",
        "metrics": {"current_value": 0, "target_value": 160},
    }
    assert measured_evidence_present(prose) is False
    with_study = {**prose, "proposed_value": "Segun docs/informe_codex_p26_auditoria_producto_2026-07-03.md"}
    assert measured_evidence_present(with_study) is True
    with_experiment = {**prose, "experiment_id": "ci_exp_123"}
    assert measured_evidence_present(with_experiment) is True


def test_retired_proposer_rejected_by_validation_agent(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    proposal = _proposal({"agent_name": "StrategyEvaluatorAgent", "proposed_value": "idea suelta"})
    result = ValidationAgent().validate(proposal, {"evaluation": {}}, settings, store=store)
    assert result["status"] == "REJECTED"
    assert result["payload"]["objective_summary"] == NOT_A_PROPOSER_REASON


def test_contract_agent_prose_rejected_and_full_contract_passes(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    prose = _proposal({"agent_name": "SoftwareReliabilityAgent", "proposed_value": "reforzar manejo de errores"})
    result = ValidationAgent().validate(prose, {"evaluation": {}}, settings, store=store)
    assert result["status"] == "REJECTED"
    assert result["payload"]["objective_summary"] == CONTRACT_VIOLATION_REASON

    config = load_cast_governance_config(tmp_path / "config" / "cast_governance.json")
    complete = _proposal(
        {
            "agent_name": "SoftwareReliabilityAgent",
            "target_files": [
                "src/agente_bolsa/continuous_improvement/digest.py",
                "tests/test_ci_phase3_digest.py",
            ],
            "test_requirement": "cubrir el caso X con la linea real",
            "rollback_plan": "git revert del commit",
            "evidence": "docs/informe_codex_p26_auditoria_producto_2026-07-03.md",
            "proposed_value": "cambio concreto",
        },
        proposal_type="CODE_CHANGE",
    )
    violation = assess_cast_governance(
        complete, complete["payload"], store=store, config=config
    )
    assert violation is None


def test_orchestrator_weekly_cap_without_evidence(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    config = load_cast_governance_config(tmp_path / "config" / "cast_governance.json")
    for index in range(10):
        store.upsert_continuous_improvement_proposal(
            {
                "proposal_id": f"ci_prop_cap_{index}",
                "cycle_id": "ci_cycle_cap",
                "fingerprint": f"ci_prop_cap_{index}",
                "proposal_type": "MONITORING_CHANGE",
                "target_component": "docs",
                "target_identifier": f"docs/idea_{index}.md",
                "status": "PENDING",
                "priority": "LOW",
                "risk_level": "LOW",
                "payload": {"agent_name": "OrchestratorAgent", "proposed_value": f"idea {index}"},
                "guard": {"status": "PENDING", "reason": "test"},
            }
        )
    capped = _proposal({"agent_name": "OrchestratorAgent", "proposed_value": "otra idea sin datos"})
    violation = assess_cast_governance(capped, capped["payload"], store=store, config=config)
    assert violation is not None
    assert violation["reason"] == CAST_CAP_REASON

    with_evidence = _proposal(
        {
            "agent_name": "OrchestratorAgent",
            "proposed_value": "idea respaldada por docs/informe_codex_p16_horizonte_salida_2026-07-02.md",
        }
    )
    assert (
        assess_cast_governance(with_evidence, with_evidence["payload"], store=store, config=config)
        is None
    )


def test_cast_governance_config_is_self_governance_protected():
    violation = self_governance_modification_violation(
        target_component="continuous_improvement",
        target_identifier="cast_governance",
        payload={},
    )
    assert violation is not None


def test_disabled_config_skips_gate(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    config = dict(DEFAULT_CAST_GOVERNANCE_CONFIG)
    config["enabled"] = False
    retired = _proposal({"agent_name": "StrategyEvaluatorAgent", "proposed_value": "idea"})
    assert assess_cast_governance(retired, retired["payload"], store=store, config=config) is None
