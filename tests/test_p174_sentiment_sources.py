"""P-L174: el sentimiento declara por que no llego al LLM.

Produccion 2026-10-29: el job corre, guarda 24 simbolos con ``supportive: []``
y ``warnings: []`` porque el presupuesto de busqueda web esta agotado y no hay
noticias locales. El productor no distinguia "sin noticias" de "proveedor
agotado", asi que la degradacion era invisible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.tools import news_sentiment


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        _env_file=None,
        WEB_SEARCH_ENABLED="true",
        news_items_per_symbol=5,
        news_sentiment_enabled=True,
    )


def _web_result(**overrides):
    payload = {
        "symbol": "AAPL",
        "provider": "brave",
        "providers_attempted": ["brave"],
        "quality": "empty",
        "items": [],
        "warnings": [],
        "cache_hits": 0,
        "provider_calls": 0,
    }
    payload.update(overrides)
    return payload


def _no_llm(*_args, **_kwargs):
    raise AssertionError("el LLM no debe llamarse cuando no hay noticias")


def test_budget_exhaustion_is_declared_and_no_llm_call(tmp_path, monkeypatch):
    monkeypatch.setattr(news_sentiment, "fetch_symbol_news", lambda *_a, **_k: [])
    monkeypatch.setattr(
        news_sentiment,
        "search_company_news",
        lambda *_a, **_k: _web_result(
            quality="empty", warnings=["web_search_budget_exhausted:brave"]
        ),
    )
    monkeypatch.setattr(news_sentiment, "chat_for_role", _no_llm)

    report = news_sentiment.analyze_news_sentiment_for_candidates(
        _settings(tmp_path),
        [{"symbol": "AAPL"}],
        tmp_path / "reports",
        "run_p174_budget",
    )

    assert report["symbols_analyzed"] == 1
    assert report["news_sources"]["unavailable_reason"] == "web_search_budget_exhausted"
    assert report["news_sources"]["symbols_without_news"] == 1
    assert "web_search:web_search_budget_exhausted:brave" in report["warnings"]
    result = report["results"][0]
    assert result["news_count"] == 0
    assert result["news_source"]["web"]["quality"] == "empty"
    assert result["sentiment"]["sentiment"] == "no_news"
    assert result["sentiment"]["risk_flags"] == ["sin_noticias"]


def test_no_provider_is_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(news_sentiment, "fetch_symbol_news", lambda *_a, **_k: [])
    monkeypatch.setattr(
        news_sentiment,
        "search_company_news",
        lambda *_a, **_k: _web_result(quality="no_provider", providers_attempted=[]),
    )
    monkeypatch.setattr(news_sentiment, "chat_for_role", _no_llm)

    report = news_sentiment.analyze_news_sentiment_for_candidates(
        _settings(tmp_path),
        [{"symbol": "MSFT"}],
        tmp_path / "reports",
        "run_p174_no_provider",
    )

    assert report["news_sources"]["unavailable_reason"] == "news_provider_unavailable"


def test_local_fresh_news_skips_web_and_keeps_metadata(tmp_path, monkeypatch):
    fresh_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        news_sentiment,
        "fetch_symbol_news",
        lambda *_a, **_k: [
            {
                "title": "AAPL sube",
                "publisher": "wire",
                "published_at": fresh_at,
                "summary": "",
                "link": "",
            }
        ],
    )
    called = {"web": False}

    def _fail_web(*_a, **_k):
        called["web"] = True
        raise AssertionError("no debe usar web si hay noticias locales frescas")

    monkeypatch.setattr(news_sentiment, "search_company_news", _fail_web)
    monkeypatch.setattr(
        news_sentiment,
        "_llm_sentiment",
        lambda *_a, **_k: {
            "sentiment": "positive",
            "sentiment_score": 1,
            "supports_technical_setup": True,
            "confidence": 0.8,
            "summary": "ok",
            "risk_flags": [],
        },
    )

    report = news_sentiment.analyze_news_sentiment_for_candidates(
        _settings(tmp_path),
        [{"symbol": "AAPL"}],
        tmp_path / "reports",
        "run_p174_local",
    )

    assert called["web"] is False
    assert report["news_sources"]["unavailable_reason"] is None
    result = report["results"][0]
    assert result["news_source"]["local"]["count"] == 1
    assert result["news_source"]["web"]["attempted"] is False
    assert result["news_source"]["quality"] == "ok"


def test_wrapper_keeps_list_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(
        news_sentiment,
        "fetch_symbol_news",
        lambda *_a, **_k: [
            {
                "title": "NVDA noticia",
                "publisher": "wire",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "summary": "",
                "link": "",
            }
        ],
    )
    items = news_sentiment.fetch_combined_symbol_news(_settings(tmp_path), "NVDA", max_items=5)
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["title"] == "NVDA noticia"

