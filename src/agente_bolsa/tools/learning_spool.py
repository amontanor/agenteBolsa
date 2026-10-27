"""Private, disposable disk spool for large JSON-compatible learning records.

This helper is deliberately independent of the production Store and does not
alter existing readers or consumers. Callers own the context and its lifetime.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Iterator
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
                "created_at TEXT NOT NULL, signal_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            self._conn.execute("CREATE INDEX records_source ON records(source_run_id, ordinal)")
            self._conn.execute(
                "CREATE INDEX records_order ON records(signal_date, created_at, signal_id, ordinal)"
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

    def append(self, record: dict[str, Any]) -> int:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        payload = json.dumps(record, ensure_ascii=True, allow_nan=True, separators=(",", ":"))
        source_run_id = str(record.get("source_run_id") or "")
        cursor = self._conn.execute(
            "INSERT INTO records(source_run_id, signal_date, created_at, signal_id, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_run_id, record.get("signal_date", ""), record.get("created_at", ""),
             record.get("signal_id", ""), payload),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def replace(self, ordinal: int, record: dict[str, Any]) -> None:
        """Replace one temporary record without changing its input ordinal."""
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        payload = json.dumps(record, ensure_ascii=True, allow_nan=True, separators=(",", ":"))
        cursor = self._conn.execute(
            "UPDATE records SET source_run_id = ?, signal_date = ?, created_at = ?, "
            "signal_id = ?, payload = ? WHERE ordinal = ?",
            (str(record.get("source_run_id") or ""), record.get("signal_date", ""),
             record.get("created_at", ""), record.get("signal_id", ""), payload, ordinal),
        )
        if cursor.rowcount != 1:
            raise KeyError(ordinal)

    def source_runs(self) -> Iterator[str]:
        """Yield source groups in first-seen order, without loading their rows."""
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT source_run_id FROM records GROUP BY source_run_id ORDER BY MIN(ordinal)"
        )
        try:
            for (source_run_id,) in cursor:
                yield source_run_id
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

    def rows_for_source(self, source_run_id: str) -> Iterator[dict[str, Any]]:
        for _, row in self.indexed_rows_for_source(source_run_id):
            yield row

    def indexed_rows_for_source(self, source_run_id: str) -> Iterator[tuple[int, dict[str, Any]]]:
        if self._conn is None:
            raise RuntimeError("learning spool is closed")
        cursor = self._conn.execute(
            "SELECT ordinal, payload FROM records WHERE source_run_id = ? ORDER BY ordinal",
            (source_run_id,),
        )
        try:
            for ordinal, payload in cursor:
                yield ordinal, json.loads(payload)
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
