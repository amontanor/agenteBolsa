from __future__ import annotations

import pandas as pd

from agente_bolsa.tools.portfolio_insights import (
    latest_analyzed_news,
    position_chart_start_date,
    position_entry_date,
    position_evolution_summary,
    single_symbol_price_frame,
)


def test_shared_position_entry_date_prefers_saved_risk_order_time():
    history = {
        "risk_levels": {"AAPL": {"source_order_time": "2026-05-20T14:30:00+00:00"}},
        "trades": [{"symbol": "AAPL", "side": "buy", "time": "2026-05-19T14:30:00+00:00"}],
    }

    assert position_entry_date(history, "aapl") == "2026-05-20"
    assert position_chart_start_date(history, "AAPL") == "2026-05-13"


def test_shared_single_symbol_price_frame_extracts_multiindex_close_volume():
    data = pd.DataFrame(
        {
            ("AAPL", "Close"): [100.0, 102.0],
            ("AAPL", "Volume"): [1000, 1200],
            ("MSFT", "Close"): [200.0, 201.0],
        },
        index=pd.to_datetime(["2026-05-18", "2026-05-19"]),
    )

    frame = single_symbol_price_frame(data, "AAPL")

    assert list(frame["fecha"]) == ["2026-05-18", "2026-05-19"]
    assert list(frame["close"]) == [100.0, 102.0]
    assert list(frame["volume"]) == [1000, 1200]


def test_shared_position_evolution_summary_calculates_distances():
    frame = pd.DataFrame(
        [
            {"fecha": "2026-05-18", "close": 100.0, "volume": 1000},
            {"fecha": "2026-05-19", "close": 110.0, "volume": 1200},
        ]
    )

    summary = position_evolution_summary(
        frame,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=120.0,
    )

    assert summary["return_from_entry"] == 0.1
    assert summary["distance_to_stop"] == 0.136364
    assert summary["distance_to_take"] == 0.090909


def test_shared_latest_analyzed_news_flattens_and_deduplicates(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "news_sentiment_run_1.json").write_text(
        """
        {
          "run_id": "run_1",
          "as_of": "2026-06-05T20:00:00+00:00",
          "results": [
            {
              "symbol": "AAPL",
              "news": [
                {"title": "Apple headline", "publisher": "Example", "published_at": "2026-06-05T19:00:00+00:00", "link": "https://example.com/aapl"},
                {"title": "Apple headline", "publisher": "Example", "published_at": "2026-06-05T19:00:00+00:00", "link": "https://example.com/aapl"}
              ],
              "sentiment": {"sentiment": "positive", "sentiment_score": 1},
              "material_risk": {"severity": "none"}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = latest_analyzed_news(reports, limit=5)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["title"] == "Apple headline"
    assert rows[0]["sentiment"] == "positive"
