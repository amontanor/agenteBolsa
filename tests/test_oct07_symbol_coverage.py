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

@pytest.mark.parametrize("metadata,reason", [
    (None, "missing_delivery_metadata"),
    ({}, "missing_delivery_metadata"),
    ({"symbols_with_data": None}, "invalid_delivery_metadata"),
    ({"symbols_with_data": "AAPL"}, "invalid_delivery_metadata"),
    ({"symbols_with_data": [None]}, "invalid_delivery_metadata"),
    ({"symbols_with_data": [""]}, "invalid_delivery_metadata"),
    ({"symbols_with_data": ["OTHER"]}, "contradictory_delivery_metadata"),
    ({"symbols_with_data": ["AAPL"], "symbols_with_data_count": 2}, "contradictory_delivery_metadata"),
    ({"symbols_with_data": ["AAPL"], "symbols_with_data_count": True}, "contradictory_delivery_metadata"),
    ({"symbols_with_data": ["AAPL"], "missing_symbols": ["AAPL"]}, "contradictory_delivery_metadata"),
])
def test_unavailable_never_infers_delivery_from_candidates(run_study, metadata, reason):
    coverage = run_study(metadata)["symbol_coverage"]
    assert coverage["status"] == "unavailable"
    assert coverage["reason"] == reason
    assert coverage["delivered_symbols_count"] is None
    assert coverage["coverage_ratio"] is None
    assert coverage["candidate_count"] == 4


@pytest.mark.parametrize("symbols,delivered,count,ratio", [
    ([" aapl ", "AAPL", "MSFT"], ["AAPL", " aapl ", "SPY"], 1, 0.5),
    (["AAPL", "spy"], ["AAPL", "SPY"], 2, 1.0),
    (["AAPL"], [], 0, 0.0),
])
def test_benchmark_and_duplicates_have_requested_denominator(symbols, delivered, count, ratio):
    coverage = study.build_symbol_coverage(symbols, {"symbols_with_data": delivered}, [])
    assert coverage["status"] == "available"
    assert coverage["delivered_symbols_count"] == count
    assert coverage["coverage_ratio"] == ratio
    assert 0 <= coverage["coverage_ratio"] <= 1


def test_empty_request_has_no_invented_ratio():
    coverage = study.build_symbol_coverage([], {"symbols_with_data": ["SPY"]}, [])
    assert coverage["reason"] == "empty_requested_symbols"
    assert coverage["coverage_ratio"] is None


def test_all_existing_report_fields_stay_equal_when_delivery_changes(run_study):
    first = run_study({"symbols_with_data": ["AAPL"]})
    second = run_study({"symbols_with_data": ["AAPL", "MSFT"]})
    for report in (first, second):
        report.pop("symbol_coverage")
        report.pop("market_data")
    assert first == second
    assert first["warnings"] == ["first", "second"]
    assert [(row["symbol"], row["score"], row["strategy_name"])
            for row in first["all_candidates"]] == [
        ("AAPL", 8, "first"), ("MSFT", 5, "first"),
        ("AAPL", 8, "second"), ("MSFT", 5, "second"),
    ]


def test_report_parity_against_exact_runtime_base(run_study, monkeypatch, tmp_path):
    import subprocess
    from types import ModuleType

    source = subprocess.run(
        ["git", "show", "1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2:src/agente_bolsa/tools/technical_study.py"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    baseline = ModuleType("agente_bolsa.tools._coverage_base")
    baseline.__package__ = "agente_bolsa.tools"
    exec(compile(source, "runtime_base_technical_study.py", "exec"), baseline.__dict__)
    metadata = {"symbols_with_data": ["AAPL"]}
    actual = run_study(metadata)
    monkeypatch.setattr(baseline, "datetime", study.datetime)
    monkeypatch.setattr(baseline, "download_daily_prices_with_metadata", study.download_daily_prices_with_metadata)
    expected = baseline.build_closed_market_technical_study(
        [" aapl ", "AAPL", "MSFT"], tmp_path, "coverage",
        top_n=1, benchmark_symbol="", persist_report=False,
    )
    actual.pop("symbol_coverage")
    assert actual == expected
