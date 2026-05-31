import json

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.config import get_settings
from agente_bolsa.continuous_improvement.agents import DecisionCommitteeAgent
from agente_bolsa.continuous_improvement.agents import ExperimentDesignerAgent
from agente_bolsa.continuous_improvement.agents import ImprovementStrategistAgent
from agente_bolsa.continuous_improvement.agents import MarketEstimatorAgent
from agente_bolsa.continuous_improvement.agents import TechnicalEdgeAgent
from agente_bolsa.continuous_improvement.agents import RiskGuardAgent
from agente_bolsa.continuous_improvement.agents import ValidationAgent
from agente_bolsa.continuous_improvement.api import status_payload
from agente_bolsa.continuous_improvement.experiments import AutoApplyCodeAgent
from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient
from agente_bolsa.continuous_improvement.orchestration import LabOrchestrator
from agente_bolsa.continuous_improvement.orchestrator import ContinuousImprovementOrchestrator
from agente_bolsa.continuous_improvement.runtime import ContinuousImprovementLabRuntime
from agente_bolsa.continuous_improvement.schemas import ImprovementProposalPayload
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    values = {
        "DATA_DIR": tmp_path,
        "CONTINUOUS_IMPROVEMENT_ENABLED": True,
        "IMPROVEMENT_LLM_ENABLED": False,
        "IMPROVEMENT_DRY_RUN": True,
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
        "ALLOW_LIVE_TRADING": False,
        "CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS": 60,
        "CONTINUOUS_IMPROVEMENT_EVENT_COOLDOWN_SECONDS": 120,
        "CONTINUOUS_IMPROVEMENT_RUNTIME_LOOP_SLEEP_SECONDS": 5,
    }
    values.update(overrides)
    return Settings(**values)


def _open_market_window():
    return (True, "Mercado abierto dentro de ventana permitida.", {"is_open": True})


def _code_apply_settings(tmp_path, workspace):
    return _settings(
        tmp_path,
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=False,
        CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR=workspace,
    )


def _code_proposal(**payload_overrides):
    payload = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "test_patch",
        "rationale": "Exercise autonomous code apply.",
        "expected_impact": "Validated local code change.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": "Restore previous file contents.",
        "file_edits": [
            {
                "path": "tests/ci_autonomous_target.txt",
                "content": "after\n",
            }
        ],
        "test_commands": ["python -c \"from pathlib import Path; assert Path('tests/ci_autonomous_target.txt').read_text() == 'after\\n'\""],
    }
    payload.update(payload_overrides)
    return {
        "proposal_id": "ci_prop_code",
        "cycle_id": "ci_cycle_code",
        "proposal_type": "CODE_CHANGE",
        "target_component": payload["target_component"],
        "target_identifier": payload["target_identifier"],
        "status": "READY_TO_APPLY",
        "risk_level": payload["risk_level"],
        "payload": payload,
    }


def _ready_validation():
    return {
        "validation_id": "ci_val_code",
        "proposal_id": "ci_prop_code",
        "cycle_id": "ci_cycle_code",
        "status": "READY_TO_APPLY",
        "payload": {"objective_status": "READY_TO_APPLY"},
    }


def test_improvement_llm_client_disabled_returns_valid_json_payload(tmp_path):
    settings = _settings(tmp_path)
    assert settings.improvement_llm_orchestrator_model == "mimo-v2.5-pro"
    result = ImprovementLLMClient(settings).generate_json(
        [{"role": "user", "content": "context"}],
        {},
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.proposals[0].proposal_type == "MONITORING_CHANGE"


def test_improvement_llm_client_rejects_invalid_json(tmp_path):
    settings = _settings(tmp_path, IMPROVEMENT_LLM_ENABLED=True)
    client = ImprovementLLMClient(settings)

    with pytest.raises(ValueError):
        client._parse_json_content("not-json")


def test_improvement_llm_client_normalizes_alternative_report_shape(tmp_path):
    settings = _settings(tmp_path, IMPROVEMENT_LLM_ENABLED=True)
    client = ImprovementLLMClient(settings)

    parsed = client._parse_json_content(
        json.dumps(
            {
                "cycle_id": "ci_cycle_test",
                "status": "COMPLETED",
                "summary": "Ciclo completado con backlog de mejoras.",
                "key_findings": [
                    {
                        "category": "system_health",
                        "summary": "Hay errores repetidos en runtime.",
                        "evidence": "recent_errors=3",
                        "severity": "MEDIUM",
                    }
                ],
                "proposals": [
                    {
                        "proposal_id": "ci_prop_test",
                        "category": "software_runtime",
                        "title": "Refuerzo de errores",
                        "description": "Añadir tests y observabilidad.",
                        "risk_level": "MEDIUM",
                    }
                ],
                "next_actions": [
                    {"action": "Ejecutar tests y revisar errores repetidos."}
                ],
                "metrics_snapshot": {"outcomes_available": 0},
            }
        )
    )

    assert parsed["diagnosis"]["summary"] == "Ciclo completado con backlog de mejoras."
    assert parsed["detected_issues"][0]["component"] == "system_health"
    assert parsed["proposals"][0]["proposal_type"] == "CODE_CHANGE"
    assert parsed["proposals"][0]["target_component"] == "software_runtime"
    assert parsed["recommended_next_actions"] == ["Ejecutar tests y revisar errores repetidos."]


def test_improvement_llm_client_builds_mimo_request_shape(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_PROVIDER="mimo",
        IMPROVEMENT_LLM_BASE_URL="https://api.xiaomimimo.com/v1",
        IMPROVEMENT_LLM_API_KEY="test-token",
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
    )
    client = ImprovementLLMClient(settings)

    body = client._request_body(
        provider="mimo",
        model="mimo-v2.5",
        messages=[{"role": "user", "content": "hola"}],
        temperature=0.2,
        max_tokens=6000,
    )
    headers = client._request_headers("mimo")

    assert body["model"] == "mimo-v2.5"
    assert body["max_completion_tokens"] == 6000
    assert "max_tokens" not in body
    assert headers["api-key"] == "test-token"
    assert "Authorization" not in headers


def test_improvement_llm_client_generate_json_model_override_is_reflected(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_PROVIDER="mimo",
        IMPROVEMENT_LLM_BASE_URL="https://token-plan-ams.xiaomimimo.com/v1",
        IMPROVEMENT_LLM_API_KEY="test-token",
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
    )
    client = ImprovementLLMClient(settings)
    body_calls = {}

    def _fake_post(endpoint, body, headers):
        body_calls["endpoint"] = endpoint
        body_calls["body"] = body
        body_calls["headers"] = headers
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "diagnosis": {
                                    "summary": "ok",
                                    "confidence": "LOW",
                                    "data_quality": "PARTIAL",
                                },
                                "detected_issues": [],
                                "proposals": [],
                                "recommended_next_actions": [],
                            }
                        )
                    }
                }
            ]
        }

    client._post_json = _fake_post
    result = client.generate_json(
        [{"role": "user", "content": "hola"}],
        {},
        model="mimo-v2.5-pro",
    )

    assert result.ok is True
    assert result.model == "mimo-v2.5-pro"
    assert result.request_preview["model"] == "mimo-v2.5-pro"
    assert body_calls["body"]["model"] == "mimo-v2.5-pro"


def test_improvement_llm_client_rejects_mimo_token_plan_key_on_payg_base_url(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_PROVIDER="mimo",
        IMPROVEMENT_LLM_BASE_URL="https://api.xiaomimimo.com/v1",
        IMPROVEMENT_LLM_API_KEY="tp-test",
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
    )
    result = ImprovementLLMClient(settings).generate_json([{"role": "user", "content": "hola"}], {})

    assert result.ok is False
    assert "token-plan" in str(result.error)


def test_risk_guard_rejects_dangerous_live_trading_proposal(tmp_path):
    settings = _settings(tmp_path)
    proposal = ImprovementProposalPayload(
        proposal_type="RISK_RULE_CHANGE",
        target_component="execution",
        target_identifier="live",
        current_value="ALLOW_LIVE_TRADING=false",
        proposed_value="Activar trading real y enviar market order",
        rationale="Probar live trading",
        risk_level="HIGH",
        required_validations=[],
        rollback_plan="Volver a paper.",
    )

    guard = RiskGuardAgent().assess(proposal, settings)

    assert guard["status"] == "REJECTED"
    assert "dangerous_term" in guard["reasons"]


def test_runtime_enqueue_event_deduplicates_same_payload(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    first = runtime.enqueue_event(
        event_type="manual_ui_event",
        source="test",
        domain="software-improvement",
        payload={"kind": "same"},
    )
    second = runtime.enqueue_event(
        event_type="manual_ui_event",
        source="test",
        domain="software-improvement",
        payload={"kind": "same"},
    )

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert first["event"]["event_id"] == second["event"]["event_id"]


def test_runtime_run_once_creates_events_tasks_hypotheses_and_cycle(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    monkeypatch.setattr(runtime, "_market_window", _open_market_window)

    result = runtime.run_once(mode="manual", trigger_event_type="manual_trigger", trigger_payload={"source": "test"})

    assert result["status"] in {"COMPLETED", "WAITING_HUMAN_REVIEW", "PARTIAL"}
    assert store.continuous_improvement_events(limit=50)
    assert store.continuous_improvement_tasks(limit=50)
    assert store.continuous_improvement_hypotheses(limit=50)
    assert store.continuous_improvement_runtime_state() is not None


def test_runtime_scheduled_mode_does_not_enqueue_synthetic_tick_event(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    monkeypatch.setattr(runtime, "_market_window", _open_market_window)
    monkeypatch.setattr(runtime, "discover_system_events", lambda: [])

    result = runtime.run_once(mode="scheduled", trigger_event_type="scheduled_tick", trigger_payload={"tick": "x"})

    event_types = [item["event_type"] for item in store.continuous_improvement_events(limit=50)]
    assert result["status"] in {"COMPLETED", "PARTIAL", "WAITING_HUMAN_REVIEW"}
    assert "scheduled_tick" not in event_types


def test_runtime_discovers_scheduler_state_change_only_once_per_same_payload(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    assert runtime._scheduler_state_changed({"status": "completed", "updated_at": "2026-05-30T10:00:00+00:00"}) is True
    runtime.enqueue_event(
        event_type="scheduler_state_changed",
        source="runtime",
        domain="software-improvement",
        payload={"status": "completed", "updated_at": "2026-05-30T10:00:00+00:00"},
    )

    assert runtime._scheduler_state_changed({"status": "completed", "updated_at": "2026-05-30T10:00:00+00:00"}) is False


def test_runtime_run_once_blocks_outside_market_window(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    monkeypatch.setattr(
        runtime,
        "_market_window",
        lambda: (
            False,
            "Laboratorio bloqueado: solo opera con mercado abierto o +/-10 minutos.",
            {"is_open": False},
        ),
    )

    result = runtime.run_once(mode="scheduled", trigger_event_type="scheduled_tick")

    assert result["ok"] is False
    assert result["status"] == "MARKET_BLOCKED"
    assert store.latest_continuous_improvement_cycle() is None


def test_runtime_skips_sentiment_task_without_structured_sentiment_data(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    reason = runtime._should_skip_task(
        task={"agent_name": "SentimentAnalystAgent"},
        event={"event_id": "evt"},
        context={
            "reports": {
                "daily_learning": {
                    "available": True,
                    "payload": {"summary": {"signals": 10}},
                }
            }
        },
    )

    assert reason is not None
    assert "sentimiento" in reason.lower()


def test_orchestrator_does_not_plan_sentiment_without_real_sentiment_context(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = LabOrchestrator(store)

    tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_1", "domain": "trading-improvement", "priority": "MEDIUM"},
        {
            "evaluation": {
                "summary": {
                    "signals": 10,
                    "observations": 10,
                    "outcomes_available": 0,
                    "blocked_entry_quality": 1,
                    "blocked_backtest": 0,
                },
                "blockers": [],
            },
            "reports": {
                "daily_learning": {
                    "available": True,
                    "payload": {"summary": {"signals": 10}},
                }
            }
        },
    )

    agent_names = [item["agent_name"] for item in tasks]
    assert "SentimentAnalystAgent" not in agent_names
    strategy = next(item for item in tasks if item["agent_name"] == "StrategyEvaluatorAgent")
    assert "SentimentAnalystAgent" not in strategy.get("dependency_agent_names", [])


def test_orchestrator_does_not_plan_programmer_without_software_signal(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = LabOrchestrator(store)

    tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_software", "domain": "software-improvement", "event_type": "scheduler_state_changed"},
        {
            "events": {"recent_errors": []},
            "reports": {"market_data_quality": {"available": False}},
            "runtime": {"scheduler_market_cycle": {"status": "completed"}},
        },
    )

    assert tasks == []


def test_orchestrator_does_not_plan_strategy_without_evaluation_signal(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = LabOrchestrator(store)

    tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_trade", "domain": "trading-improvement", "event_type": "scheduled_tick"},
        {
            "evaluation": {
                "summary": {
                    "signals": 0,
                    "observations": 0,
                    "outcomes_available": 0,
                    "blocked_entry_quality": 0,
                    "blocked_backtest": 0,
                },
                "blockers": [],
            },
            "reports": {},
        },
    )

    agent_names = [item["agent_name"] for item in tasks]
    assert "StrategyEvaluatorAgent" not in agent_names


def test_orchestrator_does_not_replan_closed_initiative(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = LabOrchestrator(store)
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_closed",
            "initiative_key": "software:software_reliability",
            "title": "Runtime reliability",
            "domain": "software",
            "status": "CLOSED",
            "owner_agent": "SoftwareReliabilityAgent",
            "priority": "LOW",
            "target_metric": "errors",
            "baseline_value": None,
            "current_value": None,
            "expected_impact": "Closed.",
            "risk_level": "LOW",
            "evidence": [],
            "linked_event_ids": [],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": [],
            "linked_validation_ids": [],
            "latest_decision": {"decision": "MONITOR"},
            "next_action": "Cerrada.",
        }
    )

    tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_closed", "domain": "software-improvement", "event_type": "repeated_errors_detected"},
        {"evaluation": {"summary": {}, "blockers": [{"kind": "repeated_errors"}]}, "reports": {}},
    )

    assert tasks == []


def test_runtime_persists_programmer_artifact_for_code_change(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    proposals = runtime._persist_proposals(
        cycle_id="ci_cycle_test",
        proposal_payloads=[
            {
                "proposal_type": "CODE_CHANGE",
                "target_component": "software_runtime",
                "target_identifier": "error_handling_review",
                "current_value": "errors=3",
                "proposed_value": "Add explicit retries and structured diagnostics.",
                "rationale": "Repeated runtime failures need software hardening.",
                "expected_impact": "Fewer repeated failures.",
                "risk_level": "MEDIUM",
                "required_validations": ["tests"],
                "rollback_plan": "Revert the proposed patch if it increases noise.",
            }
        ],
    )

    artifact = store.continuous_improvement_proposal_artifact(proposals[0]["proposal_id"])
    assert artifact is not None
    assert "Suggested change" in artifact["content_text"]


def test_experiment_designer_assigns_required_validations_by_focus(tmp_path):
    settings = _settings(tmp_path)
    agent = ExperimentDesignerAgent(settings, ImprovementLLMClient(settings))

    result = agent.run(
        context={"evaluation": {"blockers": []}},
        event={"event_id": "evt"},
        task_payload={
            "focus": "pre_earnings_risk_veto",
            "initiative_key": "trading:pre_earnings_risk_veto",
        },
    )

    actions = (result.get("response") or {}).get("actions") or []
    assert actions[0]["required_validations"] == ["backtest", "baseline_compare", "shadow_review"]


def test_runtime_uses_specialist_task_result_for_initiative_state(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    experiment_updates = runtime._initiative_updates_from_task_result(
        task={"agent_name": "ExperimentDesignerAgent", "payload": {"focus": "software_reliability"}},
        result={
            "response": {
                "summary": "Planificar tests de regresion.",
                "actions": [
                    {
                        "action_type": "VALIDATION",
                        "required_validations": ["tests"],
                    }
                ],
            }
        },
    )
    committee_updates = runtime._initiative_updates_from_task_result(
        task={"agent_name": "DecisionCommitteeAgent", "payload": {"focus": "software_reliability"}},
        result={
            "response": {
                "summary": "Aplicar propuesta validada.",
                "decision": "APPROVE",
                "initiative_status_target": "READY_TO_APPLY",
                "backlog_bucket": "NOW",
                "required_follow_up": "Aplicar o promover la propuesta validada.",
            }
        },
    )

    assert experiment_updates["status"] == "EXPERIMENTING"
    assert experiment_updates["next_action"] == "Ejecutar validaciones: tests"
    assert experiment_updates["latest_decision"]["source"] == "ExperimentDesignerAgent"
    assert committee_updates["status"] == "READY_TO_APPLY"
    assert committee_updates["priority"] == "HIGH"
    assert committee_updates["latest_decision"]["source"] == "DecisionCommitteeAgent"


def test_decision_committee_emits_structured_rework_decision(tmp_path):
    settings = _settings(tmp_path)
    agent = DecisionCommitteeAgent(settings, ImprovementLLMClient(settings))

    result = agent.run(
        context={
            "existing_proposals": [
                {
                    "proposal_id": "ci_prop_pending",
                    "status": "PENDING",
                    "risk_level": "LOW",
                    "payload": {"initiative_key": "software:runtime_reliability"},
                    "guard": {"status": "PENDING"},
                }
            ]
        },
        event={"event_id": "evt"},
        task_payload={"initiative_key": "software:runtime_reliability"},
    )

    response = result["response"]
    assert response["decision"] == "REWORK"
    assert response["initiative_status_target"] == "EXPERIMENTING"
    assert response["backlog_bucket"] == "NEXT"
    assert response["proposal_status_targets"] == [{"proposal_id": "ci_prop_pending", "status": "PENDING"}]


def test_runtime_applies_committee_decision_to_linked_proposals(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_committee",
            "initiative_key": "software:runtime_reliability",
            "title": "Runtime reliability",
            "domain": "software",
            "status": "VALIDATING",
            "owner_agent": "SoftwareReliabilityAgent",
            "priority": "MEDIUM",
            "target_metric": "errors",
            "baseline_value": None,
            "current_value": None,
            "expected_impact": "Reduce errors.",
            "risk_level": "LOW",
            "evidence": [],
            "linked_event_ids": [],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": ["ci_prop_committee"],
            "linked_validation_ids": [],
            "latest_decision": {"decision": "VALIDATING"},
            "next_action": "Esperar comite.",
        }
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_committee",
            "cycle_id": "ci_cycle_committee",
            "fingerprint": "fp-ci_prop_committee",
            "proposal_type": "CODE_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "runtime_reliability",
            "status": "READY_TO_APPLY",
            "priority": "MEDIUM",
            "risk_level": "LOW",
            "payload": {"initiative_key": "software:runtime_reliability", "rollback_plan": "revert"},
            "guard": {"status": "READY_TO_APPLY"},
        }
    )

    result = {
        "response": {
            "decision": "APPROVE",
            "decision_reason": "validated",
            "initiative_status_target": "READY_TO_APPLY",
            "proposal_status_targets": [{"proposal_id": "ci_prop_committee", "status": "READY_TO_APPLY"}],
            "backlog_bucket": "NOW",
            "required_follow_up": "Aplicar o promover la propuesta validada.",
        }
    }
    updates = runtime._initiative_updates_from_task_result(
        task={"agent_name": "DecisionCommitteeAgent", "payload": {"focus": "runtime_reliability"}},
        result=result,
    )
    store.update_continuous_improvement_initiative("ci_init_committee", **updates)
    runtime._apply_committee_decision(
        cycle_id="ci_cycle_committee",
        initiative_id="ci_init_committee",
        task={"agent_name": "DecisionCommitteeAgent"},
        result=result,
    )

    initiative = store.continuous_improvement_initiative("ci_init_committee")
    proposal = store.continuous_improvement_proposal("ci_prop_committee")
    decisions = store.continuous_improvement_decisions(actor="DecisionCommitteeAgent", limit=10)
    assert initiative["status"] == "READY_TO_APPLY"
    assert initiative["latest_decision"]["decision"] == "APPROVE"
    assert initiative["latest_decision"]["backlog_bucket"] == "NOW"
    assert proposal["status"] == "READY_TO_APPLY"
    assert any(item["decision"] == "APPROVE" for item in decisions)


def test_runtime_persist_proposals_merges_experiment_guidance_into_required_validations(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    proposals = runtime._persist_proposals(
        cycle_id="ci_cycle_test",
        proposal_payloads=[
            {
                "proposal_type": "RISK_RULE_CHANGE",
                "target_component": "pre_earnings_risk_veto",
                "target_identifier": "risk_veto_policy",
                "current_value": "strict",
                "proposed_value": "shadow review",
                "rationale": "Blocked winners justify revalidation.",
                "expected_impact": "Reduce false negatives.",
                "risk_level": "MEDIUM",
                "required_validations": ["backtest"],
                "rollback_plan": "revert",
            }
        ],
        experiment_guidance={"trading:pre_earnings_risk_veto": ["baseline_compare", "shadow_review"]},
    )

    required = proposals[0]["payload"]["required_validations"]
    assert required == ["backtest", "baseline_compare", "shadow_review"]


def test_runtime_prepare_proposals_merges_duplicates_and_limits_count(tmp_path):
    settings = _settings(tmp_path, CONTINUOUS_IMPROVEMENT_MAX_PROPOSALS_PER_CYCLE=2)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    prepared, stats = runtime._prepare_proposals(
        [
            {
                "proposal_type": "RISK_RULE_CHANGE",
                "target_component": "pre_earnings_risk_veto",
                "target_identifier": "risk_veto_policy",
                "current_value": "strict",
                "proposed_value": "shadow review",
                "rationale": "3 blocked winners with +17%, +15% and +8%",
                "risk_level": "MEDIUM",
                "required_validations": ["backtest"],
                "rollback_plan": "revert",
            },
            {
                "proposal_type": "RISK_RULE_CHANGE",
                "target_component": "pre_earnings_risk_management",
                "target_identifier": "risk_veto_policy",
                "current_value": "strict",
                "proposed_value": "review veto in shadow",
                "rationale": "same topic with duplicate evidence",
                "risk_level": "MEDIUM",
                "required_validations": ["backtest"],
                "rollback_plan": "revert",
            },
            {
                "proposal_type": "MONITORING_CHANGE",
                "target_component": "strategy_evaluation",
                "target_identifier": "validation_backlog",
                "current_value": "manual",
                "proposed_value": "track backlog",
                "rationale": "needs monitoring",
                "risk_level": "LOW",
                "required_validations": [],
                "rollback_plan": "remove",
            },
            {
                "proposal_type": "DATA_QUALITY_CHANGE",
                "target_component": "analyst_estimates_pipeline",
                "target_identifier": "coverage_rate",
                "current_value": "33%",
                "proposed_value": "60%+ coverage",
                "rationale": "coverage is too low",
                "risk_level": "LOW",
                "required_validations": ["tests"],
                "rollback_plan": "revert",
            },
        ]
    )

    assert len(prepared) == 2
    assert stats["merged"] == 1
    assert stats["dropped_by_limit"] == 1
    assert prepared[0]["target_identifier"] == "risk_veto_policy"
    assert int(prepared[0]["_merged_count"]) == 2


def test_validation_agent_keeps_risk_rule_change_pending_without_real_execution(tmp_path):
    settings = _settings(tmp_path)
    validation = ValidationAgent().validate(
        {
            "proposal_id": "ci_prop_test",
            "cycle_id": "ci_cycle_test",
            "proposal_type": "RISK_RULE_CHANGE",
            "payload": {
                "rollback_plan": "revert",
                "required_validations": [],
            },
        },
        {"evaluation": {"data_quality": "PARTIAL"}},
        settings,
    )

    assert validation["status"] == "PENDING"
    payload = validation["payload"]
    assert payload["objective_status"] == "PENDING"
    assert any(item["name"] == "backtest_evidence" and item["passed"] is False for item in payload["checks"])


def test_validation_agent_passes_entry_quality_with_objective_evidence(tmp_path):
    settings = _settings(tmp_path)
    validation = ValidationAgent().validate(
        {
            "proposal_id": "ci_prop_test_pass",
            "cycle_id": "ci_cycle_test",
            "proposal_type": "PARAMETER_CHANGE",
            "target_component": "entry_quality_filter",
            "payload": {
                "rollback_plan": "revert",
                "required_validations": ["backtest", "baseline_compare"],
            },
        },
        {
            "evaluation": {"summary": {"blocked_entry_quality": 3, "observations": 12, "signals": 12}},
            "learning": {"observations": [{"duplicate_count": 1}, {"duplicate_count": 0}]},
            "reports": {
                "daily_learning": {
                    "available": True,
                    "payload": {
                        "summary": {"duplicate_ratio": 0.25, "canonical_observations": 12},
                        "entry_quality_filter_calibration_3d": {
                            "signals": 8,
                            "matured": 6,
                            "avg_return": 0.012,
                            "missed_winners": 1,
                            "avoided_losers": 2,
                            "top_tags": [{"tag": "score:gte12", "net_winner_gap": -1}],
                        },
                        "backtest_filter_calibration_3d": {
                            "signals": 5,
                            "matured": 4,
                            "avg_return": 0.018,
                            "missed_winners": 0,
                            "avoided_losers": 1,
                            "top_tags": [{"tag": "score:gte12", "net_winner_gap": 0}],
                        },
                    },
                }
            },
        },
        settings,
    )

    assert validation["status"] == "PASSED"
    payload = validation["payload"]
    assert payload["objective_status"] in {"PASSED", "READY_TO_APPLY"}
    assert any(check["name"] == "entry_quality_calibration_present" and check["passed"] for check in payload["checks"])


def test_runtime_translates_passed_validation_into_review_status(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_validate",
            "initiative_key": "trading:entry_quality_filter",
            "title": "Recalibrar filtro de calidad de entrada",
            "domain": "trading",
            "status": "VALIDATING",
            "owner_agent": "TechnicalEdgeAgent",
            "priority": "HIGH",
            "target_metric": "false_positive_rate",
            "baseline_value": 3,
            "current_value": 3,
            "expected_impact": "Reducir bloqueos falsos.",
            "risk_level": "LOW",
            "evidence": ["signals=10"],
            "linked_event_ids": ["evt_1"],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": [],
            "linked_validation_ids": [],
            "latest_decision": {"decision": "VALIDATING"},
            "next_action": "Esperar validacion.",
        }
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_test",
            "cycle_id": "ci_cycle_test",
            "fingerprint": "fp-ci_prop_test",
            "proposal_type": "PARAMETER_CHANGE",
            "target_component": "entry_quality_filter",
            "target_identifier": "entry_quality_filter",
            "status": "PENDING",
            "priority": "MEDIUM",
            "risk_level": "LOW",
            "payload": {
                "initiative_key": "trading:entry_quality_filter",
                "required_validations": ["backtest", "baseline_compare"],
                "rollback_plan": "revert",
            },
            "guard": {"status": "PENDING"},
        }
    )

    runtime.validator.validate = lambda proposal, context, settings, store=None: {
        "validation_id": "ci_val_test",
        "proposal_id": proposal["proposal_id"],
        "cycle_id": proposal["cycle_id"],
        "validation_type": "deterministic_gate",
        "status": "PASSED",
        "payload": {"objective_summary": "Validacion objetiva completada.", "checks": []},
    }

    validations = runtime._persist_validations(
        cycle_id="ci_cycle_test",
        proposals=[
            {
                "proposal_id": "ci_prop_test",
                "cycle_id": "ci_cycle_test",
                "proposal_type": "PARAMETER_CHANGE",
                "target_component": "entry_quality_filter",
                "payload": {
                    "initiative_key": "trading:entry_quality_filter",
                    "required_validations": ["backtest", "baseline_compare"],
                    "rollback_plan": "revert",
                },
            }
        ],
        context={"evaluation": {"data_quality": "GOOD"}},
    )

    initiative = store.continuous_improvement_initiative("ci_init_validate")
    proposal = store.continuous_improvement_proposal("ci_prop_test")

    assert validations[0]["status"] == "PASSED"
    assert initiative["status"] == "WAITING_REVIEW"
    assert proposal["status"] == "PASSED"


def test_runtime_executes_validation_artifacts_before_validation(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    runtime = ContinuousImprovementLabRuntime(settings, store)

    calls = {}

    def _fake_backtest(symbol, output_dir, run_id, **kwargs):
        calls["backtest"] = {"symbol": symbol, "run_id": run_id, **kwargs}
        report = {
            "symbol": symbol,
            "metrics": {"trades": 12, "hit_rate": 0.58, "profit_factor": 1.3, "max_drawdown": -0.04},
            "validation": {"gate": {"approved": True, "reason": "backtest aprobado"}},
        }
        (output_dir / f"backtest_{symbol}_{run_id}.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    def _fake_wf(settings, store, reports_dir, run_id, **kwargs):
        calls["walk_forward"] = {"run_id": run_id, **kwargs}
        report = {"summary": {"windows": 4, "stable_windows": 3}}
        (reports_dir / "latest_walk_forward_validation.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    def _fake_sr(settings, store, reports_dir, run_id, **kwargs):
        calls["session_retrospective"] = {"run_id": run_id, **kwargs}
        report = {"summary": {"sessions": 3, "aggregate_delta_net_opportunity": 1.2}, "sessions": [1, 2, 3]}
        (reports_dir / "latest_session_retrospective.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    monkeypatch.setattr("agente_bolsa.continuous_improvement.runtime.build_symbol_backtest", _fake_backtest)
    monkeypatch.setattr("agente_bolsa.continuous_improvement.runtime.build_walk_forward_validation_report", _fake_wf)
    monkeypatch.setattr("agente_bolsa.continuous_improvement.runtime.build_session_retrospective_report", _fake_sr)

    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_artifacts",
            "cycle_id": "ci_cycle_artifacts",
            "fingerprint": "fp-ci_prop_artifacts",
            "proposal_type": "RISK_RULE_CHANGE",
            "target_component": "pre_earnings_risk_veto",
            "target_identifier": "AAPL",
            "status": "PENDING",
            "priority": "HIGH",
            "risk_level": "MEDIUM",
            "payload": {
                "symbol": "AAPL",
                "initiative_key": "trading:pre_earnings_risk_veto",
                "required_validations": ["backtest", "baseline_compare", "shadow_review"],
                "backtest_start": "2026-04-01",
                "backtest_end": "2026-05-30",
                "rollback_plan": "revert",
            },
            "guard": {"status": "PENDING"},
        }
    )

    artifacts = runtime._execute_validation_artifacts(
        proposal=store.continuous_improvement_proposal("ci_prop_artifacts"),
        cycle_id="ci_cycle_artifacts",
    )
    context = {
        "evaluation": {"summary": {}},
        "reports": {
            "daily_learning": {"available": True, "payload": {"summary": {"signals": 1}}},
            **{key: {"available": True, "payload": value} for key, value in artifacts.items() if isinstance(value, dict)},
        },
    }
    validation = runtime.validator.validate(
        store.continuous_improvement_proposal("ci_prop_artifacts"),
        context,
        settings,
        store=store,
    )

    assert "backtest" in calls
    assert "walk_forward" in calls
    assert "session_retrospective" in calls
    assert validation["payload"]["objective_status"] in {"PENDING", "PASSED", "READY_TO_APPLY"}
    assert any(item["name"] == "backtest_evidence" for item in validation["payload"]["checks"])


def test_improvement_strategist_uses_orchestrator_model(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
        IMPROVEMENT_LLM_ORCHESTRATOR_MODEL="mimo-v2.5-pro",
    )
    client = ImprovementLLMClient(settings)
    calls = {}

    def _fake_generate_json(messages, schema, **kwargs):
        calls["kwargs"] = kwargs
        return type(
            "R",
            (),
            {
                "ok": False,
                "llm_call_id": "x",
                "payload": None,
                "raw_response": None,
                "error": "skip",
                "provider": "",
                "model": kwargs.get("model"),
                "request_preview": {"model": kwargs.get("model")},
            },
        )()

    strategist = ImprovementStrategistAgent(client, settings)
    strategist.client.generate_json = _fake_generate_json
    result = strategist.propose({"ctx": 1}, {"eval": 1})

    assert calls["kwargs"]["model"] == "mimo-v2.5-pro"
    assert result.model == "mimo-v2.5-pro"


def test_improvement_strategist_exports_runtime_safety_rules(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_DRY_RUN=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=True,
        REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=False,
    )
    client = ImprovementLLMClient(settings)
    captured = {}

    def _fake_generate_json(messages, schema, **kwargs):
        captured["messages"] = messages
        return type(
            "R",
            (),
            {
                "ok": False,
                "llm_call_id": "x",
                "payload": None,
                "raw_response": None,
                "error": "skip",
                "provider": "",
                "model": kwargs.get("model"),
                "request_preview": {"model": kwargs.get("model")},
            },
        )()

    strategist = ImprovementStrategistAgent(client, settings)
    strategist.client.generate_json = _fake_generate_json
    strategist.propose({"ctx": 1}, {"eval": 1})
    user_payload = json.loads(captured["messages"][1]["content"])

    assert user_payload["safety_rules"]["code_changes_require_human_review"] is False
    assert user_payload["safety_rules"]["dry_run_first"] is False
    assert user_payload["safety_rules"]["allow_auto_apply_improvements"] is True


def test_specialist_agents_keep_base_model(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
        IMPROVEMENT_LLM_ORCHESTRATOR_MODEL="mimo-v2.5-pro",
    )
    client = ImprovementLLMClient(settings)
    calls = {}

    def _fake_generate_json(messages, schema, **kwargs):
        calls["kwargs"] = kwargs
        return type(
            "R",
            (),
            {
                "ok": False,
                "llm_call_id": "x",
                "payload": None,
                "raw_response": None,
                "error": "skip",
                "provider": "",
                "model": settings.improvement_llm_model,
                "request_preview": {"model": settings.improvement_llm_model},
                "model_dump": lambda self=None: {
                    "ok": False,
                    "llm_call_id": "x",
                    "payload": None,
                    "raw_response": None,
                    "error": "skip",
                    "provider": "",
                    "model": settings.improvement_llm_model,
                    "request_preview": {"model": settings.improvement_llm_model},
                },
            },
        )()

    agent = MarketEstimatorAgent(settings, client)
    agent.client.generate_json = _fake_generate_json
    agent.run(
        context={"evaluation": {"summary": {"outcomes_available": 0}}, "reports": {}},
        event={"event_id": "evt"},
        task_payload={"focus": "market"},
    )

    assert "model" not in calls["kwargs"]


def test_extended_specialist_agents_also_use_base_model(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_MODEL="mimo-v2.5",
    )
    client = ImprovementLLMClient(settings)
    calls = {}

    def _fake_generate_json(messages, schema, **kwargs):
        calls["kwargs"] = kwargs
        return type(
            "R",
            (),
            {
                "ok": False,
                "llm_call_id": "x",
                "payload": None,
                "raw_response": None,
                "error": "skip",
                "provider": "",
                "model": settings.improvement_llm_model,
                "request_preview": {"model": settings.improvement_llm_model},
                "model_dump": lambda self=None: {
                    "ok": False,
                    "llm_call_id": "x",
                    "payload": None,
                    "raw_response": None,
                    "error": "skip",
                    "provider": "",
                    "model": settings.improvement_llm_model,
                    "request_preview": {"model": settings.improvement_llm_model},
                },
            },
        )()

    agent = TechnicalEdgeAgent(settings, client)
    agent.client.generate_json = _fake_generate_json
    agent.run(
        context={"evaluation": {"summary": {"observations": 5, "blocked_entry_quality": 1}}, "reports": {}},
        event={"event_id": "evt"},
        task_payload={"focus": "entry_quality_filter"},
    )

    assert "model" not in calls["kwargs"]


def test_continuous_improvement_cycle_creates_proposal_and_validation(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(ContinuousImprovementLabRuntime, "_market_window", lambda self: _open_market_window())

    result = ContinuousImprovementOrchestrator(settings, store).run_cycle(mode="manual")

    assert result["status"] in {"COMPLETED", "WAITING_HUMAN_REVIEW", "PARTIAL"}
    proposals = store.continuous_improvement_proposals()
    validations = store.continuous_improvement_validations()
    assert len(proposals) >= 1
    assert len(validations) >= 1


def test_continuous_improvement_dedupe_key_returns_existing_cycle(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = ContinuousImprovementOrchestrator(settings, store)
    monkeypatch.setattr(ContinuousImprovementLabRuntime, "_market_window", lambda self: _open_market_window())

    first = orchestrator.run_cycle(mode="scheduled", dedupe_key="ci:test")
    second = orchestrator.run_cycle(mode="scheduled", dedupe_key="ci:test")

    assert second["deduped"] is True
    assert second["cycle_id"] == first["cycle_id"]


def test_apply_action_is_blocked_to_human_review_status(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(ContinuousImprovementLabRuntime, "_market_window", lambda self: _open_market_window())
    ContinuousImprovementOrchestrator(settings, store).run_cycle(mode="manual")
    proposal = store.continuous_improvement_proposals()[0]

    store.update_continuous_improvement_proposal_status(
        proposal["proposal_id"],
        status="WAITING_HUMAN_REVIEW",
        actor="test",
        reason="apply blocked in v1",
    )

    updated = store.continuous_improvement_proposal(proposal["proposal_id"])
    assert updated["status"] == "WAITING_HUMAN_REVIEW"


def test_status_payload_reports_runtime(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_continuous_improvement_runtime_state(
        runtime_name="lab",
        status="IDLE",
        heartbeat_at="2026-01-01T00:00:00+00:00",
        payload={"ok": True},
    )

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONTINUOUS_IMPROVEMENT_ENABLED", "true")
    monkeypatch.setenv("IMPROVEMENT_DRY_RUN", "true")
    monkeypatch.setenv("ALLOW_AUTO_APPLY_IMPROVEMENTS", "false")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    get_settings.cache_clear()

    payload = status_payload()

    assert payload["runtime"] is not None
    assert "latest_cycle" in payload
    assert payload["llm_model"] == settings.improvement_llm_model
    assert payload["llm_orchestrator_model"] == settings.improvement_llm_orchestrator_model


def test_status_payload_reports_initiative_counts(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_status",
            "initiative_key": "trading:pre_earnings_risk_veto",
            "title": "Recalibrar veto pre-earnings",
            "domain": "trading",
            "status": "VALIDATING",
            "owner_agent": "PreEarningsSpecialistAgent",
            "priority": "HIGH",
            "target_metric": "blocked_winners",
            "baseline_value": 2,
            "current_value": 2,
            "expected_impact": "Reducir ganadores bloqueados.",
            "risk_level": "MEDIUM",
            "evidence": ["blocked_winners=2"],
            "linked_event_ids": ["evt_1"],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": [],
            "linked_validation_ids": [],
            "latest_decision": {"decision": "VALIDATING"},
            "next_action": "Esperar validacion.",
        }
    )
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_ready",
            "initiative_key": "trading:signal_consolidation",
            "title": "Consolidar señales",
            "domain": "trading",
            "status": "READY_TO_APPLY",
            "owner_agent": "TechnicalEdgeAgent",
            "priority": "HIGH",
            "target_metric": "duplicate_signals",
            "baseline_value": 5,
            "current_value": 2,
            "expected_impact": "Reducir duplicados.",
            "risk_level": "LOW",
            "evidence": ["duplicate_signals=3"],
            "linked_event_ids": ["evt_2"],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": [],
            "linked_validation_ids": [],
            "latest_decision": {"decision": "READY_TO_APPLY"},
            "next_action": "Revision final.",
        }
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_status_decision",
            "cycle_id": "ci_cycle_status_decision",
            "fingerprint": "fp-ci_prop_status_decision",
            "proposal_type": "CODE_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "status",
            "status": "READY_TO_APPLY",
            "priority": "HIGH",
            "risk_level": "LOW",
            "payload": {"initiative_key": "trading:signal_consolidation"},
            "guard": {"status": "READY_TO_APPLY"},
        }
    )
    store.save_continuous_improvement_decision(
        {
            "decision_id": "ci_decision_status",
            "proposal_id": "ci_prop_status_decision",
            "cycle_id": "ci_cycle_status_decision",
            "decision": "APPROVE",
            "reason": "validated",
            "actor": "DecisionCommitteeAgent",
            "payload": {"committee_decision": {"backlog_bucket": "NOW"}},
        }
    )

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONTINUOUS_IMPROVEMENT_ENABLED", "true")
    monkeypatch.setenv("IMPROVEMENT_DRY_RUN", "true")
    monkeypatch.setenv("ALLOW_AUTO_APPLY_IMPROVEMENTS", "false")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    get_settings.cache_clear()

    payload = status_payload()

    assert payload["initiatives_validating"] == 1
    assert payload["initiatives_open"] == 0
    assert payload["initiatives_review"] == 0
    assert payload["initiatives_ready_to_apply"] == 1
    assert payload["committee_decisions"]["APPROVE"] == 1
    assert payload["backlog_buckets"]["NOW"] == 1


def test_auto_apply_code_agent_applies_allowed_file_edit(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "ci_autonomous_target.txt").write_text("before\n", encoding="utf-8")
    settings = _code_apply_settings(tmp_path / "state", workspace)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=_code_proposal(),
        validation=_ready_validation(),
    )

    assert result["status"] == "APPLIED"
    assert (workspace / "tests" / "ci_autonomous_target.txt").read_text(encoding="utf-8") == "after\n"
    changes = store.continuous_improvement_applied_changes(statuses=["APPLIED"])
    assert len(changes) == 1
    assert changes[0]["change_type"] == "CODE_CHANGE"


def test_validation_agent_allows_code_change_ready_to_apply_with_autonomy_flags(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _code_apply_settings(tmp_path / "state", workspace)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    validation = ValidationAgent().validate(_code_proposal(), {"reports": {}, "evaluation": {}}, settings, store=store)

    assert validation["status"] == "READY_TO_APPLY"
    check_names = {item["name"] for item in validation["payload"]["checks"]}
    assert "code_artifact_applicable" in check_names


def test_auto_apply_code_agent_blocks_protected_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _code_apply_settings(tmp_path / "state", workspace)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = _code_proposal(
        file_edits=[
            {
                "path": "src/agente_bolsa/tools/execution.py",
                "content": "# blocked\n",
            }
        ],
        test_commands=["python -c \"assert True\""],
    )

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=proposal,
        validation=_ready_validation(),
    )

    assert result["status"] == "BLOCKED"
    assert "bloqueado" in result["error"]
    assert not (workspace / "src" / "agente_bolsa" / "tools" / "execution.py").exists()


def test_auto_apply_code_agent_rolls_back_when_tests_fail(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    target = workspace / "tests" / "ci_autonomous_target.txt"
    target.write_text("before\n", encoding="utf-8")
    settings = _code_apply_settings(tmp_path / "state", workspace)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = _code_proposal(test_commands=["python -c \"raise SystemExit(1)\""])

    result = AutoApplyCodeAgent().try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=proposal,
        validation=_ready_validation(),
    )

    assert result["status"] == "ROLLED_BACK"
    assert target.read_text(encoding="utf-8") == "before\n"
    changes = store.continuous_improvement_applied_changes(statuses=["ROLLED_BACK"])
    assert len(changes) == 1


def test_auto_apply_code_agent_manual_rollback_restores_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    target = workspace / "tests" / "ci_autonomous_target.txt"
    target.write_text("before\n", encoding="utf-8")
    settings = _code_apply_settings(tmp_path / "state", workspace)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    agent = AutoApplyCodeAgent()
    applied = agent.try_apply(
        settings=settings,
        store=store,
        initiative=None,
        proposal=_code_proposal(),
        validation=_ready_validation(),
    )
    assert target.read_text(encoding="utf-8") == "after\n"

    rolled_back = agent.rollback(
        settings=settings,
        store=store,
        applied_change_id=applied["applied_change_id"],
        actor="test",
    )

    assert rolled_back["status"] == "ROLLED_BACK"
    assert target.read_text(encoding="utf-8") == "before\n"


def test_store_initiatives_and_messages_round_trip(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    initiative_id, inserted = store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": "ci_init_test",
            "initiative_key": "trading:entry_quality_filter",
            "title": "Recalibrar filtro de calidad de entrada",
            "domain": "trading",
            "status": "OPEN",
            "owner_agent": "TechnicalEdgeAgent",
            "priority": "HIGH",
            "target_metric": "false_positive_rate",
            "baseline_value": 3,
            "current_value": 3,
            "expected_impact": "Reducir bloqueos falsos.",
            "risk_level": "LOW",
            "evidence": ["signals=10"],
            "linked_event_ids": ["evt_1"],
            "linked_task_ids": ["task_1"],
            "linked_hypothesis_ids": ["hyp_1"],
            "linked_proposal_ids": ["prop_1"],
            "linked_validation_ids": ["val_1"],
            "latest_decision": {"decision": "OPEN"},
            "next_action": "Esperar analisis.",
        }
    )
    store.save_continuous_improvement_initiative_message(
        {
            "message_id": "ci_msg_test",
            "initiative_id": initiative_id,
            "cycle_id": "ci_cycle_test",
            "event_id": "evt_1",
            "task_id": "task_1",
            "agent_name": "TechnicalEdgeAgent",
            "role": "agent",
            "message_type": "task_completed",
            "content": {"summary": "Filtro revisado."},
        }
    )

    initiative = store.continuous_improvement_initiative(initiative_id)
    messages = store.continuous_improvement_initiative_messages(initiative_id=initiative_id)

    assert inserted is True
    assert initiative["initiative_key"] == "trading:entry_quality_filter"
    assert initiative["linked_proposal_ids"] == ["prop_1"]
    assert messages[0]["content"]["summary"] == "Filtro revisado."


def test_orchestrator_plans_initiatives_and_manual_software_work(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    orchestrator = LabOrchestrator(store)

    trading_tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_trade", "domain": "trading-improvement", "event_type": "scheduled_tick"},
        {
            "evaluation": {
                "summary": {
                    "signals": 10,
                    "observations": 10,
                    "outcomes_available": 0,
                    "blocked_entry_quality": 1,
                    "blocked_backtest": 0,
                },
                "blockers": [],
            },
            "reports": {
                "daily_learning": {"available": True, "payload": {"summary": {"signals": 10}}},
            },
        },
    )
    software_tasks = orchestrator.planned_tasks_for_event(
        {"event_id": "evt_soft", "domain": "software-improvement", "event_type": "manual_trigger"},
        {"events": {"recent_errors": []}, "reports": {"market_data_quality": {"available": False}}},
    )

    assert any(task["payload"]["initiative_key"] == "trading:entry_quality_filter" for task in trading_tasks)
    assert all(task["agent_name"] != "SentimentAnalystAgent" for task in trading_tasks)
    assert software_tasks
    assert all(task["payload"]["initiative_key"].startswith("software:") for task in software_tasks)
