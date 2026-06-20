"""Tests de las utilidades compartidas (agente_bolsa._utils)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from agente_bolsa._utils import (
    human_bytes,
    log_swallow,
    parse_iso,
    sqlite_connect_ro,
    table_exists,
    to_float,
)


def test_to_float_tolerant():
    assert to_float("1.5") == 1.5
    assert to_float(2) == 2.0
    assert to_float(None) is None
    assert to_float("nope") is None
    assert to_float("nope", default=0.0) == 0.0
    assert to_float(None, default=-1.0) == -1.0


def test_parse_iso_normalizes_utc():
    assert parse_iso(None) is None
    assert parse_iso("bad") is None
    d = parse_iso("2026-06-18T12:00:00Z")
    assert d is not None and d.tzinfo is not None
    assert d == datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
    naive = parse_iso("2026-06-18T12:00:00")
    assert naive is not None and naive.tzinfo == timezone.utc


def test_human_bytes():
    assert human_bytes(512) == "512.0B"
    assert human_bytes(2048) == "2.0KB"
    assert human_bytes(7.5 * 1024**3).endswith("GB")


def test_sqlite_ro_and_table_exists(tmp_path):
    db = tmp_path / "t.sqlite3"
    w = sqlite3.connect(str(db))
    w.execute("CREATE TABLE foo (id INTEGER)")
    w.execute("INSERT INTO foo VALUES (1)")
    w.commit()
    w.close()
    con = sqlite_connect_ro(db)
    assert table_exists(con, "foo") is True
    assert table_exists(con, "bar") is False
    assert con.execute("SELECT COUNT(*) FROM foo").fetchone()[0] == 1
    # solo lectura: una escritura debe fallar
    try:
        con.execute("INSERT INTO foo VALUES (2)")
        wrote = True
    except sqlite3.OperationalError:
        wrote = False
    assert wrote is False
    con.close()


def test_log_swallow_does_not_raise(caplog):
    logger = logging.getLogger("test_swallow")
    with caplog.at_level(logging.WARNING):
        try:
            raise ValueError("boom")
        except Exception as exc:  # noqa: BLE001
            log_swallow(logger, "contexto x", exc)
    assert any("contexto x" in r.getMessage() for r in caplog.records)
