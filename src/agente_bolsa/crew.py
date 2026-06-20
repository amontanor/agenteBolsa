"""CrewAI crew definition driven by YAML configuration."""

from __future__ import annotations

import os

from .agent_config import load_agent_config, load_task_config, validate_agent_task_config
from .config import Settings
from .llm_router import select_preferred_endpoint


def _enabled_crew_agents(agent_config: dict[str, dict[str, object]], task_config: dict[str, dict[str, object]]) -> list[str]:
    referenced = []
    for task in task_config.values():
        if not bool(task.get("enabled", True)):
            continue
        owner_agent = str(task.get("owner_agent") or "")
        if owner_agent and owner_agent not in referenced:
            referenced.append(owner_agent)
    return [
        agent_name
        for agent_name, config in agent_config.items()
        if config.get("status") != "disabled" and config.get("uses_llm", True) and agent_name in referenced
    ]


def build_crew(settings: Settings):
    """Build the CrewAI crew.

    Importing CrewAI happens inside this function so non-Crew commands such as
    `status` and `init-db` still work before dependencies are installed.
    """

    endpoint, _attempts = select_preferred_endpoint(settings)
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

    agent_config = load_agent_config()
    task_config = load_task_config()
    validation = validate_agent_task_config(agent_config, task_config)
    if not validation["ok"]:
        raise RuntimeError("Configuracion de agentes/tareas invalida: " + " | ".join(validation["errors"]))

    shared_llm = LLM(
        model=endpoint.model,
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )

    enabled_agents = _enabled_crew_agents(agent_config, task_config)
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
        for key, value in agent_config.items()
        if key in enabled_agents
    }

    tasks = [
        Task(
            description=str(task["prompt_template"]),
            expected_output=str(task["expected_output"]),
            agent=agents[str(task["owner_agent"])],
        )
        for task in task_config.values()
        if bool(task.get("enabled", True)) and str(task.get("owner_agent") or "") in agents
    ]

    return Crew(
        agents=[agents[key] for key in enabled_agents if key in agents],
        tasks=tasks,
        process=Process.sequential,
        memory=False,
        planning=settings.crewai_planning,
        planning_llm=shared_llm if settings.crewai_planning else None,
        verbose=False,
        output_log_file=str(settings.logs_dir / "crew_output.json"),
        checkpoint=None,
    )
