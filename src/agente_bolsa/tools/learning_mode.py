"""Config file-based para el experimento de aprendizaje en paper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings

LEARNING_EXPERIMENT_SOURCE = "learning_experiment"

DEFAULT_LEARNING_MODE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "human_gated": True,
    "daily_order_budget": 3,
    "per_trade_notional_usd": 1000,
    "max_portfolio_exposure_pct": 15,
    "allowed_strategies": ["builtin_breakout", "builtin_pullback"],
    "shadow_first": True,
    "notes": (
        "Experimento de aprendizaje en paper. Solo Antonio debe activarlo o "
        "ampliar sus cupos; la firma no puede autohabilitarlo."
    ),
}

LEARNING_MODE_GOVERNED_KEYS = {
    "learning_mode",
    "learning_mode_enabled",
    "learning_mode_human_gated",
    "learning_mode_shadow_first",
    "learning_mode_daily_order_budget",
    "learning_mode_per_trade_notional_usd",
    "learning_mode_max_portfolio_exposure_pct",
    "learning_mode_allowed_strategies",
    "data/config/learning_mode.json",
}


def load_learning_mode_config(config_path: Path, *, create: bool = True) -> dict[str, Any]:
    if create and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(DEFAULT_LEARNING_MODE_CONFIG, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    if not config_path.exists():
        return dict(DEFAULT_LEARNING_MODE_CONFIG)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        raw = {}
    config = {**DEFAULT_LEARNING_MODE_CONFIG, **(raw if isinstance(raw, dict) else {})}
    config["enabled"] = bool(config.get("enabled"))
    config["human_gated"] = bool(config.get("human_gated", True))
    config["shadow_first"] = bool(config.get("shadow_first", True))
    config["daily_order_budget"] = max(0, int(config.get("daily_order_budget") or 0))
    config["per_trade_notional_usd"] = max(0.0, float(config.get("per_trade_notional_usd") or 0.0))
    config["max_portfolio_exposure_pct"] = max(0.0, float(config.get("max_portfolio_exposure_pct") or 0.0))
    allowed = config.get("allowed_strategies")
    config["allowed_strategies"] = (
        [str(item).strip() for item in allowed if str(item).strip()]
        if isinstance(allowed, list)
        else list(DEFAULT_LEARNING_MODE_CONFIG["allowed_strategies"])
    )
    return config


def active_learning_mode(settings: Settings) -> dict[str, Any] | None:
    config = load_learning_mode_config(settings.data_dir / "config" / "learning_mode.json")
    if bool(config.get("enabled")) and bool(config.get("human_gated")):
        return config
    return None


def learning_mode_source(*, settings: Settings, default_source: str) -> str:
    return LEARNING_EXPERIMENT_SOURCE if active_learning_mode(settings) else default_source


def excluded_signal_sources(*, include_lab_book: bool = False, include_learning_experiment: bool = False) -> tuple[str, ...]:
    excluded: list[str] = []
    if not include_lab_book:
        excluded.append("lab_book")
    if not include_learning_experiment:
        excluded.append(LEARNING_EXPERIMENT_SOURCE)
    return tuple(excluded)
