"""JSONL logging utilities."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .models import AgentEvent


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=True, default=_json_default))
        file.write("\n")


class AgentHistoryLogger:
    def __init__(self, agent_logs_dir: Path) -> None:
        self.agent_logs_dir = agent_logs_dir

    def log(self, event: AgentEvent) -> None:
        payload = asdict(event) if is_dataclass(event) else dict(event)
        path = self.agent_logs_dir / f"{event.agent}.jsonl"
        append_jsonl(path, payload)


def configure_logging(logs_dir: Path, level: str = "INFO") -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / "system.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("crewai").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def log_system_event(logs_dir: Path, event_type: str, payload: dict[str, Any]) -> None:
    append_jsonl(
        logs_dir / "system.jsonl",
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        },
    )
