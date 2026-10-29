"""P-L159: unico modelo operativo, DeepSeek V4.1 Flash via opencode Go.

El lote fija defaults de codigo y catalogo de UI. Cualquier override explicito
sigue siendo la unica via para usar otro proveedor o modelo, y qwen local deja
de estar activo por defecto.
"""

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient
from agente_bolsa.llm_model_ids import DEEPSEEK_V4_1_FLASH_MODEL_ID
from agente_bolsa.llm_router import configured_llm_endpoints, role_endpoints

V41 = DEEPSEEK_V4_1_FLASH_MODEL_ID
GO_BASE = "https://opencode.ai/zen/go/v1"

_ENV_NAMES = (
    "LLM_MODEL_SELECTOR",
    "OPENCODE_API_KEY",
    "OPENCODE_API_BASE",
    "OPENCODE_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_MODEL_NAME",
    "MIMO_API_KEY",
    "MIMO_API_BASE",
    "MIMO_MODEL",
    "LLM_LOCAL_FALLBACK_ENABLED",
    "LLM_LOCAL_FALLBACK_MODEL",
    "LLM_LOCAL_FALLBACK_API_BASE",
    "IMPROVEMENT_LLM_PROVIDER",
    "IMPROVEMENT_LLM_BASE_URL",
    "IMPROVEMENT_LLM_MODEL",
    "IMPROVEMENT_LLM_ORCHESTRATOR_PROVIDER",
    "IMPROVEMENT_LLM_ORCHESTRATOR_BASE_URL",
    "IMPROVEMENT_LLM_ORCHESTRATOR_MODEL",
    "IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED",
    "LLM_ROLE_FAST_MODEL",
    "LLM_ROLE_FAST_BASE_URL",
    "LLM_ROLE_SENTIMENT_MODEL",
    "LLM_ROLE_SENTIMENT_BASE_URL",
    "LLM_ROLE_DECISION_MODEL",
    "LLM_ROLE_DECISION_BASE_URL",
    "LLM_ROLE_DEEP_MODEL",
    "LLM_ROLE_DEEP_BASE_URL",
)


@pytest.fixture(autouse=True)
def _isolate_llm_environment(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides):
    return Settings(_env_file=None, LLM_PRIMARY_PREFLIGHT_ENABLED=False, **overrides)


def test_defaults_are_go_and_v41():
    settings = _settings()

    assert settings.llm_model_selector == "opencode-go"
    assert settings.opencode_api_base == GO_BASE
    assert settings.opencode_model == V41
    assert settings.improvement_llm_provider == "opencode-go"
    assert settings.improvement_llm_base_url == GO_BASE
    assert settings.improvement_llm_orchestrator_provider == "opencode-go"
    assert settings.improvement_llm_orchestrator_base_url == GO_BASE


def test_primary_chain_has_one_go_v41_endpoint():
    endpoints = configured_llm_endpoints(_settings())

    assert [(item.provider, item.model) for item in endpoints] == [("opencode-go", V41)]


@pytest.mark.parametrize("role", ["decision", "sentiment", "deep"])
def test_trading_roles_use_only_v41(role):
    endpoints = role_endpoints(_settings(), role)

    assert endpoints
    assert {item.model for item in endpoints} == {V41}


def test_improvement_client_default_chain_uses_only_v41():
    client = ImprovementLLMClient(_settings(OPENCODE_API_KEY="test-token"))

    assert [item.model for item in client._endpoints(V41)] == [V41]


def test_local_qwen_is_not_active_by_default():
    endpoints = configured_llm_endpoints(_settings())

    assert "openai-local" not in {item.provider for item in endpoints}
    assert "qwen3.6-27b" not in {item.model for item in endpoints}


def test_local_qwen_requires_explicit_opt_in():
    endpoints = configured_llm_endpoints(_settings(LLM_LOCAL_FALLBACK_ENABLED=True))

    local = [item for item in endpoints if item.provider == "openai-local"]

    assert len(local) == 1
    assert local[0].fallback_used is True


def test_ui_catalog_exposes_only_v41_through_go():
    from agente_bolsa import web_app

    assert web_app.PRIMARY_LLM_SELECTORS == ["opencode-go"]
    assert web_app.LLM_PROVIDER_OPTIONS == ["opencode-go"]
    for provider, entry in web_app.LLM_PROVIDER_CATALOG.items():
        assert entry["models"] == [V41], provider
