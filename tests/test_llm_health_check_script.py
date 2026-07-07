from __future__ import annotations

import importlib.util
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
