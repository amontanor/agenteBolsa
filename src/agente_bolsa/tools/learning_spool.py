"""Private, disposable disk spool for large JSON-compatible learning records.

This helper is deliberately independent of the production Store and does not
alter existing readers or consumers. Callers own the context and its lifetime.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


class LearningSpool:
    """Append records to an isolated temporary SQLite database in input order."""

    def __init__(self, *, directory: Path | None = None) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="learning-spool-", dir=directory)
        self.path = Path(self._directory.name) / "spool.sqlite3"
        self._conn: sqlite3.Connection | None = None
        try:
            self._conn = sqlite3.connect(self.path)
            self._conn.execute(
                "CREATE TABLE records (ordinal INTEGER PRIMARY KEY, "
                "source_run_id TEXT NOT NULL, signal_date TEXT NOT NULL, "
                "created_at TEXT NOT NULL, signal_id TEXT NOT NULL, "
                "group_key TEXT NOT NULL, symbol TEXT NOT NULL, "
                "family TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            self._conn.execute("CREATE INDEX records_source ON records(source_run_id, ordinal)")
            self._conn.execute(
                "CREATE INDEX records_order ON records(signal_date, created_at, signal_id, ordinal)"
            )
            self._conn.execute(
                "CREATE INDEX records_group ON records(group_key, created_at, signal_id, ordinal)"
            )
            self._conn.execute("CREATE INDEX records_group_ordinal ON records(group_key, ordinal)")
            self._conn.execute(
                "CREATE INDEX records_observation ON records(signal_date, symbol, family, ordinal)"
            )
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> LearningSpool:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        finally:
            self._directory.cleanup()

    def append(self, record: dict[str, Any], *, group_key: str = "") -> int:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        payload = json.dumps(record, ensure_ascii=True, allow_nan=True, separators=(",", ":"))
        source_run_id = str(record.get("source_run_id") or "")
        cursor = self._conn.execute(
            "INSERT INTO records(source_run_id, signal_date, created_at, signal_id, group_key, symbol, family, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source_run_id, record.get("signal_date") or "", record.get("created_at") or "",
             record.get("signal_id") or "", group_key, record.get("symbol") or "",
             record.get("source_family") or "", payload),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def __len__(self) -> int:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        return int(self._conn.execute("SELECT count(*) FROM records").fetchone()[0])

    def grouped_rows(self) -> Iterator[tuple[str, int, dict[str, Any]]]:
        """Yield groups by first appearance and records by input order."""
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        self._conn.execute(
            "CREATE TEMP TABLE spool_group_order (first_ordinal INTEGER PRIMARY KEY, group_key TEXT NOT NULL UNIQUE)"
        )
        try:
            self._conn.execute(
                "INSERT INTO spool_group_order SELECT MIN(ordinal), group_key FROM records GROUP BY group_key"
            )
            cursor = self._conn.execute(
                "SELECT r.group_key, r.ordinal, r.payload FROM spool_group_order g "
                "CROSS JOIN records r INDEXED BY records_group_ordinal "
                "WHERE r.group_key = g.group_key ORDER BY g.first_ordinal, r.ordinal"
            )
            try:
                for group_key, ordinal, payload in cursor:
                    yield group_key, ordinal, json.loads(payload)
            finally:
                cursor.close()
        finally:
            self._conn.execute("DROP TABLE spool_group_order")

    def indexed_rows_for_group(self, group_key: str, *, ordered: bool = False) -> Iterator[tuple[int, dict[str, Any]]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        order = "created_at, signal_id, ordinal" if ordered else "ordinal"
        cursor = self._conn.execute(
            f"SELECT ordinal, payload FROM records WHERE group_key = ? ORDER BY {order}", (group_key,)
        )
        try:
            for ordinal, payload in cursor:
                yield ordinal, json.loads(payload)
        finally:
            cursor.close()

    def record_at(self, ordinal: int) -> dict[str, Any]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        row = self._conn.execute("SELECT payload FROM records WHERE ordinal = ?", (ordinal,)).fetchone()
        if row is None:
            raise KeyError(ordinal)
        return json.loads(row[0])

    def replace_payload(self, ordinal: int, record: dict[str, Any]) -> None:
        """Update contents only, leaving all indexed keys and cursor order fixed."""
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        payload = json.dumps(record, ensure_ascii=True, allow_nan=True, separators=(",", ":"))
        cursor = self._conn.execute("UPDATE records SET payload = ? WHERE ordinal = ?", (payload, ordinal))
        if cursor.rowcount != 1:
            raise KeyError(ordinal)

    def source_ordered_rows(self) -> Iterator[tuple[str, int, dict[str, Any]]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT source_run_id, ordinal, payload FROM records ORDER BY source_run_id, ordinal"
        )
        try:
            for source, ordinal, payload in cursor:
                yield source, ordinal, json.loads(payload)
        finally:
            cursor.close()

    def install_ranks(self, ranks: Iterable[tuple[int, int, int, int, str, int]]) -> None:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        self._conn.execute(
            "CREATE TEMP TABLE cohort_ranks (ordinal INTEGER PRIMARY KEY, rank INTEGER NOT NULL, "
            "source_count INTEGER NOT NULL, executed_count INTEGER NOT NULL, "
            "max_score_json TEXT NOT NULL, executed_loser INTEGER NOT NULL)"
        )
        self._conn.executemany("INSERT INTO cohort_ranks VALUES (?, ?, ?, ?, ?, ?)", ranks)

    def ranked_records(self) -> Iterator[tuple[int, dict[str, Any], int, int, int, float | None, bool]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT r.ordinal, r.payload, k.rank, k.source_count, k.executed_count, "
            "k.max_score_json, k.executed_loser FROM records r JOIN cohort_ranks k "
            "ON r.ordinal = k.ordinal ORDER BY r.ordinal"
        )
        try:
            for ordinal, payload, rank, count, executed, max_score, loser in cursor:
                yield ordinal, json.loads(payload), rank, count, executed, json.loads(max_score), bool(loser)
        finally:
            cursor.close()

    def rows_in_signal_order(self) -> Iterator[dict[str, Any]]:
        """Iterate stable date/time/id order using the temporary on-disk index."""
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT payload FROM records ORDER BY signal_date, created_at, signal_id, ordinal"
        )
        try:
            for (payload,) in cursor:
                yield json.loads(payload)
        finally:
            cursor.close()

    def rows_in_observation_order(self) -> Iterator[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT payload FROM records ORDER BY signal_date, symbol, family, ordinal"
        )
        try:
            for (payload,) in cursor:
                yield json.loads(payload)
        finally:
            cursor.close()

    def __iter__(self) -> Iterator[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute("SELECT payload FROM records ORDER BY ordinal")
        try:
            for (payload,) in cursor:
                yield json.loads(payload)
        finally:
            cursor.close()
