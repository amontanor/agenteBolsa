"""Create and validate a cold SQLite file-set snapshot.

The command is intentionally explicit: it refuses to run unless the operator
declares that all writers are stopped, never overwrites a destination, copies
the database and existing WAL/SHM companions, validates the copied set, and
emits a receipt consumable by ``raspberry_preflight.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

RECEIPT_SCHEMA = "p-l89.sqlite-cold-snapshot.v2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_files(source: Path) -> list[Path]:
    files = [source]
    for suffix in ("-wal", "-shm"):
        companion = Path(f"{source}{suffix}")
        if companion.exists():
            files.append(companion)
    return files


def _file_state(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}


def _validate_sqlite(path: Path) -> tuple[str, str, str]:
    safe_chars = "/\\:"
    uri = f"file:{quote(str(path), safe=safe_chars)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        connection.execute("PRAGMA query_only=ON")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        integrity_check = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    return journal_mode, quick_check, integrity_check


def _receipt(
    *,
    source: Path,
    destination: Path,
    source_host: str,
    target_host: str,
    target_mount: str,
    target_device_uuid: str,
    source_files: list[Path],
    journal_mode: str,
    quick_check: str,
    integrity_check: str,
) -> dict[str, object]:
    files = {}
    for source_file in source_files:
        destination_file = destination / source_file.name
        files[source_file.name] = {
            "size": destination_file.stat().st_size,
            "sha256": _sha256(destination_file),
        }
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_host": source_host,
        "target_host": target_host,
        "target_mount": target_mount,
        "target_device_uuid": target_device_uuid,
        "source_path": str(source),
        "snapshot_path": str(destination / source.name),
        "snapshot_method": "cold_file_set",
        "journal_mode": journal_mode,
        "quick_check": quick_check,
        "integrity_check": integrity_check,
        "sha256": files[source.name]["sha256"],
        "files": files,
    }


def create_snapshot(args: argparse.Namespace) -> dict[str, object]:
    if not args.writers_stopped:
        raise ValueError("requiere --writers-stopped; no se asume exclusividad")

    source = Path(args.source).expanduser().resolve()
    destination = Path(args.destination_dir).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"no existe la SQLite origen: {source}")
    if destination.exists():
        raise FileExistsError(f"no se sobrescribe el destino existente: {destination}")
    if destination == source.parent:
        raise ValueError("el destino no puede ser el directorio de la SQLite origen")

    files = _source_files(source)
    before = _file_state(files)
    temporary_parent = destination.parent
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.partial-", dir=temporary_parent))
    try:
        for source_file in files:
            shutil.copy2(source_file, temporary / source_file.name)
        after = _file_state(files)
        if after != before:
            raise RuntimeError("la SQLite o sus sidecars cambiaron durante la copia")

        journal_mode, quick_check, integrity_check = _validate_sqlite(
            temporary / source.name
        )
        if quick_check != "ok" or integrity_check != "ok":
            raise RuntimeError(
                f"snapshot no integro: quick_check={quick_check}, integrity_check={integrity_check}"
            )

        receipt = _receipt(
            source=source,
            destination=temporary,
            source_host=args.source_host,
            target_host=args.target_host,
            target_mount=args.target_mount,
            target_device_uuid=args.target_device_uuid,
            source_files=files,
            journal_mode=journal_mode,
            quick_check=quick_check,
            integrity_check=integrity_check,
        )
        receipt["snapshot_path"] = str(destination / source.name)
        (temporary / "receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.rename(destination)
        return receipt
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLite productiva congelada")
    parser.add_argument("--destination-dir", required=True, help="directorio nuevo del snapshot")
    parser.add_argument("--source-host", required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-mount", required=True)
    parser.add_argument("--target-device-uuid", required=True)
    parser.add_argument(
        "--writers-stopped",
        action="store_true",
        help="confirmacion explicita: todos los escritores estan detenidos",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = create_snapshot(args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
