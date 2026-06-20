"""Regresion: una orden no debe heredar el fill de una senal historica.

Bug detectado el 20-jun-2026: match_signal_row_for_buy_order filtraba
signal_date <= cutoff sin cota inferior, asi que una orden enganchaba una senal
de semanas atras y heredaba su fill (320 senales del 15-jun afectadas).
"""
from __future__ import annotations

import sqlite3

from agente_bolsa.tools.execution_linking import match_signal_row_for_buy_order

_COLS = (
    "signal_id, source_run_id, source, symbol, signal_date, decision, "
    "features_json, gate_json, outcome_json, created_at, updated_at"
)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(f"CREATE TABLE signal_outcomes ({_COLS})")
    return con


def _insert(con, signal_id, signal_date, created_at):
    con.execute(
        f"INSERT INTO signal_outcomes ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (signal_id, "run", "scan", "AAA", signal_date, "approved_buy",
         "{}", "{}", "{}", created_at, created_at),
    )
    con.commit()


def test_does_not_inherit_old_signal():
    con = _conn()
    _insert(con, "old", "2026-05-01", "2026-05-01T10:00:00")
    res = match_signal_row_for_buy_order(con, symbol="AAA", order_created_at="2026-06-15T15:00:00")
    assert res is None  # con ventana de 5 dias no debe enlazar la senal de mayo


def test_matches_recent_signal():
    con = _conn()
    _insert(con, "new", "2026-06-13", "2026-06-13T10:00:00")
    res = match_signal_row_for_buy_order(con, symbol="AAA", order_created_at="2026-06-15T15:00:00")
    assert res is not None and res["signal_id"] == "new"


def test_age_window_disabled_allows_old_signal():
    con = _conn()
    _insert(con, "old", "2026-05-01", "2026-05-01T10:00:00")
    res = match_signal_row_for_buy_order(
        con, symbol="AAA", order_created_at="2026-06-15T15:00:00", max_signal_age_days=None
    )
    assert res is not None and res["signal_id"] == "old"
