from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_opencode_go_deepseek.py"

SPEC = importlib.util.spec_from_file_location("check_opencode_go_deepseek", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RecordingTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, *, endpoint, headers, body, timeout_seconds):
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def _config(**overrides):
    values = {
        "provider": MODULE.DEFAULT_PROVIDER,
        "model": MODULE.DEFAULT_MODEL,
        "endpoint": MODULE.DEFAULT_ENDPOINT,
        "api_key": "secret-api-key-workspace-token",
        "timeout_seconds": 3.0,
    }
    values.update(overrides)
    return MODULE.ProbeConfig(**values)


def _success_response():
    return MODULE.TransportResponse(
        status=200,
        body=b'{"id":"redacted","choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}',
    )


def test_success_uses_exact_endpoint_model_and_one_request():
    transport = RecordingTransport(_success_response())

    result = MODULE.run_probe(_config(), transport)

    assert result["ok"] is True
    assert result["provider"] == "opencode-go"
    assert result["model"] == "deepseek-v4.1-flash"
    assert result["endpoint_host"] == "opencode.ai"
    assert result["endpoint_path"] == "/zen/go/v1/chat/completions"
    assert result["finish_reason"] == "stop"
    assert result["fallback_used"] is False
    assert result["requests_made"] == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["endpoint"] == MODULE.DEFAULT_ENDPOINT
    assert json.loads(transport.calls[0]["body"])["model"] == MODULE.DEFAULT_MODEL
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer secret-api-key-workspace-token"


@pytest.mark.parametrize(
    ("status", "body", "error_type"),
    [
        (401, b'{"error":"invalid api key"}', "unauthorized"),
        (403, b'{"error":"RegionError workspace=do-not-print"}', "region_forbidden"),
        (404, b'{"error":"not found"}', "not_found"),
        (429, b'{"error":"slow down"}', "rate_limited"),
    ],
)
def test_http_errors_are_sanitized(status, body, error_type):
    transport = RecordingTransport(MODULE.TransportResponse(status=status, body=body))

    result = MODULE.run_probe(_config(), transport)
    rendered = json.dumps(result, sort_keys=True)

    assert result["ok"] is False
    assert result["error_type"] == error_type
    assert result["requests_made"] == 1
    assert "secret-api-key-workspace-token" not in rendered
    assert "do-not-print" not in rendered
    assert "Authorization" not in rendered


def test_timeout_is_one_call_without_retry():
    transport = RecordingTransport(error=TimeoutError("provider timeout secret"))

    result = MODULE.run_probe(_config(), transport)

    assert result["ok"] is False
    assert result["error_type"] == "timeout"
    assert result["requests_made"] == 1
    assert len(transport.calls) == 1
    assert "provider timeout secret" not in json.dumps(result)


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        (b"not-json", "malformed_json"),
        (b'{"choices":[]}', "choices_missing"),
        (b'{"choices":[{"message":{}}]}', "response_invalid"),
    ],
)
def test_invalid_openai_compatible_responses_are_classified(body, error_type):
    transport = RecordingTransport(MODULE.TransportResponse(status=200, body=body))

    result = MODULE.run_probe(_config(), transport)

    assert result["ok"] is False
    assert result["error_type"] == error_type
    assert result["requests_made"] == 1


def test_configuration_mismatch_makes_no_request():
    transport = RecordingTransport(_success_response())

    result = MODULE.run_probe(_config(model="glm-5.2"), transport)

    assert result["ok"] is False
    assert result["error_type"] == "configuration_mismatch"
    assert result["requests_made"] == 0
    assert transport.calls == []


def test_endpoint_mismatch_makes_no_request():
    transport = RecordingTransport(_success_response())

    result = MODULE.run_probe(_config(endpoint="https://other.example/v1/chat/completions"), transport)

    assert result["error_type"] == "configuration_mismatch"
    assert result["requests_made"] == 0
    assert transport.calls == []


def test_missing_key_makes_no_request():
    transport = RecordingTransport(_success_response())

    result = MODULE.run_probe(_config(api_key=""), transport)

    assert result["error_type"] == "missing_api_key"
    assert result["requests_made"] == 0
    assert transport.calls == []


def test_config_from_existing_settings_uses_opencode_aliases_without_db():
    settings = SimpleNamespace(
        llm_model_selector="opencode-go",
        opencode_api_base="https://opencode.ai/zen/go/v1",
        opencode_model="deepseek-v4.1-flash",
        opencode_api_key="hidden-key",
    )

    config = MODULE.config_from_settings(settings)

    assert config.provider == MODULE.DEFAULT_PROVIDER
    assert config.model == MODULE.DEFAULT_MODEL
    assert config.endpoint == MODULE.DEFAULT_ENDPOINT
    assert config.api_key == "hidden-key"


def test_json_shape_is_stable_and_has_no_sensitive_fields():
    result = MODULE.run_probe(_config(), RecordingTransport(_success_response()))
    expected = {
        "endpoint_host",
        "endpoint_path",
        "error_message",
        "error_type",
        "fallback_used",
        "finish_reason",
        "http_status",
        "latency_seconds",
        "model",
        "ok",
        "provider",
        "requests_made",
        "status",
    }

    assert set(result) == expected
    assert not {"api_key", "authorization", "workspace_id", "content", "response"} & set(result)


def test_script_does_not_import_operational_boundaries():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {"sqlite3", "agente_bolsa.scheduler", "agente_bolsa.storage"} & imported
