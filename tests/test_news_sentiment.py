import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools.news_sentiment import (
    _llm_sentiment,
    assess_material_news_risk,
    fetch_combined_symbol_news,
)


def test_assess_material_news_risk_flags_competitive_threat_without_llm():
    risk = assess_material_news_risk(
        "FDX",
        [
            {
                "title": "FedEx slides as Amazon logistics expands third-party delivery",
                "summary": "The rival service adds margin pressure for parcel carriers.",
            }
        ],
        {"risk_flags": ["sentiment_failed"]},
    )

    assert risk["material"] is True
    assert risk["severity"] == "material"
    assert "amazon logistics" in risk["matched_terms"]


def test_llm_sentiment_uses_dedicated_sentiment_role(monkeypatch):
    captured: dict[str, str] = {}

    class _Message:
        content = '{"sentiment":"neutral","sentiment_score":0,"confidence":0.8,"risk_flags":[]}'

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    def fake_chat(role, **_kwargs):
        captured["chat_role"] = role
        return _Response(), object(), []

    def fake_record(_settings, _source, _response, **kwargs):
        captured["usage_role"] = kwargs["role"]

    monkeypatch.setattr("agente_bolsa.tools.news_sentiment.chat_for_role", fake_chat)
    monkeypatch.setattr("agente_bolsa.tools.news_sentiment.record_llm_response", fake_record)

    result = _llm_sentiment(
        Settings(_env_file=None),
        "AAPL",
        {"direction": "long", "score": 80},
        [{"title": "Apple launches product"}],
    )

    assert result["sentiment"] == "neutral"
    assert captured == {"chat_role": "sentiment", "usage_role": "sentiment"}


def test_llm_sentiment_rejects_empty_json(monkeypatch):
    class _Message:
        content = "{}"

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    monkeypatch.setattr(
        "agente_bolsa.tools.news_sentiment.chat_for_role",
        lambda *_args, **_kwargs: (_Response(), object(), []),
    )
    monkeypatch.setattr("agente_bolsa.tools.news_sentiment.record_llm_response", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="sentimiento incompleta"):
        _llm_sentiment(
            Settings(_env_file=None),
            "AAPL",
            {"direction": "long", "score": 80},
            [{"title": "Apple launches product"}],
        )


def test_fetch_combined_symbol_news_adds_web_results(monkeypatch):
    monkeypatch.setattr(
        "agente_bolsa.tools.news_sentiment.fetch_symbol_news",
        lambda symbol, max_items=5: [{"title": "AAPL yfinance", "link": "https://example.com/yf"}],
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.news_sentiment.search_company_news",
        lambda settings, symbol, max_items=5: {
            "items": [
                {
                    "title": "AAPL web",
                    "link": "https://example.com/web",
                    "provider": "tavily",
                }
            ]
        },
    )

    result = fetch_combined_symbol_news(
        Settings(_env_file=None, WEB_SEARCH_ENABLED=True),
        "AAPL",
        max_items=5,
    )

    assert [item["title"] for item in result] == ["AAPL yfinance", "AAPL web"]
