import json
from pathlib import Path

from agente_bolsa.research.telegram_radar.extract import (
    extract_opportunity,
    map_tickers_to_universe,
)
from agente_bolsa.research.telegram_radar.ingest import parse_telegram_posts
from agente_bolsa.research.telegram_radar.storage import TelegramRadarStore


def test_parse_telegram_fixture_and_store_deduplicates(tmp_path):
    html = Path("tests/fixtures/telegram_bolsazone_sample.html").read_text(encoding="utf-8")

    posts = parse_telegram_posts(html)
    store = TelegramRadarStore(tmp_path / "telegram")
    first = store.upsert_posts([post.to_dict() for post in posts])
    second = store.upsert_posts([post.to_dict() for post in posts])

    assert [post.message_id for post in posts] == [101, 102]
    assert posts[0].posted_at == "2026-07-01T09:30:00+00:00"
    assert "OKLO" in posts[0].text
    assert posts[0].author == "Bolsazone Free Zone"
    assert posts[0].links == ["https://t.me/bolsazonefreezone", "https://example.com/chart"]
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert len(store.load_posts()) == 2


def test_extract_opportunity_normalizes_tickers_with_mocked_llm():
    post = {
        "message_id": 101,
        "posted_at": "2026-07-01T09:30:00+00:00",
        "text": "Que me gusta? OKLO, RDDT, TEM y PALANTIR que compramos ayer a 130",
    }

    def fake_llm(_messages):
        return json.dumps(
            {
                "is_opportunity": True,
                "tickers": ["OKLO", "RDDT", "TEM", "PLTR"],
                "direction": "buy",
                "thesis": "Lista de valores que el canal dice que compro ayer.",
                "timeframe": None,
                "confidence": 0.78,
                "unresolved_mentions": [],
            }
        )

    extraction = extract_opportunity(
        post,
        llm=fake_llm,
        current_universe=["RDDT", "PLTR"],
    )

    assert extraction.extraction_status == "llm_ok"
    assert extraction.is_opportunity is True
    assert extraction.direction == "buy"
    assert extraction.tickers == ["OKLO", "PLTR", "RDDT", "TEM"]
    coverage = {item["ticker"]: item["in_universe"] for item in extraction.ticker_coverage}
    assert coverage == {"OKLO": False, "PLTR": True, "RDDT": True, "TEM": False}


def test_extract_opportunity_degrades_when_llm_unavailable():
    post = {
        "message_id": 103,
        "posted_at": "2026-07-01T09:30:00+00:00",
        "text": "$RH en radar para vigilar, Ferrari tambien.",
    }

    def broken_llm(_messages):
        raise RuntimeError("llm down")

    extraction = extract_opportunity(post, llm=broken_llm, current_universe=["RH"])

    assert extraction.extraction_status == "llm_unavailable_heuristic_fallback"
    assert extraction.direction == "watch"
    assert "RH" in extraction.tickers
    assert "RACE" in extraction.tickers
    assert extraction.llm_error == "llm down"


def test_map_tickers_to_universe_with_stub_members():
    coverage = map_tickers_to_universe(
        ["AAPL", "MELI"],
        posted_at="2026-07-01T09:30:00+00:00",
        current_universe=["AAPL", "MSFT"],
    )

    by_ticker = {item["ticker"]: item for item in coverage}
    assert by_ticker["AAPL"]["in_universe"] is True
    assert by_ticker["AAPL"]["out_of_coverage"] is False
    assert by_ticker["MELI"]["in_universe"] is False
    assert by_ticker["MELI"]["out_of_coverage"] is True


def test_opportunity_word_maps_to_watch_direction_without_llm():
    extraction = extract_opportunity(
        {
            "message_id": 104,
            "posted_at": "2026-07-01T09:30:00+00:00",
            "text": "Micron o Sandisk puede ser oportunidad",
        },
        use_llm=False,
        current_universe=["MU"],
    )

    assert extraction.is_opportunity is True
    assert extraction.direction == "watch"
    assert extraction.tickers == ["MU", "SNDK"]
