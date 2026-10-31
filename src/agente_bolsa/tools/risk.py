"""Risk controls used before any order is allowed.

P-L186: el contrato distingue direccion (long/short) y efecto
(open/close). La geometria de stop/take se invierte para cortos y los
limites de exposicion se separan en libro largo, libro corto y bruto.
Los cierres y reducciones nunca consumen cupo de apertura.
"""

from __future__ import annotations

from dataclasses import dataclass

from agente_bolsa.config import Settings
from agente_bolsa.models import RiskDecision


@dataclass(frozen=True)
class OrderProposal:
    symbol: str
    side: str
    notional: float
    portfolio_equity: float
    strategy_name: str
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    hypothesis_id: str | None = None
    current_portfolio_exposure: float = 0.0
    pending_portfolio_exposure: float = 0.0
    existing_open_risk_amount: float = 0.0
    pending_open_risk_amount: float = 0.0
    direction: str = "long"
    position_effect: str | None = None
    current_short_exposure: float = 0.0
    pending_short_exposure: float = 0.0
    open_short_positions: int = 0
    short_open_risk_amount: float = 0.0


_CLOSE_EFFECTS = frozenset({"close_long", "close_short", "reduce_long", "reduce_short"})


def _effect(proposal: OrderProposal) -> str:
    if proposal.position_effect:
        return proposal.position_effect
    # Legacy: solo largos. Un ``sell`` historico siempre cerraba un largo.
    return "close_long" if proposal.side.lower() == "sell" else "open_long"


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate_order(self, proposal: OrderProposal) -> RiskDecision:
        direction = str(proposal.direction or "long").lower()
        effect = _effect(proposal)
        checks = {
            "trading_mode": self.settings.trading_mode,
            "allow_live_trading": self.settings.allow_live_trading,
            "max_portfolio_exposure": self.settings.max_portfolio_exposure,
            "max_position_exposure": self.settings.max_position_exposure,
            "max_total_open_risk": self.settings.max_total_open_risk,
            "max_short_exposure": self.settings.max_short_exposure,
            "max_short_position_exposure": self.settings.max_short_position_exposure,
            "max_gross_exposure": self.settings.max_gross_exposure,
            "max_open_short_positions": self.settings.max_open_short_positions,
            "max_short_risk_per_trade": self.settings.max_short_risk_per_trade,
            "max_total_short_open_risk": self.settings.max_total_short_open_risk,
            "proposal_notional": proposal.notional,
            "portfolio_equity": proposal.portfolio_equity,
            "direction": direction,
            "position_effect": effect,
        }

        if self.settings.trading_mode == "live" and not self.settings.allow_live_trading:
            return RiskDecision(False, "Live trading no autorizado por configuracion.", checks)

        if proposal.portfolio_equity <= 0:
            return RiskDecision(False, "Portfolio equity invalido.", checks)

        # Un cierre o reduccion reduce riesgo: no consume cupo ni se bloquea por
        # exposicion. El kernel aplica igualmente los cerrojos globales.
        if effect in _CLOSE_EFFECTS:
            checks["close_allowed"] = True
            return RiskDecision(True, "Cierre/reduccion permitido.", checks)

        position_exposure = proposal.notional / proposal.portfolio_equity
        checks["position_exposure"] = position_exposure

        if direction == "short":
            current_short = max(0.0, float(proposal.current_short_exposure))
            pending_short = max(0.0, float(proposal.pending_short_exposure))
            projected_short = current_short + pending_short + position_exposure
            projected_gross = (
                max(0.0, float(proposal.current_portfolio_exposure))
                + max(0.0, float(proposal.pending_portfolio_exposure))
                + current_short
                + pending_short
                + position_exposure
            )
            checks["current_short_exposure"] = current_short
            checks["pending_short_exposure"] = pending_short
            checks["projected_short_exposure"] = projected_short
            checks["projected_gross_exposure"] = projected_gross
            if position_exposure > self.settings.max_short_position_exposure:
                return RiskDecision(False, "El corto supera el limite por activo.", checks)
            if projected_short > self.settings.max_short_exposure:
                return RiskDecision(False, "El libro corto supera el limite agregado.", checks)
            if projected_gross > self.settings.max_gross_exposure:
                return RiskDecision(False, "La cartera supera el limite de exposicion bruta.", checks)
            if int(proposal.open_short_positions) + 1 > int(self.settings.max_open_short_positions):
                return RiskDecision(False, "Supera el maximo de cortos abiertos.", checks)
        else:
            checks["current_portfolio_exposure"] = proposal.current_portfolio_exposure
            checks["pending_portfolio_exposure"] = proposal.pending_portfolio_exposure
            checks["projected_portfolio_exposure"] = (
                proposal.current_portfolio_exposure + proposal.pending_portfolio_exposure + position_exposure
            )
            if position_exposure > self.settings.max_position_exposure:
                return RiskDecision(False, "La posicion supera el limite por activo.", checks)
            if checks["projected_portfolio_exposure"] > self.settings.max_portfolio_exposure:
                return RiskDecision(False, "La cartera supera el limite de exposicion agregada.", checks)

        if proposal.side.lower() not in {"buy", "sell"}:
            return RiskDecision(False, "Lado de orden no permitido.", checks)

        if proposal.entry_price is None or proposal.stop_loss is None or proposal.take_profit is None:
            return RiskDecision(
                False,
                "Faltan entry_price, stop_loss o take_profit. No se permite una orden sin riesgo definido.",
                checks,
            )

        checks.update(
            {
                "entry_price": proposal.entry_price,
                "stop_loss": proposal.stop_loss,
                "take_profit": proposal.take_profit,
            }
        )
        if proposal.entry_price <= 0:
            return RiskDecision(False, "entry_price invalido.", checks)

        if direction == "short":
            if not proposal.take_profit < proposal.entry_price < proposal.stop_loss:
                return RiskDecision(
                    False,
                    "Para cortos, take_profit debe estar bajo entrada y stop_loss sobre entrada.",
                    checks,
                )
            downside = proposal.stop_loss - proposal.entry_price
            upside = proposal.entry_price - proposal.take_profit
        else:
            if not proposal.stop_loss < proposal.entry_price < proposal.take_profit:
                return RiskDecision(
                    False,
                    "Para compras, stop_loss debe estar bajo entrada y take_profit sobre entrada.",
                    checks,
                )
            downside = proposal.entry_price - proposal.stop_loss
            upside = proposal.take_profit - proposal.entry_price

        reward_risk = upside / downside if downside > 0 else 0
        checks["reward_risk"] = reward_risk
        if reward_risk + 1e-9 < 1.5:
            return RiskDecision(False, "Ratio beneficio/riesgo inferior a 1.5.", checks)

        proposed_trade_risk_amount = proposal.notional * (downside / proposal.entry_price)
        checks["proposed_trade_risk_amount"] = proposed_trade_risk_amount

        if direction == "short":
            projected_short_risk = (
                max(0.0, float(proposal.short_open_risk_amount)) + proposed_trade_risk_amount
            )
            checks["short_open_risk_amount"] = max(0.0, float(proposal.short_open_risk_amount))
            checks["projected_short_open_risk_amount"] = projected_short_risk
            checks["projected_short_open_risk_pct"] = (
                projected_short_risk / proposal.portfolio_equity
                if proposal.portfolio_equity > 0
                else 0.0
            )
            if proposed_trade_risk_amount / proposal.portfolio_equity > self.settings.max_short_risk_per_trade:
                return RiskDecision(False, "El riesgo del corto supera el limite por operacion.", checks)
            if checks["projected_short_open_risk_pct"] > self.settings.max_total_short_open_risk:
                return RiskDecision(False, "El riesgo agregado corto supera el limite.", checks)
            return RiskDecision(True, "Corto aprobado por limites iniciales.", checks)

        checks["existing_open_risk_amount"] = proposal.existing_open_risk_amount
        checks["pending_open_risk_amount"] = proposal.pending_open_risk_amount
        checks["projected_total_open_risk_amount"] = (
            proposal.existing_open_risk_amount + proposal.pending_open_risk_amount + proposed_trade_risk_amount
        )
        checks["projected_total_open_risk_pct"] = (
            checks["projected_total_open_risk_amount"] / proposal.portfolio_equity
            if proposal.portfolio_equity > 0
            else 0.0
        )
        if checks["projected_total_open_risk_pct"] > self.settings.max_total_open_risk:
            return RiskDecision(False, "El riesgo agregado abierto supera el limite de cartera.", checks)

        return RiskDecision(True, "Orden aprobada por limites iniciales.", checks)
