"""Persistent dashboard snapshots: presentation-only cache, never trading authority.

Contrato
--------
- Cada version se identifica por ``(identity_key, resource, content_hash)``.
  Mismo contenido es una escritura idempotente; contenido distinto anade una
  version nueva y nunca reescribe la anterior (append-only).
- La escritura de varios recursos de una misma lectura es atomica: se prepara,
  valida y serializa fuera de SQLite y se inserta en una unica transaccion.
- ``dashboard_snapshot_state`` guarda la ultima observacion correcta por
  ``(identity_key, resource)``. Una lectura nueva con el mismo contenido no
  anade version de payload, pero si actualiza esa observacion: la antiguedad
  refleja la lectura real mas reciente, nunca el momento en que cambio el
  contenido por ultima vez.
- La lectura valida ``schema_version``, forma del JSON y el ``content_hash``
  recalculado. Si la ultima observacion correcta apunta a un payload que ya no
  valida se devuelve la ultima version correcta y se declara la situacion
  (``observation_status``), nunca se inventa frescura; si no hay ninguna
  version valida el estado es ``None``/``none``, nunca un cero inventado.
- La identidad v2 incluye entorno, ruta de DB y una huella irreversible de las
  credenciales, mas el ``account_id`` observado. No se persisten credenciales.
  Las pistas anteriores sin aislamiento de credenciales no se reutilizan.
- Los intentos fallidos se registran aparte (``dashboard_snapshot_attempts``)
  para mostrar antiguedad y degradacion sin destruir el ultimo dato correcto.

Este modulo no crea, bloquea, retrasa ni cambia ordenes. Riesgo, ejecucion y
kernel conservan sus propias comprobaciones.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import new_id
from .storage import Store

SCHEMA_VERSION = 1

RESOURCE_ACCOUNT = "account"
RESOURCE_POSITIONS = "positions"
RESOURCE_ORDERS = "orders"
RESOURCE_FILLS = "fills"
RESOURCE_CURVE = "curve"
RESOURCE_INTRADAY = "intraday"

RESOURCES = (
    RESOURCE_ACCOUNT,
    RESOURCE_POSITIONS,
    RESOURCE_ORDERS,
    RESOURCE_FILLS,
    RESOURCE_CURVE,
    RESOURCE_INTRADAY,
)

STATUS_OK = "ok"

# Why the returned snapshot carries the timestamp it carries.
OBSERVATION_STATE_CURRENT = "current"  # Last correct observation points at a valid payload.
OBSERVATION_STATE_INVALID = "invalid_payload"  # The observed payload no longer validates.
OBSERVATION_STATE_ABSENT = "no_state"  # Legacy rows written without a state record.

SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    identity_key TEXT NOT NULL,
    resource TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (identity_key, resource, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_snapshots_latest
ON dashboard_snapshots(identity_key, resource, observed_at DESC);

CREATE TABLE IF NOT EXISTS dashboard_snapshot_state (
    identity_key TEXT NOT NULL,
    resource TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (identity_key, resource)
);

CREATE TABLE IF NOT EXISTS dashboard_snapshot_attempts (
    attempt_id TEXT PRIMARY KEY,
    identity_key TEXT NOT NULL,
    resource TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    error_code TEXT,
    duration_ms REAL
);

CREATE INDEX IF NOT EXISTS idx_dashboard_snapshot_attempts_latest
ON dashboard_snapshot_attempts(identity_key, resource, attempted_at DESC);

CREATE TABLE IF NOT EXISTS dashboard_identity_hints (
    fingerprint TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Mapping[str, Any]) -> str:
    """Stable hash of the JSON payload. Observation times are never included."""
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normal_endpoint(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if text.endswith("/v2"):
        text = text[:-3]
    return text.lower()


def environment_fingerprint(settings: Any) -> str:
    """Partition cache and in-flight reads without persisting credentials.

    Version 2 deliberately cannot hydrate legacy, credential-agnostic hints.
    Rotating either credential yields a cold cache until the account is observed.
    """
    credential_digest = sha256(_canonical_json({
        "key": str(getattr(settings, "alpaca_api_key", "") or ""),
        "secret": str(getattr(settings, "alpaca_secret_key", "") or ""),
    }).encode("utf-8")).hexdigest()
    payload = {
        "identity_contract": 2,
        "credential_digest": credential_digest,
        "database": str(Path(settings.database_path).resolve())
        if getattr(settings, "database_path", None) else "",
        "broker": str(getattr(settings, "broker", "") or ""),
        "trading_mode": str(getattr(settings, "trading_mode", "") or ""),
        "alpaca_paper": bool(getattr(settings, "alpaca_paper", False)),
        "endpoint": _normal_endpoint(getattr(settings, "alpaca_endpoint", None)),
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def identity_key(fingerprint: str, account_id: str | None) -> str:
    """Account-scoped identity. ``account_id`` is the broker account, not a secret."""
    payload = {"fingerprint": str(fingerprint or ""), "account_id": str(account_id or "")}
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


@dataclass(frozen=True)
class ResourceSnapshot:
    """One validated snapshot version of one resource.

    ``observed_at`` is the time of the last correct observation of the resource,
    which can be newer than the version that introduced the payload: reading the
    same payload again refreshes freshness without appending a version.
    """

    identity_key: str
    resource: str
    schema_version: int
    content_hash: str
    status: str
    observed_at: str
    captured_at: str
    payload: dict[str, Any]
    observation_status: str = OBSERVATION_STATE_CURRENT

    def age_seconds(self, now: datetime | None = None) -> float | None:
        observed = _parse_iso(self.observed_at)
        if observed is None:
            return None
        reference = now or datetime.now(timezone.utc)
        return max(0.0, (reference - observed).total_seconds())


@dataclass(frozen=True)
class SnapshotAttempt:
    identity_key: str
    resource: str
    attempted_at: str
    outcome: str
    error_code: str | None
    duration_ms: float | None


class SnapshotRepository:
    """SQLite repository for dashboard snapshots.

    The table definition lives in :data:`SNAPSHOT_SCHEMA` and is also applied by
    ``Store.ensure_schema`` so the canonical schema owns the storage.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.store = Store(self.database_path, self.database_path.parent / "dashboard_logs")

    def connect(self) -> sqlite3.Connection:
        return self.store.connect(timeout_seconds=0.25)

    def read_connection(self) -> sqlite3.Connection:
        connection = self.store.read_connection()
        connection.execute("PRAGMA busy_timeout=250")
        return connection

    def ensure_schema(self) -> None:
        with closing(self.connect()) as conn, conn:
            conn.executescript(SNAPSHOT_SCHEMA)

    # -- identity hints -------------------------------------------------
    def account_hint(self, fingerprint: str) -> str | None:
        with closing(self.read_connection()) as conn, conn:
            row = conn.execute(
                "SELECT account_id FROM dashboard_identity_hints WHERE fingerprint = ?",
                (str(fingerprint),),
            ).fetchone()
        if row is None:
            return None
        value = str(row["account_id"] or "").strip()
        return value or None

    def record_account_hint(self, fingerprint: str, account_id: str) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO dashboard_identity_hints (fingerprint, account_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    account_id = excluded.account_id,
                    updated_at = excluded.updated_at
                """,
                (str(fingerprint), str(account_id), utc_now_iso()),
            )

    # -- writes ---------------------------------------------------------
    def save_many(
        self,
        identity_key: str,
        entries: Iterable[tuple[str, Mapping[str, Any], str]],
        *,
        status: str = STATUS_OK,
        captured_at: str | None = None,
    ) -> list[ResourceSnapshot]:
        """Atomically append one version per ``(resource, payload)`` and record the observation.

        Preparation (validation, hashing, serialisation) happens before the
        transaction. Any invalid entry aborts the whole batch with no writes.
        Repeating an identical payload does not append a version, but it does
        refresh ``dashboard_snapshot_state`` so the age of the resource reflects
        the latest correct read.
        """
        captured = captured_at or utc_now_iso()
        prepared: list[tuple[str, str, int, str, str, str, str, str, dict[str, Any]]] = []
        for resource, payload, observed_at in entries:
            if resource not in RESOURCES:
                raise ValueError(f"Recurso de snapshot no valido: {resource!r}")
            if not isinstance(payload, Mapping):
                raise TypeError(f"Payload de snapshot no es un objeto JSON: {resource!r}")
            if _parse_iso(observed_at) is None:
                raise ValueError(f"observed_at no es ISO-8601 utilizable: {observed_at!r}")
            body = dict(payload)
            prepared.append(
                (
                    str(identity_key),
                    resource,
                    SCHEMA_VERSION,
                    content_hash(body),
                    status,
                    str(observed_at),
                    captured,
                    _canonical_json(body),
                    body,
                )
            )
        if not prepared:
            return []
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO dashboard_snapshots (
                    identity_key, resource, schema_version, content_hash,
                    status, observed_at, captured_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [row[:8] for row in prepared],
            )
            for row in prepared:
                self._record_observation(conn, row)
        return [
            ResourceSnapshot(
                identity_key=row[0],
                resource=row[1],
                schema_version=row[2],
                content_hash=row[3],
                status=row[4],
                observed_at=row[5],
                captured_at=row[6],
                payload=row[8],
            )
            for row in prepared
        ]

    def _record_observation(
        self,
        conn: sqlite3.Connection,
        row: tuple[Any, ...],
    ) -> None:
        """Upsert the last correct observation, never regressing it."""
        identity, resource, schema_version, digest, status, observed_at, captured = row[:7]
        current = conn.execute(
            """
            SELECT observed_at FROM dashboard_snapshot_state
            WHERE identity_key = ? AND resource = ?
            """,
            (identity, resource),
        ).fetchone()
        if current is not None:
            previous = _parse_iso(current["observed_at"])
            incoming = _parse_iso(observed_at)
            if previous is not None and incoming is not None and incoming < previous:
                # An out-of-order read must not roll the reported freshness back.
                return
        conn.execute(
            """
            INSERT INTO dashboard_snapshot_state (
                identity_key, resource, observed_at, captured_at,
                schema_version, status, content_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_key, resource) DO UPDATE SET
                observed_at = excluded.observed_at,
                captured_at = excluded.captured_at,
                schema_version = excluded.schema_version,
                status = excluded.status,
                content_hash = excluded.content_hash
            """,
            (identity, resource, observed_at, captured, schema_version, status, digest),
        )

    def record_attempt(
        self,
        identity_key: str,
        resource: str,
        outcome: str,
        *,
        error_code: str | None = None,
        duration_ms: float | None = None,
        attempted_at: str | None = None,
    ) -> None:
        if resource not in RESOURCES:
            raise ValueError(f"Recurso de snapshot no valido: {resource!r}")
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO dashboard_snapshot_attempts (
                    attempt_id, identity_key, resource, attempted_at,
                    outcome, error_code, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("dsa"),
                    str(identity_key),
                    resource,
                    attempted_at or utc_now_iso(),
                    str(outcome),
                    None if error_code is None else str(error_code)[:200],
                    None if duration_ms is None else float(duration_ms),
                ),
            )

    # -- reads ----------------------------------------------------------
    def _read_version_row(
        self, conn: sqlite3.Connection, identity_key: str, resource: str, content_hash_value: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT identity_key, resource, schema_version, content_hash, status,
                   observed_at, captured_at, payload_json
            FROM dashboard_snapshots
            WHERE identity_key = ? AND resource = ? AND content_hash = ?
            """,
            (str(identity_key), resource, str(content_hash_value)),
        ).fetchone()

    def _read_state(
        self, conn: sqlite3.Connection, identity_key: str, resource: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT identity_key, resource, observed_at, captured_at, schema_version,
                   status, content_hash
            FROM dashboard_snapshot_state
            WHERE identity_key = ? AND resource = ?
            """,
            (str(identity_key), resource),
        ).fetchone()

    @staticmethod
    def _decode_state(row: sqlite3.Row) -> dict[str, Any] | None:
        """Validate the stored observation; a broken one never grants freshness."""
        if _parse_iso(row["observed_at"]) is None:
            return None
        try:
            schema_version = int(row["schema_version"])
        except (TypeError, ValueError):
            return None
        if schema_version != SCHEMA_VERSION:
            return None
        digest = str(row["content_hash"] or "")
        if not digest:
            return None
        return {
            "observed_at": str(row["observed_at"]),
            "captured_at": str(row["captured_at"] or ""),
            "status": str(row["status"] or STATUS_OK),
            "content_hash": digest,
        }

    def latest(self, identity_key: str, resource: str, *, max_versions: int = 50) -> ResourceSnapshot | None:
        """Newest valid payload, carrying the time of the last correct observation.

        When the last observation points at a payload that no longer validates,
        the newest still-valid version is returned with its own timestamps and
        ``observation_status = invalid_payload``: freshness is never invented.
        """
        with closing(self.read_connection()) as conn, conn:
            state_row = self._read_state(conn, identity_key, resource)
            state = None if state_row is None else self._decode_state(state_row)
            if state is not None:
                observed = self._read_version_row(
                    conn, str(identity_key), resource, state["content_hash"]
                )
                snapshot = None if observed is None else self._decode(observed)
                if snapshot is not None:
                    return replace(
                        snapshot,
                        observed_at=state["observed_at"],
                        captured_at=state["captured_at"] or snapshot.captured_at,
                        status=state["status"],
                    )
            rows = conn.execute(
                """
                SELECT identity_key, resource, schema_version, content_hash, status,
                       observed_at, captured_at, payload_json
                FROM dashboard_snapshots
                WHERE identity_key = ? AND resource = ?
                ORDER BY observed_at DESC, captured_at DESC, content_hash DESC
                LIMIT ?
                """,
                (str(identity_key), resource, int(max_versions)),
            ).fetchall()
        for row in rows:
            snapshot = self._decode(row)
            if snapshot is not None:
                return replace(
                    snapshot,
                    observation_status=(
                        OBSERVATION_STATE_INVALID
                        if state_row is not None
                        else OBSERVATION_STATE_ABSENT
                    ),
                )
        return None

    def load_all(self, identity_key: str) -> dict[str, ResourceSnapshot]:
        result: dict[str, ResourceSnapshot] = {}
        for resource in RESOURCES:
            snapshot = self.latest(identity_key, resource)
            if snapshot is not None:
                result[resource] = snapshot
        return result

    def last_attempt(self, identity_key: str, resource: str) -> SnapshotAttempt | None:
        with closing(self.read_connection()) as conn, conn:
            row = conn.execute(
                """
                SELECT identity_key, resource, attempted_at, outcome, error_code, duration_ms
                FROM dashboard_snapshot_attempts
                WHERE identity_key = ? AND resource = ?
                ORDER BY attempted_at DESC, attempt_id DESC
                LIMIT 1
                """,
                (str(identity_key), resource),
            ).fetchone()
        if row is None:
            return None
        return SnapshotAttempt(
            identity_key=str(row["identity_key"]),
            resource=str(row["resource"]),
            attempted_at=str(row["attempted_at"]),
            outcome=str(row["outcome"]),
            error_code=None if row["error_code"] is None else str(row["error_code"]),
            duration_ms=None if row["duration_ms"] is None else float(row["duration_ms"]),
        )

    # -- validation -----------------------------------------------------
    def _decode(self, row: sqlite3.Row) -> ResourceSnapshot | None:
        try:
            schema_version = int(row["schema_version"])
        except (TypeError, ValueError):
            return None
        if schema_version != SCHEMA_VERSION:
            return None
        if _parse_iso(row["observed_at"]) is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        stored_hash = str(row["content_hash"] or "")
        if not stored_hash or content_hash(payload) != stored_hash:
            return None
        if str(row["resource"]) not in RESOURCES:
            return None
        return ResourceSnapshot(
            identity_key=str(row["identity_key"]),
            resource=str(row["resource"]),
            schema_version=schema_version,
            content_hash=stored_hash,
            status=str(row["status"] or STATUS_OK),
            observed_at=str(row["observed_at"]),
            captured_at=str(row["captured_at"] or ""),
            payload=payload,
        )
