"""Coordinación durable y fail-open del postmarket.

La coordinación no introduce tablas nuevas: usa ``runtime_state`` como vista
de lease y ``agent_events`` como historial append-only del intento.  La
transacción que adquiere o libera un lease es deliberadamente corta; nunca se
mantiene abierta durante el trabajo de aprendizaje.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..storage import Store

SCHEMA_VERSION = "p-l45b1.postmarket-run.v1"
LEASE_SCHEMA_VERSION = "p-l47b1.lease.v1"
ACTIVE_KEY = "post_market_coordination:active"
RECONCILIATION_KEY = "post_market_coordination:reconciliation"
SESSION_KEY_PREFIX = "post_market_coordination:session:"
LAST_SESSION_KEY = "post_market_review_last_session"
_PROCESS_OWNER_TOKEN = uuid.uuid4().hex


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:  # pragma: no cover - platform fallback.
            return False
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def _reason(value: str | None) -> str:
    normalized = "_".join(str(value or "unknown").strip().lower().split())
    return normalized[:120] or "unknown"


def _owner_is_live(owner: dict[str, Any] | None, *, current_pid: int, current_token: str) -> bool:
    """Comprueba vida y evita aceptar un PID reutilizado con otro token."""

    if not isinstance(owner, dict):
        return False
    try:
        owner_pid = int(owner.get("owner_pid") or 0)
    except (TypeError, ValueError):
        return False
    if not _pid_alive(owner_pid):
        return False
    owner_token = str(owner.get("owner_process_token") or owner.get("owner_token") or "").strip()
    # Los estados legacy pueden carecer de token: un PID vivo no se roba. Si el
    # PID coincide pero el token no, el proceso que lo reclama es distinto.
    return not (owner_pid == current_pid and owner_token and owner_token != current_token)


def _terminal_status_for_run(conn: Any, run_id: str) -> str | None:
    """Return a durable terminal status for ``run_id`` when one exists.

    Runtime state is only a mutable view.  A terminal event is authoritative
    when an old process left an ``active`` view behind, including the case
    where the terminal event was written just before a process was killed.
    """

    if not run_id:
        return None
    rows = conn.execute(
        "SELECT event_id, payload_json FROM agent_events "
        "WHERE event_id LIKE ? ORDER BY created_at DESC",
        (f"%:{run_id}:terminal:%",),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] if hasattr(row, "keys") else row[1])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status in {"completed", "failed", "skipped"}:
            return status
    return None


def _lease_payload(
    *,
    status: str,
    session_date: str,
    run_id: str,
    trigger: str,
    owner_pid: int,
    owner_token: str,
    stage: str,
    started_at: str | None = None,
    updated_at: str | None = None,
    finished_at: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lease_schema_version": LEASE_SCHEMA_VERSION,
        "status": status,
        "session_date": session_date,
        "run_id": run_id,
        "trigger": trigger,
        "owner_pid": owner_pid,
        "owner_process_token": owner_token,
        # Keep the old key readable for existing consumers and fixtures.
        "owner_token": owner_token,
        "stage": stage,
    }
    if started_at is not None:
        payload["started_at"] = started_at
    if updated_at is not None:
        payload["updated_at"] = updated_at
    if finished_at is not None:
        payload["finished_at"] = finished_at
    if reason is not None:
        payload["reason"] = _reason(reason)
    return payload


@dataclass(frozen=True)
class CoordinationLease:
    run_id: str
    session_date: str
    trigger: str
    owner_pid: int
    owner_token: str
    effective: bool
    status: str
    reason: str | None = None


class PostmarketCoordinator:
    """Coordina PMR y reconciliación sin bloquear durante el pipeline."""

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self._stage_starts: dict[tuple[str, str], str] = {}
        self._run_starts: dict[str, str] = {}

    @property
    def owner_pid(self) -> int:
        return os.getpid()

    @property
    def owner_token(self) -> str:
        return f"pid:{self.owner_pid}:process:{_PROCESS_OWNER_TOKEN}"

    def _event(self, *, run_id: str, session_date: str, trigger: str, stage: str, status: str, reason: str | None = None, started_at: str | None = None, finished_at: str | None = None, error: str | None = None, owner_pid: int | None = None, owner_token: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_date": session_date,
            "run_id": run_id,
            "trigger": trigger,
            "owner_pid": owner_pid if owner_pid is not None else self.owner_pid,
            "owner_token": owner_token or self.owner_token,
            "owner_process_token": owner_token or self.owner_token,
            "stage": stage,
            "status": status,
            "reason": _reason(reason) if reason else None,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration": None,
            "error": str(error)[:500] if error else None,
        }
        if started_at and finished_at:
            try:
                payload["duration"] = round(
                    (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds(),
                    3,
                )
            except (TypeError, ValueError):
                payload["duration"] = None
        payload["content_hash"] = _stable_hash({k: v for k, v in payload.items() if k != "content_hash"})
        return payload

    def _persist_event(self, payload: dict[str, Any], *, event_id: str) -> None:
        try:
            self.store.record_append_only_event(
                event_id=event_id,
                event_type="postmarket_run",
                cycle_id=str(payload.get("run_id") or ""),
                payload=payload,
            )
        except Exception:
            # La telemetría nunca debe ocultar el resultado del pipeline.
            return

    def _persist_marker(
        self,
        event_type: str,
        *,
        event_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist a small coordination marker without affecting the lease."""

        marker = {
            "schema_version": LEASE_SCHEMA_VERSION,
            "event_type": event_type,
            **payload,
        }
        marker["content_hash"] = _stable_hash({k: v for k, v in marker.items() if k != "content_hash"})
        try:
            self.store.record_append_only_event(
                event_id=event_id,
                event_type=event_type,
                cycle_id=str(payload.get("run_id") or payload.get("owner_pid") or ""),
                payload=marker,
            )
        except Exception:
            return

    @staticmethod
    def _same_owner(state: dict[str, Any] | None, lease: CoordinationLease) -> bool:
        if not isinstance(state, dict):
            return False
        try:
            pid = int(state.get("owner_pid") or 0)
        except (TypeError, ValueError):
            return False
        token = str(state.get("owner_process_token") or state.get("owner_token") or "").strip()
        return pid == lease.owner_pid and token == lease.owner_token and str(state.get("run_id") or "") == lease.run_id

    @staticmethod
    def _same_runtime_identity(
        state: dict[str, Any] | None,
        *,
        run_id: str,
        owner_pid: int,
        owner_token: str,
    ) -> bool:
        if not isinstance(state, dict):
            return False
        try:
            pid = int(state.get("owner_pid") or 0)
        except (TypeError, ValueError):
            return False
        token = str(state.get("owner_process_token") or state.get("owner_token") or "").strip()
        return pid == owner_pid and token == owner_token and str(state.get("run_id") or "") == run_id

    @classmethod
    def _release_recovered_session_view(cls, conn: Any, owner: dict[str, Any]) -> None:
        """Remove only the old session view owned by the recovered run."""

        session_date = str(owner.get("session_date") or "").strip()
        run_id = str(owner.get("run_id") or "").strip()
        owner_token = str(owner.get("owner_process_token") or owner.get("owner_token") or "").strip()
        if not session_date or not run_id or not owner_token:
            return
        try:
            owner_pid = int(owner.get("owner_pid") or 0)
        except (TypeError, ValueError):
            return
        key = f"{SESSION_KEY_PREFIX}{session_date}"
        row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return
        raw = row["value_json"] if hasattr(row, "keys") else row[0]
        try:
            state = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if cls._same_runtime_identity(
            state,
            run_id=run_id,
            owner_pid=owner_pid,
            owner_token=owner_token,
        ):
            conn.execute(
                "DELETE FROM runtime_state WHERE key = ? AND value_json = ?",
                (key, raw),
            )

    def _release_runtime_lease(
        self,
        lease: CoordinationLease,
        *,
        finished: str,
        status: str,
        reason: str | None,
    ) -> tuple[bool, str]:
        """Release only keys owned by this exact PID/token/run identity."""

        released_keys: list[str] = []
        try:
            with self.store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for key in (ACTIVE_KEY, RECONCILIATION_KEY):
                    row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (key,)).fetchone()
                    if not row:
                        continue
                    try:
                        state = json.loads(row["value_json"] if hasattr(row, "keys") else row[0])
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if self._same_owner(state, lease):
                        conn.execute("DELETE FROM runtime_state WHERE key = ?", (key,))
                        released_keys.append(key)
        except Exception as exc:  # noqa: BLE001 - release failure must be visible.
            self._persist_marker(
                "lease_release_failed",
                event_id=f"lease_release_failed:{lease.run_id}:{status}",
                payload={
                    "run_id": lease.run_id,
                    "session_date": lease.session_date,
                    "owner_pid": lease.owner_pid,
                    "owner_process_token": lease.owner_token,
                    "status": status,
                    "reason": _reason(reason) if reason else None,
                    "error": str(exc)[:500],
                },
            )
            return False, str(exc)
        self._persist_marker(
            "lease_released",
            event_id=f"lease_released:{lease.run_id}:{status}",
            payload={
                "run_id": lease.run_id,
                "session_date": lease.session_date,
                "owner_pid": lease.owner_pid,
                "owner_process_token": lease.owner_token,
                "status": status,
                "reason": _reason(reason) if reason else None,
                "released_keys": released_keys,
                "finished_at": finished,
            },
        )
        return True, ""

    def _runtime(self, key: str) -> dict[str, Any] | None:
        value = self.store.get_runtime_value(key)
        return value if isinstance(value, dict) else None

    def acquire(self, *, session_date: str, run_id: str, trigger: str) -> CoordinationLease:
        started = _iso()
        self._run_starts[run_id] = started
        trigger = _reason(trigger)
        pid = self.owner_pid
        token = self.owner_token
        session_key = f"{SESSION_KEY_PREFIX}{session_date}"
        status = "started"
        reason: str | None = None
        recovered_run_id: str | None = None
        recovered_started_at: str | None = None
        recovered_owner: dict[str, Any] | None = None
        recovered_session_date: str | None = None
        recovery_event_type: str | None = None
        recovered_terminal_status: str | None = None
        effective = False
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (ACTIVE_KEY,)).fetchone()
            session_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (session_key,)).fetchone()
            last_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", ("post_market_review_last_session",)).fetchone()
            active = json.loads(active_row[0]) if active_row else None
            session_state = json.loads(session_row[0]) if session_row else None
            last_session = json.loads(last_row[0]) if last_row else None
            if isinstance(last_session, str) and last_session >= session_date:
                reason = "session_already_completed" if last_session == session_date else "session_behind_latest"
            elif isinstance(session_state, dict) and session_state.get("status") == "completed":
                reason = "session_already_completed"
            elif isinstance(active, dict) and active.get("status") == "active":
                try:
                    active_pid = int(active.get("owner_pid") or 0)
                except (TypeError, ValueError):
                    active_pid = 0
                active_token = str(active.get("owner_process_token") or active.get("owner_token") or "").strip()
                active_run_id = str(active.get("run_id") or "")
                terminal_status = _terminal_status_for_run(conn, active_run_id)
                if _owner_is_live(active, current_pid=pid, current_token=token):
                    # A live owner may be between its terminal event and the
                    # final runtime-state release.  Do not steal that lease.
                    reason = "postmarket_already_running"
                elif terminal_status in {"completed", "failed", "skipped"}:
                    reason = "terminal_lease_recovered"
                    recovered_run_id = active_run_id or None
                    recovered_started_at = str(active.get("started_at") or "") or None
                    recovered_owner = dict(active)
                    recovered_session_date = str(active.get("session_date") or "") or None
                    recovery_event_type = "terminal_lease_recovered"
                    recovered_terminal_status = terminal_status
                    effective = True
                else:
                    # Lease muerto: se recupera de forma determinista y se
                    # deja constancia del propietario sustituido.
                    reason = "owner_token_mismatch_recovered" if active_pid == pid and active_token and active_token != token else "dead_owner_recovered"
                    recovered_run_id = str(active.get("run_id") or "") or None
                    recovered_started_at = str(active.get("started_at") or "") or None
                    recovered_owner = dict(active)
                    recovered_session_date = str(active.get("session_date") or "") or None
                    recovery_event_type = "stale_lease_recovered"
                    effective = True
            else:
                effective = True
            if effective:
                if recovered_owner:
                    self._release_recovered_session_view(conn, recovered_owner)
                state = {
                    **_lease_payload(
                        status="active",
                        session_date=session_date,
                        run_id=run_id,
                        trigger=trigger,
                        owner_pid=pid,
                        owner_token=token,
                        stage="coordination",
                        started_at=started,
                    ),
                }
                encoded = json.dumps(state, ensure_ascii=True, sort_keys=True)
                conn.execute(
                    "INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (ACTIVE_KEY, encoded, started),
                )
                conn.execute(
                    "INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (session_key, encoded, started),
                )
                status = "started"
            else:
                status = "skipped"
        if recovered_run_id and recovered_owner:
            recovered_identity_session = recovered_session_date or session_date
            if recovery_event_type != "terminal_lease_recovered":
                recovered = self._event(
                    run_id=recovered_run_id,
                    session_date=recovered_identity_session,
                    trigger=str(recovered_owner.get("trigger") or "scheduled"),
                    stage="terminal",
                    status="failed",
                    reason="owner_dead_recovered",
                    error="owner_pid_not_alive",
                    started_at=recovered_started_at,
                    finished_at=started,
                    owner_pid=int(recovered_owner.get("owner_pid") or 0),
                    owner_token=str(recovered_owner.get("owner_process_token") or recovered_owner.get("owner_token") or ""),
                )
                self._persist_event(recovered, event_id=f"pmr:{recovered_run_id}:terminal:failed")
            # A terminal residual already has its canonical event; only emit a
            # recovery marker.  Never overwrite or conflict with that event.
            self._persist_marker(
                recovery_event_type or "stale_lease_recovered",
                event_id=f"{recovery_event_type or 'stale_lease_recovered'}:{recovered_run_id}:{run_id}",
                payload={
                    "run_id": recovered_run_id,
                    "replacement_run_id": run_id,
                    "session_date": recovered_identity_session,
                    "replacement_session_date": session_date,
                    "owner_pid": int(recovered_owner.get("owner_pid") or 0),
                    "owner_process_token": str(recovered_owner.get("owner_process_token") or recovered_owner.get("owner_token") or ""),
                    "reason": reason,
                    "terminal_status": recovered_terminal_status,
                },
            )
        payload = self._event(
            run_id=run_id,
            session_date=session_date,
            trigger=trigger,
            stage="coordination",
            status=status,
            reason=reason,
            started_at=started,
            finished_at=_iso() if not effective else None,
            owner_pid=pid,
            owner_token=token,
        )
        self._stage_starts[(run_id, "coordination")] = started
        self._persist_event(payload, event_id=f"pmr:{run_id}:coordination:{status}")
        if effective:
            self._persist_marker(
                "lease_acquired",
                event_id=f"lease_acquired:{run_id}",
                payload={
                    "run_id": run_id,
                    "session_date": session_date,
                    "trigger": trigger,
                    "owner_pid": pid,
                    "owner_process_token": token,
                    "reason": reason,
                },
            )
        elif reason == "postmarket_already_running":
            self._persist_marker(
                "ownership_conflict",
                event_id=f"ownership_conflict:{run_id}",
                payload={
                    "run_id": run_id,
                    "session_date": session_date,
                    "owner_pid": pid,
                    "owner_process_token": token,
                    "reason": reason,
                },
            )
        if not effective:
            terminal = self._event(
                run_id=run_id,
                session_date=session_date,
                trigger=trigger,
                stage="terminal",
                status="skipped",
                reason=reason,
                started_at=started,
                finished_at=_iso(),
                owner_pid=pid,
                owner_token=token,
            )
            self._persist_event(terminal, event_id=f"pmr:{run_id}:terminal:skipped")
        return CoordinationLease(run_id, session_date, trigger, pid, token, effective, status, reason)

    def stage(self, lease: CoordinationLease, stage: str, status: str, *, error: str | None = None) -> None:
        now = _iso()
        if status == "started":
            self._stage_starts[(lease.run_id, stage)] = now
        started_at = self._stage_starts.get((lease.run_id, stage)) if status != "started" else now
        payload = self._event(
            run_id=lease.run_id,
            session_date=lease.session_date,
            trigger=lease.trigger,
            stage=stage,
            status=status,
            error=error,
            owner_pid=lease.owner_pid,
            owner_token=lease.owner_token,
            started_at=started_at,
            finished_at=now if status != "started" else None,
        )
        self._persist_event(payload, event_id=f"pmr:{lease.run_id}:{stage}:{status}")
        if lease.effective:
            try:
                self.store.set_runtime_value(
                    ACTIVE_KEY,
                    _lease_payload(
                        status="active",
                        session_date=lease.session_date,
                        run_id=lease.run_id,
                        trigger=lease.trigger,
                        owner_pid=lease.owner_pid,
                        owner_token=lease.owner_token,
                        stage=stage,
                        updated_at=now,
                    ),
                )
            except Exception:
                pass

    def terminal(self, lease: CoordinationLease, status: str, *, reason: str | None = None, error: str | None = None) -> None:
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError(f"Unsupported coordination terminal status: {status}")
        finished = _iso()
        payload = self._event(
            run_id=lease.run_id,
            session_date=lease.session_date,
            trigger=lease.trigger,
            stage="terminal",
            status=status,
            reason=reason,
            error=error,
            started_at=self._run_starts.get(lease.run_id),
            finished_at=finished,
            owner_pid=lease.owner_pid,
            owner_token=lease.owner_token,
        )
        self._persist_event(payload, event_id=f"pmr:{lease.run_id}:terminal:{status}")
        if not lease.effective:
            return
        try:
            with self.store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = _lease_payload(
                    status=status,
                    session_date=lease.session_date,
                    run_id=lease.run_id,
                    trigger=lease.trigger,
                    owner_pid=lease.owner_pid,
                    owner_token=lease.owner_token,
                    stage="terminal",
                    finished_at=finished,
                    reason=reason,
                )
                encoded = json.dumps(state, ensure_ascii=True, sort_keys=True)
                key = f"{SESSION_KEY_PREFIX}{lease.session_date}"
                row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (key,)).fetchone()
                if row:
                    raw = row["value_json"] if hasattr(row, "keys") else row[0]
                    try:
                        current = json.loads(raw)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        current = None
                    if self._same_owner(current, lease):
                        conn.execute(
                            "UPDATE runtime_state SET value_json = ?, updated_at = ? "
                            "WHERE key = ? AND value_json = ?",
                            (encoded, finished, key, raw),
                        )
        except Exception as exc:  # noqa: BLE001 - release failure must be visible.
            self._persist_marker(
                "lease_release_failed",
                event_id=f"lease_release_failed:{lease.run_id}:{status}",
                payload={
                    "run_id": lease.run_id,
                    "session_date": lease.session_date,
                    "owner_pid": lease.owner_pid,
                    "owner_process_token": lease.owner_token,
                    "status": status,
                    "reason": _reason(reason) if reason else None,
                    "error": str(exc)[:500],
                },
            )
            return
        self._release_runtime_lease(lease, finished=finished, status=status, reason=reason)

    def acquire_reconciliation(self, *, run_id: str, session_date: str, trigger: str = "scheduled") -> CoordinationLease:
        started = _iso()
        self._run_starts[run_id] = started
        pid = self.owner_pid
        token = self.owner_token
        reason: str | None = None
        recovered_run_id: str | None = None
        recovered_owner: dict[str, Any] | None = None
        recovered_session_date: str | None = None
        recovery_event_type: str | None = None
        recovered_terminal_status: str | None = None
        effective = False
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pmr_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (ACTIVE_KEY,)).fetchone()
            recon_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (RECONCILIATION_KEY,)).fetchone()
            pmr = json.loads(pmr_row[0]) if pmr_row else None
            recon = json.loads(recon_row[0]) if recon_row else None
            if isinstance(pmr, dict) and pmr.get("status") == "active":
                pmr_run_id = str(pmr.get("run_id") or "")
                pmr_terminal = _terminal_status_for_run(conn, pmr_run_id)
                if _owner_is_live(pmr, current_pid=pid, current_token=token):
                    reason = "postmarket_already_running"
                elif pmr_terminal in {"completed", "failed", "skipped"}:
                    conn.execute("DELETE FROM runtime_state WHERE key = ? AND value_json = ?", (ACTIVE_KEY, pmr_row[0]))
                    recovered_run_id = pmr_run_id or None
                    recovered_owner = dict(pmr)
                    recovered_session_date = str(pmr.get("session_date") or "") or None
                    recovery_event_type = "terminal_lease_recovered"
                    recovered_terminal_status = pmr_terminal
                    effective = True
                else:
                    reason = "postmarket_already_running"
            elif isinstance(recon, dict) and recon.get("status") == "active":
                try:
                    recon_pid = int(recon.get("owner_pid") or 0)
                except (TypeError, ValueError):
                    recon_pid = 0
                recon_token = str(recon.get("owner_process_token") or recon.get("owner_token") or "").strip()
                recon_run_id = str(recon.get("run_id") or "")
                recon_terminal = _terminal_status_for_run(conn, recon_run_id)
                if _owner_is_live(recon, current_pid=pid, current_token=token):
                    reason = "reconciliation_already_running"
                elif recon_terminal in {"completed", "failed", "skipped"}:
                    conn.execute("DELETE FROM runtime_state WHERE key = ? AND value_json = ?", (RECONCILIATION_KEY, recon_row[0]))
                    recovered_run_id = recon_run_id or None
                    recovered_owner = dict(recon)
                    recovered_session_date = str(recon.get("session_date") or "") or None
                    recovery_event_type = "terminal_lease_recovered"
                    recovered_terminal_status = recon_terminal
                    effective = True
                else:
                    reason = "owner_token_mismatch_recovered" if recon_pid == pid and recon_token and recon_token != token else "dead_reconciliation_recovered"
                    recovered_run_id = str(recon.get("run_id") or "") or None
                    recovered_owner = recon
                    recovered_session_date = str(recon.get("session_date") or "") or None
                    recovery_event_type = "stale_lease_recovered"
                    effective = True
            else:
                effective = True
            if effective:
                if recovered_owner:
                    self._release_recovered_session_view(conn, recovered_owner)
                state = {
                    **_lease_payload(
                        status="active",
                        session_date=session_date,
                        run_id=run_id,
                        trigger=_reason(trigger),
                        owner_pid=pid,
                        owner_token=token,
                        stage="reconciliation",
                        started_at=started,
                    ),
                }
                encoded = json.dumps(state, ensure_ascii=True, sort_keys=True)
                conn.execute(
                    "INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (RECONCILIATION_KEY, encoded, started),
                )
        if recovered_run_id and recovered_owner:
            recovered_identity_session = recovered_session_date or session_date
            if recovery_event_type != "terminal_lease_recovered":
                recovered = self._event(
                    run_id=recovered_run_id,
                    session_date=recovered_identity_session,
                    trigger=str(recovered_owner.get("trigger") or "scheduled"),
                    stage="terminal",
                    status="failed",
                    reason="owner_dead_recovered",
                    error="owner_pid_not_alive",
                    started_at=str(recovered_owner.get("started_at") or "") or None,
                    finished_at=started,
                    owner_pid=int(recovered_owner.get("owner_pid") or 0),
                    owner_token=str(recovered_owner.get("owner_process_token") or recovered_owner.get("owner_token") or ""),
                )
                self._persist_event(recovered, event_id=f"recon:{recovered_run_id}:terminal:failed")
            self._persist_marker(
                recovery_event_type or "stale_lease_recovered",
                event_id=f"{recovery_event_type or 'stale_lease_recovered'}:{recovered_run_id}:{run_id}",
                payload={
                    "run_id": recovered_run_id,
                    "replacement_run_id": run_id,
                    "session_date": recovered_identity_session,
                    "replacement_session_date": session_date,
                    "owner_pid": int(recovered_owner.get("owner_pid") or 0),
                    "owner_process_token": str(recovered_owner.get("owner_process_token") or recovered_owner.get("owner_token") or ""),
                    "reason": reason or recovery_event_type,
                    "terminal_status": recovered_terminal_status,
                },
            )
        status = "started" if effective else "skipped"
        payload = self._event(
            run_id=run_id,
            session_date=session_date,
            trigger=_reason(trigger),
            stage="coordination",
            status=status,
            reason=reason,
            started_at=started,
            finished_at=_iso() if not effective else None,
            owner_pid=pid,
            owner_token=token,
        )
        self._stage_starts[(run_id, "coordination")] = started
        self._persist_event(payload, event_id=f"recon:{run_id}:coordination:{status}")
        if effective:
            self._persist_marker(
                "lease_acquired",
                event_id=f"lease_acquired:reconciliation:{run_id}",
                payload={
                    "run_id": run_id,
                    "session_date": session_date,
                    "trigger": _reason(trigger),
                    "owner_pid": pid,
                    "owner_process_token": token,
                    "reason": reason,
                },
            )
        elif reason in {"postmarket_already_running", "reconciliation_already_running"}:
            self._persist_marker(
                "ownership_conflict",
                event_id=f"ownership_conflict:reconciliation:{run_id}",
                payload={
                    "run_id": run_id,
                    "session_date": session_date,
                    "owner_pid": pid,
                    "owner_process_token": token,
                    "reason": reason,
                },
            )
        if not effective:
            terminal = self._event(
                run_id=run_id,
                session_date=session_date,
                trigger=_reason(trigger),
                stage="terminal",
                status="skipped",
                reason=reason,
                started_at=started,
                finished_at=_iso(),
                owner_pid=pid,
                owner_token=token,
            )
            self._persist_event(terminal, event_id=f"recon:{run_id}:terminal:skipped")
        return CoordinationLease(run_id, session_date, _reason(trigger), pid, token, effective, status, reason)

    def advance_last_session(self, session_date: str) -> bool:
        """Avanza el marcador únicamente hacia una sesión más reciente."""

        now = _iso()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value_json FROM runtime_state WHERE key = ?",
                (LAST_SESSION_KEY,),
            ).fetchone()
            current = json.loads(row[0]) if row else None
            if isinstance(current, str) and current >= session_date:
                return False
            conn.execute(
                "INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (LAST_SESSION_KEY, json.dumps(session_date), now),
            )
        return True

    def finish_reconciliation(self, lease: CoordinationLease, status: str, *, reason: str | None = None, error: str | None = None) -> None:
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError(f"Unsupported reconciliation terminal status: {status}")
        if not lease.effective:
            return
        finished = _iso()
        payload = self._event(
            run_id=lease.run_id,
            session_date=lease.session_date,
            trigger=lease.trigger,
            stage="terminal",
            status=status,
            reason=reason,
            error=error,
            started_at=self._run_starts.get(lease.run_id),
            finished_at=finished,
            owner_pid=lease.owner_pid,
            owner_token=lease.owner_token,
        )
        self._persist_event(payload, event_id=f"recon:{lease.run_id}:terminal:{status}")
        self._release_runtime_lease(lease, finished=finished, status=status, reason=reason)
