from inspect import getsource

import pandas as pd

import agente_bolsa.web_app as web_app
from agente_bolsa.web_app import (
    DEFAULT_START_DATE,
    PORTFOLIO_CHART_START_DATE,
    PORTFOLIO_CHART_WINDOWS,
    PORTFOLIO_HISTORY_PERIOD,
    _latest_daily_equity_change,
    _performance_baseline_chart,
    _portfolio_chart_visible_summary,
    _portfolio_chart_window_label,
    _portfolio_equity_summary,
    _portfolio_equity_summary_detail,
    _portfolio_period_metric_payload,
    _portfolio_value_series_from_alpaca,
)


def _descending_equity_history() -> dict[str, list[object]]:
    return {
        "timestamp": [
            "2026-04-01T00:00:00Z",
            "2026-04-28T00:00:00Z",
            "2026-07-28T00:00:00Z",
        ],
        "equity": [71550.0, 71000.0, 70600.0],
    }


def test_p63_reproduces_april_baseline_exclusion_on_base():
    df = _portfolio_value_series_from_alpaca(
        _descending_equity_history(),
        current_equity=70588.17,
    )

    assert DEFAULT_START_DATE == "2026-04-01"
    assert PORTFOLIO_CHART_START_DATE == DEFAULT_START_DATE
    assert df["fecha"].iloc[0] == "2026-04-01"
    assert _portfolio_chart_visible_summary(df)["start_value"] == 71550.0


def test_portfolio_history_request_is_single_and_covers_april_cutoff():
    assert PORTFOLIO_HISTORY_PERIOD == "all"
    source = getsource(web_app.page_dashboard)
    assert source.count("alpaca_portfolio_history(") == 1
    call_start = source.index("portfolio_history = BrokerClientFactory")
    call_end = source.index("except Exception", call_start)
    history_call = source[call_start:call_end]
    assert "period=PORTFOLIO_HISTORY_PERIOD" in history_call
    assert 'timeframe="1D"' in history_call


def test_account_header_uses_equity_summary_not_trade_history_total_pl():
    source = getsource(web_app.page_dashboard)

    assert "full_equity_summary" in source
    assert 'stats.get("total_pl")' not in source


def test_account_header_captures_equity_dates_source_and_coverage(monkeypatch):
    df = _portfolio_value_series_from_alpaca(
        _descending_equity_history(),
        current_equity=70588.17,
    )
    summary = _portfolio_equity_summary(df)
    captured: list[str] = []
    monkeypatch.setattr(web_app.st, "markdown", lambda content, **_: captured.append(content))

    web_app._account_group(
        initial_equity=summary["start_value"],
        current_equity=summary["end_value"],
        cash=None,
        exposure=None,
        exposure_pct=None,
        total_pl=summary["pl"],
        total_pct=summary["pl_pct"],
        today_pl=None,
        today_pct=None,
        positions_count=0,
        orders_count=0,
        equity_summary=summary,
    )

    rendered = captured[0]
    assert "Cuenta · desde el 1 de abril" in rendered
    assert "primer dato 01/04/2026" in rendered
    assert "cobertura completa" in rendered
    assert "$-961.83" in rendered
    assert "$70,578.74" not in rendered


def test_april_equity_result_is_negative_even_with_positive_trade_total():
    df = _portfolio_value_series_from_alpaca(
        _descending_equity_history(),
        current_equity=70588.17,
    )
    summary = _portfolio_equity_summary(df)
    metric = _portfolio_period_metric_payload(summary)

    assert summary["pl"] == -961.83
    assert metric["amount"] == "$-961.83"
    assert "cobertura completa" in metric["detail"]
    assert _portfolio_equity_summary_detail(summary).startswith("Variación de equity · Desde 01/04/2026")


def test_missing_april_equity_is_partial_or_unavailable_without_trade_reconstruction(monkeypatch):
    later = {
        "timestamp": ["2026-04-28T00:00:00Z", "2026-07-28T00:00:00Z"],
        "equity": [71000.0, 70600.0],
    }
    partial = _portfolio_equity_summary(
        _portfolio_value_series_from_alpaca(later, current_equity=None),
    )
    assert partial["coverage"] == "partial"
    assert partial["start_date"] == "2026-04-28"

    captured: list[str] = []
    monkeypatch.setattr(web_app.st, "markdown", lambda content, **_: captured.append(content))
    unavailable = web_app._portfolio_value_chart(
        {"days": [{"date": "2026-04-01", "realized_pl": 9.43, "open_unrealized_pl": 0.0}]},
        current_equity=70588.17,
        portfolio_history={},
        days=None,
    )
    assert unavailable["coverage"] == "unavailable"
    assert unavailable["pl"] is None
    assert "Sin datos suficientes" in captured[0]


def test_descending_equity_cannot_render_positive_trade_total_as_green_result():
    payload = {
        "timestamp": ["2026-04-01T00:00:00Z", "2026-07-28T00:00:00Z"],
        "equity": [71550.0, 70700.0],
    }
    summary = _portfolio_equity_summary(
        _portfolio_value_series_from_alpaca(payload, current_equity=70700.0),
    )
    metric = _portfolio_period_metric_payload(summary)

    trade_total_pl = 106.83
    assert trade_total_pl > 0
    assert summary["pl"] == -850.0
    assert metric["amount"] == "$-850.00"
    assert metric["tone"] == "bad"
    assert "Variación de equity" in metric["detail"]
    assert "+$106.83" not in metric["detail"]
    assert "P/L hoy" not in metric["detail"]
    assert "P/L abierto" not in metric["detail"]


def test_explicit_june_window_has_date_authority_and_exact_visible_dates():
    assert "2026-06-01" in PORTFOLIO_CHART_WINDOWS
    assert _portfolio_chart_window_label("2026-06-01") == "Desde 01/06/2026"
    assert _portfolio_chart_window_label(None) == "Desde el 1 de abril (01/04/2026)"
    df = _portfolio_value_series_from_alpaca(
        {
            "timestamp": [
                "2026-04-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                "2026-07-28T00:00:00Z",
            ],
            "equity": [71550.0, 71200.0, 70700.0],
        },
        current_equity=None,
    )
    june = web_app._trim_portfolio_chart_range(df, days="2026-06-01")
    summary = _portfolio_equity_summary(june, requested_start_date="2026-06-01")
    metric = _portfolio_period_metric_payload(summary)

    assert summary["start_date"] == "2026-06-01"
    assert summary["end_date"] == "2026-07-28"
    assert summary["pl"] == -500.0
    assert "01/06/2026" in metric["detail"]


def test_today_percentage_uses_daily_equity_not_current_exposure():
    display = web_app._today_pl_display(190.42, 9078.06, 0.002693)
    same_equity_different_exposure = web_app._today_pl_display(190.42, 30000.0, 0.002693)
    metric = web_app._today_pl_metric_payload(190.42, 9078.06, 0.002693)

    assert display == same_equity_different_exposure
    assert display["primary_pct"] == "0.27%"
    assert "sobre invertido" not in metric["detail_html"]
    assert "desde apertura" not in metric["detail_html"].lower()
    assert "acciones subieron" not in metric["detail_html"].lower()
    assert "cierre anterior" in metric["detail_html"]
    assert metric["amount"] == "$190.42"


def test_today_percentage_is_unavailable_without_previous_equity():
    change = _latest_daily_equity_change(
        history={},
        current_equity=None,
        portfolio_history={
            "timestamp": ["2026-07-28T00:00:00Z"],
            "equity": [70700.0],
        },
    )

    assert change["pl"] is None
    assert change["pl_pct"] is None
    display = web_app._today_pl_display(change["pl"], 9078.06, change["pl_pct"])
    assert display["primary_pct"] == "n/d"


def test_performance_baseline_tooltip_is_explicit_in_line_and_point_layers():
    chart = _performance_baseline_chart(
        pd.DataFrame(
            {
                "fecha": ["2026-07-27"],
                "serie": ["Sistema"],
                "retorno_acumulado": [0.013208],
            }
        )
    )
    spec = chart.to_dict()
    layers = spec["layer"]

    assert len(layers) == 2
    expected_tooltip = [
        {"field": "fecha", "title": "Fecha", "type": "nominal"},
        {"field": "retorno_acumulado", "format": "+.2%", "title": "% ganancias", "type": "quantitative"},
        {"field": "serie", "title": "Serie", "type": "nominal"},
    ]
    for layer in layers:
        y_encoding = layer["encoding"]["y"]
        assert y_encoding["field"] == "retorno_acumulado"
        assert y_encoding["title"] == "% ganancias"
        assert y_encoding["type"] == "quantitative"
        assert y_encoding["axis"]["format"] == "+.1%"
        assert layer["encoding"]["tooltip"] == expected_tooltip
        assert "tooltip" not in layer.get("mark", {})
    assert spec["layer"][0]["encoding"]["tooltip"][1]["format"] == "+.2%"
