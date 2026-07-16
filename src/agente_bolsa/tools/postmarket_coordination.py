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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..storage import Store

SCHEMA_VERSION = "p-l45b1.postmarket-run.v1"
ACTIVE_KEY = "post_market_coordination:active"
RECONCILIATION_KEY = "post_market_coordination:reconciliation"
SESSION_KEY_PREFIX = "post_market_coordination:session:"


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
        return f"pid:{self.owner_pid}"

    def _event(self, *, run_id: str, session_date: str, trigger: str, stage: str, status: str, reason: str | None = None, started_at: str | None = None, finished_at: str | None = None, error: str | None = None, owner_pid: int | None = None, owner_token: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_date": session_date,
            "run_id": run_id,
            "trigger": trigger,
            "owner_pid": owner_pid if owner_pid is not None else self.owner_pid,
            "owner_token": owner_token or self.owner_token,
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
        effective = False
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (ACTIVE_KEY,)).fetchone()
            session_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (session_key,)).fetchone()
            last_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", ("post_market_review_last_session",)).fetchone()
            active = json.loads(active_row[0]) if active_row else None
            session_state = json.loads(session_row[0]) if session_row else None
            last_session = json.loads(last_row[0]) if last_row else None
            if last_session == session_date or (isinstance(session_state, dict) and session_state.get("status") == "completed"):
                reason = "session_already_completed"
            elif isinstance(active, dict) and active.get("status") == "active":
                active_pid = int(active.get("owner_pid") or 0)
                if _pid_alive(active_pid):
                    reason = "postmarket_already_running"
                else:
                    # Lease muerto: se recupera de forma determinista y se
                    # deja constancia del propietario sustituido.
                    reason = "dead_owner_recovered"
                    recovered_run_id = str(active.get("run_id") or "") or None
                    recovered_started_at = str(active.get("started_at") or "") or None
                    effective = True
            else:
                effective = True
            if effective:
                state = {
                    "status": "active",
                    "session_date": session_date,
                    "run_id": run_id,
                    "trigger": trigger,
                    "owner_pid": pid,
                    "owner_token": token,
                    "stage": "coordination",
                    "started_at": started,
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
        if recovered_run_id:
            recovered = self._event(
                run_id=recovered_run_id,
                session_date=session_date,
                trigger=str(active.get("trigger") or "scheduled"),
                stage="terminal",
                status="failed",
                reason="owner_dead_recovered",
                error="owner_pid_not_alive",
                started_at=recovered_started_at,
                finished_at=started,
                owner_pid=int(active.get("owner_pid") or 0),
                owner_token=str(active.get("owner_token") or ""),
            )
            self._persist_event(recovered, event_id=f"pmr:{recovered_run_id}:terminal:failed")
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
                    {
                        "status": "active",
                        "session_date": lease.session_date,
                        "run_id": lease.run_id,
                        "trigger": lease.trigger,
                        "owner_pid": lease.owner_pid,
                        "owner_token": lease.owner_token,
                        "stage": stage,
                        "updated_at": now,
                    },
                )
            except Exception:
                pass

    def terminal(self, lease: CoordinationLease, status: str, *, reason: str | None = None, error: str | None = None) -> None:
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
                state = {
                    "status": status,
                    "session_date": lease.session_date,
                    "run_id": lease.run_id,
                    "trigger": lease.trigger,
                    "owner_pid": lease.owner_pid,
                    "owner_token": lease.owner_token,
                    "finished_at": finished,
                    "reason": _reason(reason) if reason else None,
                }
                encoded = json.dumps(state, ensure_ascii=True, sort_keys=True)
                conn.execute(
                    "UPDATE runtime_state SET value_json = ?, updated_at = ? WHERE key = ?",
                    (encoded, finished, f"{SESSION_KEY_PREFIX}{lease.session_date}"),
                )
                conn.execute(
                    "DELETE FROM runtime_state WHERE key = ? AND value_json LIKE ?",
                    (ACTIVE_KEY, f'%"run_id": "{lease.run_id}"%'),
                )
        except Exception:
            pass

    def acquire_reconciliation(self, *, run_id: str, session_date: str, trigger: str = "scheduled") -> CoordinationLease:
        started = _iso()
        self._run_starts[run_id] = started
        pid = self.owner_pid
        token = self.owner_token
        reason: str | None = None
        recovered_run_id: str | None = None
        recovered_owner: dict[str, Any] | None = None
        effective = False
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pmr_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (ACTIVE_KEY,)).fetchone()
            recon_row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (RECONCILIATION_KEY,)).fetchone()
            pmr = json.loads(pmr_row[0]) if pmr_row else None
            recon = json.loads(recon_row[0]) if recon_row else None
            if isinstance(pmr, dict) and pmr.get("status") == "active":
                reason = "postmarket_already_running"
            elif isinstance(recon, dict) and recon.get("status") == "active":
                recon_pid = int(recon.get("owner_pid") or 0)
                if _pid_alive(recon_pid):
                    reason = "reconciliation_already_running"
                else:
                    reason = "dead_reconciliation_recovered"
                    recovered_run_id = str(recon.get("run_id") or "") or None
                    recovered_owner = recon
                    effective = True
            else:
                effective = True
            if effective:
                state = {
                    "status": "active",
                    "session_date": session_date,
                    "run_id": run_id,
                    "trigger": _reason(trigger),
                    "owner_pid": pid,
                    "owner_token": token,
                    "stage": "reconciliation",
                    "started_at": started,
                }
                encoded = json.dumps(state, ensure_ascii=True, sort_keys=True)
                conn.execute(
                    "INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (RECONCILIATION_KEY, encoded, started),
                )
        if recovered_run_id and recovered_owner:
            recovered = self._event(
                run_id=recovered_run_id,
                session_date=session_date,
                trigger=str(recovered_owner.get("trigger") or "scheduled"),
                stage="terminal",
                status="failed",
                reason="owner_dead_recovered",
                error="owner_pid_not_alive",
                started_at=str(recovered_owner.get("started_at") or "") or None,
                finished_at=started,
                owner_pid=int(recovered_owner.get("owner_pid") or 0),
                owner_token=str(recovered_owner.get("owner_token") or ""),
            )
            self._persist_event(recovered, event_id=f"recon:{recovered_run_id}:terminal:failed")
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

    def finish_reconciliation(self, lease: CoordinationLease, status: str, *, reason: str | None = None, error: str | None = None) -> None:
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
        try:
            with self.store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM runtime_state WHERE key = ?", (RECONCILIATION_KEY,))
        except Exception:
            pass
