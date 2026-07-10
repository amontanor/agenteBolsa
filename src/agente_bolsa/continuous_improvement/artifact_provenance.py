"""Provenance and expiry checks for generated code-diff artifacts."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .versioning import VERSION_FILE


def build_diff_provenance(
    repo: Path,
    target_paths: list[str],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    now = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "base_commit": _git_head(repo),
        "base_version": _version(repo),
        "generated_at": now.isoformat(),
        "target_hashes": {path: _file_hash(repo / path) for path in sorted(set(target_paths))},
    }


def validate_diff_provenance(
    repo: Path,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
) -> dict[str, Any]:
    provenance = payload.get("provenance") or {}
    failures: list[str] = []
    if not isinstance(provenance, dict) or not provenance:
        return {"valid": False, "failures": ["missing_provenance"], "provenance": {}}
    generated = _parse_datetime(provenance.get("generated_at"))
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if generated is None:
        failures.append("generated_at_invalid")
    elif generated < reference - timedelta(hours=max_age_hours) or generated > reference + timedelta(minutes=5):
        failures.append("artifact_expired")
    if str(provenance.get("base_version") or "") != _version(repo):
        failures.append("base_version_changed")
    target_hashes = provenance.get("target_hashes")
    if not isinstance(target_hashes, dict) or not target_hashes:
        failures.append("missing_target_hashes")
    else:
        for target, expected in target_hashes.items():
            if _file_hash(repo / str(target)) != expected:
                failures.append(f"target_changed:{target}")
    return {"valid": not failures, "failures": failures, "provenance": provenance}


def _git_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _version(repo: Path) -> str:
    path = repo / VERSION_FILE
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def _file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
