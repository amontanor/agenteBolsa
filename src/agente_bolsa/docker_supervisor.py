"""Linux supervisor for the auxiliary Docker services.

The Windows deployment uses one PowerShell supervisor per auxiliary job. This
module keeps the same daily catch-up and idempotence rules without requiring
PowerShell inside the ARM64 image.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:  # pragma: no cover - available on the Linux deployment image.
    import fcntl
except ImportError:  # pragma: no cover - keeps import-only tooling usable on Windows.
    fcntl = None  # type: ignore[assignment]


SERVICE_NAMES = (
    "telegram_radar",
    "overlay_shadow",
    "ci_digest",
    "codegen_nightly",
    "core_sleeve",
)
AUXILIARY_SERVICE = "auxiliary"
AUXILIARY_SCHEDULES = {
    "core_sleeve": "22:15",
    "overlay_shadow": "22:30",
    "telegram_radar": "23:00",
    "ci_digest": "08:30",
    "codegen_nightly": "03:00",
}
DEFAULT_TIMEZONE = "Europe/Madrid"
HEARTBEAT_MAX_AGE_SECONDS = 3600


class _AlreadyRunning(RuntimeError):
    pass


class _ServiceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> _ServiceLock:
        if fcntl is None:
            raise RuntimeError("El supervisor Docker requiere fcntl en Linux.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            self.handle = None
            raise _AlreadyRunning(str(self.path)) from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(json.dumps({"pid": os.getpid(), "started_at": _utc_now()}))
        self.handle.flush()
        return self

    def __exit__(self, *_args: Any) -> None:
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def _utc_now() -> str:
    return datetime.now().astimezone().astimezone(ZoneInfo("UTC")).isoformat()


def _timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("LOCAL_TIMEZONE", DEFAULT_TIMEZONE))


def _data_root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def _parse_run_at(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("run_at debe usar HH:mm.")
    hour, minute = (int(part) for part in parts)
    if hour not in range(24) or minute not in range(60):
        raise ValueError("run_at debe usar una hora valida en formato HH:mm.")
    return time(hour=hour, minute=minute)


def _local_at(day: date, run_at: time, timezone: ZoneInfo) -> datetime:
    return datetime.combine(day, run_at, tzinfo=timezone)


def next_run(now: datetime, run_at: str) -> datetime:
    """Return the next local occurrence, preserving Europe/Madrid wall time."""

    timezone = now.tzinfo if isinstance(now.tzinfo, ZoneInfo) else _timezone()
    local_now = now.astimezone(timezone)
    target_time = _parse_run_at(run_at)
    target = _local_at(local_now.date(), target_time, timezone)
    if local_now >= target:
        target = _local_at(local_now.date() + timedelta(days=1), target_time, timezone)
    return target


def _today_target(now: datetime, run_at: str) -> datetime:
    timezone = now.tzinfo if isinstance(now.tzinfo, ZoneInfo) else _timezone()
    local_now = now.astimezone(timezone)
    return _local_at(local_now.date(), _parse_run_at(run_at), timezone)


def _heartbeat_path(data_root: Path, service: str) -> Path:
    return data_root / "run" / f"{service}.heartbeat.json"


def _state_path(data_root: Path, service: str) -> Path:
    return data_root / "run" / f"{service}.state.json"


def _lock_path(data_root: Path, service: str) -> Path:
    return data_root / "run" / f"{service}.lock"


def _log_path(data_root: Path, service: str) -> Path:
    return data_root / "logs" / f"{service}.supervisor.log"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_heartbeat(data_root: Path, service: str, *, status: str, detail: str = "", next_run_at: str | None = None) -> None:
    payload: dict[str, Any] = {
        "service": service,
        "status": status,
        "updated_at": _utc_now(),
        "pid": os.getpid(),
    }
    if detail:
        payload["detail"] = detail
    if next_run_at:
        payload["next_run_at"] = next_run_at
    _write_json_atomic(_heartbeat_path(data_root, service), payload)


def _log(data_root: Path, service: str, message: str) -> None:
    path = _log_path(data_root, service)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _run_command(
    data_root: Path,
    service: str,
    command: list[str],
    output_path: Path | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    path = _log_path(data_root, service)
    path.parent.mkdir(parents=True, exist_ok=True)
    _log(data_root, service, f"START command={' '.join(command)}")
    if output_path is None:
        with path.open("a", encoding="utf-8") as handle:
            result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output_handle, path.open("a", encoding="utf-8") as log_handle:
                result = subprocess.run(command, stdout=output_handle, stderr=log_handle, text=True, check=False)
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
    _log(data_root, service, f"DONE returncode={result.returncode}")
    if check and result.returncode != 0:
        raise RuntimeError(f"{service} devolvio returncode={result.returncode}")
    return result


def _run_json_command(data_root: Path, service: str, command: list[str]) -> dict[str, Any]:
    path = _log_path(data_root, service)
    path.parent.mkdir(parents=True, exist_ok=True)
    _log(data_root, service, f"START json_command={' '.join(command)}")
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(result.stdout)
        if result.stdout and not result.stdout.endswith("\n"):
            handle.write("\n")
    if result.returncode != 0:
        raise RuntimeError(f"{service} devolvio returncode={result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        start = result.stdout.find("{")
        end = result.stdout.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError(f"{service} no devolvio JSON valido") from None
        payload = json.loads(result.stdout[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError(f"{service} devolvio un JSON no estructurado")
    if payload.get("ok") is False:
        raise RuntimeError(f"{service} declaro ok=false")
    return payload


def _artifact_exists(data_root: Path, service: str, run_date: date) -> bool:
    date_text = run_date.isoformat()
    if service == "telegram_radar":
        return (data_root / "research" / "telegram" / "reports" / f"radar_{date_text}.md").exists()
    if service == "overlay_shadow":
        return (data_root / "research" / "overlay_shadow" / f"overlay_shadow_{date_text}.json").exists()
    if service == "ci_digest":
        return (data_root / "reports" / f"ci_digest_{date_text}.md").exists()
    if service == "codegen_nightly":
        path = data_root / "research" / "codegen_nightly" / "runs.jsonl"
        if not path.exists():
            return False
        return date_text in path.read_text(encoding="utf-8", errors="replace")
    if service == "core_sleeve":
        return (data_root / "research" / "core_sleeve" / f"parity_{date_text}.md").exists()
    raise ValueError(f"Servicio auxiliar desconocido: {service}")


def run_service_once(data_root: Path, service: str, run_date: date | None = None) -> dict[str, Any]:
    if service not in SERVICE_NAMES:
        raise ValueError(f"Servicio auxiliar desconocido: {service}")
    data_root = Path(data_root)
    run_date = run_date or datetime.now(_timezone()).date()
    python = sys.executable
    main = [python, "-m", "agente_bolsa.main"]

    if service == "telegram_radar":
        ingest = _run_json_command(data_root, service, main + ["telegram-radar", "ingest", "--backfill", "1", "--json"])
        report_path = data_root / "research" / "telegram" / "reports" / f"radar_{run_date.isoformat()}.md"
        _run_json_command(
            data_root,
            service,
            main + ["telegram-radar", "report", "--days", "7", "--out", str(report_path), "--json"],
        )
        return {"ok": True, "service": service, "ingest": ingest, "artifact": str(report_path)}

    if service == "overlay_shadow":
        output_dir = data_root / "research" / "overlay_shadow"
        result = _run_json_command(
            data_root,
            service,
            [python, "-m", "agente_bolsa.research.overlay_shadow", "--start", "2020-01-01", "--out-dir", str(output_dir), "--json"],
        )
        return {"ok": True, "service": service, "result": result}

    if service == "ci_digest":
        report_path = data_root / "reports" / f"ci_digest_{run_date.isoformat()}.md"
        result = _run_json_command(
            data_root,
            service,
            [python, "-m", "agente_bolsa.digest_cli", "--days", "1", "--out", str(report_path), "--json"],
        )
        return {"ok": True, "service": service, "result": result, "artifact": str(report_path)}

    if service == "codegen_nightly":
        result = _run_json_command(
            data_root,
            service,
            main + ["continuous-improvement-lab", "codegen-nightly", "--json"],
        )
        return {"ok": True, "service": service, "result": result}

    config_path = data_root / "config" / "core_sleeve.json"
    output_dir = data_root / "research" / "core_sleeve"
    result = _run_json_command(
        data_root,
        service,
        [
            python,
            "-m",
            "agente_bolsa.strategies.core_sleeve",
            "--config",
            str(config_path),
            "--log-dir",
            str(output_dir),
            "--json",
        ],
    )
    parity_path = output_dir / f"parity_{run_date.isoformat()}.md"
    parity_script = Path(__file__).resolve().parents[2] / "scripts" / "core_sleeve_parity_check.py"
    if parity_script.exists():
        _run_command(
            data_root,
            service,
            [python, str(parity_script), "--config", str(config_path)],
            output_path=parity_path,
            check=False,
        )
    if not parity_path.exists():
        parity_path.write_text("Core sleeve parity check completed by Docker supervisor.\n", encoding="utf-8")
    return {"ok": True, "service": service, "result": result, "artifact": str(parity_path)}


def _state_for_today(data_root: Path, service: str, run_date: date) -> dict[str, Any]:
    state = _read_json(_state_path(data_root, service))
    return state if state.get("last_attempt_date") == run_date.isoformat() else {}


def run_all_once(data_root: Path, run_date: date | None = None) -> list[dict[str, Any]]:
    """Run auxiliary jobs in their deterministic, memory-bounded order."""

    run_date = run_date or datetime.now(_timezone()).date()
    return [run_service_once(data_root, service, run_date) for service in AUXILIARY_SCHEDULES]


def _write_state(data_root: Path, service: str, *, run_date: date, status: str, detail: str = "") -> None:
    payload: dict[str, Any] = {
        "service": service,
        "last_attempt_date": run_date.isoformat(),
        "last_status": status,
        "updated_at": _utc_now(),
    }
    if detail:
        payload["detail"] = detail
    _write_json_atomic(_state_path(data_root, service), payload)


def healthcheck(data_root: Path, service: str, *, max_age_seconds: int = HEARTBEAT_MAX_AGE_SECONDS) -> bool:
    if service not in SERVICE_NAMES:
        return False
    payload = _read_json(_heartbeat_path(data_root, service))
    updated_at = payload.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    age = (datetime.now(updated.tzinfo) - updated).total_seconds()
    if age < 0 or age > max_age_seconds:
        return False
    state = _read_json(_state_path(data_root, service))
    today = datetime.now(_timezone()).date().isoformat()
    return not (state.get("last_attempt_date") == today and state.get("last_status") == "failed")


def healthcheck_all(data_root: Path, *, max_age_seconds: int = HEARTBEAT_MAX_AGE_SECONDS) -> bool:
    """Check the single resident auxiliary supervisor and its daily states."""

    payload = _read_json(_heartbeat_path(data_root, AUXILIARY_SERVICE))
    updated_at = payload.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    age = (datetime.now(updated.tzinfo) - updated).total_seconds()
    if age < 0 or age > max_age_seconds:
        return False
    today = datetime.now(_timezone()).date().isoformat()
    for service in SERVICE_NAMES:
        state = _read_json(_state_path(data_root, service))
        if state.get("last_attempt_date") == today and state.get("last_status") == "failed":
            return False
    return True


def run_forever(data_root: Path, service: str, run_at: str) -> int:
    stop_event = threading.Event()

    def stop_handler(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    data_root.mkdir(parents=True, exist_ok=True)

    try:
        with _ServiceLock(_lock_path(data_root, service)):
            _write_heartbeat(data_root, service, status="starting")
            _log(data_root, service, f"START supervisor run_at={run_at}")
            while not stop_event.is_set():
                now = datetime.now(_timezone())
                target = _today_target(now, run_at)
                today = now.date()
                state = _state_for_today(data_root, service, today)
                if now >= target and not state:
                    if _artifact_exists(data_root, service, today):
                        _write_state(data_root, service, run_date=today, status="skipped", detail="artifact_exists")
                        _write_heartbeat(data_root, service, status="idle", detail="artifact_exists")
                    else:
                        _write_state(data_root, service, run_date=today, status="running")
                        _write_heartbeat(data_root, service, status="running")
                        try:
                            run_service_once(data_root, service, today)
                        except Exception as exc:  # noqa: BLE001 - persisted for operator diagnosis.
                            _write_state(data_root, service, run_date=today, status="failed", detail=str(exc))
                            _write_heartbeat(data_root, service, status="failed", detail=str(exc))
                            _log(data_root, service, f"ERROR {type(exc).__name__}: {exc}")
                        else:
                            _write_state(data_root, service, run_date=today, status="completed")
                            _write_heartbeat(data_root, service, status="idle", detail="completed")
                next_target = next_run(now, run_at)
                _write_heartbeat(data_root, service, status="idle", next_run_at=next_target.isoformat())
                wait_seconds = max(1.0, min(300.0, (next_target - now).total_seconds()))
                stop_event.wait(wait_seconds)
            _write_heartbeat(data_root, service, status="stopped")
            _log(data_root, service, "STOP supervisor")
    except _AlreadyRunning:
        _log(data_root, service, "ALREADY_RUNNING another supervisor owns the lock")
    return 0


def run_forever_all(data_root: Path) -> int:
    """Run all auxiliary daily jobs sequentially in one resident process."""

    stop_event = threading.Event()

    def stop_handler(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    data_root.mkdir(parents=True, exist_ok=True)

    try:
        with _ServiceLock(_lock_path(data_root, AUXILIARY_SERVICE)):
            _log(data_root, AUXILIARY_SERVICE, "START auxiliary supervisor")
            for service, run_at in AUXILIARY_SCHEDULES.items():
                _write_heartbeat(
                    data_root,
                    service,
                    status="starting",
                    next_run_at=next_run(datetime.now(_timezone()), run_at).isoformat(),
                )
            while not stop_event.is_set():
                now = datetime.now(_timezone())
                for service, run_at in AUXILIARY_SCHEDULES.items():
                    today = now.date()
                    target = _today_target(now, run_at)
                    state = _state_for_today(data_root, service, today)
                    if now >= target and not state:
                        if _artifact_exists(data_root, service, today):
                            _write_state(data_root, service, run_date=today, status="skipped", detail="artifact_exists")
                            _write_heartbeat(data_root, service, status="idle", detail="artifact_exists")
                        else:
                            _write_state(data_root, service, run_date=today, status="running")
                            _write_heartbeat(data_root, service, status="running")
                            _write_heartbeat(data_root, AUXILIARY_SERVICE, status="running", detail=service)
                            try:
                                run_service_once(data_root, service, today)
                            except Exception as exc:  # noqa: BLE001 - persisted for diagnosis.
                                _write_state(data_root, service, run_date=today, status="failed", detail=str(exc))
                                _write_heartbeat(data_root, service, status="failed", detail=str(exc))
                                _write_heartbeat(data_root, AUXILIARY_SERVICE, status="failed", detail=service)
                                _log(data_root, service, f"ERROR {type(exc).__name__}: {exc}")
                            else:
                                _write_state(data_root, service, run_date=today, status="completed")
                                _write_heartbeat(data_root, service, status="idle", detail="completed")
                    _write_heartbeat(
                        data_root,
                        service,
                        status="idle",
                        next_run_at=next_run(now, run_at).isoformat(),
                    )
                next_targets = [next_run(now, run_at) for run_at in AUXILIARY_SCHEDULES.values()]
                next_target = min(next_targets)
                _write_heartbeat(
                    data_root,
                    AUXILIARY_SERVICE,
                    status="idle",
                    next_run_at=next_target.isoformat(),
                )
                wait_seconds = max(1.0, min(300.0, (next_target - now).total_seconds()))
                stop_event.wait(wait_seconds)
            for service in SERVICE_NAMES:
                _write_heartbeat(data_root, service, status="stopped")
            _write_heartbeat(data_root, AUXILIARY_SERVICE, status="stopped")
            _log(data_root, AUXILIARY_SERVICE, "STOP auxiliary supervisor")
    except _AlreadyRunning:
        _log(data_root, AUXILIARY_SERVICE, "ALREADY_RUNNING another supervisor owns the lock")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervisor Linux de servicios auxiliares de agenteBolsa.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--service", choices=SERVICE_NAMES)
    group.add_argument("--all", dest="all_services", action="store_true")
    parser.add_argument("--run-at", default="23:00", help="Hora local Europe/Madrid en formato HH:mm.")
    parser.add_argument("--once", action="store_true", help="Ejecuta el servicio una vez y termina.")
    parser.add_argument("--healthcheck", action="store_true", help="Comprueba el heartbeat sin ejecutar el servicio.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data_root = _data_root()
    if args.healthcheck:
        healthy = healthcheck_all(data_root) if args.all_services else healthcheck(data_root, args.service)
        return 0 if healthy else 1
    if args.once:
        if args.all_services:
            try:
                run_all_once(data_root)
            except Exception as exc:  # noqa: BLE001 - CLI returns a useful non-zero status.
                _log(data_root, AUXILIARY_SERVICE, f"ERROR once {type(exc).__name__}: {exc}")
                return 1
            return 0
        try:
            run_service_once(data_root, args.service)
        except Exception as exc:  # noqa: BLE001 - CLI returns a useful non-zero status.
            _log(data_root, args.service, f"ERROR once {type(exc).__name__}: {exc}")
            return 1
        return 0
    if args.all_services:
        return run_forever_all(data_root)
    return run_forever(data_root, args.service, args.run_at)


if __name__ == "__main__":  # pragma: no cover - exercised by the container command.
    raise SystemExit(main())
