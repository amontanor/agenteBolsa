"""QA focal de P-L65B: un rowset comparable para Sistema frente a SP500."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from inspect import getsource

import agente_bolsa.web_app as web_app

CONSUMER_READ_AT = datetime(2026, 7, 28, 21, 0, tzinfo=timezone.utc)


def _row(
    session_date: str,
    *,
    equity: float = 100.27,
    previous_equity: float = 100.0,
    spy_previous: float | None = 100.0,
    spy_close: float | None = 100.5,
    quality: str = "available",
    price_basis: str | None = "close_unadjusted",
    source: str | None = "persisted_p40b",
    captured_hour: int = 21,
    captured_at: str | None = None,
    as_of: str | None = None,
    avg_exposure: float | None = 0.1,
    interpolated: bool = False,
) -> dict:
    as_of = as_of or f"{session_date}T20:00:00+00:00"
    payload = {
        "performance_benchmark": {
            "schema_version": "p-l40b.performance-benchmark.v1",
            "captured_at": captured_at or f"{session_date}T{captured_hour:02d}:00:00+00:00",
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
    return {
        "session_date": session_date,
        "payload": payload,
    }


def _daily_rows(count: int = 39) -> list[dict]:
    start = date(2026, 6, 1)
    rows: list[dict] = []
    for index in range(count):
        session_date = (start + timedelta(days=index)).isoformat()
        if index < 13:
            rows.append(_row(session_date, equity=101.0, spy_close=100.5))
        elif index < 30:
            rows.append(_row(session_date, equity=100.27, spy_close=101.0))
        else:
            rows.append(_row(session_date, quality="partial"))
    return rows


def test_primary_system_return_is_equity_and_exposure_is_secondary_only():
    row = _row(
        "2026-07-28",
        equity=71_000.0,
        previous_equity=70_807.69,
        spy_previous=100.0,
        spy_close=100.5,
        avg_exposure=8_041.72 / 70_807.69,
    )
    normalized = web_app._canonical_daily_vs_spy_row(row, consumer_read_at=CONSUMER_READ_AT)

    assert normalized["equity_delta"] == 192.31
    assert normalized["system_pct"] == (192.31 / 70_807.69)
    assert normalized["spy_pct"] == 0.005
    assert normalized["exposure_pct"] == (192.31 / 8_041.72)
    assert normalized["comparison_status"] == "comparable"
    assert normalized["system_pct"] < normalized["spy_pct"]


def test_two_closes_and_contract_quality_are_required_for_winner():
    missing_close = web_app._canonical_daily_vs_spy_row(
        _row("2026-07-28", spy_previous=None), consumer_read_at=CONSUMER_READ_AT
    )
    partial = web_app._canonical_daily_vs_spy_row(
        _row("2026-07-27", quality="partial"), consumer_read_at=CONSUMER_READ_AT
    )
    after_capture = web_app._canonical_daily_vs_spy_row(
        _row("2026-07-26", captured_hour=20, as_of="2026-07-26T21:00:00+00:00"),
        consumer_read_at=CONSUMER_READ_AT,
    )
    unknown_basis = web_app._canonical_daily_vs_spy_row(
        _row("2026-07-25", price_basis="unknown"), consumer_read_at=CONSUMER_READ_AT
    )

    assert missing_close["comparison_status"] == "pending"
    assert "spy_close_pair_unavailable" in missing_close["reason_codes"]
    assert partial["comparison_status"] == "pending"
    assert after_capture["comparison_status"] == "pending"
    assert "benchmark_as_of_after_generated_at" in after_capture["reason_codes"]
    assert unknown_basis["comparison_status"] == "pending"
    assert all(row["comparison_status"] != "comparable" for row in (missing_close, partial, unknown_basis))


def test_legacy_values_without_canonical_payload_are_unavailable():
    row = {"session_date": "2026-07-28", "pnl_pct": 0.0239, "spy_pct": 0.005}
    normalized = web_app._canonical_daily_vs_spy_row(row, consumer_read_at=CONSUMER_READ_AT)

    assert normalized["comparison_status"] == "pending"
    assert normalized["system_pct"] is None
    assert normalized["spy_pct"] is None
    assert "equity_pair_unavailable" in normalized["reason_codes"]


def test_same_visible_rowset_closes_windows_and_excludes_gaps_from_session_count():
    rows = web_app._canonical_daily_vs_spy_rows(_daily_rows(), consumer_read_at=CONSUMER_READ_AT)

    assert len(rows) == 39
    for window in (7, 15, 30, 90, None):
        visible = web_app._daily_vs_spy_window(rows, window)
        summary = web_app._daily_vs_spy_summary(visible)
        expected = len(rows) if window is None else min(window, len(rows))
        assert summary["visible_total"] == expected
        assert summary["visible_total"] == summary["comparable"] + summary["pending"]
        assert summary["comparable"] == summary["system_wins"] + summary["spy_wins"] + summary["ties"]
    assert web_app._daily_vs_spy_summary(web_app._daily_vs_spy_window(rows, 7))["visible_total"] != 39


def test_duplicate_dates_are_deterministic_and_order_does_not_mutate_input():
    rows = [_row("2026-07-28", equity=100.1), _row("2026-07-27"), _row("2026-07-28", equity=100.2)]
    original = list(rows)
    normalized = web_app._canonical_daily_vs_spy_rows(rows, consumer_read_at=CONSUMER_READ_AT)

    assert [item["session_date"] for item in normalized] == ["2026-07-27", "2026-07-28"]
    assert normalized[-1]["equity"] == 100.2
    assert rows == original


def test_chart_data_layers_share_explicit_formatted_tooltip_and_aux_layers_do_not():
    chart = web_app._daily_vs_spy_chart(
        web_app._canonical_daily_vs_spy_rows(
            [_row("2026-07-28")], consumer_read_at=CONSUMER_READ_AT
        )
    )
    assert chart is not None
    spec = chart.to_dict()
    data_layers = [
        layer
        for layer in spec["layer"]
        if layer.get("mark", {}).get("type") in {"line", "point"}
    ]
    assert len(data_layers) == 2
    expected = [
        {"field": "fecha_visual", "title": "Fecha visible", "type": "nominal"},
        {"field": "sesion_iniciada", "title": "Sesión iniciada", "type": "nominal"},
        {"field": "retorno", "format": "+.2%", "title": "% ganancias", "type": "quantitative"},
        {"field": "serie", "title": "Serie", "type": "nominal"},
        {"field": "estado", "title": "Estado", "type": "nominal"},
        {"field": "periodo", "title": "Intervalo", "type": "nominal"},
        {"field": "as_of", "title": "As of", "type": "nominal"},
    ]
    for layer in data_layers:
        assert layer["encoding"]["tooltip"] == expected
        assert layer["encoding"]["y"]["field"] == "retorno"
        assert layer["encoding"]["y"]["title"] == "% ganancias"
    assert all("tooltip" not in layer.get("mark", {}) for layer in spec["layer"])
    assert all("tooltip" not in layer.get("encoding", {}) for layer in spec["layer"] if layer not in data_layers)


def test_dashboard_wiring_is_readonly_and_does_not_add_operational_sources():
    panel_source = getsource(web_app._render_daily_vs_spy_table)
    page_source = getsource(web_app.page_dashboard)

    assert "opening_context" in panel_source
    assert "performance_daily" not in panel_source
    assert "BrokerClientFactory" not in panel_source
    assert "yfinance" not in panel_source.lower()
    assert "_render_daily_vs_spy_table(opening_context)" in page_source


def test_daily_panel_is_presentation_only_and_has_no_trading_authority():
    source = getsource(web_app._render_daily_vs_spy_table)

    for forbidden in (
        "build_buy_order_plans",
        "RiskManager",
        "save_order_plan",
        "submit_order",
        "close_position",
        "BrokerClientFactory",
    ):
        assert forbidden not in source


def test_freshness_is_contract_lag_not_historical_age():
    fresh = web_app._canonical_daily_vs_spy_row(
        _row("2026-06-01"), consumer_read_at=CONSUMER_READ_AT
    )
    stale = web_app._canonical_daily_vs_spy_row(
        _row(
            "2026-06-01",
            captured_at="2026-06-05T20:00:01+00:00",
            as_of="2026-06-01T20:00:00+00:00",
        ),
        consumer_read_at=CONSUMER_READ_AT,
    )

    assert fresh["freshness_status"] == "fresh"
    assert fresh["comparison_status"] == "comparable"
    assert stale["freshness_status"] == "stale"
    assert stale["comparison_status"] == "pending"
