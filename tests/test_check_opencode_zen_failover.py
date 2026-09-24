from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_opencode_zen_failover.py"
SPEC = importlib.util.spec_from_file_location("check_opencode_zen_failover", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _config(provider="opencode-zen", model="deepseek-v4-flash-free", mode="health", max_tokens=512):
    return MODULE.ProbeConfig(
        provider=provider,
        model=model,
        endpoint=MODULE.endpoint_from_base(
            "https://opencode.ai/zen/v1" if provider == "opencode-zen" else "https://opencode.ai/zen/go/v1"
        ),
        api_key="synthetic-key",
        mode=mode,
        max_tokens=max_tokens,
    )


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(
    status=200,
    *,
    content="ready",
    reasoning_content=None,
    finish_reason="stop",
    body=None,
    headers=None,
):
    if body is None:
        message = {"content": content}
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        body = json.dumps(
            {
                "choices": [{"message": message, "finish_reason": finish_reason}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                    "completion_tokens_details": {"reasoning_tokens": 1},
                },
            }
        ).encode()
    return MODULE.TransportResponse(status=status, body=body, headers=headers or {})


class TokenAwareTransport(FakeTransport):
    def post(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs["body"])
        if request["max_tokens"] <= 32:
            return _response(content="partial", finish_reason="length")
        return _response()


def test_zen_success_is_one_request_and_reports_safe_identity():
    transport = FakeTransport([_response(headers={"x-request-id": "secret-id", "x-ratelimit-limit": "9"})])

    result = MODULE.run_probe(_config(), transport=transport)

    assert result["ok"] is True
    assert result["provider"] == "opencode-zen"
    assert result["model"] == "deepseek-v4.1-flash"
    assert json.loads(transport.calls[0]["body"])["model"] == "deepseek-v4.1-flash"
    assert result["endpoint_path"] == "/zen/v1/chat/completions"
    assert result["requests_made"] == 1
    assert result["request_id_present"] is True
    assert result["rate_limit_headers_present"] is True
    assert result["content_present"] is True
    assert result["reasoning_content_present"] is False
    assert result["captured_at"].endswith("+00:00")
    assert result["usage"]["reasoning_tokens"] == 1
    assert "secret-id" not in json.dumps(result)


def test_retired_model_is_migrated_in_health_probe_request():
    transport = FakeTransport([_response()])

    result = MODULE.run_probe(_config(model="deepseek-v4-flash-free"), transport=transport)

    assert result["model"] == "deepseek-v4.1-flash"
    assert json.loads(transport.calls[0]["body"])["model"] == "deepseek-v4.1-flash"
    assert transport.calls[0]["endpoint"] == "https://opencode.ai/zen/v1/chat/completions"


def test_structured_multiturn_and_combined_modes_validate_without_network():
    structured = FakeTransport([_response(content='{"ok":true}')])
    result = MODULE.run_probe(_config(mode="structured"), transport=structured)
    assert result["ok"] is True
    assert json.loads(structured.calls[0]["body"])["response_format"] == {"type": "json_object"}

    multiturn = FakeTransport([_response()])
    result = MODULE.run_probe(_config(mode="multiturn"), transport=multiturn)
    assert result["ok"] is True
    assert json.loads(multiturn.calls[0]["body"])["reasoning_effort"] == "low"

    combined = FakeTransport([_response(content='{"ok":true}', reasoning_content="short")])
    result = MODULE.run_probe(_config(mode="combined"), transport=combined)
    assert result["ok"] is True
    combined_body = json.loads(combined.calls[0]["body"])
    assert combined_body["response_format"] == {"type": "json_object"}
    assert combined_body["reasoning_effort"] == "low"
    assert result["reasoning_content_present"] is True


def test_low_cap_can_produce_length_but_aligned_cap_is_valid():
    low = MODULE.run_probe(_config(max_tokens=32), transport=TokenAwareTransport([]))
    assert low["ok"] is False
    assert low["finish_reason"] == "length"
    assert low["error_type"] == "finish_reason_invalid"

    aligned = MODULE.run_probe(_config(max_tokens=512), transport=TokenAwareTransport([]))
    assert aligned["ok"] is True
    assert aligned["finish_reason"] == "stop"
    assert aligned["content_present"] is True


def test_reasoning_content_never_substitutes_required_final_content():
    with_content = MODULE.run_probe(
        _config(),
        transport=FakeTransport([_response(content="ready", reasoning_content="hidden")]),
    )
    assert with_content["ok"] is True
    assert with_content["reasoning_content_present"] is True

    reasoning_only = MODULE.run_probe(
        _config(),
        transport=FakeTransport([_response(content="", reasoning_content="hidden")]),
    )
    assert reasoning_only["ok"] is False
    assert reasoning_only["error_type"] == "response_invalid"
    assert reasoning_only["content_present"] is False
    assert reasoning_only["reasoning_content_present"] is True


def test_http_failures_are_classified_without_response_body():
    for status, error_type in (
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (408, "request_timeout"),
        (409, "conflict"),
        (429, "rate_limited"),
        (503, "provider_error"),
    ):
        result = MODULE.run_probe(_config(), transport=FakeTransport([_response(status, body=b"private-token region")]))
        assert result["ok"] is False
        assert result["error_type"] in {error_type, "region_forbidden"} if status == 403 else result["error_type"] == error_type
        assert "private-token" not in json.dumps(result)
        assert result["requests_made"] == 1


def test_malformed_empty_and_unuseful_finish_reason_fail_closed():
    malformed = MODULE.run_probe(_config(), transport=FakeTransport([_response(body=b"not-json")]))
    assert malformed["error_type"] == "malformed_response"
    empty = MODULE.run_probe(_config(), transport=FakeTransport([_response(content="")]))
    assert empty["error_type"] == "response_invalid"
    length = MODULE.run_probe(_config(), transport=FakeTransport([_response(finish_reason="length")]))
    assert length["error_type"] == "finish_reason_invalid"


def test_failover_calls_go_once_only_after_primary_failure():
    primary = _config()
    fallback = _config(provider="opencode-go", model="deepseek-v4-flash")
    transport = FakeTransport([_response(status=403, body=b"region forbidden"), _response()])

    result = MODULE.run_failover(primary, fallback, transport=transport)

    assert result["ok"] is True
    assert result["provider"] == "opencode-go"
    assert result["model"] == "deepseek-v4-flash"
    assert result["fallback_used"] is True
    assert result["primary_error_class"] == "region_forbidden"
    assert result["requests_made"] == 2
    assert len(transport.calls) == 2


def test_no_fallback_on_primary_success():
    primary = _config()
    fallback = _config(provider="opencode-go", model="deepseek-v4-flash")
    transport = FakeTransport([_response()])

    result = MODULE.run_failover(primary, fallback, transport=transport)

    assert result["ok"] is True
    assert result["provider"] == "opencode-zen"
    assert result["fallback_used"] is False
    assert result["requests_made"] == 1
    assert len(transport.calls) == 1
