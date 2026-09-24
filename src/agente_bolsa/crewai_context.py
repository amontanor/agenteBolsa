"""Contextual identity for CrewAI execution telemetry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CrewExecutionContext:
    cycle_id: str
    crew_agent_run_id: str
    attempt: int
    fallback: bool
    task_observer: Any = None


_current_context: ContextVar[CrewExecutionContext | None] = ContextVar(
    "agente_bolsa_crew_execution_context", default=None
)


def get_crew_execution_context() -> CrewExecutionContext | None:
    """Return current CrewAI context, or ``None`` outside a kickoff."""

    return _current_context.get()


@contextmanager
def crew_execution_context(
    *, cycle_id: str, crew_agent_run_id: str, attempt: int, fallback: bool,
    task_observer: Any = None,
) -> Iterator[None]:
    """Set execution identity and restore it even when kickoff raises."""

    token = _current_context.set(
        CrewExecutionContext(
            cycle_id=str(cycle_id),
            crew_agent_run_id=str(crew_agent_run_id),
            attempt=int(attempt),
            fallback=bool(fallback),
            task_observer=task_observer,
        )
    )
    try:
        yield
    finally:
        _current_context.reset(token)
