"""CrewAI execution listener with contextual, non-authoritative evidence."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from agente_bolsa.agent_run import sanitize_error
from agente_bolsa.config import get_settings
from agente_bolsa.crewai_context import get_crew_execution_context
from agente_bolsa.logging_utils import AgentHistoryLogger
from agente_bolsa.models import AgentEvent

try:
    from crewai.events import (
        AgentExecutionCompletedEvent,
        AgentExecutionErrorEvent,
        AgentExecutionStartedEvent,
        BaseEventListener,
    )
except ImportError as exc:  # pragma: no cover - only active when CrewAI is installed.
    raise RuntimeError("CrewAI no esta instalado.") from exc


SCHEMA_VERSION = "p-l111.crewai-agent-execution.v1"
_AGENT_FILENAME_RE = re.compile(r"[^a-z0-9_.-]+")


def _field(event: Any, name: str) -> str | None:
    value = getattr(event, name, None)
    if value is not None and str(value).strip():
        return str(value)
    if name == "task_id":
        value = getattr(getattr(event, "task", None), "id", None)
    elif name == "task_name":
        value = getattr(getattr(event, "task", None), "name", None)
    elif name == "agent_id":
        value = getattr(getattr(event, "agent", None), "id", None)
    elif name == "agent_role":
        value = getattr(getattr(event, "agent", None), "role", None)
    return str(value) if value is not None and str(value).strip() else None


def _utc_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _agent_filename(event: Any, source: Any = None) -> str:
    role = _field(event, "agent_role") or getattr(source, "role", None) or "unknown_agent"
    safe = _AGENT_FILENAME_RE.sub("_", role.lower()).strip("._")
    return safe or "unknown_agent"


def _error_code(event: Any) -> str:
    explicit = getattr(event, "error_code", None)
    if explicit:
        return sanitize_error(explicit)[:120]
    error = getattr(event, "error", None)
    if error is not None and not isinstance(error, str):
        return type(error).__name__[:120]
    return "agent_execution_error"


class AgentHistoryListener(BaseEventListener):
    def __init__(self, history: AgentHistoryLogger | None = None) -> None:
        self._started_events: dict[str, datetime] = {}
        super().__init__()
        self.history = history or AgentHistoryLogger(get_settings().agent_logs_dir)

    def setup_listeners(self, crewai_event_bus: Any) -> None:
        @crewai_event_bus.on(AgentExecutionStartedEvent)
        def on_agent_started(source: Any, event: Any) -> None:
            self._record(event, "started", source)

        @crewai_event_bus.on(AgentExecutionCompletedEvent)
        def on_agent_completed(source: Any, event: Any) -> None:
            self._record(event, "completed", source)

        @crewai_event_bus.on(AgentExecutionErrorEvent)
        def on_agent_error(source: Any, event: Any) -> None:
            self._record(event, "error", source)

    def _record(self, event: Any, status: str, source: Any = None) -> None:
        event_id = _field(event, "event_id")
        event_time = _timestamp(getattr(event, "timestamp", None))
        if status == "started" and event_id and event_time:
            self._started_events[event_id] = event_time

        started_event_id = _field(event, "started_event_id")
        started_at = self._started_events.get(started_event_id or "")
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "crew_event_id": event_id,
            "cycle_id": None,
            "crew_agent_run_id": None,
            "attempt": None,
            "fallback": None,
            "context_status": "unavailable",
            "task_id": _field(event, "task_id"),
            "task_name": _field(event, "task_name"),
            "agent_id": _field(event, "agent_id"),
            "agent_role": _field(event, "agent_role"),
            "started_event_id": started_event_id,
            "parent_event_id": _field(event, "parent_event_id"),
            "timestamp": _utc_iso(getattr(event, "timestamp", None)),
            "status": status,
        }
        context = get_crew_execution_context()
        if context is not None:
            payload.update(
                {
                    "cycle_id": context.cycle_id,
                    "crew_agent_run_id": context.crew_agent_run_id,
                    "attempt": context.attempt,
                    "fallback": context.fallback,
                    "context_status": "available",
                }
            )
            if context.task_observer is not None:
                try:
                    context.task_observer.on_execution_event(
                        payload["task_id"], status, getattr(event, "error", None)
                    )
                except Exception:  # noqa: BLE001 - keep lifecycle telemetry fail-open.
                    pass
        if started_at and event_time:
            payload["duration_seconds"] = round(max(0.0, (event_time - started_at).total_seconds()), 6)
        if status == "completed":
            output = str(getattr(event, "output", "") or "")
            payload["output_chars"] = len(output)
            payload["output_sha256"] = hashlib.sha256(output.encode("utf-8")).hexdigest()
        elif status == "error":
            error = sanitize_error(getattr(event, "error", ""))[:500]
            payload["error_code"] = _error_code(event)
            payload["error_sanitized"] = error
        if status != "started" and started_event_id:
            self._started_events.pop(started_event_id, None)

        try:
            self.history.log(
                AgentEvent(
                    agent=_agent_filename(event, source),
                    event_type=f"agent_execution_{status}",
                    cycle_id=payload["cycle_id"],
                    payload=payload,
                )
            )
        except Exception:  # noqa: BLE001 - telemetry cannot change CrewAI result.
            return


agent_history_listener = AgentHistoryListener()
