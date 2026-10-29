"""P-L178: el callback de tarea CrewAI no puede depender de una closure.

Causa raiz observada en produccion (2026-10-29): CrewAI valida cada Task y, si el
callback es una closure, emite un ``UserWarning``. Cuando ``sys.stderr`` apunta a
un flujo cerrado -el ciclo redirige stdout/stderr al fichero del intento- ese
aviso lanza ``ValueError: I/O operation on closed file`` y pydantic invalida la
tarea, con lo que el crew cae a decision LLM directa en todos los ciclos.
"""

from __future__ import annotations

import io
import sys
import warnings
from types import SimpleNamespace

import pytest

from agente_bolsa import crew as crew_module
from agente_bolsa.config import Settings

AGENT_CONFIG = {
    "technical_analyst": {
        "role": "Analista tecnico",
        "goal": "Medir setups",
        "backstory": "Analiza mercado",
        "lane": "technical",
        "status": "active",
        "uses_llm": True,
    }
}

TASK_CONFIG = {
    "daily_research": {
        "description": "Investiga",
        "expected_output": "JSON",
        "prompt_template": "Analiza el snapshot",
        "layer": "research",
        "owner_agent": "technical_analyst",
        "agents": ["technical_analyst"],
        "enabled": True,
    }
}


class _FakeObserver:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str, str]] = []
        self.identities: dict[tuple[str, str], tuple[str, str]] = {}
        self.calls: list[tuple[str, str, object]] = []

    def register_task(self, task_name, agent_name, layer, *, task_id=None):  # noqa: ANN001
        self.registered.append((task_name, agent_name, layer))

    def bind_task_identity(self, task_name, agent_name, agent_role):  # noqa: ANN001
        self.identities[(str(task_name), str(agent_role))] = (str(task_name), str(agent_name))

    def resolve_task_identity(self, task_name, agent_role):  # noqa: ANN001
        return self.identities.get((str(task_name), str(agent_role)), (str(task_name), str(agent_role)))

    def on_task_complete(self, task_name, agent_name, output):  # noqa: ANN001
        self.calls.append((task_name, agent_name, output))
        return output


@pytest.fixture(autouse=True)
def _isolated_crew_config(monkeypatch):
    monkeypatch.setattr(crew_module, "load_agent_config", lambda: AGENT_CONFIG)
    monkeypatch.setattr(crew_module, "load_task_config", lambda: TASK_CONFIG)
    monkeypatch.setattr(
        crew_module,
        "validate_agent_task_config",
        lambda agents, tasks: {"ok": True, "errors": [], "warnings": []},
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        _env_file=None,
        opencode_api_key="test-key",
        news_sentiment_enabled=False,
    )


def _endpoint() -> SimpleNamespace:
    return SimpleNamespace(
        provider="opencode-go",
        model="deepseek-v4.1-flash",
        base_url="https://example.invalid/go/v1",
        api_key="test-key",
    )


def test_closure_callback_emits_crewai_serialization_warning():
    """Disparador del defecto: crewai avisa al recibir una closure.

    Ese aviso se escribe en ``sys.stderr``; si el flujo esta cerrado -como en el
    intento del ciclo- el aviso se convierte en ``ValueError`` dentro de la
    validacion pydantic de la Task.
    """

    from crewai import Task

    def _closure(output):
        return output

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Task(name="t", description="d", expected_output="e", agent=None, callback=_closure)

    assert any("cannot be serialized" in str(item.message) for item in caught)


def test_build_crew_registers_module_level_callback_with_closed_stderr(tmp_path):
    """Antes del arreglo esto lanzaba ValueError al validar la primera Task."""

    settings = _settings(tmp_path)
    observer = _FakeObserver()
    closed = io.StringIO()
    closed.close()
    original = sys.stderr
    sys.stderr = closed
    try:
        built = crew_module.build_crew(settings, endpoint=_endpoint(), task_observer=observer)
    finally:
        sys.stderr = original

    assert built.tasks
    for task in built.tasks:
        assert task.callback is crew_module._crew_task_callback
        assert "<locals>" not in task.callback.__qualname__
    assert observer.registered
    assert observer.identities == {("daily_research", "Analista tecnico"): ("daily_research", "technical_analyst")}


def test_module_level_callback_emits_no_serialization_warning():
    """El callback de modulo no dispara el aviso que mata la Task."""

    from crewai import Task

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        task = Task(
            name="daily_research",
            description="d",
            expected_output="e",
            agent=None,
            callback=crew_module._crew_task_callback,
        )

    assert task.callback is crew_module._crew_task_callback
    assert not any("cannot be serialized" in str(item.message) for item in caught)


def test_callback_delegates_with_bound_identity(tmp_path):
    observer = _FakeObserver()
    observer.bind_task_identity("daily_research", "technical_analyst", "Analista tecnico")
    output = SimpleNamespace(name="daily_research", agent="Analista tecnico")

    from agente_bolsa.crewai_context import crew_execution_context

    with crew_execution_context(
        cycle_id="mkt_test",
        crew_agent_run_id="agent_run_test",
        attempt=1,
        fallback=False,
        task_observer=observer,
    ):
        result = crew_module._crew_task_callback(output)

    assert result is output
    assert observer.calls == [("daily_research", "technical_analyst", output)]


def test_callback_without_observer_returns_output():
    output = SimpleNamespace(name="daily_research", agent="Analista tecnico")
    assert crew_module._crew_task_callback(output) is output
