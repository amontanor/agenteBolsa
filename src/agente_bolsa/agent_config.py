"""Shared agent/task configuration loaders and validators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ALLOWED_AGENT_STATUSES = {"active", "support", "disabled"}


def _config_dir() -> Path:
    return Path(__file__).parent / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} debe contener un mapping YAML en la raiz.")
    return loaded


def load_agent_config(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    config = _load_yaml((config_dir or _config_dir()) / "agents.yaml")
    normalized: dict[str, dict[str, Any]] = {}
    for agent_name, raw in config.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Agente {agent_name} invalido en agents.yaml.")
        normalized[agent_name] = {
            "role": str(raw.get("role") or "").strip(),
            "goal": str(raw.get("goal") or "").strip(),
            "backstory": str(raw.get("backstory") or "").strip(),
            "lane": str(raw.get("lane") or "unknown").strip(),
            "status": str(raw.get("status") or "active").strip().lower(),
            "runtime_entrypoints": [str(item).strip() for item in list(raw.get("runtime_entrypoints") or []) if str(item).strip()],
            "uses_llm": bool(raw.get("uses_llm", True)),
            "can_block_execution": bool(raw.get("can_block_execution", False)),
        }
    return normalized


def load_task_config(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    config = _load_yaml((config_dir or _config_dir()) / "tasks.yaml")
    normalized: dict[str, dict[str, Any]] = {}
    for task_name, raw in config.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Tarea {task_name} invalida en tasks.yaml.")
        agents = [str(item).strip() for item in list(raw.get("agents") or []) if str(item).strip()]
        normalized[task_name] = {
            "description": str(raw.get("description") or "").strip(),
            "expected_output": str(raw.get("expected_output") or "").strip(),
            "prompt_template": str(raw.get("prompt_template") or raw.get("description") or "").strip(),
            "owner_agent": str(raw.get("owner_agent") or (agents[0] if agents else "")).strip(),
            "agents": agents,
            "requires": [str(item).strip() for item in list(raw.get("requires") or []) if str(item).strip()],
            "produces": [str(item).strip() for item in list(raw.get("produces") or []) if str(item).strip()],
            "enabled": bool(raw.get("enabled", True)),
        }
    return normalized


def validate_agent_task_config(
    agent_config: dict[str, dict[str, Any]] | None = None,
    task_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    agent_config = agent_config or load_agent_config()
    task_config = task_config or load_task_config()
    errors: list[str] = []
    warnings: list[str] = []
    agent_usage: dict[str, set[str]] = {name: set() for name in agent_config}

    for agent_name, config in agent_config.items():
        if config["status"] not in ALLOWED_AGENT_STATUSES:
            errors.append(f"agent:{agent_name}: status invalido {config['status']!r}")
        for key in ("role", "goal", "backstory", "lane"):
            if not str(config.get(key) or "").strip():
                errors.append(f"agent:{agent_name}: falta {key}")

    for task_name, config in task_config.items():
        if not config["description"]:
            errors.append(f"task:{task_name}: falta description")
        if not config["expected_output"]:
            errors.append(f"task:{task_name}: falta expected_output")
        if not config["prompt_template"]:
            errors.append(f"task:{task_name}: falta prompt_template")
        if not config["owner_agent"]:
            errors.append(f"task:{task_name}: falta owner_agent")
        if not config["agents"]:
            errors.append(f"task:{task_name}: debe referenciar al menos un agente")
        for agent_name in config["agents"]:
            if agent_name not in agent_config:
                errors.append(f"task:{task_name}: referencia agente inexistente {agent_name}")
                continue
            agent_usage.setdefault(agent_name, set()).add(task_name)
        owner_agent = config["owner_agent"]
        if owner_agent and owner_agent not in agent_config:
            errors.append(f"task:{task_name}: owner_agent inexistente {owner_agent}")
        elif owner_agent and owner_agent not in config["agents"]:
            errors.append(f"task:{task_name}: owner_agent {owner_agent} debe estar en agents")

    for agent_name, config in agent_config.items():
        if config["status"] != "active":
            continue
        has_task = bool(agent_usage.get(agent_name))
        has_runtime_entrypoints = bool(config.get("runtime_entrypoints"))
        if not has_task and not has_runtime_entrypoints:
            errors.append(
                f"agent:{agent_name}: activo sin tareas habilitadas ni runtime_entrypoints"
            )
        if has_task and config["status"] == "support":
            warnings.append(f"agent:{agent_name}: support referenciado por tareas activas")

    enabled_tasks = {name for name, config in task_config.items() if config["enabled"]}
    disabled_task_agents = sorted(
        {
            agent_name
            for agent_name, used_by in agent_usage.items()
            if used_by and not (used_by & enabled_tasks)
        }
    )
    for agent_name in disabled_task_agents:
        warnings.append(f"agent:{agent_name}: solo referenciado por tareas deshabilitadas")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "agents": len(agent_config),
            "tasks": len(task_config),
            "enabled_tasks": len(enabled_tasks),
            "active_agents": sum(1 for config in agent_config.values() if config["status"] == "active"),
            "support_agents": sum(1 for config in agent_config.values() if config["status"] == "support"),
            "disabled_agents": sum(1 for config in agent_config.values() if config["status"] == "disabled"),
        },
        "agent_usage": {agent_name: sorted(task_names) for agent_name, task_names in agent_usage.items() if task_names},
    }
