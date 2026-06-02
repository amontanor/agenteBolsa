from agente_bolsa.config import Settings
from agente_bolsa.llm_router import configured_llm_endpoints, select_preferred_endpoint


def test_configured_llm_endpoints_prioritize_primary_then_fallback():
    settings = Settings(
        OPENAI_API_KEY="local-llama",
        OPENAI_API_BASE="http://127.0.0.1:8080/v1",
        OPENAI_MODEL_NAME="qwen3.6-27b",
        LLM_FALLBACK_ENABLED=True,
        LLM_FALLBACK_API_KEY="gemini-key",
        LLM_FALLBACK_API_BASE="https://generativelanguage.googleapis.com/v1beta/openai/",
        LLM_FALLBACK_MODEL="gemini-3.5-flash",
    )

    endpoints = configured_llm_endpoints(settings)

    assert [endpoint.name for endpoint in endpoints] == ["primary", "fallback"]
    assert endpoints[0].base_url == "http://127.0.0.1:8080/v1"
    assert endpoints[0].model == "qwen3.6-27b"
    assert endpoints[1].base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert endpoints[1].model == "gemini-3.5-flash"


def test_select_preferred_endpoint_uses_fallback_when_primary_preflight_fails(monkeypatch):
    settings = Settings(
        OPENAI_API_KEY="local-llama",
        OPENAI_API_BASE="http://127.0.0.1:8080/v1",
        OPENAI_MODEL_NAME="qwen3.6-27b",
        LLM_FALLBACK_ENABLED=True,
        LLM_FALLBACK_API_KEY="gemini-key",
        LLM_FALLBACK_API_BASE="https://generativelanguage.googleapis.com/v1beta/openai/",
        LLM_FALLBACK_MODEL="gemini-3.5-flash",
    )

    def fake_is_endpoint_available(endpoint, timeout_seconds):
        if endpoint.name == "primary":
            return False, "connection refused"
        return True, None

    monkeypatch.setattr("agente_bolsa.llm_router.is_endpoint_available", fake_is_endpoint_available)

    endpoint, attempts = select_preferred_endpoint(settings)

    assert endpoint.name == "fallback"
    assert endpoint.model == "gemini-3.5-flash"
    assert attempts[0]["available"] is False
