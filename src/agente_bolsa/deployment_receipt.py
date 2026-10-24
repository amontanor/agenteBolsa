"""Read and append verified deployment receipts stored with persistent data."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RECEIPT_FILENAME = "deployment_receipts.jsonl"
RECEIPT_SCHEMA = "agente-bolsa.verified-deployment.v1"
LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")
UTC = timezone.utc
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_RECEIPT_FILE_BYTES = 1_048_576
_MAX_RECEIPT_LINE_BYTES = 16_384


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _validate_receipt(payload: Any, *, current_version: str) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != RECEIPT_SCHEMA or payload.get("status") != "verified":
        return None
    if payload.get("version") != current_version:
        return None
    image_id = payload.get("image_id")
    source_head = payload.get("source_head")
    source_tree = payload.get("source_tree")
    if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
        return None
    if not isinstance(source_head, str) or not _GIT_OBJECT_RE.fullmatch(source_head):
        return None
    if not isinstance(source_tree, str) or not _GIT_OBJECT_RE.fullmatch(source_tree):
        return None
    if payload.get("timezone") != "Europe/Madrid":
        return None

    utc_value = _aware_datetime(payload.get("verified_at_utc"))
    local_value = _aware_datetime(payload.get("verified_at_local"))
    if utc_value is None or local_value is None:
        return None
    utc_value = utc_value.astimezone(UTC)
    expected_local = utc_value.astimezone(LOCAL_TIMEZONE)
    if (
        local_value.utcoffset() != expected_local.utcoffset()
        or local_value.replace(tzinfo=None) != expected_local.replace(tzinfo=None)
    ):
        return None

    return {
        "version": current_version,
        "image_id": image_id,
        "source_head": source_head,
        "source_tree": source_tree,
        "verified_at_utc": utc_value.isoformat().replace("+00:00", "Z"),
        "verified_at_local": expected_local.isoformat(),
        "timezone": "Europe/Madrid",
    }


def latest_verified_deployment_receipt(
    data_dir: Path | str,
    *,
    current_version: str,
) -> dict[str, str] | None:
    """Read newest receipt; malformed or mismatched latest data stays unavailable."""
    path = Path(data_dir) / RECEIPT_FILENAME
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            if size == 0 or size > _MAX_RECEIPT_FILE_BYTES:
                return None
            stream.seek(0)
            content = stream.read(_MAX_RECEIPT_FILE_BYTES + 1)
    except OSError:
        return None
    if len(content) > _MAX_RECEIPT_FILE_BYTES:
        return None

    lines = [line for line in content.splitlines() if line.strip()]
    if not lines or len(lines[-1]) > _MAX_RECEIPT_LINE_BYTES:
        return None
    try:
        payload = json.loads(lines[-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _validate_receipt(payload, current_version=current_version)


def append_verified_deployment_receipt(
    data_dir: Path | str,
    *,
    current_version: str,
    image_id: str,
    source_head: str,
    source_tree: str,
    verified_at: datetime | None = None,
) -> dict[str, str]:
    """Append receipt after runbook verifies deployed image and service health."""
    if not _IMAGE_ID_RE.fullmatch(image_id):
        raise ValueError("image_id must be a full sha256 Docker image ID")
    if not _GIT_OBJECT_RE.fullmatch(source_head) or not _GIT_OBJECT_RE.fullmatch(source_tree):
        raise ValueError("source_head and source_tree must be full Git object IDs")

    timestamp = verified_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("verified_at must include a timezone")
    timestamp = timestamp.astimezone(UTC)
    payload = {
        "schema": RECEIPT_SCHEMA,
        "status": "verified",
        "version": current_version,
        "image_id": image_id,
        "source_head": source_head,
        "source_tree": source_tree,
        "verified_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "verified_at_local": timestamp.astimezone(LOCAL_TIMEZONE).isoformat(),
        "timezone": "Europe/Madrid",
    }
    validated = _validate_receipt(payload, current_version=current_version)
    if validated is None:
        raise ValueError("deployment receipt failed validation")

    path = Path(data_dir) / RECEIPT_FILENAME
    line = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(line) > _MAX_RECEIPT_LINE_BYTES:
        raise ValueError("deployment receipt exceeds the size limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        written = os.write(descriptor, line)
        if written != len(line):
            raise OSError("incomplete deployment receipt write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return validated


def format_verified_deployment_time(receipt: dict[str, str] | None) -> str:
    if receipt is None:
        return "Fecha de despliegue no disponible"
    local_value = _aware_datetime(receipt.get("verified_at_local"))
    utc_value = _aware_datetime(receipt.get("verified_at_utc"))
    if local_value is None or utc_value is None:
        return "Fecha de despliegue no disponible"
    local_text = local_value.strftime("%Y-%m-%d %H:%M:%S")
    utc_text = utc_value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"Despliegue verificado: {local_text} Europe/Madrid · {utc_text}"
