"""Caracterización P-L65A del contrato Sistema vs SPY.

Este lote no implementa el contrato en ``src``. Las pruebas fijan la
semántica que debe implementar P-L65B y documentan las fronteras observadas
en P-L63R1: equity frente a exposición, fila visible frente a histórico y
comparabilidad/freshness del benchmark.
"""

from __future__ import annotations

from datetime import date, timedelta
from inspect import getsource

import pandas as pd

import agente_bolsa.web_app as web_app
from agente_bolsa.web_app import (
    _performance_baseline_chart,
    _performance_baseline_series,
    _portfolio_period_metric_payload,
    _trim_portfolio_chart_range,
)


def _canonical_row(
    session_date: str = "2026-07-28",
    *,
    equity: float = 71_000.0,
    previous_equity: float = 70_807.69,
    spy_previous: float = 100.0,
    spy_close: float = 100.5,
    quality: str = "available",
    price_basis: str = "close_unadjusted",
    source: str | None = "persisted_p40b",
    captured_at: str = "2026-07-28T20:10:00+00:00",
    as_of: str | None = "2026-07-28T20:00:00+00:00",
    avg_exposure: float | None = 0.25,
    interpolated: bool = False,
) -> dict:
    payload = {
        "performance_benchmark": {
            "schema_version": "p-l40b.performance-benchmark.v1",
            "captured_at": captured_at,
            "account": {"equity": equity, "previous_equity": previous_equity},
            "benchmark": {
                "symbol": "SPY",
                "previous_close": spy_previous,
                "close": spy_close,
                "price_basis": price_basis,
                "source": source,
                "as_of": as_of,
                "eod_authority": "post_session_cache",
                "comparison_status": "comparable",
                "data_quality": quality,
            },
            "data_quality": {"status": quality},
        },
    }
    if avg_exposure is not None:
        payload["avg_exposure"] = avg_exposure
    if interpolated:
        payload["interpolated"] = True
    return {"session_date": session_date, "payload": payload}


def _equity_return(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous


def _contract_visible_rows(rows: list[dict], *, visible_sessions: int) -> dict:
    """Oráculo de prueba: solo sesiones reales llegan al comparador."""

    ordered = sorted(rows, key=lambda row: row["session_date"])
    visible = ordered[-visible_sessions:]
    comparable = [row for row in visible if row.get("comparison_status") == "comparable"]
    pending = [row for row in visible if row.get("comparison_status") != "comparable"]
    system_wins = sum(row.get("winner") == "system" for row in comparable)
    spy_wins = sum(row.get("winner") == "spy" for row in comparable)
    ties = sum(row.get("winner") == "tie" for row in comparable)
    return {
        "visible_total": len(visible),
        "comparable": len(comparable),
        "pending": len(pending),
        "system_wins": system_wins,
        "spy_wins": spy_wins,
        "ties": ties,
        "rows": visible,
    }


def _thirty_nine_sessions() -> list[dict]:
    start = date(2026, 5, 1)
    return [
        {
            "session_date": (start + timedelta(days=index * 2)).isoformat(),
            "comparison_status": "comparable" if index % 5 else "pending",
            "winner": "spy" if index % 3 == 0 else "system" if index % 3 == 1 else "tie",
        }
        for index in range(39)
    ]


def test_equity_is_primary_and_invested_is_only_secondary_description():
    previous_equity = 70_807.69
    current_equity = 71_000.00
    change = round(current_equity - previous_equity, 2)
    equity_return = _equity_return(current_equity, previous_equity)
    invested = 8_041.72
    invested_equivalent = change / invested

    assert change == 192.31
    assert round(equity_return, 4) == 0.0027
    assert round(invested_equivalent, 4) == 0.0239

    primary = web_app._today_pl_metric_payload(change, invested, equity_return)
    assert primary["amount"] == "$192.31"
    # P-L63R1 currently renders this positive percentage without a leading
    # sign; P-L65B may standardize the visible sign together with the chart.
    assert primary["display"]["primary_pct"] == "0.27%"
    assert "sobre invertido" not in primary["detail_html"]
    assert "desde apertura" not in primary["detail_html"].lower()


def test_normalized_system_return_cannot_win_against_raw_spy_return():
    system_equity_return = 0.0027
    exposure_normalized_return = 0.0239
    spy_return = 0.005

    assert exposure_normalized_return > spy_return
    assert system_equity_return < spy_return
    assert max((system_equity_return, spy_return)) == spy_return

    rows, _, _ = _performance_baseline_series([_canonical_row(spy_close=100.5)])
    assert rows[0]["Sistema"] == round((71_000.0 - 70_807.69) / 70_807.69, 6)
    assert rows[0]["SPY"] == spy_return


def test_baseline_requires_canonical_pair_and_comparability_gate():
    row = {
        "session_date": "2026-07-28",
        "pnl_pct": 0.0027,
        "spy_pct": 0.005,
        "payload": {
            "performance_benchmark": {
                "data_quality": {"status": "partial"},
                "price_basis": "unknown",
                "source": None,
                "as_of": None,
            }
        },
    }

    chart_rows, cumulative_system, cumulative_spy = _performance_baseline_series([row])

    # Caracterización: el lector actual no consulta el bloque canónico y
    # dibuja valores aun cuando la fila declara basis/fuente no comparables.
    assert chart_rows[0]["Sistema"] is None
    assert chart_rows[0]["SPY"] is None
    assert cumulative_system is None
    assert cumulative_spy is None
    assert "_canonical_daily_vs_spy_row" in getsource(_performance_baseline_series)


def test_visible_contract_closes_39_rows_as_7_visible_plus_pending():
    result = _contract_visible_rows(_thirty_nine_sessions(), visible_sessions=7)

    assert len(_thirty_nine_sessions()) == 39
    assert result["visible_total"] == 7
    assert result["visible_total"] == result["comparable"] + result["pending"]
    assert result["comparable"] == result["system_wins"] + result["spy_wins"] + result["ties"]
    assert result["pending"] > 0
    assert result["visible_total"] != 39


def test_current_portfolio_selector_uses_calendar_days_not_last_real_sessions():
    dates = [date(2026, 5, 1) + timedelta(days=index * 2) for index in range(39)]
    frame = pd.DataFrame(
        {
            "fecha": [item.isoformat() for item in dates],
            "valor_cartera": [70_000.0 + index for index in range(39)],
        }
    )

    visible = _trim_portfolio_chart_range(frame, days=7)

    # Reproducción del gap de contrato: siete días naturales pueden contener
    # menos de siete sesiones reales. La implementación futura debe seleccionar
    # las últimas siete sesiones, sin consumir cupo por huecos XNYS.
    assert len(visible) == 4
    assert list(visible["fecha"]) == [item.isoformat() for item in dates[-4:]]
    assert len(dates[-7:]) == 7


def test_daily_vs_spy_panel_uses_one_readonly_rowset_and_visible_window_counts():
    source = getsource(web_app._render_daily_vs_spy_table)

    assert "opening_context" in source
    assert "performance_daily" not in source
    assert "daily_vs_spy_days" in source
    assert "_daily_vs_spy_summary" in source
    assert "visible_rows" in source
    assert "reversed(visible_rows)" in source
    assert "BrokerClientFactory" not in source
    assert "yfinance" not in source.lower()
    # La selectbox de P-L63R1 pertenece al gráfico Valor de cartera, no a este
    # baseline diario; por tanto el caso observado 13/17/0/9 de 39 no se puede
    # atribuir a un selector implementado en este árbol.


def test_missing_or_estimated_rows_are_pending_not_zero_or_winner():
    rows = [
        {"session_date": "2026-07-24", "comparison_status": "comparable", "winner": "system"},
        {"session_date": "2026-07-25", "comparison_status": "estimated", "winner": None},
        {"session_date": "2026-07-28", "comparison_status": "source_mismatch", "winner": None},
    ]

    result = _contract_visible_rows(rows, visible_sessions=7)

    assert result["pending"] == 2
    assert result["system_wins"] == 1
    assert result["spy_wins"] == 0
    assert result["ties"] == 0
    assert all(row["winner"] is None for row in result["rows"] if row["comparison_status"] != "comparable")


def test_first_equity_without_previous_close_is_unavailable_not_zero():
    assert _equity_return(70_700.0, None) is None
    assert _equity_return(70_700.0, 0.0) is None
    summary = _portfolio_period_metric_payload(
        {"pl": None, "pl_pct": None, "start_date": "2026-07-28", "end_date": "2026-07-28"}
    )
    assert summary["amount"] == "-"
    assert summary["tone"] == "neutral"


def test_performance_baseline_keeps_missing_values_pending_and_never_zero():
    rows = [
        {"session_date": "2026-07-27", "pnl_pct": None, "spy_pct": 0.005},
        {"session_date": "2026-07-28", "pnl_pct": 0.0027, "spy_pct": None},
    ]

    chart_rows, system_total, spy_total = _performance_baseline_series(rows)

    assert chart_rows == [
        {"fecha": "2026-07-27", "Sistema": None, "SPY": None, "iq_score": None},
        {"fecha": "2026-07-28", "Sistema": None, "SPY": None, "iq_score": None},
    ]
    assert system_total is None
    assert spy_total is None


def test_system_spy_tooltip_is_explicit_and_auxiliary_raw_fields_are_absent():
    chart = _performance_baseline_chart(
        pd.DataFrame(
            {
                "fecha": ["2026-07-28"],
                "serie": ["Sistema"],
                "retorno_acumulado": [0.013208],
            }
        )
    )
    spec = chart.to_dict()
    layers = spec["layer"]
    expected = [
        {"field": "fecha", "title": "Fecha", "type": "nominal"},
        {"field": "retorno_acumulado", "format": "+.2%", "title": "% ganancias", "type": "quantitative"},
        {"field": "serie", "title": "Serie", "type": "nominal"},
    ]

    assert len(layers) == 2
    for layer in layers:
        assert layer["encoding"]["tooltip"] == expected
        assert layer["encoding"]["y"]["field"] == "retorno_acumulado"
        assert layer["encoding"]["y"]["title"] == "% ganancias"
        assert layer["encoding"]["tooltip"][1]["format"] == "+.2%"
        assert "y0" not in layer["encoding"]
        assert "y1" not in layer["encoding"]
        assert "tooltip" not in layer.get("mark", {})


def test_baseline_render_is_single_store_read_and_no_broker_network_call():
    source = getsource(web_app._render_performance_baseline)

    assert source.count("performance_daily(") == 1
    assert "BrokerClientFactory" not in source
    assert "download_daily_prices" not in source
    # Gap for P-L65B: the Store API supports a readonly connection but this UI
    # reader does not request it explicitly.
    assert "readonly=True" in source


def test_p63_header_and_period_metric_remain_equity_authority():
    page_source = getsource(web_app.page_dashboard)
    assert "full_equity_summary" in page_source
    assert 'stats.get("total_pl")' not in page_source

    frame = web_app._portfolio_value_series_from_alpaca(
        {
            "timestamp": ["2026-04-02T00:00:00Z", "2026-07-29T00:00:00Z"],
            "equity": [71_550.0, 70_700.0],
        },
        current_equity=70_700.0,
    )
    summary = web_app._portfolio_chart_visible_summary(frame)
    metric = _portfolio_period_metric_payload(summary)
    assert metric["amount"] == "$-850.00"
    assert metric["tone"] == "bad"
    assert "Variaci" in metric["detail"]
