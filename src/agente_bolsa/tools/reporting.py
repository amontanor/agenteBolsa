"""Shared JSON report and manifest helpers."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agente_bolsa.config import get_settings

from .retention import should_persist_report


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "symbols_scanned",
        "symbols_with_data",
        "symbols_analyzed",
        "summary",
        "health",
        "period",
        "session_date",
        "warnings",
        "update_result",
        "observations_summary",
    ):
        if key in report:
            value = report.get(key)
            summary[key] = len(value) if isinstance(value, list) else value
    return summary


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=_json_default), encoding="utf-8")
    temporary.replace(path)


def write_json_report(
    report: dict[str, Any],
    output_dir: Path,
    prefix: str,
    run_id: str,
    *,
    latest_filename: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    persist_report = should_persist_report(settings, prefix)
    output_path = output_dir / f"{prefix}_{run_id}.json" if persist_report else None
    manifest_path = output_dir / f"{prefix}_{run_id}.manifest.json" if persist_report else None
    latest_path = output_dir / latest_filename if latest_filename and persist_report else None

    payload = dict(report)
    payload["path"] = str(output_path) if output_path is not None else None
    payload["manifest_path"] = str(manifest_path) if manifest_path is not None else None
    payload["persisted"] = persist_report
    if latest_path is not None:
        payload["latest_path"] = str(latest_path)

    if output_path is not None:
        _write_json_atomic(output_path, payload)
    if latest_path is not None:
        _write_json_atomic(latest_path, payload)

    if manifest_path is None:
        return payload

    manifest_payload = {
        "report_type": prefix,
        "run_id": run_id,
        "as_of": payload.get("as_of"),
        "report_path": str(output_path),
        "latest_path": str(latest_path) if latest_path is not None else None,
        "summary": _report_summary(payload),
        "inputs": manifest or {},
    }
    _write_json_atomic(manifest_path, manifest_payload)
    return payload
