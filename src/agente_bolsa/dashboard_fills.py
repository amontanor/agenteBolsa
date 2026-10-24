"""Local fill repository, incremental synchronization and explicit coverage.

Este modulo es una cache de presentacion y contabilidad local. No crea,
bloquea, retrasa ni cambia ordenes; riesgo, ejecucion y kernel conservan sus
propias comprobaciones.

Contrato
--------
- Cada fill se identifica por el ``id`` unico de la actividad del broker dentro
  de una identidad de cuenta/entorno. Nunca por simbolo ni por fecha.
- ``content_hash`` cubre solo los campos del fill (id, symbol, side, qty, price,
  transaction_time, order_id). ``observed_at`` no forma parte del hash.
- Mismo ID y mismo contenido es un no-op. Mismo ID y contenido distinto conserva
  el original y anade un conflicto auditable; no existe ``INSERT OR REPLACE``.
- La preparacion, validacion y serializacion ocurren antes de abrir la
  transaccion; cada pagina se escribe en una transaccion corta
  ``BEGIN IMMEDIATE``.
- El cursor incremental se persiste con su direccion y token de pagina, de modo
  que un fallo intermedio se reanuda donde se quedo, no desde el principio.
- La cobertura distingue ``unavailable`` (sin fills), ``partial`` (ventana
  sincronizada) y ``complete`` (backfill agotado y sin truncacion pendiente).
  Solo ``complete`` permite presentar el P/L como historico completo.
- La reconciliacion compara IDs dentro de la ventana sincronizada y solo
  informa; no borra ni corrige fills a ciegas.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .dashboard_broker import DashboardBroker as BrokerClientFactory
from .storage import Store

SCHEMA_VERSION = 1

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"

FILL_CONTENT_FIELDS = (
    "fill_id",
    "symbol",
    "side",
    "qty",
    "price",
    "transaction_time",
    "order_id",
)

# Bounded refresh: the dashboard never walks the whole history. The separate
# backfill script is the only caller allowed to paginate until exhaustion.
FILLS_SYNC_MAX_PAGES = 3
FILLS_PAGE_SIZE = 100

FILLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_fills (
    identity_key TEXT NOT NULL,
    fill_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    qty REAL,
    price REAL,
    transaction_time TEXT,
    order_id TEXT,
    content_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    PRIMARY KEY (identity_key, fill_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_fills_time
ON dashboard_fills(identity_key, transaction_time, fill_id);

CREATE TABLE IF NOT EXISTS dashboard_fill_conflicts (
    conflict_id TEXT PRIMARY KEY,
    identity_key TEXT NOT NULL,
    fill_id TEXT NOT NULL,
    expected_hash TEXT NOT NULL,
    observed_hash TEXT NOT NULL,
    observed_payload_json TEXT NOT NULL,
    detected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dashboard_fill_conflicts_fill
ON dashboard_fill_conflicts(identity_key, fill_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS dashboard_fill_sync_state (
    identity_key TEXT PRIMARY KEY,
    cursor_after TEXT,
    pending_page_token TEXT,
    pending_after TEXT,
    pending_direction TEXT,
    last_sync_at TEXT,
    last_success_at TEXT,
    pages_last_sync INTEGER,
    truncated INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_error_at TEXT,
    backfill_before TEXT,
    backfill_page_token TEXT,
    backfill_completed_at TEXT,
    backfill_pages_total INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dashboard_fill_reconciliations (
    run_id TEXT PRIMARY KEY,
    identity_key TEXT NOT NULL,
    run_at TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    local_only_count INTEGER NOT NULL,
    broker_only_count INTEGER NOT NULL,
    local_only_json TEXT NOT NULL,
    broker_only_json TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_dashboard_fill_reconciliations_latest
ON dashboard_fill_reconciliations(identity_key, run_at DESC);
"""

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fill_activity_key(item: Mapping[str, Any]) -> tuple[str, str]:
    """Stable ordering key: transaction time, then the activity id."""
    stamp = str(item.get("transaction_time") or item.get("date") or "")
    return (stamp, str(item.get("id") or item.get("fill_id") or ""))


def normalize_fill(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalise one broker activity.

    Returns ``None`` when the activity has no usable id: an unidentifiable fill
    is rejected, never merged by symbol or date. Missing quantities or prices
    stay ``None`` instead of becoming zero.
    """
    if not isinstance(item, Mapping):
        return None
    activity_id = str(item.get("id") or item.get("fill_id") or "").strip()
    if not activity_id:
        return None
    symbol = str(item.get("symbol") or "").strip().upper() or None
    raw_side = str(item.get("side") or item.get("order_side") or "").strip().lower()
    qty_signed = _number(item.get("qty") or item.get("cum_qty") or item.get("filled_qty"))
    qty = abs(qty_signed) if qty_signed is not None else None
    if raw_side in {"buy", "sell"}:
        side = raw_side
    elif qty_signed is None:
        side = None
    else:
        # Same normalisation the existing trade-history reader applies today.
        side = "sell" if qty_signed < 0 else "buy"
    price = _number(item.get("price") or item.get("filled_avg_price") or item.get("avg_price"))
    transaction_time = (
        str(
            item.get("transaction_time")
            or item.get("date")
            or item.get("created_at")
            or ""
        ).strip()
        or None
    )
    order_id = str(item.get("order_id") or "").strip() or None
    return {
        "fill_id": activity_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "transaction_time": transaction_time,
        "order_id": order_id,
    }


def fill_content_hash(row: Mapping[str, Any]) -> str:
    """Hash of the fill fields only; observation times never enter it."""
    return _content_hash({key: row.get(key) for key in FILL_CONTENT_FIELDS})


def merge_fill_lists(*sources: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Merge fill lists by activity id, keeping the first occurrence.

    A fill without an id cannot be deduplicated by identity; it is kept with a
    content-derived fallback key so two different anonymous rows are not merged.
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        for item in source or []:
            if not isinstance(item, Mapping):
                continue
            row = dict(item)
            activity_id = str(row.get("id") or row.get("fill_id") or "").strip()
            key = activity_id or f"anon:{_content_hash(row)}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return sorted(merged, key=fill_activity_key)


@dataclass(frozen=True)
class StoreResult:
    stored: int = 0
    unchanged: int = 0
    conflicts: int = 0
    rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "stored": self.stored,
            "unchanged": self.unchanged,
            "conflicts": self.conflicts,
            "rejected": self.rejected,
        }


@dataclass(frozen=True)
class SyncState:
    identity_key: str
    cursor_after: str | None = None
    pending_page_token: str | None = None
    pending_after: str | None = None
    pending_direction: str | None = None
    last_sync_at: str | None = None
    last_success_at: str | None = None
    pages_last_sync: int | None = None
    truncated: bool = False
    last_error: str | None = None
    last_error_at: str | None = None
    backfill_before: str | None = None
    backfill_page_token: str | None = None
    backfill_completed_at: str | None = None
    backfill_pages_total: int = 0


@dataclass(frozen=True)
class SyncResult:
    status: str
    pages: int = 0
    fetched: int = 0
    stored: int = 0
    unchanged: int = 0
    conflicts: int = 0
    rejected: int = 0
    truncated: bool = False
    stop_reason: str = "exhausted"
    cursor_after: str | None = None
    next_page_token: str | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {            "status": self.status,
            "pages": self.pages,
            "fetched": self.fetched,
            "stored": self.stored,
            "unchanged": self.unchanged,
            "conflicts": self.conflicts,
            "rejected": self.rejected,
            "truncated": self.truncated,
            "stop_reason": self.stop_reason,
            "cursor_after": self.cursor_after,
            "next_page_token": self.next_page_token,
            "coverage": dict(self.coverage),
            "reconciliation": dict(self.reconciliation),
            "error": self.error,
        }


class FillRepository:
    """SQLite repository of local fills and their synchronization state."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.store = Store(self.database_path, self.database_path.parent / "dashboard_logs")

    # -- connection -----------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        return self.store.connect(timeout_seconds=0.25)

    def read_connection(self) -> sqlite3.Connection:
        connection = self.store.read_connection()
        connection.execute("PRAGMA busy_timeout=250")
        return connection

    def ensure_schema(self) -> None:
        reference = str(self.database_path.resolve())
        with _SCHEMA_LOCK:
            if reference in _SCHEMA_READY:
                return
        with closing(self.connect()) as conn, conn:
            conn.executescript(FILLS_SCHEMA)
        with _SCHEMA_LOCK:
            _SCHEMA_READY.add(reference)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.ensure_schema()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    # -- writes ---------------------------------------------------------
    def store_fills(
        self,
        identity_key: str,
        fills: Iterable[Mapping[str, Any]] | None,
        *,
        observed_at: str | None = None,
    ) -> StoreResult:
        """Insert fills idempotently, preserving the original on conflict.

        All rows are validated, normalised and hashed before the transaction
        starts. Duplicate ids inside one batch keep the first occurrence.
        """
        identity = str(identity_key or "").strip()
        if not identity:
            raise ValueError("identity_key es obligatorio para guardar fills.")
        stamp = observed_at or utc_now_iso()
        prepared: dict[str, dict[str, Any]] = {}
        batch_conflicts: list[dict[str, Any]] = []
        rejected = 0
        for item in fills or []:
            if not isinstance(item, Mapping):
                rejected += 1
                continue
            row = normalize_fill(item)
            if row is None:
                rejected += 1
                continue
            digest = fill_content_hash(row)
            existing = prepared.get(row["fill_id"])
            if existing is not None:
                if existing["content_hash"] != digest:
                    batch_conflicts.append(
                        {
                            "row": row,
                            "digest": digest,
                            "expected_hash": existing["content_hash"],
                            "payload": _canonical_json(row),
                        }
                    )
                continue
            prepared[row["fill_id"]] = {**row, "content_hash": digest}
        if not prepared and not batch_conflicts:
            return StoreResult(rejected=rejected)

        stored = unchanged = conflicts = 0
        with self._transaction() as conn:
            for fill_id, row in prepared.items():
                current = conn.execute(
                    """
                    SELECT content_hash FROM dashboard_fills
                    WHERE identity_key = ? AND fill_id = ?
                    """,
                    (identity, fill_id),
                ).fetchone()
                if current is None:
                    conn.execute(
                        """
                        INSERT INTO dashboard_fills (
                            identity_key, fill_id, symbol, side, qty, price,
                            transaction_time, order_id, content_hash, observed_at,
                            first_seen_at, schema_version
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identity,
                            fill_id,
                            row["symbol"],
                            row["side"],
                            row["qty"],
                            row["price"],
                            row["transaction_time"],
                            row["order_id"],
                            row["content_hash"],
                            stamp,
                            stamp,
                            SCHEMA_VERSION,
                        ),
                    )
                    stored += 1
                elif str(current["content_hash"]) == row["content_hash"]:
                    unchanged += 1
                else:
                    conflicts += self._insert_conflict(
                        conn,
                        identity,
                        fill_id,
                        expected=str(current["content_hash"]),
                        observed=row["content_hash"],
                        payload=_canonical_json(row),
                        detected_at=stamp,
                    )
            for conflict in batch_conflicts:
                conflicts += self._insert_conflict(
                    conn,
                    identity,
                    conflict["row"]["fill_id"],
                    expected=conflict["expected_hash"],
                    observed=conflict["digest"],
                    payload=conflict["payload"],
                    detected_at=stamp,
                )
        return StoreResult(
            stored=stored, unchanged=unchanged, conflicts=conflicts, rejected=rejected
        )

    def _insert_conflict(
        self,
        conn: sqlite3.Connection,
        identity: str,
        fill_id: str,
        *,
        expected: str,
        observed: str,
        payload: str,
        detected_at: str,
    ) -> int:
        conflict_id = _content_hash(
            {
                "identity": identity,
                "fill_id": fill_id,
                "expected": expected,
                "observed": observed,
            }
        )[:32]
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO dashboard_fill_conflicts (
                conflict_id, identity_key, fill_id, expected_hash,
                observed_hash, observed_payload_json, detected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (conflict_id, identity, fill_id, expected, observed, payload, detected_at),
        )
        return 1 if cursor.rowcount == 1 else 0

    def record_sync(
        self,
        identity_key: str,
        *,
        cursor_after: str | None,
        pending_page_token: str | None,
        pending_after: str | None,
        pending_direction: str | None,
        pages: int,
        truncated: bool,
        at: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        identity = str(identity_key or "").strip()
        if not identity:
            raise ValueError("identity_key es obligatorio para el estado de sync.")
        stamp = at or utc_now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO dashboard_fill_sync_state (
                    identity_key, cursor_after, pending_page_token, pending_after,
                    pending_direction, last_sync_at, last_success_at, pages_last_sync,
                    truncated, last_error, last_error_at, schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity_key) DO UPDATE SET
                    cursor_after = COALESCE(excluded.cursor_after, dashboard_fill_sync_state.cursor_after),
                    pending_page_token = excluded.pending_page_token,
                    pending_after = excluded.pending_after,
                    pending_direction = excluded.pending_direction,
                    last_sync_at = excluded.last_sync_at,
                    last_success_at = CASE
                        WHEN excluded.last_success_at IS NULL
                        THEN dashboard_fill_sync_state.last_success_at
                        ELSE excluded.last_success_at
                    END,
                    pages_last_sync = excluded.pages_last_sync,
                    truncated = excluded.truncated,
                    last_error = excluded.last_error,
                    last_error_at = excluded.last_error_at,
                    schema_version = excluded.schema_version
                """,
                (
                    identity,
                    cursor_after,
                    pending_page_token,
                    pending_after,
                    pending_direction,
                    stamp,
                    stamp if success else None,
                    int(pages),
                    1 if truncated else 0,
                    None if error is None else str(error)[:500],
                    None if error is None else stamp,
                    SCHEMA_VERSION,
                ),
            )

    def mark_backfill(
        self,
        identity_key: str,
        *,
        before: str | None,
        page_token: str | None,
        pages_total: int,
        completed_at: str | None = None,
        at: str | None = None,
    ) -> None:
        identity = str(identity_key or "").strip()
        if not identity:
            raise ValueError("identity_key es obligatorio para el backfill.")
        stamp = at or utc_now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO dashboard_fill_sync_state (
                    identity_key, backfill_before, backfill_page_token,
                    backfill_completed_at, backfill_pages_total, schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity_key) DO UPDATE SET
                    backfill_before = excluded.backfill_before,
                    backfill_page_token = excluded.backfill_page_token,
                    backfill_completed_at = COALESCE(
                        excluded.backfill_completed_at,
                        dashboard_fill_sync_state.backfill_completed_at
                    ),
                    backfill_pages_total = excluded.backfill_pages_total
                """,
                (identity, before, page_token, completed_at, int(pages_total), SCHEMA_VERSION),
            )
            conn.execute(
                "UPDATE dashboard_fill_sync_state SET last_sync_at = ? WHERE identity_key = ?",
                (stamp, identity),
            )

    def record_reconciliation(
        self,
        identity_key: str,
        *,
        run_at: str,
        window_start: str | None,
        window_end: str | None,
        local_only: list[str],
        broker_only: list[str],
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        identity = str(identity_key or "").strip()
        if not identity:
            raise ValueError("identity_key es obligatorio para la reconciliacion.")
        run_id = _content_hash(
            {"identity": identity, "run_at": run_at, "local": local_only, "broker": broker_only}
        )[:32]
        payload = {
            "run_id": run_id,
            "identity_key": identity,
            "run_at": run_at,
            "window_start": window_start,
            "window_end": window_end,
            "local_only_count": len(local_only),
            "broker_only_count": len(broker_only),
            "local_only": list(local_only),
            "broker_only": list(broker_only),
            "status": status,
            "reason": reason,
        }
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO dashboard_fill_reconciliations (
                    run_id, identity_key, run_at, window_start, window_end,
                    local_only_count, broker_only_count, local_only_json,
                    broker_only_json, status, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    identity,
                    run_at,
                    window_start,
                    window_end,
                    len(local_only),
                    len(broker_only),
                    _canonical_json(local_only),
                    _canonical_json(broker_only),
                    status,
                    reason,
                ),
            )
        return payload

    # -- reads ----------------------------------------------------------
    def load_fills(self, identity_key: str) -> list[dict[str, Any]]:
        identity = str(identity_key or "").strip()
        if not identity:
            return []
        self.ensure_schema()
        with closing(self.read_connection()) as conn, conn:
            rows = conn.execute(
                """
                SELECT fill_id, symbol, side, qty, price, transaction_time,
                       order_id, content_hash, observed_at
                FROM dashboard_fills
                WHERE identity_key = ?
                ORDER BY COALESCE(transaction_time, '') ASC, fill_id ASC
                """,
                (identity,),
            ).fetchall()
        return [
            {
                "id": str(row["fill_id"]),
                "symbol": row["symbol"],
                "side": row["side"],
                "qty": row["qty"],
                "price": row["price"],
                "transaction_time": row["transaction_time"],
                "order_id": row["order_id"],
                "content_hash": str(row["content_hash"]),
                "observed_at": str(row["observed_at"]),
            }
            for row in rows
        ]

    def count_fills(self, identity_key: str) -> int:
        identity = str(identity_key or "").strip()
        if not identity:
            return 0
        self.ensure_schema()
        with closing(self.read_connection()) as conn, conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM dashboard_fills WHERE identity_key = ?",
                (identity,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def sync_state(self, identity_key: str) -> SyncState | None:
        identity = str(identity_key or "").strip()
        if not identity:
            return None
        self.ensure_schema()
        with closing(self.read_connection()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM dashboard_fill_sync_state WHERE identity_key = ?",
                (identity,),
            ).fetchone()
        if row is None:
            return None
        return SyncState(
            identity_key=identity,
            cursor_after=row["cursor_after"],
            pending_page_token=row["pending_page_token"],
            pending_after=row["pending_after"],
            pending_direction=row["pending_direction"],
            last_sync_at=row["last_sync_at"],
            last_success_at=row["last_success_at"],
            pages_last_sync=None
            if row["pages_last_sync"] is None
            else int(row["pages_last_sync"]),
            truncated=bool(row["truncated"]),
            last_error=row["last_error"],
            last_error_at=row["last_error_at"],
            backfill_before=row["backfill_before"],
            backfill_page_token=row["backfill_page_token"],
            backfill_completed_at=row["backfill_completed_at"],
            backfill_pages_total=int(row["backfill_pages_total"] or 0),
        )

    def coverage(self, identity_key: str) -> dict[str, Any]:
        """Explicit coverage. Without data nothing is presented as complete."""
        identity = str(identity_key or "").strip()
        state = self.sync_state(identity) if identity else None
        totals = {"fills_stored": 0, "oldest": None, "newest": None}
        if identity:
            with closing(self.read_connection()) as conn, conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           MIN(NULLIF(transaction_time, '')) AS oldest,
                           MAX(NULLIF(transaction_time, '')) AS newest
                    FROM dashboard_fills
                    WHERE identity_key = ?
                    """,
                    (identity,),
                ).fetchone()
            totals = {
                "fills_stored": int(row["total"] or 0),
                "oldest": row["oldest"],
                "newest": row["newest"],
            }
        backfilled = bool(state and state.backfill_completed_at)
        truncated = bool(state and state.truncated)
        if totals["fills_stored"] == 0:
            status = STATUS_UNAVAILABLE
        elif backfilled:
            # Completeness is granted by an exhausted backfill, not by a recent
            # sync. A truncated incremental read is reported separately and does
            # not rewrite the already covered history.
            status = STATUS_COMPLETE
        else:
            status = STATUS_PARTIAL
        return {
            "status": status,
            "oldest_fill_at": totals["oldest"],
            "newest_fill_at": totals["newest"],
            "fills_stored": totals["fills_stored"],
            "complete_since": totals["oldest"] if status == STATUS_COMPLETE else None,
            "truncated": truncated,
            "last_sync_at": None if state is None else state.last_sync_at,
            "last_success_at": None if state is None else state.last_success_at,
            "pages_last_sync": None if state is None else state.pages_last_sync,
            "last_error": None if state is None else state.last_error,
            "pending_page_token": None if state is None else state.pending_page_token,
            "backfill_completed_at": None if state is None else state.backfill_completed_at,
            "source": "local_sync",
        }

    def conflicts(self, identity_key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        identity = str(identity_key or "").strip()
        if not identity:
            return []
        self.ensure_schema()
        with closing(self.read_connection()) as conn, conn:
            rows = conn.execute(
                """
                SELECT conflict_id, fill_id, expected_hash, observed_hash,
                       observed_payload_json, detected_at
                FROM dashboard_fill_conflicts
                WHERE identity_key = ?
                ORDER BY detected_at DESC, conflict_id ASC
                LIMIT ?
                """,
                (identity, int(limit)),
            ).fetchall()
        return [
            {
                "conflict_id": str(row["conflict_id"]),
                "fill_id": str(row["fill_id"]),
                "expected_hash": str(row["expected_hash"]),
                "observed_hash": str(row["observed_hash"]),
                "observed_payload": json.loads(row["observed_payload_json"]),
                "detected_at": str(row["detected_at"]),
            }
            for row in rows
        ]

    def latest_reconciliation(self, identity_key: str) -> dict[str, Any] | None:
        identity = str(identity_key or "").strip()
        if not identity:
            return None
        self.ensure_schema()
        with closing(self.read_connection()) as conn, conn:
            row = conn.execute(
                """
                SELECT * FROM dashboard_fill_reconciliations
                WHERE identity_key = ?
                ORDER BY run_at DESC, run_id DESC
                LIMIT 1
                """,
                (identity,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "run_at": str(row["run_at"]),
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "local_only_count": int(row["local_only_count"]),
            "broker_only_count": int(row["broker_only_count"]),
            "local_only": json.loads(row["local_only_json"]),
            "broker_only": json.loads(row["broker_only_json"]),
            "status": str(row["status"]),
            "reason": row["reason"],
        }


# -- synchronization ----------------------------------------------------


def _envelope_items(envelope: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(envelope, Mapping):
        items = envelope.get("items")
        token = envelope.get("next_page_token")
        if envelope.get("stop_reason") in {"repeated_token", "single_page_fallback"}:
            raise ValueError("No se ha demostrado la continuidad de la pagina de fills.")
        if envelope.get("truncated") and not token:
            raise ValueError("Pagina truncada sin cursor de continuacion.")
        if isinstance(items, list):
            if not items and token:
                raise ValueError("Pagina vacia con cursor pendiente.")
            return [item for item in items if isinstance(item, dict)], (
                str(token).strip() if token else None
            )
        raise ValueError("La pagina de fills no trae una lista de items utilizable.")
    if isinstance(envelope, list):
        if any(not isinstance(item, dict) or not item.get("id") for item in envelope):
            raise ValueError("Pagina de fills con actividad sin ID.")
        return envelope, str(envelope[-1]["id"]) if envelope else None
    raise ValueError("Respuesta de fills no interpretable.")


def fetch_for_client(client: Any, *, page_size: int = FILLS_PAGE_SIZE) -> Callable[..., Any]:
    """One-page reader bound to an already constructed client.

    Prefers the paginated envelope and falls back to the legacy list method for
    clients that only implement ``alpaca_trade_activities``.
    """
    page_reader = getattr(client, "alpaca_trade_activities_page", None)
    if callable(page_reader):
        def fetch_page(**kwargs: Any) -> Any:
            return page_reader(
                limit=kwargs.get("page_size", page_size),
                page_size=kwargs.get("page_size", page_size),
                page_token=kwargs.get("page_token"),
                after=kwargs.get("after"),
                direction=kwargs.get("direction", "desc"),
                max_pages=1,
            )

        return fetch_page

    def fetch_legacy(**kwargs: Any) -> Any:
        items = client.alpaca_trade_activities(
            limit=kwargs.get("page_size", page_size),
            page_token=kwargs.get("page_token"),
            after=kwargs.get("after"),
            direction=kwargs.get("direction", "desc"),
            max_pages=1,
        )
        if not isinstance(items, list):
            raise ValueError("Respuesta legacy de fills no interpretable.")
        valid_items, token = _envelope_items(items)
        return {
            "items": valid_items,
            "next_page_token": token,
            "pages": 1,
            "truncated": bool(token),
            "stop_reason": "max_pages" if token else "empty_page",
        }

    return fetch_legacy


def default_fetch(settings: Any) -> Callable[..., Any]:
    return fetch_for_client(BrokerClientFactory(settings))


def _advance_cursor(
    current_id: str | None,
    current_key: tuple[str, str] | None,
    items: list[dict[str, Any]],
) -> tuple[str | None, tuple[str, str] | None]:
    """Newest activity id seen so far; a sync never moves its cursor backwards."""
    cursor_id = current_id
    cursor_key = current_key
    for item in items:
        if not str(item.get("id") or "").strip():
            continue
        key = fill_activity_key(item)
        if cursor_key is None or key > cursor_key:
            cursor_key = key
            cursor_id = str(item.get("id")).strip()
    return cursor_id, cursor_key


def reconcile_fills(
    repository: FillRepository,
    identity_key: str,
    broker_items: Iterable[Mapping[str, Any]] | None,
    *,
    run_at: str | None = None,
) -> dict[str, Any]:
    """Compare local fills with the broker window; report only, never mutate.

    The comparison is limited to the transaction-time window covered by
    ``broker_items``. A local fill outside that window is not evidence of a
    broker deletion and is not reported as such.
    """
    stamp = run_at or utc_now_iso()
    items = [item for item in (broker_items or []) if isinstance(item, Mapping)]
    broker_ids = {
        str(item.get("id") or item.get("fill_id") or "").strip()
        for item in items
    }
    broker_ids.discard("")
    times = [
        str(item.get("transaction_time") or item.get("date") or "")
        for item in items
        if str(item.get("transaction_time") or item.get("date") or "")
    ]
    if not broker_ids or not times:
        return repository.record_reconciliation(
            identity_key,
            run_at=stamp,
            window_start=None,
            window_end=None,
            local_only=[],
            broker_only=[],
            status="skipped",
            reason="empty_window",
        )
    window_start = min(times)
    window_end = max(times)
    local = repository.load_fills(identity_key)
    local_in_window = [
        row
        for row in local
        if row.get("transaction_time")
        and window_start <= str(row["transaction_time"]) <= window_end
    ]
    local_ids = {str(row.get("id") or "") for row in local_in_window}
    local_ids.discard("")
    local_only = sorted(local_ids - broker_ids)
    broker_only = sorted(broker_ids - local_ids)
    status = "ok" if not local_only and not broker_only else "mismatch"
    return repository.record_reconciliation(
        identity_key,
        run_at=stamp,
        window_start=window_start,
        window_end=window_end,
        local_only=local_only,
        broker_only=broker_only,
        status=status,
        reason=None,
    )


def sync_recent(
    settings: Any,
    *,
    repository: FillRepository,
    identity_key: str,
    fetch: Callable[..., Any] | None = None,
    max_pages: int = FILLS_SYNC_MAX_PAGES,
    page_size: int = FILLS_PAGE_SIZE,
    now: str | None = None,
) -> SyncResult:
    """Bounded incremental sync from the last persisted cursor.

    The first call seeds the newest window (``direction="desc"``). Later calls
    ask only for activities newer than the cursor (``direction="asc"`` with
    ``page_token``). A failure or a page ceiling persists the next page token, so the
    following call resumes instead of downloading the same window again.
    """
    identity = str(identity_key or "").strip()
    if not identity:
        raise ValueError("identity_key es obligatorio para sincronizar fills.")
    repository.ensure_schema()
    stamp = now or utc_now_iso()
    reader = fetch or default_fetch(settings)
    state = repository.sync_state(identity)

    if state is not None and state.pending_page_token:
        direction = state.pending_direction or "desc"
        after = None
        token: str | None = state.pending_page_token
    else:
        direction = "asc" if state is not None and state.cursor_after else "desc"
        after = None
        token = state.cursor_after if direction == "asc" else None

    cursor = state.cursor_after if state is not None else None
    cursor_key: tuple[str, str] | None = None
    if cursor:
        with closing(repository.connect()) as conn:
            row = conn.execute(
                "SELECT transaction_time, fill_id FROM dashboard_fills "
                "WHERE identity_key = ? AND fill_id = ?", (identity, cursor)
            ).fetchone()
        if row is not None:
            cursor_key = (str(row["transaction_time"] or ""), str(row["fill_id"]))
    fetched = stored = unchanged = conflicts = rejected = 0
    pages_done = 0
    window_items: list[dict[str, Any]] = []
    seen_tokens: set[str] = {token} if token else set()
    truncated = False
    stop_reason = "exhausted"
    next_token: str | None = token

    try:
        for _ in range(max(1, int(max_pages))):
            envelope = reader(
                after=after,
                page_token=token,
                page_size=int(page_size),
                direction=direction,
            )
            items, next_token = _envelope_items(envelope)
            pages_done += 1
            fetched += len(items)
            window_items.extend(items)
            result = repository.store_fills(identity, items, observed_at=stamp)
            stored += result.stored
            unchanged += result.unchanged
            conflicts += result.conflicts
            rejected += result.rejected
            cursor, cursor_key = _advance_cursor(cursor, cursor_key, items)

            repeated = bool(next_token and next_token in seen_tokens)
            if repeated:
                raise ValueError("Cursor repetido: sincronizacion incompleta.")
            pending = None if (not next_token or repeated) else next_token
            truncated = bool(next_token)
            if not next_token:
                stop_reason = "exhausted"
            elif repeated:
                stop_reason = "repeated_token"
            elif pages_done >= max_pages:
                stop_reason = "max_pages"
            else:
                stop_reason = "page_continued"
            repository.record_sync(
                identity,
                cursor_after=cursor,
                pending_page_token=pending,
                pending_after=after,
                pending_direction=direction if pending else None,
                pages=pages_done,
                truncated=truncated,
                at=stamp,
                success=True,
            )
            if not next_token or repeated or not items:
                if not items and next_token:
                    stop_reason = "empty_page"
                break
            seen_tokens.add(next_token)
            token = next_token
        else:
            truncated = True
            stop_reason = "max_pages"
    except Exception as exc:  # noqa: BLE001 - fail-open: previous fills are kept.
        error = f"{type(exc).__name__}: {exc}"
        repository.record_sync(
            identity,
            cursor_after=cursor,
            pending_page_token=token,
            pending_after=after,
            pending_direction=direction,
            pages=pages_done,
            truncated=True,
            at=stamp,
            success=False,
            error=error,
        )
        return SyncResult(
            status="degraded",
            pages=pages_done,
            fetched=fetched,
            stored=stored,
            unchanged=unchanged,
            conflicts=conflicts,
            rejected=rejected,
            truncated=True,
            stop_reason="error",
            cursor_after=cursor,
            next_page_token=token,
            coverage=repository.coverage(identity),
            error=str(exc),
        )

    reconciliation = reconcile_fills(repository, identity, window_items, run_at=stamp)
    return SyncResult(
        status="ok",
        pages=pages_done,
        fetched=fetched,
        stored=stored,
        unchanged=unchanged,
        conflicts=conflicts,
        rejected=rejected,
        truncated=truncated,
        stop_reason=stop_reason,
        cursor_after=cursor,
        next_page_token=next_token,
        coverage=repository.coverage(identity),
        reconciliation=reconciliation,
    )


def backfill_fills(
    settings: Any,
    *,
    repository: FillRepository,
    identity_key: str,
    fetch: Callable[..., Any] | None = None,
    max_pages: int = 50,
    page_size: int = FILLS_PAGE_SIZE,
    now: str | None = None,
) -> dict[str, Any]:
    """Page the whole history on demand, resuming from the persisted cursor.

    This is the only path allowed to walk the full history; it is never called by
    the dashboard load or its refresh. Only validated exhaustion without a
    pending token, rejected data or conflicts can certify complete coverage.
    """
    identity = str(identity_key or "").strip()
    if not identity:
        raise ValueError("identity_key es obligatorio para el backfill.")
    repository.ensure_schema()
    stamp = now or utc_now_iso()
    reader = fetch or default_fetch(settings)
    state = repository.sync_state(identity)
    # Activity IDs belong in page_token, never in the date filter `after`.
    before = None
    token = state.backfill_page_token if state is not None else None
    pages_total = state.backfill_pages_total if state is not None else 0
    completed_before = state.backfill_completed_at if state is not None else None

    if completed_before:
        return {
            "status": "complete",
            "pages": 0,
            "fetched": 0,
            "stored": 0,
            "unchanged": 0,
            "conflicts": 0,
            "rejected": 0,
            "truncated": False,
            "stop_reason": "already_complete",
            "coverage": repository.coverage(identity),
        }

    fetched = stored = unchanged = conflicts = rejected = 0
    pages_done = 0
    seen_tokens: set[str] = {token} if token else set()
    truncated = False
    stop_reason = "exhausted"
    next_token: str | None = token

    try:
        for _ in range(max(1, int(max_pages))):
            envelope = reader(
                after=before,
                page_token=token,
                page_size=int(page_size),
                direction="desc",
            )
            items, next_token = _envelope_items(envelope)
            pages_done += 1
            fetched += len(items)
            result = repository.store_fills(identity, items, observed_at=stamp)
            stored += result.stored
            unchanged += result.unchanged
            conflicts += result.conflicts
            rejected += result.rejected
            repeated = bool(next_token and next_token in seen_tokens)
            if repeated or rejected or conflicts or repository.conflicts(identity, limit=1):
                raise ValueError("Backfill incompleto: cursor repetido o datos rechazados/en conflicto.")
            pending = None if (not next_token or repeated) else next_token
            truncated = bool(next_token)
            if not next_token:
                stop_reason = "exhausted"
            elif repeated:
                stop_reason = "repeated_token"
            elif pages_done >= max_pages:
                stop_reason = "max_pages"
            else:
                stop_reason = "page_continued"
            repository.mark_backfill(
                identity,
                before=before,
                page_token=pending,
                pages_total=pages_total + pages_done,
                completed_at=stamp if not next_token else None,
                at=stamp,
            )
            if not next_token or repeated or not items:
                if not items and next_token:
                    stop_reason = "empty_page"
                break
            seen_tokens.add(next_token)
            token = next_token
        else:
            truncated = True
            stop_reason = "max_pages"
    except Exception as exc:  # noqa: BLE001 - partial progress is kept.
        return {
            "status": "degraded",
            "pages": pages_done,
            "fetched": fetched,
            "stored": stored,
            "unchanged": unchanged,
            "conflicts": conflicts,
            "rejected": rejected,
            "truncated": True,
            "stop_reason": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "coverage": repository.coverage(identity),
        }

    return {
        "status": "ok",
        "pages": pages_done,
        "fetched": fetched,
        "stored": stored,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "rejected": rejected,
        "truncated": truncated,
        "stop_reason": stop_reason,
        "coverage": repository.coverage(identity),
    }
