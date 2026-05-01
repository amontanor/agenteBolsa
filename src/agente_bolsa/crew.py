"""CrewAI crew definition."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .config import Settings


AGENT_ORDER = [
    "market_data_researcher",
    "macro_news_researcher",
    "technical_analyst",
    "fundamental_analyst",
    "hypothesis_generator",
    "quant_backtester",
    "risk_manager",
    "portfolio_manager",
    "execution_agent",
    "post_trade_analyst",
    "self_improvement_engineer",
    "compliance_guardian",
]


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def build_crew(settings: Settings):
    """Build the CrewAI crew.

    Importing CrewAI happens inside this function so non-Crew commands such as
    `status` and `init-db` still work before dependencies are installed.
    """

    os.environ["OPENAI_API_KEY"] = settings.openai_api_key or "local-llama"
    os.environ["OPENAI_API_BASE"] = settings.openai_api_base
    os.environ["OPENAI_BASE_URL"] = settings.openai_api_base
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")

    try:
        from crewai import Agent, Crew, LLM, Process, Task
    except ImportError as exc:
        raise RuntimeError("Instala dependencias con `pip install -r requirements.txt`.") from exc

    import agente_bolsa.listeners  # noqa: F401

    config_dir = Path(__file__).parent / "config"
    agent_config = _load_yaml(config_dir / "agents.yaml")
    shared_llm = LLM(
        model=settings.openai_model,
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key or "local-llama",
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )

    agents = {
        key: Agent(
            role=value["role"],
            goal=value["goal"],
            backstory=value["backstory"],
            llm=shared_llm,
            verbose=False,
            allow_delegation=False,
            max_iter=settings.crew_agent_max_iter,
            max_execution_time=settings.crew_agent_max_execution_seconds,
        )
        for key, value in agent_config.items()
        if key in AGENT_ORDER
    }

    tasks = [
        Task(
            description=(
                "Actualiza el estado del universo {universe} usando solo datos verificables del "
                "snapshot siguiente. No inventes precios, fechas ni fundamentales que no esten "
                "en el snapshot. Fecha del ciclo: {current_date}. Snapshot: {market_snapshot}. "
                "Contexto tecnico adicional del escaneo amplio: {technical_context}. "
                "Devuelve observaciones tecnicas y de contexto. No propongas operaciones sin "
                "reglas medibles."
            ),
            expected_output="Observaciones estructuradas con evidencia y simbolos afectados.",
            agent=agents["market_data_researcher"],
        ),
        Task(
            description=(
                "Genera hipotesis falsables a partir de las observaciones. Cada hipotesis debe "
                "tener entrada, salida, invalidacion, horizonte y metricas de promocion."
            ),
            expected_output="Lista JSON de hipotesis candidatas.",
            agent=agents["hypothesis_generator"],
        ),
        Task(
            description=(
                "Evalua las hipotesis. Penaliza sobreajuste, pocos trades, coste no modelado y "
                "dependencia de un unico periodo."
            ),
            expected_output="Decision de validacion con metricas minimas y razones de rechazo.",
            agent=agents["quant_backtester"],
        ),
        Task(
            description=(
                "Aplica limites de riesgo y decide si alguna propuesta puede pasar a paper trading. "
                "Bloquea cualquier ejecucion live si la configuracion no lo permite."
            ),
            expected_output="Aprobaciones o rechazos de riesgo con checks concretos.",
            agent=agents["risk_manager"],
        ),
        Task(
            description=(
                "Resume aprendizajes del ciclo y propone mejoras controladas para investigar. "
                "Las mejoras de codigo deben quedar como propuesta, no como cambio productivo activo."
            ),
            expected_output="Post-mortem y backlog de mejoras priorizado.",
            agent=agents["post_trade_analyst"],
        ),
    ]

    return Crew(
        agents=[agents[key] for key in AGENT_ORDER if key in agents],
        tasks=tasks,
        process=Process.sequential,
        memory=False,
        planning=settings.crewai_planning,
        planning_llm=shared_llm if settings.crewai_planning else None,
        verbose=False,
        output_log_file=str(settings.logs_dir / "crew_output.json"),
        checkpoint=None,
    )
