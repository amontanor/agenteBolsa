from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.research_evidence import (
    _source_score,
    build_research_evidence_report,
    load_research_evidence_context,
    research_block_reason,
)


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=True)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def test_source_score_uses_curated_domain_levels():
    assert _source_score("Random", "web", source_type="symbol_news", url="https://www.sec.gov/Archives/x") == 0.95
    assert _source_score("Random", "web", source_type="symbol_news", url="https://www.reuters.com/markets/x") == 0.85
    assert _source_score("Random", "web", source_type="symbol_news", url="https://finance.yahoo.com/news/x") == 0.65
    assert _source_score("Reuters", "web", source_type="symbol_news", url="https://unknown.example/x") == 0.55


def test_build_research_report_persists_rows_and_latest_file(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    store.upsert_market_thesis(
        {
            "thesis_date": "2026-06-15",
            "payload": {"stance": "neutral", "key_risks": ["macro"]},
            "stance": "neutral",
            "confidence": 0.6,
        }
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_combined_symbol_news",
        lambda _settings, symbol, max_items=5: [
            {
                "title": f"{symbol} rallies on demand",
                "publisher": "Reuters",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "summary": "Demand remains strong",
                "link": "https://example.com/news",
            }
        ],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_1",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    assert report["summary"]["decision_ready"] is True
    rows = store.research_evidence(limit=10)
    assert any(item["symbol"] == "AAPL" for item in rows)
    latest = load_research_evidence_context(tmp_path)
    assert latest["summary"]["symbols_with_fresh_evidence"] == 1


def test_research_block_reason_uses_symbol_specific_failures(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_combined_symbol_news",
        lambda _settings, symbol, max_items=5: [],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_2",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    assert report["summary"]["decision_ready"] is False
    assert research_block_reason(report, symbol="AAPL") == "research_evidence_missing_or_stale"


def test_build_research_report_persists_web_provider_rows(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    settings = settings.model_copy(update={"web_search_enabled": True})
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.search_general_market_news",
        lambda _settings, max_items=10: {
            "provider": "tavily",
            "quality": "ok",
            "items": [
                {
                    "title": "Markets await Fed",
                    "publisher": "Reuters",
                    "provider": "tavily",
                    "link": "https://example.com/macro",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_combined_symbol_news",
        lambda _settings, symbol, max_items=5: [
            {
                "title": f"{symbol} web catalyst",
                "publisher": "CNBC",
                "provider": "brave",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "summary": "Fresh catalyst",
                "link": "https://example.com/company",
            }
        ],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_web",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    rows = store.research_evidence(limit=10)
    assert any(item["provider"] == "brave" and item["symbol"] == "AAPL" for item in rows)
    assert any(item["provider"] == "tavily" and item["scope"] == "macro" for item in rows)
    assert report["summary"]["providers"]["news"]["provider"] == "combined"


def test_freshness_v2_shadow_does_not_unlock_live_gate_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_FRESHNESS_V2", raising=False)
    settings, store = _setup(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_macro_events",
        lambda _settings: {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "ok"},
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.research_evidence.fetch_combined_symbol_news",
        lambda _settings, symbol, max_items=5: [
            {
                "title": f"{symbol} catalyst",
                "publisher": "Reuters",
                "provider": "brave",
                "published_at": "2 hours ago",
                "summary": "Fresh relative date only V2 can parse",
                "link": "https://example.com/company",
            }
        ],
    )

    report = build_research_evidence_report(
        store,
        settings,
        tmp_path / "reports",
        "run_shadow",
        symbols=["AAPL"],
        sentiment_context={},
        market_state={},
    )

    shadow = report["summary"]["freshness_v2_shadow"]
    assert report["summary"]["decision_ready"] is False
    assert shadow["enabled"] is False
    assert shadow["symbols_unknown_to_fresh"] == ["AAPL"]
    assert shadow["would_unblock_gate"] is True
