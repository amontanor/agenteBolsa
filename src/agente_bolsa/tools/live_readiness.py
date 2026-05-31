"""Live trading readiness checklist."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .operational_health import load_operational_block_context
from .operational_learning import audit_trade_memory_traceability
from .reporting import write_json_report


def _latest_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False, "warning": "json invalido", "path": str(path)}
    return {"available": True, "path": str(path), "payload": payload}


def _check(checks: list[dict[str, Any]], key: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> None:
    checks.append(
        {
            "key": key,
            "status": status,
            "detail": detail,
            "evidence": evidence or {},
        }
    )


def build_live_readiness_report(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str = "2026-04-01",
) -> dict[str, Any]:
    store.ensure_schema()
    reports_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    reports_root = settings.data_dir / "reports"

    _check(
        checks,
        "live_trading_manual_enable",
        "block" if not settings.allow_live_trading else "warn",
        "ALLOW_LIVE_TRADING debe revisarse manualmente antes de operar real."
        if not settings.allow_live_trading
        else "ALLOW_LIVE_TRADING=true; confirmar que esto fue una decision manual reciente.",
        {"trading_mode": settings.trading_mode, "allow_live_trading": settings.allow_live_trading},
    )
    _check(
        checks,
        "human_approval",
        "pass" if settings.require_human_approval else "block",
        "REQUIRE_HUMAN_APPROVAL activo." if settings.require_human_approval else "REQUIRE_HUMAN_APPROVAL=false antes de live.",
        {"require_human_approval": settings.require_human_approval},
    )
    _check(
        checks,
        "operational_kill_switch",
        "pass" if settings.operational_kill_switch_enabled else "block",
        "Kill switch operativo habilitado." if settings.operational_kill_switch_enabled else "Kill switch operativo deshabilitado.",
        {"operational_kill_switch_enabled": settings.operational_kill_switch_enabled},
    )
    operational_block = load_operational_block_context(settings.data_dir)
    _check(
        checks,
        "operational_health_clear",
        "block" if operational_block.get("block_buy_execution") else "pass",
        "Hay alertas criticas activas." if operational_block.get("block_buy_execution") else "No hay bloqueo operativo activo.",
        operational_block,
    )
    official_data = settings.market_data_provider == "fmp" or (
        settings.market_data_provider == "auto" and bool(settings.fmp_api_key)
    )
    _check(
        checks,
        "market_data_provider",
        "pass" if official_data else "block",
        "Proveedor de datos oficial/configurado disponible."
        if official_data
        else "Configurar FMP_API_KEY o MARKET_DATA_PROVIDER=fmp antes de live.",
        {"market_data_provider": settings.market_data_provider, "has_fmp_api_key": bool(settings.fmp_api_key)},
    )
    _check(
        checks,
        "risk_limits",
        "pass"
        if settings.max_risk_per_trade <= 0.01 and settings.max_total_open_risk <= 0.03
        else "warn",
        "Riesgo por trade y riesgo abierto agregado dentro de umbrales conservadores.",
        {
            "max_risk_per_trade": settings.max_risk_per_trade,
            "max_total_open_risk": settings.max_total_open_risk,
            "max_portfolio_exposure": settings.max_portfolio_exposure,
        },
    )
    _check(
        checks,
        "validation_gates",
        "pass" if settings.backtest_gate_enabled and settings.entry_quality_gate_enabled else "block",
        "Backtest gate y entry-quality gate activos."
        if settings.backtest_gate_enabled and settings.entry_quality_gate_enabled
        else "Backtest gate y entry-quality gate deben estar activos antes de live.",
        {
            "backtest_gate_enabled": settings.backtest_gate_enabled,
            "entry_quality_gate_enabled": settings.entry_quality_gate_enabled,
        },
    )
    traceability = audit_trade_memory_traceability(store, since_date=since_date)
    _check(
        checks,
        "fill_signal_traceability",
        "pass" if traceability.get("complete") else "block",
        "Memoria de fills enlazada con ordenes y senales."
        if traceability.get("complete")
        else "Hay fills/memorias con trazabilidad incompleta.",
        traceability,
    )

    latest_backtest = _latest_json(reports_root / "latest_daily_learning_digest.json")
    _check(
        checks,
        "daily_learning_digest",
        "pass" if latest_backtest.get("available") else "warn",
        "Digest diario de aprendizaje disponible."
        if latest_backtest.get("available")
        else "No hay latest_daily_learning_digest.json disponible.",
        {"path": latest_backtest.get("path")},
    )
    latest_operational_learning = _latest_json(reports_root / "latest_operational_learning.json")
    _check(
        checks,
        "operational_learning",
        "pass" if latest_operational_learning.get("available") else "warn",
        "Informe de aprendizaje operativo disponible."
        if latest_operational_learning.get("available")
        else "No hay latest_operational_learning.json disponible.",
        {"path": latest_operational_learning.get("path")},
    )

    blockers = [item for item in checks if item["status"] == "block"]
    warnings = [item for item in checks if item["status"] == "warn"]
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "since_date": since_date,
        "summary": {
            "ready_for_live": not blockers,
            "checks": len(checks),
            "blocks": len(blockers),
            "warnings": len(warnings),
        },
        "checks": checks,
        "required_before_live": [item for item in checks if item["status"] == "block"],
        "warnings": warnings,
    }
    return write_json_report(report, reports_dir, "live_readiness", run_id, latest_filename="latest_live_readiness.json")
