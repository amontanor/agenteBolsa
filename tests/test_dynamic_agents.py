"""Tests de la fabrica de agentes dinamicos (T2.2)."""

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.dynamic_agents import (
    DynamicSpecialistAgent,
    create_agent,
    instantiate_active,
    score_dynamic_agents,
    validate_agent_definition,
)
from agente_bolsa.storage import Store


def _store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _definition(key="semis", **overrides):
    base = {
        "agent_key": key,
        "role": "Especialista en semiconductores",
        "goal": "vigilar el sector semis",
        "inputs": ["market_state", "signal_outcomes"],
        "output_schema": {"confidence": "number", "evidence": "list", "call": "string"},
    }
    base.update(overrides)
    return base


def test_valid_definition_passes_gate():
    ok, _ = validate_agent_definition(_definition(), existing_active=0, max_agents=8)
    assert ok


def test_definition_rejects_unknown_inputs():
    ok, reason = validate_agent_definition(_definition(inputs=["secret_table"]), existing_active=0, max_agents=8)
    assert not ok
    assert "catalogo" in reason


def test_definition_requires_confidence_and_evidence():
    ok, reason = validate_agent_definition(_definition(output_schema={"call": "x"}), existing_active=0, max_agents=8)
    assert not ok
    assert "output_schema" in reason


def test_create_agent_respects_max_quota(tmp_path):
    settings, store = _store(tmp_path)
    settings = Settings(DATA_DIR=tmp_path, MAX_DYNAMIC_AGENTS=2)
    assert create_agent(store, settings, _definition("a"))["ok"]
    assert create_agent(store, settings, _definition("b"))["ok"]
    third = create_agent(store, settings, _definition("c"))
    assert not third["ok"]
    assert "cupo" in third["error"]
    assert len(instantiate_active(store)) == 2


def test_validate_output_against_schema():
    agent = DynamicSpecialistAgent(_definition())
    ok, _ = agent.validate_output({"confidence": 0.7, "evidence": ["e1"], "call": "buy"})
    assert ok
    bad, reason = agent.validate_output({"confidence": 1.5, "evidence": [], "call": "x"})
    assert not bad
    missing, _ = agent.validate_output({"confidence": 0.5, "call": "x"})
    assert not missing


def test_score_retires_useless_agents(tmp_path):
    settings, store = _store(tmp_path)
    store.upsert_agent_definition({**_definition("lo"), "performance": {"correct_calls": 2, "total_calls": 20}})
    store.upsert_agent_definition({**_definition("hi"), "performance": {"correct_calls": 18, "total_calls": 20}})
    store.upsert_agent_definition({**_definition("new"), "performance": {"total_calls": 3}})

    results = {row["agent_key"]: row for row in score_dynamic_agents(store)}

    assert results["lo"]["retired"] is True
    assert results["hi"]["retired"] is False
    assert results["new"]["retired"] is False
    status = {row["agent_key"]: row["status"] for row in store.agent_definitions()}
    assert status["lo"] == "RETIRED"
    assert status["hi"] == "ACTIVE"
