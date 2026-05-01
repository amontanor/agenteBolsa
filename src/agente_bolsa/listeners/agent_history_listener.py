"""CrewAI event listener that mirrors agent activity into local JSONL files."""

from __future__ import annotations

from typing import Any

from agente_bolsa.config import get_settings
from agente_bolsa.logging_utils import AgentHistoryLogger
from agente_bolsa.models import AgentEvent

try:
    from crewai.events import AgentExecutionCompletedEvent, BaseEventListener
except ImportError as exc:  # pragma: no cover - only active when CrewAI is installed.
    raise RuntimeError("CrewAI no esta instalado.") from exc


def _safe_payload(event: Any) -> dict[str, Any]:
    raw = getattr(event, "__dict__", {})
    payload: dict[str, Any] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        payload[key] = str(value)
    return payload


class AgentHistoryListener(BaseEventListener):
    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self.history = AgentHistoryLogger(settings.agent_logs_dir)

    def setup_listeners(self, crewai_event_bus: Any) -> None:
        @crewai_event_bus.on(AgentExecutionCompletedEvent)
        def on_agent_completed(source: Any, event: Any) -> None:
            agent_name = (
                getattr(getattr(event, "agent", None), "role", None)
                or getattr(source, "role", None)
                or "unknown_agent"
            )
            self.history.log(
                AgentEvent(
                    agent=str(agent_name).lower().replace(" ", "_"),
                    event_type="agent_execution_completed",
                    payload=_safe_payload(event),
                )
            )


agent_history_listener = AgentHistoryListener()
