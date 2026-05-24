from types import SimpleNamespace

from agente_bolsa.llm_usage import usage_tokens
from agente_bolsa.storage import Store
from agente_bolsa.web_app import (
    _estimated_portfolio_value_series,
    _portfolio_chart_visible_summary,
    _portfolio_value_series_from_alpaca,
    _trim_portfolio_chart_range,
)


def test_usage_tokens_reads_compatible_llm_usage_object():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )

    assert usage_tokens(response) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_usage_tokens_estimates_missing_local_backend_usage():
    response = SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"recommendations":[]}')
            )
        ],
    )

    tokens = usage_tokens(response, prompt=[{"role": "user", "content": "x" * 40}])

    assert tokens["prompt_tokens"] > 0
    assert tokens["completion_tokens"] > 0
    assert tokens["total_tokens"] == tokens["prompt_tokens"] + tokens["completion_tokens"]


def test_store_daily_llm_usage_counts_requests_and_tokens(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()

    store.record_llm_usage(
        usage_id="usage_1",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        payload={},
    )
    store.record_llm_usage(
        usage_id="usage_2",
        source="test",
        model="gpt-test",
        request_count=1,
        prompt_tokens=7,
        completion_tokens=3,
        total_tokens=10,
        payload={},
    )

    rows = store.daily_llm_usage()

    assert rows[0]["requests"] == 2
    assert rows[0]["prompt_tokens"] == 17
    assert rows[0]["completion_tokens"] == 8
    assert rows[0]["total_tokens"] == 25


def test_portfolio_value_series_from_alpaca_builds_daily_changes():
    payload = {
        "timestamp": [
            "2026-05-08T00:00:00Z",
            "2026-05-09T00:00:00Z",
            "2026-05-10T00:00:00Z",
        ],
        "equity": [1000.0, 1015.0, 1005.0],
    }

    df = _portfolio_value_series_from_alpaca(payload, current_equity=None, start_date="2026-05-01")

    assert list(df["fecha"]) == ["2026-05-08", "2026-05-09", "2026-05-10"]
    assert list(df["valor_cartera"]) == [1000.0, 1015.0, 1005.0]
    assert list(df["P/L dia"]) == [0.0, 15.0, -10.0]
    assert list(df["fuente"]) == ["Alpaca", "Alpaca", "Alpaca"]


def test_trim_portfolio_chart_range_keeps_latest_window():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1001.0, 1002.0, 1003.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=2)

    assert list(trimmed["fecha"]) == ["2026-05-08", "2026-05-09"]
    assert list(trimmed["valor_cartera"]) == [1002.0, 1003.0]


def test_estimated_portfolio_value_series_still_available_as_fallback():
    history = {
        "days": [
            {"date": "2026-05-11", "realized_pl": 10.0, "open_unrealized_pl": 0.0, "buy_notional": 1000.0},
            {"date": "2026-05-12", "realized_pl": -5.0, "open_unrealized_pl": 0.0, "sell_notional": 500.0},
        ]
    }

    df = _estimated_portfolio_value_series(history, current_equity=1005.0, days=2)

    assert list(df["valor_cartera"]) == [1010.0, 1005.0]
    assert list(df["P/L dia"]) == [10.0, -5.0]
    assert list(df["fuente"]) == ["estimado", "estimado"]


def test_portfolio_chart_visible_summary_uses_visible_window_change():
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-05-06T00:00:00Z",
                "2026-05-07T00:00:00Z",
                "2026-05-08T00:00:00Z",
                "2026-05-09T00:00:00Z",
            ],
            "equity": [1000.0, 1020.0, 1010.0, 1035.0],
        },
        current_equity=None,
        start_date="2026-05-01",
    )

    trimmed = _trim_portfolio_chart_range(df, days=3)
    summary = _portfolio_chart_visible_summary(trimmed)

    assert summary["days"] == 3
    assert summary["pl"] == 15.0
    assert summary["pl_pct"] == 0.014706
