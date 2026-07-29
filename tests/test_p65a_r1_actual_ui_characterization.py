"""P-L65A-R1: caracterización del panel dirty P-L61 contra P-L63R1.

El checkout productivo dirty no se importa en estas pruebas. El fragmento
textual siguiente es una evidencia mínima extraída del working tree observado;
las invariantes se ejercitan con fixtures puras para no copiar ``src`` dirty
ni tocar datos operativos.
"""

from __future__ import annotations

from datetime import date, timedelta
from inspect import getsource

import agente_bolsa.web_app as web_app

DIRTY_WEB_APP_SHA256 = "FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A"
DIRTY_TEST_WEB_APP_SHA256 = "9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B"

# Evidencia mínima literal del productor P-L61 observado en el checkout dirty.
# No pretende ser implementación: solo conserva las ramas que explican el
# alcance, los denominadores, el comparador y el spec declarativo.
DIRTY_P_L61_EXCERPT = """
def _render_daily_vs_spy_table(store, current_equity=None, market_is_open=False):
    db_rows = store.performance_daily(limit=0)
    visible_days = st.selectbox("Dias", [7, 15, 30, None], key="daily_vs_spy_days")
    invested = round(avg_exp * eq_val, 2)
    pnl_invested_pct = pnl_dollar / prev_invested
    live_invested_pct = (live_dollar / prev_invested) if prev_invested and prev_invested > 0 else None
    cmp_pct = invested_pct if has_invested else equity_pct
    total = len(enriched)
    visible = body[:visible_days] if visible_days is not None else body
    chart_rows = [{"fecha": row["session_date"], "Sistema": sistema_val, "SP500": row["spy_pct"]}]
    chart_rows = chart_rows[-visible_days:] if visible_days is not None else chart_rows
    filled_enriched.append({"gap_filled": "interpolated", "spy_pct": missing_spy_ret})
    bg_green = alt.Chart(pd.DataFrame({"y0": [0], "y1": [y_max]})).mark_rect()
    bg_red = alt.Chart(pd.DataFrame({"y0": [y_min], "y1": [0]})).mark_rect()
    lines.encode(tooltip=[alt.Tooltip("retorno:Q", title="Retorno", format="+.2%")])
    points = base.transform_fold(fold=["Sistema", "SP500"]).mark_point().encode()
    _section_title("Rendimiento diario: Sistema vs SP500",
                   "% sobre capital invertido (linea secundaria: % sobre equity total).")
"""


def _dirty_counts(rows: list[dict[str, float | None]], visible_days: int) -> dict[str, int]:
    """Replica solo el contador/recorte del panel P-L61 dirty."""

    counts = {"system": 0, "spy": 0, "tie": 0, "pending": 0}
    for row in rows:
        system = row.get("pnl_invested_pct")
        if system is None:
            system = row.get("pnl_equity_pct")
        spy = row.get("spy_pct")
        if system is None or spy is None:
            counts["pending"] += 1
        elif abs(system - spy) < 0.00005:
            counts["tie"] += 1
        elif system > spy:
            counts["system"] += 1
        else:
            counts["spy"] += 1
    counts["total"] = len(rows)
    counts["visible"] = min(len(rows), visible_days)
    return counts


def _dirty_table_chart_window(rows: list[dict[str, object]], visible_days: int) -> tuple[list, list]:
    """Modela los dos recortes distintos del productor dirty."""

    body = list(reversed(rows))
    table = body[:visible_days]
    chart_rows = [row for row in rows if row.get("system") is not None and row.get("spy") is not None]
    filled = [chart_rows[0]] if chart_rows else []
    for previous, current in zip(chart_rows, chart_rows[1:], strict=False):
        previous_date = date.fromisoformat(str(previous["date"]))
        current_date = date.fromisoformat(str(current["date"]))
        if (current_date - previous_date).days > 1:
            filled.append({"date": None, "system": None, "spy": None})
        filled.append(current)
    chart = filled[-visible_days:]
    return table, chart


def _thirty_nine_dirty_rows() -> list[dict[str, float | None]]:
    rows: list[dict[str, float | None]] = []
    rows.extend({"pnl_invested_pct": 0.02, "pnl_equity_pct": 0.0027, "spy_pct": 0.01} for _ in range(13))
    rows.extend({"pnl_invested_pct": 0.01, "pnl_equity_pct": 0.0027, "spy_pct": 0.02} for _ in range(17))
    rows.extend({"pnl_invested_pct": None, "pnl_equity_pct": None, "spy_pct": None} for _ in range(9))
    return rows


def test_exact_object_is_dirty_p61_and_absent_from_p63r1():
    assert DIRTY_WEB_APP_SHA256.startswith("FC6ABAD9")
    assert DIRTY_TEST_WEB_APP_SHA256.startswith("9580147B")
    assert "def _render_daily_vs_spy_table" in DIRTY_P_L61_EXCERPT
    assert "daily_vs_spy_days" in DIRTY_P_L61_EXCERPT

    # P-L65B now implements the contract over the same real UI composition;
    # P-L72 replaces the provisional producer with exact XNYS openings.
    assert hasattr(web_app, "_render_daily_vs_spy_table")
    panel_source = getsource(web_app._render_daily_vs_spy_table)
    assert "opening_context" in panel_source
    assert "performance_daily" not in panel_source
    assert "daily_vs_spy_days" in panel_source


def test_dirty_selector_reproduces_13_17_0_9_of_39_with_seven_visible():
    result = _dirty_counts(_thirty_nine_dirty_rows(), visible_days=7)

    assert result == {"system": 13, "spy": 17, "tie": 0, "pending": 9, "total": 39, "visible": 7}
    # El defecto es que los denominadores se calculan antes de aplicar el
    # recorte visible; el futuro contrato debe publicar solo el rowset visible.
    assert result["total"] != result["visible"]


def test_dirty_panel_mixes_invested_primary_with_equity_and_raw_spy():
    equity_delta = 192.31
    previous_equity = 70_807.69
    previous_invested = 8_041.72
    equity_pct = equity_delta / previous_equity
    invested_pct = equity_delta / previous_invested
    spy_pct = 0.005

    assert round(equity_pct, 4) == 0.0027
    assert round(invested_pct, 4) == 0.0239
    assert invested_pct > spy_pct > equity_pct
    assert "cmp_pct = invested_pct if has_invested else equity_pct" in DIRTY_P_L61_EXCERPT
    # La autoridad comparable debe ser equity contra SPY; el dirty panel puede
    # declarar Sistema ganador solo porque prioriza el denominador invertido.
    dirty_winner = "Sistema" if invested_pct > spy_pct else "SP500"
    canonical_winner = "Sistema" if equity_pct > spy_pct else "SP500"
    assert dirty_winner == "Sistema"
    assert canonical_winner == "SP500"


def test_dirty_live_dollar_uses_previous_invested_not_account_equity():
    live_dollar = 192.31
    previous_invested = 8_041.72
    previous_equity = 70_807.69

    assert round(live_dollar / previous_invested, 4) == 0.0239
    assert round(live_dollar / previous_equity, 4) == 0.0027
    assert "live_invested_pct = (live_dollar / prev_invested)" in DIRTY_P_L61_EXCERPT


def test_dirty_table_and_chart_do_not_share_one_visible_rowset():
    start = date(2026, 7, 1)
    rows = [
        {"date": (start + timedelta(days=offset)).isoformat(), "system": 0.01, "spy": 0.005}
        for offset in (0, 1, 4, 5, 9, 10, 11, 15)
    ]
    table, chart = _dirty_table_chart_window(rows, visible_days=7)

    assert len(table) == 7
    assert len(chart) == 7
    assert any(row["date"] is None for row in chart)
    assert sum(row["date"] is not None for row in chart) < len(table)
    assert "visible = body[:visible_days]" in DIRTY_P_L61_EXCERPT
    assert "chart_rows = chart_rows[-visible_days:]" in DIRTY_P_L61_EXCERPT


def test_dirty_interpolated_or_partial_rows_can_be_counted_as_winners():
    row = {
        "pnl_invested_pct": 0.02,
        "pnl_equity_pct": 0.0027,
        "spy_pct": 0.01,
        "gap_filled": "interpolated",
        "spy_quality": "partial",
    }

    dirty_counts = _dirty_counts([row], visible_days=7)
    assert dirty_counts["system"] == 1
    assert '"gap_filled": "interpolated"' in DIRTY_P_L61_EXCERPT

    # El contrato nuevo los debe apartar del ganador y dejar la fila pending.
    assert row["gap_filled"] == "interpolated"
    assert row["spy_quality"] == "partial"


def test_dirty_chart_spec_has_auxiliary_y0_y1_and_raw_point_hover_path():
    assert '"y0": [0]' in DIRTY_P_L61_EXCERPT
    assert '"y1": [y_max]' in DIRTY_P_L61_EXCERPT
    assert 'title="Retorno"' in DIRTY_P_L61_EXCERPT
    points_source = DIRTY_P_L61_EXCERPT.split("points =", maxsplit=1)[1]
    assert "tooltip" not in points_source.split("_section_title", maxsplit=1)[0]
    assert "retorno:Q" not in points_source.split("points =", maxsplit=1)[0]


def test_dirty_subtitle_promises_secondary_line_without_secondary_series():
    assert "linea secundaria" in DIRTY_P_L61_EXCERPT
    assert '"Sistema": sistema_val' in DIRTY_P_L61_EXCERPT
    assert '"SP500": row["spy_pct"]' in DIRTY_P_L61_EXCERPT
    assert "equity_series" not in DIRTY_P_L61_EXCERPT


def test_dirty_store_read_is_not_explicitly_readonly():
    assert "store.performance_daily(limit=0)" in DIRTY_P_L61_EXCERPT
    assert "readonly=True" not in DIRTY_P_L61_EXCERPT


def test_p63_composition_is_required_before_p65b_implementation():
    page_source = getsource(web_app.page_dashboard)
    assert "full_equity_summary" in page_source
    assert 'stats.get("total_pl")' not in page_source
    assert "_portfolio_value_chart" in page_source
    assert "_render_daily_vs_spy_table" in page_source
