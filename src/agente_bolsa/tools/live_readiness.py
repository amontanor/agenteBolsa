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


def _autonomous_metrics(settings: Settings, store: Store) -> dict[str, Any]:
    """Metricas automaticas del ciclo autonomo para el semaforo a live (T4.3)."""

    rows = store.performance_daily(limit=0)
    sessions = len(rows)
    alpha_cum = sum(r["alpha"] for r in rows if isinstance(r.get("alpha"), (int, float)))
    last = rows[-1] if rows else {}
    sharpe60 = last.get("sharpe_60") if isinstance(last.get("sharpe_60"), (int, float)) else None
    max_dd = max((r["max_dd"] for r in rows if isinstance(r.get("max_dd"), (int, float))), default=None)

    applied = store.continuous_improvement_applied_changes(limit=1000)
    applied_n = sum(1 for c in applied if c.get("status") == "APPLIED")
    rolled = sum(
        1
        for c in applied
        if c.get("status") == "ROLLED_BACK" and str(((c.get("decision") or {}).get("rollback_actor"))) == "change_watchdog"
    )
    total_changes = applied_n + rolled
    rollback_ratio = (rolled / total_changes) if total_changes else 0.0

    try:
        from agente_bolsa.kernel import kernel_integrity

        integrity = kernel_integrity(settings)
        kernel_violations = len(integrity.get("violations", []))
    except Exception:  # noqa: BLE001
        kernel_violations = 0

    return {
        "sessions": sessions,
        "alpha_cum": round(alpha_cum, 6),
        "sharpe_60": sharpe60,
        "max_drawdown": max_dd,
        "rollback_ratio": round(rollback_ratio, 4),
        "kernel_violations": kernel_violations,
    }


def _append_autonomous_criteria(settings: Settings, store: Store, checks: list[dict[str, Any]]) -> None:
    metrics = _autonomous_metrics(settings, store)
    _check(
        checks,
        "paper_sessions_60",
        "pass" if metrics["sessions"] >= 60 else "block",
        f"{metrics['sessions']} sesiones de paper con ciclo autonomo (minimo 60).",
        {"sessions": metrics["sessions"]},
    )
    _check(
        checks,
        "alpha_vs_spy_positive",
        "pass" if metrics["alpha_cum"] > 0 else "block",
        f"alpha_vs_spy acumulado = {metrics['alpha_cum']} (debe ser > 0).",
        {"alpha_cum": metrics["alpha_cum"]},
    )
    _check(
        checks,
        "sharpe_60_above_0_8",
        "pass" if isinstance(metrics["sharpe_60"], (int, float)) and metrics["sharpe_60"] > 0.8 else "block",
        f"Sharpe 60 sesiones = {metrics['sharpe_60']} (debe ser > 0.8).",
        {"sharpe_60": metrics["sharpe_60"]},
    )
    _check(
        checks,
        "max_drawdown_below_12",
        "pass" if isinstance(metrics["max_drawdown"], (int, float)) and metrics["max_drawdown"] < 0.12 else "block",
        f"max drawdown = {metrics['max_drawdown']} (debe ser < 0.12).",
        {"max_drawdown": metrics["max_drawdown"]},
    )
    _check(
        checks,
        "watchdog_rollbacks_below_10pct",
        "pass" if metrics["rollback_ratio"] < 0.10 else "block",
        f"ratio de rollbacks del watchdog = {metrics['rollback_ratio']} (debe ser < 0.10).",
        {"rollback_ratio": metrics["rollback_ratio"]},
    )
    _check(
        checks,
        "zero_kernel_violations",
        "pass" if metrics["kernel_violations"] == 0 else "block",
        f"violaciones de integridad del kernel = {metrics['kernel_violations']} (debe ser 0).",
        {"kernel_violations": metrics["kernel_violations"]},
    )


def live_capital_recommendation(settings: Settings, store: Store) -> dict[str, Any]:
    """Recomienda la fraccion de capital live; des-escala automaticamente (T4.3).

    Reducir riesgo nunca requiere aprobacion: una semana con perdida > 3% recorta
    la fraccion a la mitad. Subirla es decision humana (solo se recomienda).
    """

    base = float(getattr(settings, "live_capital_fraction", 0.10))
    rows = store.performance_daily(limit=0)[-5:]
    week_pnl = sum(r["pnl_pct"] for r in rows if isinstance(r.get("pnl_pct"), (int, float)))
    recommended = base
    reason = "sin cambios"
    if week_pnl < -0.03:
        recommended = round(base / 2.0, 4)
        reason = f"semana con perdida {week_pnl:.4f} > 3%: des-escalado automatico a la mitad"
    return {"current_fraction": base, "recommended_fraction": recommended, "week_pnl_pct": round(week_pnl, 4), "reason": reason}


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

    formal_data = settings.market_data_provider == "fmp" or (
        settings.market_data_provider == "auto" and bool(settings.fmp_api_key)
    )
    _check(
        checks,
        "market_data_provider",
        "pass" if formal_data else "block",
        "Proveedor de datos formal configurado."
        if formal_data
        else "Live requiere proveedor formal: FMP_API_KEY o MARKET_DATA_PROVIDER=fmp.",
        {"market_data_provider": settings.market_data_provider, "fmp_api_key_set": bool(settings.fmp_api_key)},
    )

    operational_block = load_operational_block_context(settings.data_dir)
    _check(
        checks,
        "operational_alerts",
        "block" if operational_block.get("block_buy_execution") else "pass",
        "Alertas operativas criticas activas." if operational_block.get("block_buy_execution") else "Sin alertas operativas bloqueantes.",
        {"reasons": operational_block.get("reasons", [])[:5]},
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

    latest_digest = _latest_json(reports_root / "latest_daily_learning_digest.json")
    _check(
        checks,
        "daily_learning_digest",
        "pass" if latest_digest.get("available") else "warn",
        "Digest diario de aprendizaje disponible."
        if latest_digest.get("available")
        else "No hay latest_daily_learning_digest.json disponible.",
        {"path": latest_digest.get("path")},
    )

    # Criterios automaticos del ciclo autonomo (T4.3).
    _append_autonomous_criteria(settings, store, checks)

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
        "required_before_live": blockers,
        "warnings": warnings,
        "capital_recommendation": live_capital_recommendation(settings, store),
    }
    return write_json_report(report, reports_dir, "live_readiness", run_id, latest_filename="latest_live_readiness.json")
