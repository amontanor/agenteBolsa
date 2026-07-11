"""Read-only timing evidence for observable market cycles."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa import __version__

from .reporting import write_json_report

STAGES = (
    "data_loading",
    "technical_analysis",
    "llm_decision",
    "deterministic_gates",
    "persistence",
    "report_generation",
)


class MarketCycleTiming:
    """Accumulates measured stages without affecting the market-cycle outcome."""

    def __init__(self, reports_dir: Path, cycle_id: str, *, started_at: datetime | None = None) -> None:
        self.reports_dir = reports_dir
        self.cycle_id = cycle_id
        self.started_at = (started_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._stages = {name: _unavailable_stage() for name in STAGES}

    def is_running(self, name: str) -> bool:
        return self._stages[name]["status"] == "running"

    def start(self, name: str, *, started_at: datetime | None = None) -> None:
        self._stages[name] = {
            "started_at": _iso(started_at or datetime.now(timezone.utc)),
            "finished_at": None,
            "duration_seconds": None,
            "status": "running",
        }

    def finish(self, name: str, *, finished_at: datetime | None = None) -> None:
        stage = self._stages[name]
        if stage["status"] != "running":
            return
        _finish(stage, "completed", finished_at or datetime.now(timezone.utc))

    def fail(self, name: str, error: Exception | str, *, finished_at: datetime | None = None) -> None:
        stage = self._stages[name]
        if stage["status"] != "running":
            return
        _finish(stage, "failed", finished_at or datetime.now(timezone.utc), error=str(error))

    def skip(self, name: str, reason: str) -> None:
        if self._stages[name]["status"] != "unavailable":
            return
        self._stages[name] = {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "status": "skipped",
            "reason": reason,
        }

    def finalize(self, status: str, *, error: Exception | str | None = None, finished_at: datetime | None = None) -> dict[str, Any]:
        finished = (finished_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        for name, stage in self._stages.items():
            if stage["status"] == "running":
                _finish(stage, "failed" if status == "failed" else "unavailable", finished, error=str(error) if error else None)
            elif stage["status"] == "unavailable":
                self.skip(name, "sin instrumentacion en este ciclo")
        payload = {
            "cycle_id": self.cycle_id,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(finished),
            "duration_seconds": _duration(self.started_at, finished),
            "status": status,
            "system_version": __version__,
            "stages": self._stages,
        }
        if error is not None:
            payload["error"] = str(error)
        return write_json_report(
            payload,
            self.reports_dir,
            "market_cycle_timing",
            self.cycle_id,
            latest_filename="latest_market_cycle_timing.json",
        )


def summarize_market_cycle_timings(reports_dir: Path, *, limit: int = 20) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("market_cycle_timing_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    measured = [item for item in rows if isinstance(item.get("stages"), dict)]
    durations = [float(item["duration_seconds"]) for item in measured if isinstance(item.get("duration_seconds"), (int, float))]
    stage_metrics: dict[str, dict[str, Any]] = {}
    for name in STAGES:
        values = [
            float((item.get("stages") or {}).get(name, {}).get("duration_seconds"))
            for item in measured
            if (item.get("stages") or {}).get(name, {}).get("status") == "completed"
            and isinstance((item.get("stages") or {}).get(name, {}).get("duration_seconds"), (int, float))
        ]
        stage_metrics[name] = {"sample": len(values), "p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)}
    return {
        "status": "available" if measured else "unavailable",
        "sample_available": len(measured),
        "sample_limit": limit,
        "legacy_unavailable": len(rows) - len(measured),
        "coverage_ratio": round(len(measured) / len(rows), 4) if rows else None,
        "total_duration_seconds": {"p50": _percentile(durations, 0.50), "p95": _percentile(durations, 0.95), "max": max(durations) if durations else None},
        "over_600_seconds": {"count": sum(value > 600 for value in durations), "pct": round(sum(value > 600 for value in durations) / len(durations), 4) if durations else None},
        "dominant_stage": {
            "p50": _dominant_stage(stage_metrics, "p50"),
            "p95": _dominant_stage(stage_metrics, "p95"),
        },
        "stages": stage_metrics,
    }


def _unavailable_stage() -> dict[str, Any]:
    return {"started_at": None, "finished_at": None, "duration_seconds": None, "status": "unavailable"}


def _finish(stage: dict[str, Any], status: str, finished_at: datetime, *, error: str | None = None) -> None:
    started = _parse(stage.get("started_at"))
    stage["finished_at"] = _iso(finished_at)
    stage["duration_seconds"] = _duration(started, finished_at) if started else None
    stage["status"] = status
    if error:
        stage["error"] = error


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _duration(started: datetime, finished: datetime) -> float:
    return round(max(0.0, (finished - started).total_seconds()), 4)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _dominant_stage(metrics: dict[str, dict[str, Any]], key: str) -> str | None:
    candidates = [(item.get(key), name) for name, item in metrics.items() if item.get(key) is not None]
    return max(candidates)[1] if candidates else None
