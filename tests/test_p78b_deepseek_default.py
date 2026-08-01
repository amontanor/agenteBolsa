"""Caracterizacion P-L78B del default global y sus fronteras de override."""

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen import _codegen_model
from agente_bolsa.llm_router import configured_llm_endpoints, role_endpoints


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
