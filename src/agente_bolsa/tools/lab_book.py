"""Log-only laboratory book for tiny hypothetical trade samples."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.logging_utils import log_system_event
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .technical_study import build_closed_market_technical_study
from .universe import resolve_study_universe

DEFAULT_LAB_BOOK_CONFIG = {
    "enabled": False,
    "mode": "log_only",
    "fixed_notional": 200.0,
    "daily_cap": 10,
    "candidate_sources": ["all_candidates", "shadow_candidates"],
    "allowed_directions": ["long"],
    "default_stop_pct": 0.05,
    "default_take_profit_pct": 0.10,
    "max_universe_symbols": 0,
}
DEFAULT_LAB_BOOK_CONFIG_PATH = Path("data/config/lab_book.json")
LAB_BOOK_SOURCE = "lab_book"


@dataclass(frozen=True)
class LabBookConfig:
    enabled: bool = False
    mode: str = "log_only"
    fixed_notional: float = 200.0
    daily_cap: int = 10
    candidate_sources: tuple[str, ...] = ("all_candidates", "shadow_candidates")
    allowed_directions: tuple[str, ...] = ("long",)
    default_stop_pct: float = 0.05
    default_take_profit_pct: float = 0.10
    max_universe_symbols: int = 0


def load_lab_book_config(config_path: Path, *, create: bool = True) -> LabBookConfig:
    if create and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(DEFAULT_LAB_BOOK_CONFIG, indent=2) + "\n", encoding="utf-8")
    payload = dict(DEFAULT_LAB_BOOK_CONFIG)
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"Configuracion lab book invalida: {config_path}")
        payload.update(raw)
    return LabBookConfig(
        enabled=bool(payload.get("enabled")),
        mode=str(payload.get("mode") or "log_only"),
        fixed_notional=max(0.0, float(payload.get("fixed_notional", 200.0))),
        daily_cap=max(0, int(payload.get("daily_cap", 10))),
        candidate_sources=tuple(str(item) for item in payload.get("candidate_sources") or ()),
        allowed_directions=tuple(str(item).lower() for item in payload.get("allowed_directions") or ()),
        default_stop_pct=max(0.0, float(payload.get("default_stop_pct", 0.05))),
        default_take_profit_pct=max(0.0, float(payload.get("default_take_profit_pct", 0.10))),
        max_universe_symbols=max(0, int(payload.get("max_universe_symbols", 0))),
    )


def run_lab_book_once(
    settings: Settings,
    store: Store,
    *,
    config_path: Path | None = None,
    report_builder: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config_path = config_path or settings.data_dir / "config" / "lab_book.json"
    config = load_lab_book_config(config_path)
    if config.mode != "log_only":
        raise ValueError("lab_book solo implementa mode='log_only' en esta entrega.")
    if not config.enabled:
        result = {
            "ok": True,
            "status": "disabled",
            "mode": config.mode,
            "recorded": 0,
            "orders_submitted": 0,
            "config_path": str(config_path),
        }
        log_system_event(settings.logs_dir, "lab_book_run", result)
        return result

    source_report = report_builder() if report_builder is not None else _build_source_report(settings, store, config)
    rows = build_lab_book_signal_rows(source_report, config=config)
    store.save_signal_outcomes_bulk(rows)
    result = {
        "ok": True,
        "status": "recorded",
        "mode": config.mode,
        "recorded": len(rows),
        "orders_submitted": 0,
        "source_run_id": source_report.get("run_id"),
        "symbols": [row["symbol"] for row in rows],
        "config_path": str(config_path),
    }
    log_system_event(settings.logs_dir, "lab_book_run", result)
    return result


def build_lab_book_signal_rows(report: dict[str, Any], *, config: LabBookConfig) -> list[dict[str, Any]]:
    run_id = str(report.get("run_id") or new_id("lab_book"))
    selected = select_lab_book_candidates(report, config=config)
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(selected, start=1):
        symbol = str(candidate.get("symbol") or "").upper()
        signal_date = _signal_date(candidate, report)
        entry_price = _entry_price(candidate)
        stop_loss = _stop_loss(candidate, entry_price=entry_price, config=config)
        take_profit = _take_profit(candidate, entry_price=entry_price, config=config)
        features = {
            "source": LAB_BOOK_SOURCE,
            "lab_book": True,
            "lab_book_mode": config.mode,
            "fixed_notional": round(config.fixed_notional, 2),
            "hypothetical_notional": round(config.fixed_notional, 2),
            "daily_cap": config.daily_cap,
            "source_rank": rank,
            "source_run_id": run_id,
            "candidate_source": candidate.get("_lab_candidate_source"),
            "direction": candidate.get("direction"),
            "score": _as_float(candidate.get("score")),
            "setup_name": candidate.get("setup_name"),
            "strategy_name": candidate.get("strategy_name") or "unknown",
            "strategy_status": candidate.get("strategy_status"),
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "selected_for_llm": False,
            "affects_real_book": False,
            "promotion_eligible_without_oos": False,
            "technical_state": candidate.get("technical_state") or {},
        }
        rows.append(
            {
                "signal_id": f"{LAB_BOOK_SOURCE}:{signal_date}:{symbol}",
                "source_run_id": run_id,
                "source": LAB_BOOK_SOURCE,
                "symbol": symbol,
                "signal_date": signal_date,
                "decision": "candidate",
                "features": features,
                "gate": {
                    "source": LAB_BOOK_SOURCE,
                    "mode": config.mode,
                    "executed_buy": False,
                    "orders_disabled": True,
                    "affects_real_book": False,
                    "promotion_eligible_without_oos": False,
                },
                "outcome": {},
            }
        )
    return rows


def select_lab_book_candidates(report: dict[str, Any], *, config: LabBookConfig) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source_name in config.candidate_sources:
        for item in list(report.get(source_name, []) or []):
            if not isinstance(item, dict):
                continue
            candidates.append({**item, "_lab_candidate_source": source_name})
    allowed = {direction.lower() for direction in config.allowed_directions}
    filtered = [
        item
        for item in candidates
        if str(item.get("symbol") or "").strip()
        and str(item.get("direction") or "").lower() in allowed
        and _entry_price(item) is not None
    ]
    filtered.sort(key=lambda item: (_as_float(item.get("score")) or 0.0), reverse=True)
    unique_by_symbol: dict[str, dict[str, Any]] = {}
    for item in filtered:
        symbol = str(item.get("symbol") or "").upper()
        unique_by_symbol.setdefault(symbol, item)
    return list(unique_by_symbol.values())[: config.daily_cap]


def _build_source_report(settings: Settings, store: Store, config: LabBookConfig) -> dict[str, Any]:
    symbols = resolve_study_universe(
        settings.closed_market_study_universe,
        settings.universe,
        max_symbols=config.max_universe_symbols or int(settings.closed_market_study_max_symbols),
        cache_dir=settings.data_dir,
    )
    return build_closed_market_technical_study(
        symbols,
        settings.data_dir / "reports",
        new_id("lab_book_source"),
        top_n=max(config.daily_cap, 10),
        store=store,
    )


def _signal_date(candidate: dict[str, Any], report: dict[str, Any]) -> str:
    for value in (
        candidate.get("last_date"),
        (candidate.get("technical_state") or {}).get("last_date"),
        report.get("as_of"),
        report.get("date"),
    ):
        text = str(value or "")
        if text:
            return text[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _entry_price(candidate: dict[str, Any]) -> float | None:
    risk = candidate.get("risk_plan") or {}
    technical = candidate.get("technical_state") or {}
    return _as_float(risk.get("entry_price")) or _as_float(technical.get("close"))


def _stop_loss(candidate: dict[str, Any], *, entry_price: float | None, config: LabBookConfig) -> float | None:
    value = _as_float((candidate.get("risk_plan") or {}).get("stop_loss"))
    if value is not None:
        return value
    return round(entry_price * (1.0 - config.default_stop_pct), 4) if entry_price else None


def _take_profit(candidate: dict[str, Any], *, entry_price: float | None, config: LabBookConfig) -> float | None:
    value = _as_float((candidate.get("risk_plan") or {}).get("take_profit"))
    if value is not None:
        return value
    return round(entry_price * (1.0 + config.default_take_profit_pct), 4) if entry_price else None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
