from agente_bolsa import main as main_module
from agente_bolsa.config import Settings
from agente_bolsa.tools import web_research
from agente_bolsa.tools.web_research import (
    _normalize_brave_result,
    _normalize_tavily_result,
    dedupe_news_items,
    search_company_news,
)


def test_normalize_tavily_result():
    result = _normalize_tavily_result(
        {
            "title": "Apple shares rise",
            "url": "https://example.com/aapl",
            "content": "Demand improved.",
            "published_date": "2026-07-05T10:00:00Z",
            "source": "Reuters",
        },
        query="AAPL stock news",
    )

    assert result is not None
    assert result.provider == "tavily"
    assert result.source_name == "Reuters"
    assert result.url == "https://example.com/aapl"


def test_normalize_brave_result():
    result = _normalize_brave_result(
        {
            "title": "Microsoft guidance in focus",
            "url": "https://example.com/msft",
            "description": "Investors watch guidance.",
            "profile": {"name": "MarketWatch"},
        },
        query="MSFT stock news",
    )

    assert result is not None
    assert result.provider == "brave"
    assert result.source_name == "MarketWatch"
    assert result.summary == "Investors watch guidance."


def test_dedupe_news_items_prefers_first_url():
    rows = dedupe_news_items(
        [
            {"title": "A", "link": "https://example.com/a"},
            {"title": "A duplicate", "link": "https://example.com/a"},
            {"title": "B", "link": ""},
            {"title": "B", "link": ""},
        ]
    )

    assert [item["title"] for item in rows] == ["A", "B"]


def test_search_company_news_auto_falls_back_to_brave(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        WEB_SEARCH_ENABLED=True,
        WEB_SEARCH_PROVIDER="auto",
        TAVILY_API_KEY="tv",
        BRAVE_API_KEY="br",
    )

    def fail_tavily(_settings, query, *, max_items):
        raise RuntimeError("boom")

    def fake_brave(_settings, query, *, max_items):
        return [
            web_research.WebSearchResult(
                title="AAPL catalyst",
                url="https://example.com/aapl",
                summary="Catalyst",
                published_at="2026-07-05T10:00:00Z",
                source_name="CNBC",
                provider="brave",
                query=query,
                payload={"x": 1},
            )
        ]

    monkeypatch.setattr(web_research, "_tavily_search", fail_tavily)
    monkeypatch.setattr(web_research, "_brave_search", fake_brave)

    result = search_company_news(settings, "AAPL", max_items=5)

    assert result["quality"] == "ok"
    assert result["providers_attempted"] == ["tavily", "brave"]
    assert result["items"][0]["provider"] == "brave"
    assert result["warnings"]


def test_search_company_news_without_provider_is_no_provider(tmp_path):
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, WEB_SEARCH_ENABLED=True, WEB_SEARCH_PROVIDER="auto")

    result = search_company_news(settings, "AAPL")

    assert result["quality"] == "no_provider"
    assert result["provider"] == "none"
    assert result["items"] == []


def test_search_company_news_can_merge_providers_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_MERGE_PROVIDERS", "true")
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        WEB_SEARCH_ENABLED=True,
        WEB_SEARCH_PROVIDER="auto",
        TAVILY_API_KEY="tv",
        BRAVE_API_KEY="br",
    )

    def fake_tavily(_settings, query, *, max_items):
        return [
            web_research.WebSearchResult(
                title="AAPL catalyst",
                url="https://example.com/aapl",
                summary="Tavily",
                published_at="2026-07-05T10:00:00Z",
                source_name="Reuters",
                provider="tavily",
                query=query,
                payload={},
            )
        ]

    def fake_brave(_settings, query, *, max_items):
        return [
            web_research.WebSearchResult(
                title="AAPL catalyst duplicate",
                url="https://example.com/aapl",
                summary="Brave duplicate",
                published_at="2026-07-05T10:00:00Z",
                source_name="CNBC",
                provider="brave",
                query=query,
                payload={},
            ),
            web_research.WebSearchResult(
                title="AAPL guidance",
                url="https://example.com/aapl-guidance",
                summary="Brave",
                published_at="2026-07-05T10:00:00Z",
                source_name="CNBC",
                provider="brave",
                query=query,
                payload={},
            ),
        ]

    monkeypatch.setattr(web_research, "_tavily_search", fake_tavily)
    monkeypatch.setattr(web_research, "_brave_search", fake_brave)

    result = search_company_news(settings, "AAPL", max_items=5)

    assert result["providers_attempted"] == ["tavily", "brave"]
    assert result["provider_calls"] == 4
    assert [item["link"] for item in result["items"]] == [
        "https://example.com/aapl",
        "https://example.com/aapl-guidance",
    ]


def test_command_web_research_outputs_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(_env_file=None, DATA_DIR=tmp_path, WEB_SEARCH_ENABLED=True),
    )
    monkeypatch.setattr(
        main_module,
        "build_web_research_report",
        lambda settings, output_dir, run_id, **kwargs: {
            "path": str(tmp_path / "reports" / "web_research_run.json"),
            "summary": {"quality": "ok", "provider": "tavily", "items": 1, "warnings": []},
            "result": {"items": [{"title": "AAPL news"}]},
        },
    )

    args = type(
        "Args",
        (),
        {"symbol": "AAPL", "market": False, "max_items": 1, "json": True},
    )()
    main_module.command_web_research(args)

    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert '"provider": "tavily"' in out


def test_command_study_symbol_forwards_with_web_news(tmp_path, monkeypatch, capsys):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(_env_file=None, DATA_DIR=tmp_path),
    )
    monkeypatch.setattr(
        main_module,
        "build_symbol_study",
        lambda symbol, settings, output_dir, run_id, **kwargs: (
            captured.update(kwargs)
            or {
                "path": str(tmp_path / "reports" / "symbol_study.json"),
                "symbol": symbol,
                "latest_bar": {"close": 100},
                "summary": {"direction": "long"},
                "benchmark": {"symbol": "SPY"},
                "fundamentals": {"available": True},
                "news": {"items": [{"title": "web item"}]},
            }
        ),
    )

    args = type(
        "Args",
        (),
        {
            "symbol": "AAPL",
            "lookback_days": 420,
            "with_news": False,
            "with_web_news": True,
            "with_news_llm": True,
            "news_items": 5,
            "full": False,
        },
    )()
    main_module.command_study_symbol(args)

    out = capsys.readouterr().out
    assert '"news_count": 1' in out
    assert captured["include_web_news"] is True
    assert captured["include_news_llm"] is True
