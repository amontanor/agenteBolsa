from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from agente_bolsa.tools import technical_study as study


@pytest.fixture
def run_study(monkeypatch, tmp_path):
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 18, 49, tzinfo=timezone.utc)

    monkeypatch.setattr(study, "datetime", FrozenClock)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    rows = [
        {"symbol": "AAPL", "direction": "long", "score": 8},
        {"symbol": "MSFT", "direction": "short", "score": 5},
    ]
    strategies = [
        SimpleNamespace(name=name, version="1", status="ACTIVE", last_warnings=[name],
                        generate_candidates=lambda context: deepcopy(rows))
        for name in ["first", "second"]
    ]
    monkeypatch.setattr("agente_bolsa.strategies.registry.discover", lambda store: strategies)

    def run(metadata, symbols=None):
        monkeypatch.setattr(study, "download_daily_prices_with_metadata",
                            lambda *args, **kwargs: (pd.DataFrame(), deepcopy(metadata)))
        return study.build_closed_market_technical_study(
            symbols or [" aapl ", "AAPL", "MSFT"], tmp_path, "coverage",
            top_n=1, benchmark_symbol="", persist_report=False,
        )

    return run


def test_symbol_coverage_separates_candidates_from_delivered_symbols(run_study):
    report = run_study({"symbols_with_data": ["AAPL"]})
    assert report["symbols_with_data"] == 4  # legacy deliberately preserved
    assert report["symbol_coverage"] == {
        "status": "available", "reason": None,
        "requested_symbols_count": 2, "delivered_symbols_count": 1,
        "coverage_ratio": 0.5, "candidate_count": 4,
        "unique_candidate_symbols_count": 2,
    }
    assert len(report["top_longs"]) == len(report["top_shorts"]) == 1
