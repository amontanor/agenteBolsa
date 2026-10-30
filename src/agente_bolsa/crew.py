"""Build concrete, bounded advisory tasks while preserving CrewAI telemetry."""

from __future__ import annotations

import os
from typing import Any

from .agent_config import load_agent_config, load_task_config, validate_agent_task_config
from .config import Settings
from .crewai_context import get_crew_execution_context
from .llm_router import LLMEndpoint, provider_client_headers, select_preferred_endpoint

# v2 binds secondary LLM participants to their own tasks. Historical v1 events
# remain unchanged and must not be relabelled as executed secondary work.
MANIFEST_SCHEMA_VERSION = "p-l110.crew-participant-manifest.v2"
LAYER_ORDER = ("research", "validation", "committee", "learning")


def _ordered_task_items(task_config: dict[str, dict[str, object]]) -> list[tuple[str, dict[str, object]]]:
    ranks = {layer: index for index, layer in enumerate(LAYER_ORDER)}
    original = {name: index for index, name in enumerate(task_config)}
    return sorted(
        task_config.items(),
        key=lambda item: (ranks.get(str(item[1].get("layer") or "research"), 999), original[item[0]]),
    )


def _configured_participants(task: dict[str, object]) -> list[str]:
    return list(dict.fromkeys(
        str(name).strip()
        for name in (task.get("agents") or [task.get("owner_agent")])
        if name is not None and str(name).strip()
    ))


def _task_participants(
    task: dict[str, object], agent_config: dict[str, dict[str, object]]
) -> tuple[list[str], list[str]]:
    configured = _configured_participants(task)
    enabled = [
        name for name in configured
        if name in agent_config and agent_config[name].get("status") != "disabled"
    ]
    return (
        [name for name in enabled if agent_config[name].get("uses_llm", True)],
        [name for name in enabled if not agent_config[name].get("uses_llm", True)],
    )


def build_crew_task_manifest(
    agent_config: dict[str, dict[str, object]] | None = None,
    task_config: dict[str, dict[str, object]] | None = None,
) -> dict[str, Any]:
    """Describe construction, never claim execution from configuration alone."""
    agents = load_agent_config() if agent_config is None else agent_config
    tasks = load_task_config() if task_config is None else task_config
    validation = validate_agent_task_config(agents, tasks)
    if not validation["ok"]:
        raise ValueError("Configuracion de agentes/tareas invalida: " + " | ".join(validation["errors"]))
    rows: list[dict[str, Any]] = []
    crew_agents: list[str] = []
    deterministic_agents: list[str] = []
    for task_name, task in _ordered_task_items(tasks):
        if not bool(task.get("enabled", True)):
            continue
        actual, deterministic = _task_participants(task, agents)
        for name in actual:
            if name not in crew_agents:
                crew_agents.append(name)
        for name in deterministic:
            if name not in deterministic_agents:
                deterministic_agents.append(name)
        owner = str(task.get("owner_agent") or "")
        configured = _configured_participants(task)
        rows.append({
            "task_name": task_name,
            "layer": str(task.get("layer") or "research"),
            "owner_agent": owner,
            "owner_instantiated": owner in actual,
            "task_created": bool(actual),
            "bound_agent": owner if owner in actual else None,
            "bound_participants": actual,
            "unbound_participants": [name for name in configured if name not in actual],
            "configured_participants": configured,
            "crew_participants": actual,
            "deterministic_advisory_participants": deterministic,
            "concrete_task_count": len(actual),
            "execution_mode": "advisory_shadow",
            "execution_observed": False,
        })
    assigned = set(crew_agents) | set(deterministic_agents)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "valid": True,
        "validation_errors": [],
        "layers": list(LAYER_ORDER),
        "tasks": rows,
        "enabled_crew_agents": crew_agents,
        "crew_agents": crew_agents,
        "deterministic_advisory_agents": deterministic_agents,
        "unassigned_llm_agents": [
            name for name, config in agents.items()
            if config.get("status") != "disabled" and config.get("uses_llm", True) and name not in assigned
        ],
    }


def _enabled_crew_agents(
    agent_config: dict[str, dict[str, object]], task_config: dict[str, dict[str, object]]
) -> list[str]:
    # Preserve the selector's narrow contract for callers with partial records.
    # Full configuration validation belongs to build_crew_task_manifest/build_crew.
    return list(dict.fromkeys(
        agent_name
        for _task_name, task in _ordered_task_items(task_config)
        if bool(task.get("enabled", True))
        for agent_name in _task_participants(task, agent_config)[0]
    ))


def _task_description(task_name: str, task: dict[str, object], agent_name: str) -> str:
    layer = str(task.get("layer") or "research")
    return (
        f"Capa {layer}. Participante {agent_name}. Tarea {task_name}.\n"
        "Trabajo asesor en modo shadow: no crea ordenes, no cambia configuracion, no autoriza live y no sustituye "
        "los gates deterministas. Usa solo el snapshot y referencias disponibles en los inputs. "
        "Devuelve JSON estructurado. Para una observacion por candidato usa las claves "
        "signal_id, candidate_id, stance, confidence, reason_codes, evidence_refs, data_quality y as_of; "
        "si no existen IDs exactos devuelve contributions vacio. Nunca conviertas texto libre en una orden.\n"
        + str(task["prompt_template"])
    )


def build_crew(
    settings: Settings, *, endpoint: LLMEndpoint | None = None, task_observer: Any = None
):
    """Build one advisory task per enabled LLM participant, without starting it."""
    endpoint = endpoint or select_preferred_endpoint(settings)[0]
    os.environ["OPENAI_API_KEY"] = endpoint.api_key
    os.environ["OPENAI_API_BASE"] = endpoint.base_url
    os.environ["OPENAI_BASE_URL"] = endpoint.base_url
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    try:
        from crewai import LLM, Agent, Crew, Process, Task
    except ImportError as exc:
        raise RuntimeError("Instala dependencias con `pip install -r requirements.txt`.") from exc
    import agente_bolsa.listeners  # noqa: F401

    context = get_crew_execution_context()
    if task_observer is None and context is not None:
        task_observer = context.task_observer
    agent_config = load_agent_config()
    task_config = load_task_config()
    manifest = build_crew_task_manifest(agent_config, task_config)
    # P-L147: Console Go/Zen exige x-opencode-session tambien en crews.
    # CrewAI LLM fusiona additional_params en litellm; extra_headers viaja
    # al cliente OpenAI. Vacio para proveedores que no lo necesitan.
    crew_headers = provider_client_headers(endpoint.provider, scope="crew")
    shared_llm = LLM(
        model=endpoint.model,
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        additional_params={"extra_headers": crew_headers} if crew_headers else {},
    )
    enabled_agents = manifest["crew_agents"]
    agents = {
        key: Agent(
            role=str(value["role"]),
            goal=str(value["goal"]),
            backstory=str(value["backstory"]),
            llm=shared_llm,
            verbose=False,
            allow_delegation=False,
            max_iter=settings.crew_agent_max_iter,
            max_execution_time=settings.crew_agent_max_execution_seconds,
        )
        for key, value in agent_config.items() if key in enabled_agents
    }
    tasks = []
    layer_tasks: dict[str, list[Any]] = {layer: [] for layer in LAYER_ORDER}
    for task_name, task in _ordered_task_items(task_config):
        if not bool(task.get("enabled", True)):
            continue
        layer = str(task.get("layer") or "research")
        participants, _deterministic = _task_participants(task, agent_config)
        for agent_name in participants:
            previous: list[Any] = []
            layer_index = LAYER_ORDER.index(layer) if layer in LAYER_ORDER else 0
            if layer_index:
                previous = list(layer_tasks[LAYER_ORDER[layer_index - 1]])
            kwargs: dict[str, Any] = {
                "name": task_name,
                "description": _task_description(task_name, task, agent_name),
                "expected_output": str(task["expected_output"]),
                "agent": agents[agent_name],
            }
            if previous:
                kwargs["context"] = previous
            if task_observer is not None:
                def callback(output: Any, *, _task=task_name, _agent=agent_name) -> Any:
                    return task_observer.on_task_complete(_task, _agent, output)
                kwargs["callback"] = callback
            crew_task = Task(**kwargs)
            if task_observer is not None:
                task_observer.register_task(
                    task_name, agent_name, layer,
                    task_id=str(crew_task.id) if getattr(crew_task, "id", None) is not None else None,
                )
            tasks.append(crew_task)
            layer_tasks.setdefault(layer, []).append(crew_task)
    return Crew(
        agents=[agents[key] for key in enabled_agents],
        tasks=tasks,
        process=Process.sequential,
        memory=False,
        planning=settings.crewai_planning,
        planning_llm=shared_llm if settings.crewai_planning else None,
        verbose=False,
        output_log_file=str(settings.logs_dir / "crew_output.json"),
        checkpoint=None,
    )
