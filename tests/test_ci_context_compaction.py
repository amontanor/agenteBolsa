from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.context_compaction import (
    compact_ci_context_for_llm,
    compact_ci_context_for_local_fallback,
    compact_messages_for_token_budget,
    estimate_json_tokens,
)
from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient
from agente_bolsa.web_app import _ci_llm_route_label, _ci_llm_truncation_label, _ci_llm_usage_label


def _settings(tmp_path, **overrides):
    values = {
        "DATABASE_PATH": tmp_path / "test.db",
        "DATA_DIR": tmp_path / "data",
        "LOGS_DIR": tmp_path / "logs",
        "AGENT_LOGS_DIR": tmp_path / "logs" / "agents",
        "IMPROVEMENT_LLM_ENABLED": True,
        "IMPROVEMENT_LLM_PROVIDER": "openai",
        "IMPROVEMENT_LLM_BASE_URL": "http://primary.local/v1",
        "IMPROVEMENT_LLM_API_KEY": "primary-key",
        "IMPROVEMENT_LLM_MODEL": "test-model",
        "IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _large_context() -> dict:
    huge_text = "x" * 200_000
    return {
        "cycle_id": "ci_cycle_test",
        "evaluation": {"summary": {"status": "PARTIAL"}, "giant": huge_text},
        "events": {
            "latest": [
                {
                    "event_type": "lab_error",
                    "agent": "agent",
                    "created_at": f"2026-01-01T00:{index:02d}:00+00:00",
                    "payload": {"message": huge_text, "error": huge_text},
                }
                for index in range(60)
            ],
            "recent_errors": [{"event_type": "error", "payload": {"error": huge_text}} for _ in range(30)],
        },
        "reports": {
            "operational_health": {
                "available": True,
                "path": "latest_operational_health.json",
                "payload": {
                    "summary": {"healthy": False, "overall_status": "warning"},
                    "issues": [{"message": huge_text} for _ in range(80)],
                    "recommendations": [{"message": huge_text} for _ in range(80)],
                    "full_report": huge_text,
                },
            }
        },
        "learning": {
            "signals": [{"symbol": "AAA", "notes": huge_text} for _ in range(100)],
            "observations": [{"kind": "error", "details": huge_text} for _ in range(100)],
        },
        "existing_proposals": [
            {
                "proposal_id": f"ci_prop_{index}",
                "status": "PENDING" if index % 2 == 0 else "PASSED",
                "payload": {"rationale": huge_text, "expected_impact": huge_text},
            }
            for index in range(100)
        ],
        "initiatives": [{"initiative_id": f"ci_init_{index}", "payload": {"next_action": huge_text}} for index in range(100)],
        "initiative_messages": [{"content": huge_text} for _ in range(100)],
        "hypotheses": [{"description": huge_text} for _ in range(100)],
        "memories": [{"content": huge_text} for _ in range(100)],
    }


def test_compact_ci_context_keeps_payload_below_hard_limit_and_drops_report_blobs():
    payload = compact_ci_context_for_llm(
        context=_large_context(),
        evaluation={"summary": {"status": "PARTIAL"}},
        safety_rules={"no_live_trading": True},
        target_tokens=4000,
        hard_limit_tokens=8000,
    )

    assert estimate_json_tokens(payload) <= 8000
    report = payload["real_context"]["reports"]["operational_health"]["summary"]
    assert "full_report" not in report
    assert len(report.get("issues", [])) <= 5
    assert len(payload["real_context"]["events"]["latest"]) <= 20
    assert len(payload["real_context"]["existing_proposals"]) <= 40
    assert payload["_compaction"]["truncations"]


def test_local_fallback_compaction_is_more_restrictive():
    primary = compact_ci_context_for_llm(
        context=_large_context(),
        evaluation={"summary": {"status": "PARTIAL"}},
        target_tokens=40000,
        hard_limit_tokens=55000,
    )
    local = compact_ci_context_for_local_fallback(
        context=_large_context(),
        evaluation={"summary": {"status": "PARTIAL"}},
        target_tokens=30000,
        hard_limit_tokens=50000,
    )

    assert estimate_json_tokens(local) <= estimate_json_tokens(primary)
    assert len(local["real_context"]["events"]["latest"]) <= 15
    assert len(local["real_context"]["initiative_messages"]) <= 20


def test_compact_messages_for_token_budget_truncates_json_content():
    messages = [{"role": "user", "content": json.dumps({"items": ["x" * 2000 for _ in range(100)]})}]

    compacted, metadata = compact_messages_for_token_budget(
        messages,
        target_tokens=500,
        hard_limit_tokens=1000,
        force=True,
    )

    assert metadata["compacted"] is True
    assert estimate_json_tokens(compacted) <= 1000
    content = json.loads(compacted[0]["content"])
    assert len(content["items"]) <= 20
    assert "truncated" in content["items"][0]


def test_improvement_llm_client_rejects_prompt_above_hard_limit_before_request(tmp_path):
    settings = _settings(
        tmp_path,
        IMPROVEMENT_LLM_CONTEXT_TARGET_TOKENS=10,
        IMPROVEMENT_LLM_CONTEXT_HARD_LIMIT_TOKENS=10,
    )
    client = ImprovementLLMClient(settings)
    calls = []

    def _fake_post(endpoint, body, headers):
        calls.append((endpoint, body, headers))
        raise AssertionError("endpoint should not be called")

    client._post_json = _fake_post
    result = client.generate_json([{"role": "user", "content": "x" * 10000}], {})

    assert result.ok is False
    assert "context_too_large_before_request" in str(result.error)
    assert result.prompt_tokens_estimate is not None
    assert result.context_limit_tokens == 10
    assert calls == []


def test_ci_llm_ui_helpers_show_route_tokens_and_truncation(tmp_path):
    settings = _settings(tmp_path)
    result = {
        "provider": "openai-local",
        "model": "qwen3.6-27b",
        "base_url": "http://127.0.0.1:8080/v1",
        "fallback_used": True,
        "prompt_tokens_estimate": 1234,
        "context_limit_tokens": 50000,
        "context_compacted": True,
        "truncation_report": {"truncations": [{"path": "reports.big", "original": 1000, "kept": 5}]},
    }

    assert "fallback local" in _ci_llm_route_label(settings, result)
    assert "1234 / 50000 tokens" in _ci_llm_usage_label(result)
    assert "compactado: si" in _ci_llm_usage_label(result)
    assert "reports.big" in _ci_llm_truncation_label(result)
