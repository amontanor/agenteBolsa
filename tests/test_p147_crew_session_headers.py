"""P-L147: CrewAI LLM carries provider session headers (Console Go/Zen)."""

from types import SimpleNamespace

from agente_bolsa import crew as crew_module
from agente_bolsa.config import Settings
from agente_bolsa.llm_router import OPENCODE_SESSION_HEADER, provider_client_headers


def _settings() -> Settings:
    return Settings(_env_file=None)


def _endpoint(provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        api_key="synthetic-key",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4.1-flash",
    )


def test_crew_llm_forwards_session_headers_to_litellm(monkeypatch):
    endpoint = _endpoint("opencode-go")
    monkeypatch.setattr(
        crew_module, "select_preferred_endpoint", lambda settings: (endpoint, [])
    )

    built = crew_module.build_crew(_settings())

    expected = provider_client_headers("opencode-go", scope="crew")
    assert expected[OPENCODE_SESSION_HEADER]
    for agent in built.agents:
        assert agent.llm.additional_params["extra_headers"] == expected


def test_crew_llm_sends_no_extra_headers_for_plain_provider(monkeypatch):
    endpoint = _endpoint("openai")
    monkeypatch.setattr(
        crew_module, "select_preferred_endpoint", lambda settings: (endpoint, [])
    )

    built = crew_module.build_crew(_settings())

    assert provider_client_headers("openai", scope="crew") == {}
    for agent in built.agents:
        assert agent.llm.additional_params == {}
