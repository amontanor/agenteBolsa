"""Caracterizacion P-L78B del default global y sus fronteras de override."""

import json
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen import _codegen_model
from agente_bolsa.llm_router import (
    LLMEndpoint,
    build_llm_identity,
    configured_llm_endpoints,
    role_endpoints,
)
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.storage import Store
from agente_bolsa.tools.decision_context import build_decision_context_snapshot


def test_settings_without_environment_use_opencode_deepseek_flash_defaults():
    settings = Settings(_env_file=None)

    assert settings.llm_model_selector == "opencode-go"
    assert settings.opencode_model == "deepseek-v4-flash"
    assert settings.improvement_llm_model == "deepseek-v4-flash"
    assert settings.improvement_llm_orchestrator_model == "deepseek-v4-flash"


def test_default_role_chain_uses_deepseek_flash_without_override():
    settings = Settings(_env_file=None, LLM_PRIMARY_PREFLIGHT_ENABLED=False)

    assert role_endpoints(settings, "decision")[0].model == "deepseek-v4-flash"
    assert role_endpoints(settings, "sentiment")[0].model == "deepseek-v4-flash"
    assert role_endpoints(settings, "deep")[0].model == "deepseek-v4-flash"


def test_codegen_inherits_global_deepseek_default_without_override():
    settings = Settings(_env_file=None)

    assert _codegen_model(settings) == "deepseek-v4-flash"


def test_explicit_role_override_remains_authoritative():
    settings = Settings(
        _env_file=None,
        LLM_PRIMARY_PREFLIGHT_ENABLED=False,
        LLM_ROLE_DECISION_MODEL="glm-5.2",
        LLM_ROLE_DECISION_BASE_URL="http://127.0.0.1:9100/v1",
    )

    endpoint = role_endpoints(settings, "decision")[0]

    assert endpoint.model == "glm-5.2"
    assert endpoint.base_url == "http://127.0.0.1:9100/v1"


def test_custom_provider_model_is_an_explicit_override_not_a_global_default():
    settings = Settings(
        _env_file=None,
        LLM_MODEL_SELECTOR="custom",
        OPENAI_API_KEY="fake-key",
        OPENAI_API_BASE="http://127.0.0.1:9200/v1",
        OPENAI_MODEL_NAME="glm-5.2",
        LLM_PRIMARY_PREFLIGHT_ENABLED=False,
    )

    endpoint = configured_llm_endpoints(settings)[0]

    assert endpoint.name == "primary:custom"
    assert endpoint.model == "glm-5.2"


def test_local_fallback_remains_qwen_and_never_glm():
    settings = Settings(
        _env_file=None,
        LLM_PRIMARY_PREFLIGHT_ENABLED=False,
        LLM_LOCAL_FALLBACK_ENABLED=True,
        LLM_LOCAL_FALLBACK_MODEL="qwen3.6-27b",
    )

    endpoints = configured_llm_endpoints(settings)

    assert endpoints[-1].name == "local_fallback"
    assert endpoints[-1].model == "qwen3.6-27b"
    assert all(endpoint.model != "glm-5.2" for endpoint in endpoints)


def test_effective_endpoint_identity_survives_response_without_model(tmp_path):
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        LLM_PRIMARY_PREFLIGHT_ENABLED=False,
        OPENAI_MODEL_NAME="kimi-k2.6",
    )
    endpoint = role_endpoints(settings, "decision")[0]
    response = SimpleNamespace(
        model=None,
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
    )

    record_llm_response(
        settings,
        "trade_decision",
        response,
        prompt=[{"role": "user", "content": "fixture"}],
        role="decision",
        endpoint=endpoint,
    )

    row = Store(settings.database_path, settings.agent_logs_dir).latest_llm_usage(limit=1)[0]
    identity = json.loads(row["payload_json"])["llm_identity"]
    assert row["model"] == "deepseek-v4-flash"
    assert identity["provider"] == "opencode-go"
    assert identity["requested_model"] == "deepseek-v4-flash"
    assert identity["effective_model"] == "deepseek-v4-flash"
    assert identity["fallback_used"] is False


def test_decision_snapshot_uses_effective_identity_not_generic_settings_model():
    recommendation = SimpleNamespace(
        symbol="AAPL",
        action="buy",
        source="llm",
        decision_origin=None,
        decision_lineage={},
        llm_selected=True,
    )
    identity = {
        "status": "ok",
        "provider": "opencode-go",
        "requested_model": "deepseek-v4-flash",
        "effective_model": "deepseek-v4-flash",
        "fallback_used": False,
    }

    snapshot = build_decision_context_snapshot(
        recommendation,
        cycle_id="cycle_p78b",
        source_run_id=None,
        market_state=None,
        llm_provider=identity["provider"],
        llm_requested_model=identity["requested_model"],
        llm_effective_model=identity["effective_model"],
        llm_fallback_used=identity["fallback_used"],
        llm_response_status="ok",
    )

    assert snapshot["llm_provider"] == "opencode-go"
    assert snapshot["llm_model"] == "deepseek-v4-flash"
    assert snapshot["llm_requested_model"] == "deepseek-v4-flash"
    assert snapshot["llm_effective_model"] == "deepseek-v4-flash"
    assert snapshot["llm_fallback_used"] is False


def test_local_fallback_identity_is_explicit_and_not_primary_model():
    endpoint = LLMEndpoint(
        name="local_fallback",
        provider="openai-local",
        api_key="local-llama",
        base_url="http://127.0.0.1:8080/v1",
        model="qwen3.6-27b",
    )

    identity = build_llm_identity(endpoint)

    assert identity["provider"] == "openai-local"
    assert identity["effective_model"] == "qwen3.6-27b"
    assert identity["fallback_used"] is True
