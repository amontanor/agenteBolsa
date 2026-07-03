"""Closed-market research mode controls for the CI lab."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CI_RESEARCH_MODE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "human_gated": True,
    "max_new_proposals_per_cycle": 3,
    "allow_event_types": [
        "manual_trigger",
        "repeated_errors_detected",
        "scheduler_state_changed",
        "latest_market_data_quality",
    ],
    "allow_domains": [
        "software-improvement",
        "research",
        "observability",
    ],
    "proposal_target_allowlist": [
        "docs/",
        "scripts/",
        "tests/",
        "src/agente_bolsa/continuous_improvement/",
        "src/agente_bolsa/tools/ops_reports.py",
        "src/agente_bolsa/tools/operational_health.py",
    ],
    "notes": "OFF por defecto. Solo Antonio debe activar este modo para ciclos sin mercado.",
}

RESEARCH_MODE_GOVERNED_KEYS = {
    "ci_research_mode",
    "ci_research_mode_enabled",
    "data/config/ci_research_mode.json",
}


def load_ci_research_mode_config(config_path: Path, *, create: bool = True) -> dict[str, Any]:
    if create and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULT_CI_RESEARCH_MODE_CONFIG, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if not config_path.exists():
        return dict(DEFAULT_CI_RESEARCH_MODE_CONFIG)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    config = {**DEFAULT_CI_RESEARCH_MODE_CONFIG, **(raw if isinstance(raw, dict) else {})}
    config["enabled"] = bool(config.get("enabled"))
    config["human_gated"] = bool(config.get("human_gated", True))
    config["max_new_proposals_per_cycle"] = max(0, int(config.get("max_new_proposals_per_cycle") or 0))
    for key in ("allow_event_types", "allow_domains", "proposal_target_allowlist"):
        value = config.get(key)
        config[key] = [str(item) for item in value] if isinstance(value, list) else list(DEFAULT_CI_RESEARCH_MODE_CONFIG[key])
    return config


def ci_research_mode_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("enabled")) and bool(config.get("human_gated"))
