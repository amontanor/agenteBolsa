"""Read-only preflight for the Raspberry Docker migration.

The command deliberately does not run compose, stop processes, touch locks, or
open SQLite.  It reports active WAL/SHM state and requires a separately
validated cold snapshot before considering the data gate satisfied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_HOST = "192.168.1.234"
DEFAULT_USER = "antonio"
DEFAULT_MOUNT = "/var/lib/agente-bolsa"
DEFAULT_UUID = "1a8cb7c0-3a65-4d72-866f-340db4c6bafc"
DEFAULT_CANDIDATE_IMAGE = "agente-bolsa:0.4.230-arm64"
REQUIRED_CONTAINERS = (
    "agente-bolsa-scheduler-1",
    "agente-bolsa-auxiliary-1",
    "agente-bolsa-web-1",
)


def _remote_script(mount: str) -> str:
    mount_q = shlex.quote(mount)
    return f"""#!/bin/sh
set +e
emit() {{
  key="$1"
  shift
  value="$*"
  value=$(printf '%s' "$value" | tr '\\r\\n\\t' '   ')
  printf 'PREFLIGHT\\t%s\\t%s\\n' "$key" "$value"
}}

emit host "$(hostname 2>/dev/null)"
emit arch "$(uname -m 2>/dev/null)"
emit now "$(date --iso-8601=seconds 2>/dev/null || date 2>/dev/null)"
emit boot_time "$(uptime -s 2>/dev/null)"
emit uptime_seconds "$(awk '{{print int($1)}}' /proc/uptime 2>/dev/null)"
emit mount "$(findmnt -T {mount_q} -n -o SOURCE,FSTYPE,OPTIONS 2>/dev/null)"
emit block "$(lsblk -P -o NAME,MODEL,SERIAL,TRAN,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS,STATE 2>/dev/null | tr '\\n' ';')"
emit disk "$(df -P -B1 {mount_q} 2>/dev/null | tail -n 1)"
emit inode "$(df -Pi {mount_q} 2>/dev/null | tail -n 1)"
emit memory "$(free -b 2>/dev/null | awk '/^Mem:/ {{print}}')"
emit swap "$(free -b 2>/dev/null | awk '/^Swap:/ {{print}}')"
emit load "$(cat /proc/loadavg 2>/dev/null)"
emit d_state "$(ps -eo state,pid,comm,args --no-headers 2>/dev/null | awk '$1 ~ /D/ {{print}}' | tail -n 50)"
emit kernel_storage "$(dmesg --ctime 2>/dev/null | tail -n 500 | grep -Ei 'I/O error|Buffer I/O|EXT4-fs.*(error|warning)|usb.*(reset|disconnect)|uas.*(error|reset)|mmc.*(error|timeout)|read-only|remount.*(read-only|,ro)|filesystem.*shutdown' | tail -n 80)"
emit docker_version "$(docker --version 2>/dev/null)"
emit compose_version "$(docker compose version 2>/dev/null)"
emit services "$(docker ps --format '{{{{.Names}}}}|{{{{.Image}}}}|{{{{.Status}}}}|{{{{.Ports}}}}' 2>/dev/null | tr '\\n' ';')"
emit stats "$(docker stats --no-stream --format '{{{{.Name}}}}|{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.MemPerc}}}}|{{{{.PIDs}}}}' 2>/dev/null | tr '\\n' ';')"
for image in agente-bolsa:0.4.229-arm64 agente-bolsa:0.4.230-arm64; do
  emit "image.$image" "$(docker image inspect "$image" --format '{{{{.Id}}}}|{{{{.Architecture}}}}|{{{{.Created}}}}|{{{{index .Config.Labels \"org.opencontainers.image.revision\"}}}}' 2>/dev/null)"
done
for name in {' '.join(REQUIRED_CONTAINERS)}; do
  emit "inspect.$name" "$(docker inspect "$name" --format '{{{{.State.Status}}}}|{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}none{{{{end}}}}|{{{{.RestartCount}}}}|{{{{.Config.Image}}}}|{{{{.State.StartedAt}}}}' 2>/dev/null)"
  emit "flags.$name" "$(docker inspect "$name" --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' 2>/dev/null | grep -E '^(TRADING_MODE|ALPACA_PAPER|AUTO_PAPER_TRADING|REQUIRE_HUMAN_APPROVAL|ALLOW_LIVE_TRADING|ALLOW_AUTO_APPLY_IMPROVEMENTS)=' | tr '\\n' ';')"
done
emit sqlite_files "$(find {mount_q} -maxdepth 5 -type f \\( -name 'agente_bolsa.sqlite3*' -o -name '*.db' \\) -printf '%p|%s|%M|%u:%g;' 2>/dev/null | sort)"
emit data_mount_owner "$(stat -c '%U:%G %a' {mount_q} 2>/dev/null)"
"""


def _run_ssh(args: argparse.Namespace) -> tuple[dict[str, str], str | None]:
    target = f"{args.user}@{args.host}"
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.connect_timeout}",
        "-p",
        str(args.port),
    ]
    if args.identity:
        command.extend(["-i", args.identity, "-o", "IdentitiesOnly=yes"])
    command.extend([target, "bash", "-s"])
    try:
        completed = subprocess.run(
            command,
            input=_remote_script(args.mount).replace("\r\n", "\n").encode("utf-8"),
            text=False,
            capture_output=True,
            timeout=args.command_timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"ssh_error:{exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(errors="replace").strip().replace("\n", " ")
        return {}, f"ssh_exit_{completed.returncode}:{detail}"
    observations: dict[str, str] = {}
    stdout = completed.stdout.decode(errors="replace")
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0] == "PREFLIGHT":
            observations[parts[1]] = parts[2]
    if not observations:
        return {}, "ssh_protocol_error:no_preflight_records"
    return observations, None


def _parse_available_bytes(value: str) -> int | None:
    fields = value.split()
    if len(fields) < 4:
        return None
    try:
        return int(fields[3])
    except ValueError:
        return None


def _parse_memory_available(value: str) -> int | None:
    fields = value.split()
    if len(fields) < 7 or fields[0] != "Mem:":
        return None
    try:
        return int(fields[6])
    except ValueError:
        return None


def _has_expected_mount(value: str, expected_uuid: str, block: str) -> tuple[bool, str]:
    fields = value.split()
    if len(fields) < 3:
        return False, "findmnt no devolvio SOURCE/FSTYPE/OPTIONS"
    source, fstype, options = fields[0], fields[1], fields[2]
    if source != "/dev/sda1":
        return False, f"source={source!r}; esperado /dev/sda1"
    if fstype != "ext4":
        return False, f"fstype={fstype!r}; esperado ext4"
    if "rw" not in options.split(",") or "ro" in options.split(","):
        return False, f"options={options!r}; se requiere rw sin ro"
    if expected_uuid not in block:
        return False, f"UUID esperado no aparece en lsblk: {expected_uuid}"
    return True, f"{source} {fstype} {options} UUID={expected_uuid}"


def _service_rows(value: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw in value.split(";"):
        if not raw or "|" not in raw:
            continue
        name = raw.split("|", 1)[0]
        rows[name] = raw
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inspect_rows(observations: dict[str, str]) -> list[str]:
    failures = []
    for name in REQUIRED_CONTAINERS:
        raw = observations.get(f"inspect.{name}", "")
        fields = raw.split("|")
        healthy = len(fields) >= 4 and fields[0] == "running" and fields[1] == "healthy"
        if not healthy:
            failures.append(f"{name}: {raw or 'sin inspeccion'}")
    return failures


def _verify_snapshot_receipt(path: str | None, args: argparse.Namespace) -> tuple[bool, str]:
    if not path:
        return False, "unavailable: falta --sqlite-receipt"
    receipt_path = Path(path)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"receipt invalido: {exc}"
    required = {
        "schema": "p-l89.sqlite-cold-snapshot.v1",
        "status": "ok",
        "quick_check": "ok",
        "integrity_check": "ok",
        "source_host": args.expected_host,
        "mount": args.mount,
        "device_uuid": args.expected_uuid,
    }
    mismatches = [f"{key}={receipt.get(key)!r} (esperado {value!r})" for key, value in required.items() if receipt.get(key) != value]
    sha256 = str(receipt.get("sha256", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        mismatches.append("sha256 ausente o no hexadecimal de 64 caracteres")
    snapshot_path_value = receipt.get("snapshot_path")
    snapshot_path = Path(snapshot_path_value) if isinstance(snapshot_path_value, str) else None
    source_name = Path(str(receipt.get("source_path", ""))).name
    files = receipt.get("files")
    if snapshot_path is None or not snapshot_path.is_file():
        mismatches.append(f"snapshot_path no existe: {snapshot_path_value!r}")
    else:
        if snapshot_path.parent != receipt_path.parent:
            mismatches.append("snapshot_path no pertenece al directorio de la receipt")
        if not source_name:
            mismatches.append("source_path ausente o invalido")
        elif snapshot_path.name != source_name:
            mismatches.append(f"snapshot_path={snapshot_path.name!r} no coincide con source_path={source_name!r}")
        observed_sha256 = _sha256(snapshot_path)
        if observed_sha256.lower() != sha256.lower():
            mismatches.append(
                f"sha256 snapshot={observed_sha256} (receipt {sha256.lower()})"
            )
        primary = files.get(source_name) if isinstance(files, dict) else None
        if not isinstance(primary, dict):
            mismatches.append(f"files no contiene la SQLite primaria {source_name!r}")
        else:
            if primary.get("size") != snapshot_path.stat().st_size:
                mismatches.append(
                    f"size snapshot={snapshot_path.stat().st_size} (receipt {primary.get('size')!r})"
                )
            if str(primary.get("sha256", "")).lower() != observed_sha256.lower():
                mismatches.append("files.sha256 no coincide con el snapshot")
            for name, metadata in files.items() if isinstance(files, dict) else []:
                if not isinstance(name, str) or Path(name).name != name or not isinstance(metadata, dict):
                    mismatches.append(f"entrada files invalida: {name!r}")
                    continue
                companion = snapshot_path if name == snapshot_path.name else snapshot_path.parent / name
                if not companion.is_file():
                    mismatches.append(f"sidecar declarado ausente: {companion}")
                    continue
                if metadata.get("size") != companion.stat().st_size:
                    mismatches.append(f"size no coincide para {name}")
                if str(metadata.get("sha256", "")).lower() != _sha256(companion).lower():
                    mismatches.append(f"sha256 no coincide para {name}")
    if mismatches:
        return False, "receipt no valida: " + "; ".join(mismatches)
    return True, f"receipt validada {receipt_path.name}, sha256={sha256.lower()}"


def _local_windows_status() -> tuple[dict[str, Any] | None, str | None]:
    script = Path(__file__).with_name("stack_status.ps1")
    if not script.exists():
        return None, "stack_status.ps1 no existe"
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"stack_status_error:{exc}"
    if completed.returncode != 0:
        return None, f"stack_status_exit_{completed.returncode}"
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"stack_status_json_error:{exc}"


def build_report(args: argparse.Namespace, observations: dict[str, str], ssh_error: str | None) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []

    def add(name: str, ok: bool, detail: str, blocking: bool = True) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}
        if blocking and not ok:
            blockers.append(f"{name}: {detail}")

    if ssh_error:
        add("ssh", False, ssh_error)
        return {
            "schema": "p-l89.raspberry-preflight.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "target": vars(args),
            "observations": {},
            "checks": checks,
            "blocking_reasons": blockers,
            "mutations": [],
            "ok": False,
        }

    add("ssh", True, "conexion SSH y protocolo read-only correctos")
    add(
        "host_identity",
        observations.get("host") == args.expected_host and observations.get("arch") == "aarch64",
        f"hostname={observations.get('host')!r}, arch={observations.get('arch')!r}",
    )
    uptime = int(observations.get("uptime_seconds", "0") or 0)
    add(
        "host_stability",
        uptime >= args.min_uptime_seconds,
        f"uptime_seconds={uptime}, minimo={args.min_uptime_seconds}",
    )
    mount_ok, mount_detail = _has_expected_mount(
        observations.get("mount", ""), args.expected_uuid, observations.get("block", "")
    )
    add("usb_mount", mount_ok, mount_detail)
    storage_errors = observations.get("kernel_storage", "").strip()
    add("kernel_storage", not storage_errors, storage_errors or "sin errores I/O/USB/ext4 recientes detectados")
    d_state = observations.get("d_state", "").strip()
    add("no_blocked_io_process", not d_state, d_state or "sin procesos en estado D")

    available = _parse_available_bytes(observations.get("disk", ""))
    add(
        "disk_space",
        available is not None and available >= args.min_free_bytes,
        f"available_bytes={available}, minimo={args.min_free_bytes}",
    )
    memory_available = _parse_memory_available(observations.get("memory", ""))
    add(
        "memory",
        memory_available is not None and memory_available >= args.min_memory_bytes,
        f"available_bytes={memory_available}, minimo={args.min_memory_bytes}",
    )

    rows = _service_rows(observations.get("services", ""))
    missing = [name for name in REQUIRED_CONTAINERS if name not in rows]
    unhealthy = [name for name, row in rows.items() if name in REQUIRED_CONTAINERS and "(healthy)" not in row]
    add(
        "docker_core_health",
        not missing and not unhealthy,
        f"missing={missing}, unhealthy={unhealthy}; whale-copy se observa pero no es gate del core",
    )
    candidate = observations.get(f"image.{args.candidate_image}", "")
    add(
        "candidate_image",
        bool(candidate),
        f"{args.candidate_image}={candidate or 'no disponible'}",
    )
    required_flags = {
        "TRADING_MODE=paper",
        "ALPACA_PAPER=true",
        "AUTO_PAPER_TRADING=true",
        "REQUIRE_HUMAN_APPROVAL=false",
        "ALLOW_LIVE_TRADING=false",
        "ALLOW_AUTO_APPLY_IMPROVEMENTS=false",
    }
    missing_by_container: dict[str, list[str]] = {}
    for name in REQUIRED_CONTAINERS:
        raw = observations.get(f"flags.{name}", "")
        observed_flags = {item for item in raw.split(";") if item}
        missing = sorted(required_flags - observed_flags)
        if missing:
            missing_by_container[name] = missing
    add("paper_policy", not missing_by_container, f"missing={missing_by_container}")

    sqlite_files = observations.get("sqlite_files", "")
    sidecars = [item for item in sqlite_files.split(";") if item.endswith("-wal|") or "-wal|" in item or "-shm|" in item]
    add(
        "sqlite_files",
        "agente_bolsa.sqlite3|" in sqlite_files,
        f"base_present={'agente_bolsa.sqlite3|' in sqlite_files}, sidecars={len(sidecars)}",
    )
    snapshot_ok, snapshot_detail = _verify_snapshot_receipt(args.sqlite_receipt, args)
    add("sqlite_integrity", snapshot_ok, snapshot_detail)

    windows_status: dict[str, Any] | None = None
    if args.require_windows_stopped:
        windows_status, local_error = _local_windows_status()
        if local_error:
            add("windows_exclusivity", False, local_error)
        else:
            services = {item.get("service"): item for item in windows_status.get("services", [])}
            active = [
                name
                for name in ("scheduler", "web")
                if services.get(name, {}).get("state") != "PARADO"
            ]
            foreign = windows_status.get("foreign_processes", [])
            add("windows_exclusivity", not active and not foreign, f"active={active}, foreign={foreign}")

    report = {
        "schema": "p-l89.raspberry-preflight.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "target": vars(args),
        "observations": observations,
        "checks": checks,
        "blocking_reasons": blockers,
        "windows_status": windows_status,
        "mutations": [],
        "ok": not blockers,
    }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--identity", default=os.environ.get("RASP_KEY"))
    parser.add_argument("--mount", default=DEFAULT_MOUNT)
    parser.add_argument("--expected-host", default="Raspberryi5")
    parser.add_argument("--expected-uuid", default=DEFAULT_UUID)
    parser.add_argument("--candidate-image", default=DEFAULT_CANDIDATE_IMAGE)
    parser.add_argument("--min-uptime-seconds", type=int, default=600)
    parser.add_argument("--min-free-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--min-memory-bytes", type=int, default=256 * 1024**2)
    parser.add_argument("--connect-timeout", type=int, default=8)
    parser.add_argument("--command-timeout", type=int, default=30)
    parser.add_argument("--require-windows-stopped", action="store_true")
    parser.add_argument(
        "--sqlite-receipt",
        help="receipt JSON local de un snapshot frio validado; nunca se genera ni modifica aqui",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON; default is also JSON for automation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    observations, ssh_error = _run_ssh(args)
    report = build_report(args, observations, ssh_error)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
