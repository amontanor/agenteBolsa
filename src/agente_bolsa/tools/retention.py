"""Runtime data retention helpers for reports, logs and caches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agente_bolsa.config import Settings


@dataclass(frozen=True)
class RetentionSummary:
    reports_deleted: int = 0
    logs_deleted: int = 0
    cache_deleted: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "reports_deleted": self.reports_deleted,
            "logs_deleted": self.logs_deleted,
            "cache_deleted": self.cache_deleted,
            "errors": self.errors,
        }


def should_persist_report(settings: Settings, prefix: str) -> bool:
    if not settings.retention_enabled:
        return True
    return prefix not in set(settings.disabled_report_prefix_list)


def _cutoff(days: int, now: datetime | None = None) -> datetime | None:
    if days <= 0:
        return None
    current = now or datetime.now(timezone.utc)
    return current - timedelta(days=days)


def _is_older_than(path: Path, cutoff: datetime | None) -> bool:
    if cutoff is None or not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified < cutoff


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def _delete_if_old(path: Path, cutoff: datetime | None) -> tuple[bool, bool]:
    if not _is_older_than(path, cutoff):
        return False, False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False, True
    return True, False


def cleanup_runtime_data(settings: Settings, *, now: datetime | None = None) -> RetentionSummary:
    if not settings.retention_enabled:
        return RetentionSummary()

    report_cutoff = _cutoff(settings.report_retention_days, now)
    log_cutoff = _cutoff(settings.log_retention_days, now)
    cache_cutoff = _cutoff(settings.cache_retention_days, now)

    reports_deleted = 0
    logs_deleted = 0
    cache_deleted = 0
    errors = 0

    for path in _iter_files(settings.data_dir / "reports"):
        if path.name.startswith("latest_"):
            continue
        deleted, failed = _delete_if_old(path, report_cutoff)
        reports_deleted += int(deleted)
        errors += int(failed)

    for path in _iter_files(settings.logs_dir):
        deleted, failed = _delete_if_old(path, log_cutoff)
        logs_deleted += int(deleted)
        errors += int(failed)

    for path in _iter_files(settings.data_dir / "cache"):
        deleted, failed = _delete_if_old(path, cache_cutoff)
        cache_deleted += int(deleted)
        errors += int(failed)

    return RetentionSummary(
        reports_deleted=reports_deleted,
        logs_deleted=logs_deleted,
        cache_deleted=cache_deleted,
        errors=errors,
    )


def latest_report_path(data_dir: Path, prefix: str, latest_filename: str) -> Path | None:
    latest_path = data_dir / "reports" / latest_filename
    if latest_path.exists():
        return latest_path
    reports = [
        path
        for path in (data_dir / "reports").glob(f"{prefix}_*.json")
        if not path.name.endswith(".manifest.json")
    ]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)
