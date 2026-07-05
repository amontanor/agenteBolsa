from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.tools.web_research_budget import (
    budgeted_provider_search,
    freshness_hours,
    parse_published_at,
)


def test_budget_counter_increments_only_real_provider_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_MONTHLY_BUDGET", "5")
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    calls = {"count": 0}

    def fetcher():
        calls["count"] += 1
        return [{"title": "AAPL"}]

    first = budgeted_provider_search(
        settings,
        provider="tavily",
        query="AAPL stock news",
        max_items=3,
        scope="symbol",
        fetcher=fetcher,
    )
    second = budgeted_provider_search(
        settings,
        provider="tavily",
        query="AAPL stock news",
        max_items=3,
        scope="symbol",
        fetcher=fetcher,
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls["count"] == 1
    report = tmp_path / "reports" / "latest_web_search_budget.json"
    assert report.exists()
    assert '"calls_used": 1' in report.read_text(encoding="utf-8")


def test_budget_cap_degrades_without_provider_call(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_MONTHLY_BUDGET", "0")
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    calls = {"count": 0}

    def fetcher():
        calls["count"] += 1
        return [{"title": "AAPL"}]

    result = budgeted_provider_search(
        settings,
        provider="brave",
        query="AAPL stock news",
        max_items=3,
        scope="symbol",
        fetcher=fetcher,
    )

    assert result.items == []
    assert result.warnings == ["web_search_budget_exhausted"]
    assert calls["count"] == 0
    assert '"degraded": true' in (tmp_path / "reports" / "latest_web_search_budget.json").read_text(encoding="utf-8")


def test_cache_expiry_uses_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_MONTHLY_BUDGET", "5")
    monkeypatch.setenv("WEB_SEARCH_CACHE_TTL_SYMBOL_HOURS", "0")
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    calls = {"count": 0}

    def fetcher():
        calls["count"] += 1
        return [{"title": f"AAPL {calls['count']}"}]

    budgeted_provider_search(
        settings,
        provider="tavily",
        query="AAPL stock news",
        max_items=3,
        scope="symbol",
        fetcher=fetcher,
    )
    budgeted_provider_search(
        settings,
        provider="tavily",
        query="AAPL stock news",
        max_items=3,
        scope="symbol",
        fetcher=fetcher,
    )

    assert calls["count"] == 2


def test_parse_freshness_absolute_and_relative_dates():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

    assert parse_published_at("2026-07-05T10:00:00Z", now=now).isoformat() == "2026-07-05T10:00:00+00:00"
    assert freshness_hours("2 hours ago", fetched_at=now) == 2.0
    assert freshness_hours("yesterday", fetched_at=now) == 24.0
