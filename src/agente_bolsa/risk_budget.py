"""Presupuesto de riesgo como unica correa (T4.1).

En vez de una maraña de gates finos de cantidad, los agentes operan con libertad
mientras el riesgo agregado quepa en un presupuesto simple: VaR diario total,
riesgo nuevo por dia y riesgo por cluster correlacionado (sector). El kernel
(T0.1) sigue siendo el suelo absoluto: el presupuesto se acota a sus limites.

Nucleo stdlib y funciones puras sobre el estado (dict), mas envoltorios que lo
persisten en `runtime_state`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .kernel import KernelLimits

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from .config import Settings
    from .storage import Store


RUNTIME_KEY = "risk_budget_state"


@dataclass(frozen=True)
class RiskBudget:
    daily_var_budget_pct: float = 0.03
    max_new_risk_per_day_pct: float = 0.015
    max_correlated_cluster_pct: float = 0.012

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskBudget:
        limits = KernelLimits()
        # El presupuesto jamas excede el suelo del kernel.
        daily = min(
            float(getattr(settings, "risk_budget_daily_var_pct", 0.03)),
            limits.absolute_max_daily_loss_pct,
        )
        new_risk = min(float(getattr(settings, "risk_budget_max_new_risk_per_day_pct", 0.015)), daily)
        cluster = min(float(getattr(settings, "risk_budget_max_correlated_cluster_pct", 0.012)), daily)
        return cls(daily_var_budget_pct=daily, max_new_risk_per_day_pct=new_risk, max_correlated_cluster_pct=cluster)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def fresh_state() -> dict[str, Any]:
    return {"date": _today(), "open_risk_pct": 0.0, "new_risk_today_pct": 0.0, "by_sector": {}}


def _ensure_today(state: dict[str, Any]) -> dict[str, Any]:
    if not state or state.get("date") != _today():
        # Nuevo dia: el riesgo nuevo diario se reinicia; el riesgo abierto persiste.
        carried = float((state or {}).get("open_risk_pct") or 0.0)
        carried_sector = {k: v for k, v in ((state or {}).get("by_sector") or {}).items()}
        return {"date": _today(), "open_risk_pct": carried, "new_risk_today_pct": 0.0, "by_sector": carried_sector}
    return state


def available(budget: RiskBudget, state: dict[str, Any]) -> dict[str, Any]:
    state = _ensure_today(state)
    return {
        "daily_var_remaining_pct": round(budget.daily_var_budget_pct - float(state.get("open_risk_pct") or 0.0), 6),
        "new_risk_remaining_pct": round(budget.max_new_risk_per_day_pct - float(state.get("new_risk_today_pct") or 0.0), 6),
        "open_risk_pct": float(state.get("open_risk_pct") or 0.0),
        "new_risk_today_pct": float(state.get("new_risk_today_pct") or 0.0),
        "by_sector": dict(state.get("by_sector") or {}),
    }


def can_consume(budget: RiskBudget, state: dict[str, Any], risk_pct: float, sector: str = "unknown") -> tuple[bool, str]:
    state = _ensure_today(state)
    if risk_pct <= 0:
        return True, "sin riesgo nuevo"
    open_risk = float(state.get("open_risk_pct") or 0.0)
    new_today = float(state.get("new_risk_today_pct") or 0.0)
    sector_risk = float((state.get("by_sector") or {}).get(sector) or 0.0)
    if open_risk + risk_pct > budget.daily_var_budget_pct + 1e-9:
        return False, f"excede VaR diario ({open_risk + risk_pct:.4f}>{budget.daily_var_budget_pct:.4f})"
    if new_today + risk_pct > budget.max_new_risk_per_day_pct + 1e-9:
        return False, f"excede riesgo nuevo diario ({new_today + risk_pct:.4f}>{budget.max_new_risk_per_day_pct:.4f})"
    if sector_risk + risk_pct > budget.max_correlated_cluster_pct + 1e-9:
        return False, f"excede cluster sector {sector} ({sector_risk + risk_pct:.4f}>{budget.max_correlated_cluster_pct:.4f})"
    return True, "dentro del presupuesto"


def consume(state: dict[str, Any], risk_pct: float, sector: str = "unknown") -> dict[str, Any]:
    state = _ensure_today(state)
    by_sector = dict(state.get("by_sector") or {})
    by_sector[sector] = round(float(by_sector.get(sector) or 0.0) + risk_pct, 6)
    return {
        "date": state["date"],
        "open_risk_pct": round(float(state.get("open_risk_pct") or 0.0) + risk_pct, 6),
        "new_risk_today_pct": round(float(state.get("new_risk_today_pct") or 0.0) + risk_pct, 6),
        "by_sector": by_sector,
    }


def release(state: dict[str, Any], risk_pct: float, sector: str = "unknown") -> dict[str, Any]:
    state = _ensure_today(state)
    by_sector = dict(state.get("by_sector") or {})
    by_sector[sector] = round(max(0.0, float(by_sector.get(sector) or 0.0) - risk_pct), 6)
    return {
        "date": state["date"],
        "open_risk_pct": round(max(0.0, float(state.get("open_risk_pct") or 0.0) - risk_pct), 6),
        "new_risk_today_pct": float(state.get("new_risk_today_pct") or 0.0),
        "by_sector": by_sector,
    }


# -- envoltorios persistentes ---------------------------------------------
def _plan_risk_pct(plan: dict[str, Any]) -> tuple[float, str]:
    payload = plan.get("payload") or {}
    checks = (payload.get("risk_decision") or {}).get("checks") or {}
    equity = checks.get("portfolio_equity") or payload.get("portfolio_equity")
    risk_amount = checks.get("proposed_trade_risk_amount")
    sector = str(payload.get("sector") or checks.get("sector") or "unknown")
    if isinstance(risk_amount, (int, float)) and isinstance(equity, (int, float)) and equity > 0:
        return float(risk_amount) / float(equity), sector
    pct = checks.get("projected_total_open_risk_pct")
    if isinstance(pct, (int, float)):
        return float(pct), sector
    return 0.0, sector


def check_order(store: Store, settings: Settings, plan: dict[str, Any]) -> tuple[bool, str]:
    """Consulta el presupuesto para una compra; si cabe, lo consume."""

    if not getattr(settings, "risk_budget_enabled", False):
        return True, "risk_budget_disabled"
    budget = RiskBudget.from_settings(settings)
    state = _ensure_today(store.get_runtime_value(RUNTIME_KEY) or fresh_state())
    risk_pct, sector = _plan_risk_pct(plan)
    ok, reason = can_consume(budget, state, risk_pct, sector)
    if ok and risk_pct > 0:
        store.set_runtime_value(RUNTIME_KEY, consume(state, risk_pct, sector))
    else:
        store.set_runtime_value(RUNTIME_KEY, state)
    return ok, reason


def release_position(store: Store, settings: Settings, risk_pct: float, sector: str = "unknown") -> None:
    state = _ensure_today(store.get_runtime_value(RUNTIME_KEY) or fresh_state())
    store.set_runtime_value(RUNTIME_KEY, release(state, risk_pct, sector))


def available_now(store: Store, settings: Settings) -> dict[str, Any]:
    budget = RiskBudget.from_settings(settings)
    state = store.get_runtime_value(RUNTIME_KEY) or fresh_state()
    return {"budget": budget.__dict__, **available(budget, state)}


def risk_budget_throttle(store: Store, settings: Settings, factor: float) -> dict[str, Any]:
    """Ajusta el presupuesto persistido por un factor (>1 amplia, <1 recorta).

    El resultado se acota a los limites del kernel via `RiskBudget.from_settings`
    cuando se reconstruye. Aqui solo persistimos el override propuesto.
    """

    base = RiskBudget.from_settings(settings)
    limits = KernelLimits()
    proposed = {
        "risk_budget_daily_var_pct": min(round(base.daily_var_budget_pct * factor, 6), limits.absolute_max_daily_loss_pct),
        "risk_budget_max_new_risk_per_day_pct": round(base.max_new_risk_per_day_pct * factor, 6),
        "risk_budget_max_correlated_cluster_pct": round(base.max_correlated_cluster_pct * factor, 6),
    }
    store.set_runtime_value("risk_budget_override", {"factor": factor, "proposed": proposed, "at": _today()})
    return proposed
