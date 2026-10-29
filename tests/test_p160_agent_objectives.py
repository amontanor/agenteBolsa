"""Tests for the P-L160 agent objective contract and funnel report.

Sin red, sin broker, sin LLM y sin SQLite productiva: base sintetica temporal,
reloj congelado y configuracion explicita.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agente_bolsa.continuous_improvement.agent_funnel import (
    build_report,
    classify_rejection,
    resolve_data_dir,
)
from agente_bolsa.continuous_improvement.agent_objectives import (
    duplicate_agents,
    evaluate_agent_objectives,
    load_agent_objectives,
    objective_by_agent,
)
from agente_bolsa.continuous_improvement.agents import (
    DecisionCommitteeAgent,
    initiative_owner_from_key,
)
from agente_bolsa.continuous_improvement.schemas import AgentName

ROOT = Path(__file__).resolve().parents[1]
REPO_CONFIG = ROOT / "data" / "config" / "agent_objectives.json"
FUNNEL_SCRIPT = ROOT / "scripts" / "agent_funnel_report.py"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def _load_funnel_module():
    spec = importlib.util.spec_from_file_location("agent_funnel_report", FUNNEL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_config(tmp_path: Path, payload: dict) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "agent_objectives.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _contract(agent: str = "TechnicalEdgeAgent", **overrides) -> dict:
    base = {
        "agent": agent,
        "primary_metric": "false_positive_rate",
        "denominator": "matured_with_control",
        "direction": "lower_is_better",
        "source": "agent_learning",
        "maturity_horizon": "10d",
        "require_control": True,
        "min_sample": 2,
        "status": "shadow",
    }
    base.update(overrides)
    return base


def _scoreboard(agent: str = "TechnicalEdgeAgent", **counts) -> dict:
    return {
        "status": "available",
        "agents": [
            {
                "agent_name": agent,
                "agent_role": "producer",
                "signals": counts.get("signals", 0),
                "matured": counts.get("matured", 0),
                "matured_with_control": counts.get("matured_with_control", 0),
                "comparable_control_sets": {
                    "verified": counts.get("control_sets_verified", 0),
                    "total": counts.get("signals", 0),
                },
            }
        ],
    }


def _make_db(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    db_path = state / "agente_bolsa.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE continuous_improvement_cycles (
            cycle_id TEXT PRIMARY KEY, status TEXT, mode TEXT, started_at TEXT,
            finished_at TEXT, created_at TEXT
        );
        CREATE TABLE continuous_improvement_initiatives (
            initiative_id TEXT PRIMARY KEY, initiative_key TEXT, domain TEXT,
            status TEXT, owner_agent TEXT, target_metric TEXT, created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE continuous_improvement_proposals (
            proposal_id TEXT PRIMARY KEY, cycle_id TEXT, status TEXT,
            proposal_type TEXT, target_component TEXT, target_identifier TEXT,
            payload_json TEXT, guard_json TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE continuous_improvement_agent_tasks (
            task_id TEXT PRIMARY KEY, agent_name TEXT, domain TEXT, status TEXT,
            created_at TEXT, finished_at TEXT
        );
        CREATE TABLE continuous_improvement_decisions (
            decision_id TEXT PRIMARY KEY, proposal_id TEXT, decision TEXT
        );
        CREATE TABLE agent_events (
            event_id TEXT PRIMARY KEY, agent TEXT, event_type TEXT,
            cycle_id TEXT, payload_json TEXT, created_at TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO continuous_improvement_cycles VALUES (?,?,?,?,?,?)",
        ("c1", "PARTIAL", "market", "2026-10-01T14:00:00+00:00", "2026-10-01T14:10:00+00:00", "2026-10-01T14:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO continuous_improvement_initiatives VALUES (?,?,?,?,?,?,?,?)",
        ("i1", "trading:entry_quality_filter", "trading", "OPEN", "TechnicalEdgeAgent", "false_positive_rate", "2026-10-01T14:00:00+00:00", "2026-10-02T14:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO continuous_improvement_agent_tasks VALUES (?,?,?,?,?,?)",
        ("t1", "TechnicalEdgeAgent", "trading-improvement", "COMPLETED", "2026-10-01T14:00:00+00:00", "2026-10-01T14:05:00+00:00"),
    )
    rows = [
        (
            "p_own",
            "REJECTED",
            {"status": "REJECTED", "reasons": ["dangerous_term", "autonomous_apply_enabled"]},
        ),
        (
            "p_inherited",
            "REJECTED",
            {"status": "PENDING", "reasons": ["autonomous_apply_enabled"]},
        ),
        (
            "p_invalid",
            "REJECTED",
            {"status": "READY_TO_APPLY", "reasons": ["autonomous_apply_enabled"]},
        ),
        (
            "p_ready",
            "READY_TO_APPLY",
            {"status": "PENDING", "reasons": ["autonomous_apply_enabled"]},
        ),
        ("p_closed", "APPLIED", {"status": "PENDING", "reasons": []}),
    ]
    for proposal_id, status, guard in rows:
        connection.execute(
            "INSERT INTO continuous_improvement_proposals VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                proposal_id,
                "c1",
                status,
                "PARAMETER_CHANGE",
                "entry_quality_filter",
                "false_positive_rate",
                json.dumps({"initiative_key": "trading:entry_quality_filter"}),
                json.dumps(guard),
                "2026-07-01T10:00:00+00:00",
                "2026-07-02T10:00:00+00:00",
            ),
        )
    connection.execute(
        "INSERT INTO continuous_improvement_decisions VALUES (?,?,?)",
        ("d1", "p_own", "REJECTED"),
    )
    connection.execute(
        "INSERT INTO agent_events VALUES (?,?,?,?,?,?)",
        ("e1", "continuous_improvement_lab", "lab_market_window_blocked", None, "{}", "2026-10-01T10:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO agent_events VALUES (?,?,?,?,?,?)",
        ("e2", "continuous_improvement_lab", "lab_market_window_blocked", None, "{}", "2026-10-01T11:00:00+00:00"),
    )
    connection.commit()
    connection.close()
    return db_path


# --- Contrato versionado -------------------------------------------------


def test_repository_config_covers_every_declared_agent() -> None:
    payload = json.loads(REPO_CONFIG.read_text(encoding="utf-8-sig"))
    names = [item["agent"] for item in payload["agents"]]
    assert sorted(names) == sorted(item.value for item in AgentName)
    assert len(names) == len(set(names)) == len(AgentName)


def test_repository_config_fields_are_valid() -> None:
    payload = json.loads(REPO_CONFIG.read_text(encoding="utf-8-sig"))
    for item in payload["agents"]:
        assert item["status"] in {"shadow", "guarded_active", "active", "retired", "unavailable"}
        assert item["source"] in {"agent_learning", "proposal_funnel", "unavailable"}
        assert item["direction"] in {"higher_is_better", "lower_is_better", "target_range"}
        assert item["min_sample"] >= 0
        assert item["primary_metric"]


def test_missing_config_is_unavailable_not_zero(tmp_path: Path) -> None:
    config = load_agent_objectives(tmp_path)
    assert config["status"] == "unavailable"
    assert config["reason"] == "config_missing"
    result = evaluate_agent_objectives(None, config, now=NOW)
    assert result["status"] == "unavailable"
    assert result["agents_total"] == 0


def test_duplicate_agents_are_reported(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract(), _contract()]})
    config = load_agent_objectives(tmp_path)
    assert duplicate_agents(config) == ["TechnicalEdgeAgent"]
    assert len(objective_by_agent(config)) == 1


# --- Evaluacion determinista --------------------------------------------


def test_zero_denominator_is_collecting_never_zero_percent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract()]})
    config = load_agent_objectives(tmp_path)
    result = evaluate_agent_objectives(_scoreboard(matured_with_control=0), config, now=NOW)
    agent = result["agents"][0]
    assert agent["status"] == "collecting"
    assert agent["denominator"] == 0
    assert agent["reason"] == "denominator_zero"
    assert result["status"] == "collecting"


def test_sample_below_minimum_is_collecting(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract(min_sample=5)]})
    config = load_agent_objectives(tmp_path)
    result = evaluate_agent_objectives(_scoreboard(matured_with_control=3), config, now=NOW)
    agent = result["agents"][0]
    assert agent["status"] == "collecting"
    assert agent["sample_shortfall"] == 2


def test_available_requires_sample_and_attribution(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract(min_sample=2)]})
    config = load_agent_objectives(tmp_path)
    result = evaluate_agent_objectives(_scoreboard(matured_with_control=2), config, now=NOW)
    assert result["agents"][0]["status"] == "available"
    assert result["status"] == "available"


def test_unattributed_agent_stays_unavailable(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract(agent="SentimentAnalystAgent")]})
    config = load_agent_objectives(tmp_path)
    result = evaluate_agent_objectives(_scoreboard(matured_with_control=9), config, now=NOW)
    assert result["agents"][0]["status"] == "unavailable"
    assert result["agents"][0]["reason"] == "agent_not_attributed"


def test_proposal_funnel_source_requires_stats(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "agents": [_contract(source="proposal_funnel", denominator="proposals", min_sample=1)],
        },
    )
    config = load_agent_objectives(tmp_path)
    without = evaluate_agent_objectives(None, config, now=NOW)
    assert without["agents"][0]["reason"] == "proposal_stats_not_provided"
    with_stats = evaluate_agent_objectives(
        None,
        config,
        proposal_stats={"TechnicalEdgeAgent": {"proposals": 4}},
        now=NOW,
    )
    assert with_stats["agents"][0]["status"] == "available"


def test_retired_contract_is_not_measurable(tmp_path: Path) -> None:
    _write_config(tmp_path, {"schema_version": 1, "agents": [_contract(status="retired")]})
    config = load_agent_objectives(tmp_path)
    result = evaluate_agent_objectives(_scoreboard(matured_with_control=80), config, now=NOW)
    assert result["agents"][0]["status"] == "retired"
    assert result["agents"][0]["denominator"] is None


# --- Cast coherente ------------------------------------------------------


def test_retired_proposers_are_not_initiative_owners() -> None:
    retired = {"StrategyEvaluatorAgent", "ExperimentDesignerAgent"}
    topics = (
        "pre_earnings_risk_veto",
        "entry_quality_filter",
        "analyst_estimates_pipeline",
        "signal_consolidation",
        "outcome_generation",
        "runtime_reliability",
        "market_regime",
        "strategy_evaluation",
        "continuous_improvement",
        "opportunistic_parameters",
        "risk_manager",
        "risk_capital",
        "data_quality",
        "software_reliability",
    )
    for topic in topics:
        assert initiative_owner_from_key(f"trading:{topic}") not in retired


# --- Comite de decision --------------------------------------------------


def _committee() -> DecisionCommitteeAgent:
    return DecisionCommitteeAgent.__new__(DecisionCommitteeAgent)


def test_rejection_does_not_contaminate_sibling_proposals() -> None:
    committee = _committee()
    proposals = [
        {"proposal_id": "a", "status": "REJECTED", "risk_level": "LOW", "guard": {"status": "REJECTED"}},
        {"proposal_id": "b", "status": "PENDING", "risk_level": "LOW", "guard": {"status": "PENDING"}},
        {"proposal_id": "c", "status": "READY_TO_APPLY", "risk_level": "LOW", "guard": {"status": "PENDING"}},
    ]
    response = committee._deterministic({"existing_proposals": proposals}, {}, {})
    assert isinstance(response, dict)
    targets = {item["proposal_id"]: item["status"] for item in response["proposal_status_targets"]}
    assert targets == {"a": "REJECTED", "b": "PENDING", "c": "READY_TO_APPLY"}
    assert response["close_initiative"] is False


def test_all_rejected_closes_initiative() -> None:
    committee = _committee()
    proposals = [
        {"proposal_id": "a", "status": "REJECTED", "risk_level": "LOW", "guard": {"status": "REJECTED"}},
        {"proposal_id": "b", "status": "REJECTED", "risk_level": "LOW", "guard": {"status": "REJECTED"}},
    ]
    response = committee._deterministic({"existing_proposals": proposals}, {}, {})
    assert response["decision"] == "REJECT"
    assert response["close_initiative"] is True


def test_monitoring_does_not_close_initiative() -> None:
    committee = _committee()
    proposals = [{"proposal_id": "a", "status": "MONITORED", "risk_level": "LOW", "guard": {"status": "PENDING"}}]
    response = committee._deterministic({"existing_proposals": proposals}, {}, {})
    assert response["decision"] == "MONITOR"
    assert response["close_initiative"] is False


def test_high_risk_escalates_without_rejecting_others() -> None:
    committee = _committee()
    proposals = [
        {"proposal_id": "a", "status": "PENDING", "risk_level": "HIGH", "guard": {"status": "PENDING"}},
        {"proposal_id": "b", "status": "PENDING", "risk_level": "LOW", "guard": {"status": "PENDING"}},
    ]
    response = committee._deterministic({"existing_proposals": proposals}, {}, {})
    assert response["decision"] == "ESCALATE"
    targets = {item["proposal_id"]: item["status"] for item in response["proposal_status_targets"]}
    assert targets == {"a": "WAITING_HUMAN_REVIEW", "b": "PENDING"}


# --- Informe de embudo ---------------------------------------------------


def test_rejection_classification_uses_the_guard() -> None:
    assert classify_rejection("REJECTED", {"status": "REJECTED"}) == "own_gate"
    assert classify_rejection("REJECTED", {"status": "PENDING"}) == "inherited_batch"
    assert classify_rejection("REJECTED", {"status": "READY_TO_APPLY"}) == "invalid_transition"
    assert classify_rejection("REJECTED", {}) == "unclassified"
    assert classify_rejection("APPLIED", {"status": "REJECTED"}) == ""


def test_script_wrapper_shares_the_package_report(tmp_path: Path) -> None:
    _make_db(tmp_path)
    module = _load_funnel_module()
    assert module.build_report is build_report
    assert module.resolve_data_dir(str(tmp_path)) == tmp_path
    assert isinstance(resolve_data_dir(None), Path)


def test_funnel_report_separates_denominators_and_attribution(tmp_path: Path) -> None:
    _make_db(tmp_path)
    _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "agents": [
                _contract(source="proposal_funnel", denominator="proposals", min_sample=1),
                _contract(agent="SentimentAnalystAgent", min_sample=1),
            ],
        },
    )
    report = build_report(tmp_path, now=NOW)
    assert report["status"] == "available"
    assert report["database"]["mode"] == "ro"
    denominators = report["denominators"]
    assert denominators["cycles"] == 1
    assert denominators["proposals"] == 5
    assert denominators["decisions"] == 1
    assert denominators["tasks"] == 1
    funnel_block = report["proposals"]["funnel"]
    assert funnel_block["generated"] == 5
    assert funnel_block["admitted"] == 2
    assert funnel_block["applied"] == 1
    assert funnel_block["rejected"] == 3
    attribution = report["proposals"]["rejection_attribution"]
    assert attribution["own_gate"] == 1
    assert attribution["inherited_batch"] == 1
    assert attribution["invalid_transition"] == 1
    assert report["proposals"]["informational_reasons"] == {"autonomous_apply_enabled": 4}
    assert report["cycles"]["market_window_blocked_events"] == 2
    assert report["proposals"]["ready_to_apply_aging"]["count"] == 1
    assert report["proposals"]["ready_to_apply_aging"]["max_age_days"] == pytest.approx(119.08, abs=0.5)
    objectives = report["objectives"]
    by_agent = {item["agent"]: item for item in objectives["agents"]}
    assert by_agent["TechnicalEdgeAgent"]["status"] == "available"
    assert by_agent["SentimentAnalystAgent"]["status"] == "unavailable"
    assert report["limits"]["decisions_per_agent"] == "unavailable"


def test_funnel_report_missing_database_is_unavailable(tmp_path: Path) -> None:
    report = build_report(tmp_path, now=NOW)
    assert report["status"] == "unavailable"
    assert report["reason"] == "database_missing"
    assert report["objectives"]["status"] == "unavailable"


def test_funnel_report_never_writes(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    before = db_path.read_bytes()
    build_report(tmp_path, now=NOW)
    assert db_path.read_bytes() == before
    assert not list((tmp_path / "state").glob("*.wal"))
