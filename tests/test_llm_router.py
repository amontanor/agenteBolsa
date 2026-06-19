from agente_bolsa.config import Settings
from agente_bolsa.llm_router import (
    chat_for_role,
    classify_llm_client_error,
    configured_llm_endpoints,
    is_endpoint_available,
    primary_llm_endpoint,
    role_endpoints,
    role_max_tokens,
    select_preferred_endpoint,
)
from agente_bolsa.llm_usage import record_llm_response
from agente_bolsa.storage import Store


def test_default_primary_llm_endpoint_uses_opencode_go_profile():
    settings = Settings(LLM_LOCAL_FALLBACK_ENABLED=False)

    endpoint = primary_llm_endpoint(settings)

    assert endpoint.name == "primary:opencode-go"
    assert endpoint.base_url == "https://opencode.ai/zen/go/v1"
    assert endpoint.model == "kimi-k2.6"


def test_configured_llm_endpoints_return_custom_primary_and_local_fallback():
    settings = Settings(
        LLM_MODEL_SELECTOR="custom",
        OPENAI_API_KEY="mimo-key",
        OPENAI_API_BASE="https://token-plan-ams.xiaomimimo.com/v1",
        OPENAI_MODEL_NAME="mimo-v2.5-pro",
        LLM_LOCAL_FALLBACK_ENABLED=True,
        LLM_LOCAL_FALLBACK_API_KEY="local-llama",
        LLM_LOCAL_FALLBACK_API_BASE="http://127.0.0.1:8080/v1",
        LLM_LOCAL_FALLBACK_MODEL="qwen3.6-27b",
    )

    endpoints = configured_llm_endpoints(settings)

    assert [endpoint.name for endpoint in endpoints] == ["primary:custom", "local_fallback"]
    assert endpoints[0].base_url == "https://token-plan-ams.xiaomimimo.com/v1"
    assert endpoints[0].model == "mimo-v2.5-pro"
    assert endpoints[1].base_url == "http://127.0.0.1:8080/v1"
    assert endpoints[1].model == "qwen3.6-27b"


def test_select_preferred_endpoint_returns_mimo_profile_when_it_is_available(monkeypatch):
    settings = Settings(
        LLM_MODEL_SELECTOR="mimo",
        MIMO_API_KEY="mimo-key",
        MIMO_API_BASE="https://token-plan-ams.xiaomimimo.com/v1",
        MIMO_MODEL="mimo-v2.5-pro",
        LLM_LOCAL_FALLBACK_ENABLED=True,
        LLM_LOCAL_FALLBACK_API_KEY="local-llama",
        LLM_LOCAL_FALLBACK_API_BASE="http://127.0.0.1:8080/v1",
        LLM_LOCAL_FALLBACK_MODEL="qwen3.6-27b",
    )

    def fake_is_endpoint_available(endpoint, timeout_seconds):
        return True, None

    monkeypatch.setattr("agente_bolsa.llm_router.is_endpoint_available", fake_is_endpoint_available)

    endpoint, attempts = select_preferred_endpoint(settings)

    assert endpoint.name == "primary:mimo"
    assert endpoint.model == "mimo-v2.5-pro"
    assert attempts[0]["available"] is True


def test_endpoint_import_error_is_reported_as_broken_client(monkeypatch):
    settings = _role_settings(LLM_PRIMARY_PREFLIGHT_ENABLED=True)
    endpoint = configured_llm_endpoints(settings)[0]

    def broken_client(_endpoint, _timeout):
        raise ModuleNotFoundError("No module named 'jiter.jiter'")

    monkeypatch.setattr("agente_bolsa.llm_router.build_openai_client", broken_client)

    available, error = is_endpoint_available(endpoint, settings.llm_timeout_seconds)

    assert available is False
    assert error.startswith("llm_client_import_broken:")
    assert "jiter.jiter" in error


def test_classify_llm_client_error_keeps_provider_errors_plain():
    assert classify_llm_client_error(RuntimeError("Connection error.")) == "Connection error."


# -- Router por roles (T0.4) ----------------------------------------------
def _role_settings(**overrides):
    base = {
        "LLM_MODEL_SELECTOR": "custom",
        "OPENAI_API_KEY": "mimo-key",
        "OPENAI_API_BASE": "https://token-plan-ams.xiaomimimo.com/v1",
        "OPENAI_MODEL_NAME": "mimo-v2.5-pro",
        "LLM_LOCAL_FALLBACK_ENABLED": True,
        "LLM_LOCAL_FALLBACK_API_KEY": "local-llama",
        "LLM_LOCAL_FALLBACK_API_BASE": "http://127.0.0.1:8080/v1",
        "LLM_LOCAL_FALLBACK_MODEL": "qwen3.6-27b",
        "LLM_PRIMARY_PREFLIGHT_ENABLED": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_role_without_config_uses_default_chain():
    settings = _role_settings()
    endpoints = role_endpoints(settings, "fast")
    assert [endpoint.name for endpoint in endpoints] == ["primary:custom", "local_fallback"]


def test_role_with_config_prepends_its_endpoint():
    settings = _role_settings(
        LLM_ROLE_FAST_MODEL="tiny-local",
        LLM_ROLE_FAST_BASE_URL="http://127.0.0.1:9000/v1",
        LLM_ROLE_FAST_API_KEY="fast-key",
    )
    endpoints = role_endpoints(settings, "fast")
    assert endpoints[0].name == "role:fast"
    assert endpoints[0].model == "tiny-local"
    assert endpoints[0].base_url == "http://127.0.0.1:9000/v1"


def test_deep_role_defaults_to_improvement_llm():
    settings = _role_settings(
        IMPROVEMENT_LLM_MODEL="mimo-deep",
        IMPROVEMENT_LLM_BASE_URL="https://lab.example/v1",
        IMPROVEMENT_LLM_API_KEY="lab-key",
    )
    endpoints = role_endpoints(settings, "deep")
    assert endpoints[0].name == "role:deep"
    assert endpoints[0].model == "mimo-deep"
    assert role_max_tokens(settings, "deep") == 16000


def test_deep_role_uses_opencode_key_when_improvement_key_is_empty():
    settings = _role_settings(
        OPENCODE_API_KEY="opencode-key",
        IMPROVEMENT_LLM_PROVIDER="opencode-go",
        IMPROVEMENT_LLM_BASE_URL="https://opencode.ai/zen/go/v1",
        IMPROVEMENT_LLM_API_KEY="",
        IMPROVEMENT_LLM_MODEL="glm-5.2",
    )

    endpoint = role_endpoints(settings, "deep")[0]

    assert endpoint.name == "role:deep"
    assert endpoint.api_key == "opencode-key"


def test_chat_for_role_selects_role_endpoint_and_records_role(tmp_path, monkeypatch):
    settings = _role_settings(
        DATA_DIR=tmp_path,
        LLM_ROLE_DECISION_MODEL="decider-mid",
        LLM_ROLE_DECISION_BASE_URL="http://127.0.0.1:9100/v1",
    )

    captured = {}

    class _Msg:
        content = "{}"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        model = "decider-mid"
        usage = None

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _Resp()

    monkeypatch.setattr("agente_bolsa.llm_router.build_openai_client", lambda endpoint, timeout: _Client())

    response, endpoint, _attempts = chat_for_role(
        "decision",
        settings=settings,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert endpoint.name == "role:decision"
    assert captured["model"] == "decider-mid"

    record_llm_response(settings, "trade_decision", response, prompt=[{"role": "user", "content": "hi"}], role="decision")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    by_role = {row["role"]: row for row in store.llm_usage_by_role()}
    assert "decision" in by_role
    assert by_role["decision"]["requests"] == 1
