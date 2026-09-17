"""P-L120 unit tests: deterministic bridge-contract attach (no invented data)."""
from __future__ import annotations

from agente_bolsa.continuous_improvement.contract_builder import (
    attach_bridge_contract,
    enrich_raws,
)

CONTRACT = {
    "change_class": "reliability",
    "hypothesis_id": "finding:core_sleeve_parity_multi_day",
    "evidence_refs": ["scripts/core_sleeve_parity_check.py"],
    "metric_name": "failure_recurrence",
    "baseline": 1.0,
    "target": 0.0,
    "improvement_direction": "decrease",
    "evaluation_window": "30 ejecuciones deterministas",
    "min_sample": 30,
    "target_paths": ["tests/test_core_sleeve_parity_check.py"],
    "rollback": "Eliminar los tests agregados; no cambia runtime.",
    "origin": {
        "origin_role": "findings_to_proposals",
        "origin_run_id": "run_1",
        "origin_kind": "deterministic",
        "evidence_class": "reliability",
        "producer": "continuous_improvement.findings_to_proposals",
        "producer_version": "0.4.227",
        "observed_at": "2026-09-17T00:00:00+00:00",
        "source_event_ids": [],
    },
}
TARGET = "tests/test_core_sleeve_parity_check.py"


def _raw(**over):
    base = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": TARGET,
        "rationale": "Cubrir parity multi dia.",
        "expected_impact": "Reduce failure_recurrence from 1.0 to 0.0.",
        "risk_level": "LOW",
    }
    base.update(over)
    return base


def test_attach_on_exact_target_match():
    enriched, outcome = attach_bridge_contract(_raw(), {TARGET: CONTRACT})
    assert outcome["attached"] is True
    assert enriched["experiment_contract"] == CONTRACT
    assert enriched["payload"]["experiment_contract"] == CONTRACT


def test_no_match_leaves_raw_untouched():
    raw = _raw()
    enriched, outcome = attach_bridge_contract(raw, {"other/target.py": CONTRACT})
    assert outcome["attached"] is False
    assert "experiment_contract" not in enriched
    assert enriched == raw


def test_non_code_change_deferred():
    enriched, outcome = attach_bridge_contract(
        _raw(proposal_type="PARAMETER_CHANGE"), {TARGET: CONTRACT}
    )
    assert outcome["attached"] is False
    assert outcome["reasons"] == ["proposal_type_deferred:PARAMETER_CHANGE"]


def test_existing_contract_never_overwritten():
    raw = _raw()
    raw["payload"] = {"experiment_contract": {"change_class": "docs"}}
    enriched, outcome = attach_bridge_contract(raw, {TARGET: CONTRACT})
    assert outcome["attached"] is False
    assert enriched["payload"]["experiment_contract"] == {"change_class": "docs"}


def test_protected_target_rejected():
    enriched, outcome = attach_bridge_contract(
        {"proposal_type": "CODE_CHANGE", "target_identifier": "src/agente_bolsa/tools/risk.py"},
        {"src/agente_bolsa/tools/risk.py": {**CONTRACT, "target_paths": ["src/agente_bolsa/tools/risk.py"]}},
    )
    assert outcome["attached"] is False
    assert enriched == {"proposal_type": "CODE_CHANGE", "target_identifier": "src/agente_bolsa/tools/risk.py"}


def test_enrich_raws_counts_attached_and_unbuildable():
    raws = [_raw(), _raw(target_identifier="docs/otro.md")]
    enriched, stats = enrich_raws(raws, {TARGET: CONTRACT})
    assert stats == {"attached": 1, "unbuildable": 1}
    assert "experiment_contract" in enriched[0]
    assert "experiment_contract" not in enriched[1]

def _runtime(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.continuous_improvement.runtime import ContinuousImprovementLabRuntime
    from agente_bolsa.storage import Store

    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        CONTINUOUS_IMPROVEMENT_ENABLED=True,
        IMPROVEMENT_LLM_ENABLED=False,
        IMPROVEMENT_DRY_RUN=True,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
        ALLOW_LIVE_TRADING=False,
        CONTINUOUS_IMPROVEMENT_MAX_PROPOSALS_PER_CYCLE=5,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return ContinuousImprovementLabRuntime(settings, store)


def test_prepare_proposals_attaches_bridge_contract_end_to_end(tmp_path, monkeypatch):
    import pathlib

    monkeypatch.chdir(pathlib.Path(__file__).resolve().parents[1])
    runtime = _runtime(tmp_path)
    raw = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "tests/test_core_sleeve_parity_check.py",
        "rationale": "Cubrir parity multi dia.",
        "expected_impact": "Reduce failure_recurrence from 1.0 to 0.0.",
        "risk_level": "LOW",
    }
    prepared, stats = runtime._prepare_proposals([raw])
    assert stats["contract_attached"] == 1
    assert stats["contract_unbuildable"] == 0
    contract = prepared[0].get("experiment_contract") or {}
    assert contract.get("hypothesis_id") == "finding:core_sleeve_parity_multi_day"
    assert contract.get("origin", {}).get("origin_role") == "findings_to_proposals"


def test_prepare_proposals_without_evidence_stays_rejectable(tmp_path, monkeypatch):
    import pathlib

    monkeypatch.chdir(pathlib.Path(__file__).resolve().parents[1])
    runtime = _runtime(tmp_path)
    raw = {
        "proposal_type": "MONITORING_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "digest",
        "rationale": "El digest podria ser mas claro.",
        "expected_impact": "mejorar",
        "risk_level": "LOW",
    }
    prepared, stats = runtime._prepare_proposals([raw])
    assert stats["contract_attached"] == 0
    assert stats["contract_unbuildable"] == 1
    assert "experiment_contract" not in prepared[0]


