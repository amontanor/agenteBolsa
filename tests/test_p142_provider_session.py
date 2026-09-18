from __future__ import annotations

from datetime import date

from agente_bolsa.llm_router import (
    GO_PROVIDER,
    ZEN_PROVIDER,
    LLMEndpoint,
    build_openai_client,
    provider_client_headers,
    provider_session_id,
)


def test_session_id_is_stable_per_day_and_scope() -> None:
    day = date(2026, 9, 18)

    assert provider_session_id(GO_PROVIDER, scope="decision", today=day) == provider_session_id(
        GO_PROVIDER, scope="decision", today=day
    )
    assert provider_session_id(GO_PROVIDER, scope="decision", today=day) != provider_session_id(
        GO_PROVIDER, scope="improvement", today=day
    )
    assert provider_session_id(GO_PROVIDER, scope="decision", today=day) != provider_session_id(
        GO_PROVIDER, scope="decision", today=date(2026, 9, 19)
    )
    assert provider_session_id("mimo", scope="decision", today=day) is None
    assert provider_session_id(ZEN_PROVIDER, scope="decision", today=day) is not None


def test_client_headers_identify_session_and_agent() -> None:
    headers = provider_client_headers(GO_PROVIDER, scope="decision", today=date(2026, 9, 18))

    assert headers["x-opencode-session"] == provider_session_id(GO_PROVIDER, scope="decision", today=date(2026, 9, 18))
    assert headers["User-Agent"].startswith("agente-bolsa/")
    assert provider_client_headers("mimo") == {}
    assert provider_client_headers("openai-local") == {}


def test_openai_client_carries_session_headers_for_go(monkeypatch) -> None:
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    endpoint = LLMEndpoint(
        name="primary:opencode-go",
        api_key="key",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        provider=GO_PROVIDER,
    )

    build_openai_client(endpoint, 30, scope="decision")

    headers = captured.get("default_headers") or {}
    assert headers["x-opencode-session"] == provider_session_id(GO_PROVIDER, scope="decision")
    assert headers["User-Agent"].startswith("agente-bolsa/")


def test_openai_client_has_no_session_headers_for_other_providers(monkeypatch) -> None:
    captured: dict = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    endpoint = LLMEndpoint(
        name="local",
        api_key="key",
        base_url="http://127.0.0.1:8080/v1",
        model="qwen",
        provider="openai-local",
    )

    build_openai_client(endpoint, 30, scope="decision")

    assert captured.get("default_headers") in (None, {})


def test_improvement_client_sends_session_headers_for_go(tmp_path) -> None:
    from agente_bolsa.config import Settings
    from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient

    settings = Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    client = ImprovementLLMClient(settings)

    headers = client._request_headers("opencode-go", "test-token")

    assert headers["Authorization"] == "Bearer test-token"
    assert headers["x-opencode-session"] == provider_session_id(GO_PROVIDER, scope="improvement")
    assert headers["User-Agent"].startswith("agente-bolsa/")


def test_improvement_client_keeps_mimo_contract(tmp_path) -> None:
    from agente_bolsa.config import Settings
    from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient

    settings = Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    client = ImprovementLLMClient(settings)

    headers = client._request_headers("mimo", "test-token")

    assert headers["api-key"] == "test-token"
    assert "x-opencode-session" not in headers
