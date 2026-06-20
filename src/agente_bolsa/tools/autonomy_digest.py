"""Dashboard de autonomia: digest y freno humano (T4.2).

El humano observa, no aprueba. `build_autonomy_digest` resume en un vistazo que
ha cambiado el sistema, que se promovio y que se revirtio. `pause_all` es el
boton rojo: activa el kill switch persistente, congela el laboratorio y cancela
ordenes abiertas; `resume_all` lo deshace.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


LAB_ENABLED_KEY = "continuous_improvement_enabled"


def _llm_cost_today(settings: Settings) -> float:
    from ..llm_usage import today_llm_spend

    return today_llm_spend(settings)


def collect_autonomy_state(store: Store, settings: Settings) -> dict[str, Any]:
    """Reune el estado de autonomia para el dashboard y el digest."""

    def _safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 - el digest nunca debe romper.
            return default

    applied = _safe(lambda: store.continuous_improvement_applied_changes(limit=1000), [])
    perf = _safe(lambda: store.performance_daily(limit=0), [])
    latest_perf = perf[-1] if perf else {}
    try:
        from ..continuous_improvement.autonomy import active_autonomy_level

        level = active_autonomy_level(store, settings)
    except Exception:  # noqa: BLE001
        level = 1
    return {
        "autonomy_level": level,
        "applied": sum(1 for c in applied if c.get("status") == "APPLIED"),
        "rolled_back": sum(1 for c in applied if c.get("status") == "ROLLED_BACK"),
        "rejected_by_tests": sum(1 for c in applied if c.get("status") == "REJECTED_BY_TESTS"),
        "promotions_open": len(_safe(lambda: store.promotion_windows(status="OPEN"), [])),
        "dynamic_agents": len(_safe(lambda: store.agent_definitions(status="ACTIVE"), [])),
        "active_lessons": len(_safe(lambda: store.distilled_lessons(status="ACTIVE"), [])),
        "market_thesis": _safe(lambda: store.latest_market_thesis(), None),
        "iq_score": latest_perf.get("iq_score"),
        "equity": latest_perf.get("equity"),
        "alpha": latest_perf.get("alpha"),
        "result_metrics": (latest_perf.get("payload") or {}).get("result_metrics", {}),
        "process_metrics": (latest_perf.get("payload") or {}).get("process_metrics", {}),
        "llm_cost_today_usd": _safe(lambda: _llm_cost_today(settings), 0.0),
        "pnl_pct_today": latest_perf.get("pnl_pct"),
        "lab_enabled": _safe(lambda: store.get_runtime_value(LAB_ENABLED_KEY), None),
        # Flujo del laboratorio (Etapa 7): WIP, edades y throughput. Si
        # oldest_open_days crece sin parar, el lab acumula en vez de terminar.
        "lab_flow": _safe(lambda: _lab_flow(store), {}),
    }


def _lab_flow(store: Store) -> dict[str, Any]:
    from ..continuous_improvement.lifecycle import flow_report

    return flow_report(store)


def build_autonomy_digest(store: Store, settings: Settings) -> dict[str, Any]:
    """Genera el digest diario de autonomia (markdown) y lo guarda."""

    state = collect_autonomy_state(store, settings)
    thesis = state.get("market_thesis") or {}
    date = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"# Digest de autonomia — {date}",
        "",
        f"- Nivel de autonomia de codigo: **{state['autonomy_level']}**",
        f"- Cambios aplicados: {state['applied']} | revertidos: {state['rolled_back']} | rechazados por tests: {state['rejected_by_tests']}",
        f"- Promociones de estrategia en curso: {state['promotions_open']}",
        f"- Agentes dinamicos activos: {state['dynamic_agents']} | lecciones activas: {state['active_lessons']}",
        f"- iq_score: {state['iq_score']} | equity: {state['equity']} | alpha: {state['alpha']}",
        f"- Tesis de mercado: stance={thesis.get('stance')} (confidence={thesis.get('confidence')})",
        "",
        "## El proceso no es el resultado (T5.3)",
        f"- RESULTADO: {state.get('result_metrics')}",
        f"- PROCESO: {state.get('process_metrics')}",
        f"- Coste LLM hoy: ${state.get('llm_cost_today_usd')} | PnL del dia: {state.get('pnl_pct_today')} (T5.9)",
    ]
    digest_md = "\n".join(lines)
    path = settings.data_dir / "reports" / f"autonomy_digest_{date}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest_md, encoding="utf-8")
    except OSError:
        path = None  # type: ignore[assignment]
    return {"date": date, "markdown": digest_md, "path": str(path) if path else None, "state": state}


def pause_all(store: Store, settings: Settings, *, reason: str = "pausa manual desde dashboard") -> dict[str, Any]:
    """Boton rojo: kill switch + congelar laboratorio + cancelar ordenes (T4.2)."""

    actions: dict[str, Any] = {}
    try:
        from .operational_health import activate_persistent_kill_switch

        activate_persistent_kill_switch(settings.data_dir, reason=reason, kind="manual_pause")
        actions["kill_switch"] = "activado"
    except Exception as exc:  # noqa: BLE001
        actions["kill_switch_error"] = repr(exc)
    try:
        store.set_runtime_value(LAB_ENABLED_KEY, False)
        actions["lab"] = "congelado"
    except Exception as exc:  # noqa: BLE001
        actions["lab_error"] = repr(exc)
    actions["cancelled_orders"] = _cancel_open_orders(settings)
    return {"paused": True, "actions": actions}


def resume_all(store: Store, settings: Settings) -> dict[str, Any]:
    actions: dict[str, Any] = {}
    try:
        from .operational_health import clear_persistent_kill_switch

        cleared = clear_persistent_kill_switch(settings.data_dir)
        actions["kill_switch"] = "desactivado" if cleared else "no_estaba_activo"
    except Exception as exc:  # noqa: BLE001
        actions["kill_switch_error"] = repr(exc)
    try:
        store.set_runtime_value(LAB_ENABLED_KEY, True)
        actions["lab"] = "reactivado"
    except Exception as exc:  # noqa: BLE001
        actions["lab_error"] = repr(exc)
    return {"resumed": True, "actions": actions}


def _cancel_open_orders(settings: Settings) -> int:
    """Cancela ordenes abiertas en el broker (best-effort)."""

    try:
        from .broker import BrokerClientFactory

        client = BrokerClientFactory(settings).alpaca_trading_client()
        cancel_all = getattr(client, "cancel_orders", None)
        if callable(cancel_all):
            result = cancel_all()
            return len(result) if isinstance(result, (list, tuple)) else 1
    except Exception:  # noqa: BLE001 - cancelar es best-effort.
        return 0
    return 0
