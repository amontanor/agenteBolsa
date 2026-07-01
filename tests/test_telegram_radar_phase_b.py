from __future__ import annotations

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.research.telegram_radar.analysis import build_gate_verdicts
from agente_bolsa.research.telegram_radar.cli import render_report_markdown
from agente_bolsa.research.telegram_radar.scorecard import build_scorecard


def _ohlcv(closes: list[float], *, start: str = "2026-01-01") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=index,
    )


def _multi(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(frames, axis=1)


def test_scorecard_scores_winner_and_loser_with_synthetic_prices(tmp_path):
    posts = [
        {"message_id": 1, "posted_at": "2026-01-02T10:00:00+00:00"},
        {"message_id": 2, "posted_at": "2026-01-02T10:00:00+00:00"},
    ]
    extractions = [
        {
            "message_id": 1,
            "direction": "buy",
            "tickers": ["AAPL"],
            "ticker_coverage": [{"ticker": "AAPL", "in_universe": True, "out_of_coverage": False}],
        },
        {
            "message_id": 2,
            "direction": "buy",
            "tickers": ["MSFT"],
            "ticker_coverage": [{"ticker": "MSFT", "in_universe": True, "out_of_coverage": False}],
        },
    ]
    prices = _multi(
        {
            "AAPL": _ohlcv([100, 101, 102, 103, 104, 105, 110, 111]),
            "MSFT": _ohlcv([100, 99, 98, 97, 96, 95, 90, 89]),
            "SPY": _ohlcv([100, 100, 100, 100, 100, 100, 101, 101]),
        }
    )

    def fake_prices(_symbols, _start, _end):
        return prices

    report = build_scorecard(
        posts,
        extractions,
        settings=Settings(DATA_DIR=tmp_path),
        horizons=(5,),
        cost_bps_values=(10.0,),
        price_loader=fake_prices,
    )

    scored = {row["ticker"]: row for row in report["rows"]}
    assert scored["AAPL"]["status"] == "scored"
    assert scored["AAPL"]["signal_return_net"] > 0
    assert scored["MSFT"]["status"] == "scored"
    assert scored["MSFT"]["signal_return_net"] < 0
    group = report["summary"]["groups"][0]
    assert group["n_scored"] == 2
    assert group["hit_rate"] == 0.5


def test_gate_verdict_uses_stubbed_technicals(tmp_path):
    posts = [{"message_id": 3, "posted_at": "2026-12-31T10:00:00+00:00"}]
    extractions = [
        {
            "message_id": 3,
            "is_opportunity": True,
            "direction": "buy",
            "confidence": 0.9,
            "thesis": "mencion",
            "tickers": ["AAPL"],
            "ticker_coverage": [{"ticker": "AAPL", "in_universe": True, "out_of_coverage": False}],
        }
    ]
    base = [100.0 + (0.1 if i % 2 else -0.1) for i in range(260)]
    aapl = _ohlcv(base, start="2026-01-01")
    aapl.iloc[-1, aapl.columns.get_loc("Close")] = 100.0
    aapl.iloc[-5:, aapl.columns.get_loc("High")] = 110.0
    aapl.iloc[-5:, aapl.columns.get_loc("Low")] = 95.0
    spy = _ohlcv([100.0 + i * 0.2 for i in range(260)], start="2026-01-01")
    prices = _multi({"AAPL": aapl, "SPY": spy})

    def fake_prices(_symbols, _start, _end):
        return prices

    verdicts = build_gate_verdicts(
        posts,
        extractions,
        settings=Settings(DATA_DIR=tmp_path, DEFAULT_UNIVERSE="AAPL,SPY"),
        price_loader=fake_prices,
    )

    assert len(verdicts) == 1
    assert verdicts[0]["ticker"] == "AAPL"
    assert verdicts[0]["metrics"]["spy_regime_bull"] is True
    assert verdicts[0]["metrics"]["sma20_extension"] is not None
    assert "extension_sma20_excesiva" not in verdicts[0]["reasons"]


def test_render_report_markdown_contains_scorecard_and_caveats():
    markdown = render_report_markdown(
        {
            "new_opportunities": [{"message_id": 1, "posted_at": "2026-01-02", "direction": "buy", "tickers": ["AAPL"]}],
            "gate_verdicts": [
                {
                    "message_id": 1,
                    "ticker": "AAPL",
                    "our_gate": "fail",
                    "reasons": ["confidence_baja"],
                    "metrics": {"sma20_extension": 0.05, "rsi_14": 60, "reward_risk": 1.2, "spy_regime_bull": True},
                }
            ],
            "scorecard": {
                "summary": {
                    "groups": [
                        {
                            "coverage": "in_universe",
                            "horizon_days": 5,
                            "cost_bps": 10.0,
                            "n_mentions": 1,
                            "n_scored": 1,
                            "hit_rate": 1.0,
                            "avg_signal_return_net": 0.02,
                            "avg_excess_vs_spy": 0.01,
                        }
                    ]
                }
            },
        }
    )

    assert "## Nuestro veredicto" in markdown
    assert "confidence_baja" in markdown
    assert "## Marcador acumulado" in markdown
    assert "cherry-picking" in markdown
