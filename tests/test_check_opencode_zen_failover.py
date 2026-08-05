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


def _config(provider="opencode-zen", model="deepseek-v4-flash-free", mode="health"):
    return MODULE.ProbeConfig(
        provider=provider,
        model=model,
        endpoint=MODULE.endpoint_from_base(
            "https://opencode.ai/zen/v1" if provider == "opencode-zen" else "https://opencode.ai/zen/go/v1"
        ),
        api_key="synthetic-key",
        mode=mode,
    )


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(status=200, *, content="ready", finish_reason="stop", body=None, headers=None):
    if body is None:
        body = json.dumps(
            {
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        ).encode()
    return MODULE.TransportResponse(status=status, body=body, headers=headers or {})


def test_zen_success_is_one_request_and_reports_safe_identity():
    transport = FakeTransport([_response(headers={"x-request-id": "secret-id", "x-ratelimit-limit": "9"})])

    result = MODULE.run_probe(_config(), transport=transport)

    assert result["ok"] is True
    assert result["provider"] == "opencode-zen"
    assert result["model"] == "deepseek-v4-flash-free"
    assert result["endpoint_path"] == "/zen/v1/chat/completions"
    assert result["requests_made"] == 1
    assert result["request_id_present"] is True
    assert result["rate_limit_headers_present"] is True
    assert "secret-id" not in json.dumps(result)


def test_structured_and_multiturn_modes_validate_without_network():
    structured = FakeTransport([_response(content='{"ok":true}')])
    result = MODULE.run_probe(_config(mode="structured"), transport=structured)
    assert result["ok"] is True
    assert json.loads(structured.calls[0]["body"])["response_format"] == {"type": "json_object"}

    multiturn = FakeTransport([_response()])
    result = MODULE.run_probe(_config(mode="multiturn"), transport=multiturn)
    assert result["ok"] is True
    assert json.loads(multiturn.calls[0]["body"])["reasoning_effort"] == "low"


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
