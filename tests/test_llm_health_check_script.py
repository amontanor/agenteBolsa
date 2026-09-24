from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "llm_health_check.py"
SPEC = importlib.util.spec_from_file_location("llm_health_check_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_validate_probe_content_rejects_truncated_empty_response():
    spec = MODULE.ProbeSpec(
        role="decision",
        provider="decision",
        base_url="https://example.invalid/v1",
        api_key="token",
        model="test-model",
        messages=[],
        max_tokens=512,
        expected_text="OK-DECISION",
    )

    ok, error = MODULE._validate_probe_content(spec, "", "length")

    assert ok is False
    assert error == "finish_reason=length"


def test_validate_probe_content_accepts_complete_sentiment_json():
    spec = MODULE.ProbeSpec(
        role="sentiment",
        provider="sentiment",
        base_url="https://example.invalid/v1",
        api_key="token",
        model="test-model",
        messages=[],
        max_tokens=2048,
        required_json_keys=(
            "sentiment",
            "sentiment_score",
            "supports_technical_setup",
            "confidence",
            "summary",
            "risk_flags",
        ),
    )

    ok, error = MODULE._validate_probe_content(
        spec,
        (
            '{"sentiment":"positive","sentiment_score":0.8,'
            '"supports_technical_setup":true,"confidence":0.9,'
            '"summary":"ok","risk_flags":[]}'
        ),
        "stop",
    )

    assert ok is True
    assert error is None


def test_health_specs_migrate_retired_id_for_roles_and_codegen():
    specs = MODULE.build_probe_specs(
        {
            "LLM_MODEL_SELECTOR": "opencode-zen",
            "OPENCODE_MODEL": "deepseek-v4-flash-free",
            "LLM_ROLE_DECISION_MODEL": "deepseek-v4-flash-free",
            "LLM_ROLE_SENTIMENT_MODEL": "deepseek-v4-flash-free",
            "LLM_ROLE_DEEP_MODEL": "deepseek-v4-flash-free",
            "IMPROVEMENT_LLM_MODEL": "deepseek-v4-flash-free",
            "IMPROVEMENT_LLM_CODEGEN_MODEL": "deepseek-v4-flash-free",
            "IMPROVEMENT_LLM_ORCHESTRATOR_MODEL": "deepseek-v4-flash-free",
        }
    )

    assert {spec.role for spec in specs} >= {"decision", "sentiment", "deep", "improvement", "codegen"}
    assert all(spec.model == "deepseek-v4.1-flash" for spec in specs)


def test_health_probe_migrates_model_before_sending(monkeypatch):
    captured = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read():
            return json.dumps(
                {"choices": [{"message": {"content": "OK-DECISION"}, "finish_reason": "stop"}]}
            ).encode()

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", _fake_urlopen)
    spec = MODULE.ProbeSpec(
        role="decision",
        provider="decision [opencode-zen]",
        base_url="https://opencode.ai/zen/v1",
        api_key="synthetic-key",
        model="deepseek-v4-flash-free",
        messages=[],
        max_tokens=512,
        expected_text="OK-DECISION",
    )

    result = MODULE.ping_provider(spec, timeout=1)

    assert result["ok"] is True
    assert result["model"] == "deepseek-v4.1-flash"
    assert captured["body"]["model"] == "deepseek-v4.1-flash"
    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"
