"""Risk controls used before any order is allowed."""

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


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate_order(self, proposal: OrderProposal) -> RiskDecision:
        checks = {
            "trading_mode": self.settings.trading_mode,
            "allow_live_trading": self.settings.allow_live_trading,
            "max_position_exposure": self.settings.max_position_exposure,
            "proposal_notional": proposal.notional,
            "portfolio_equity": proposal.portfolio_equity,
        }

        if self.settings.trading_mode == "live" and not self.settings.allow_live_trading:
            return RiskDecision(False, "Live trading no autorizado por configuracion.", checks)

        if proposal.portfolio_equity <= 0:
            return RiskDecision(False, "Portfolio equity invalido.", checks)

        position_exposure = proposal.notional / proposal.portfolio_equity
        checks["position_exposure"] = position_exposure

        if position_exposure > self.settings.max_position_exposure:
            return RiskDecision(False, "La posicion supera el limite por activo.", checks)

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

        if proposal.side.lower() == "buy":
            if not proposal.stop_loss < proposal.entry_price < proposal.take_profit:
                return RiskDecision(
                    False,
                    "Para compras, stop_loss debe estar bajo entrada y take_profit sobre entrada.",
                    checks,
                )
            downside = proposal.entry_price - proposal.stop_loss
            upside = proposal.take_profit - proposal.entry_price
        else:
            if not proposal.take_profit < proposal.entry_price < proposal.stop_loss:
                return RiskDecision(
                    False,
                    "Para ventas, take_profit debe estar bajo entrada y stop_loss sobre entrada.",
                    checks,
                )
            downside = proposal.stop_loss - proposal.entry_price
            upside = proposal.entry_price - proposal.take_profit

        reward_risk = upside / downside if downside > 0 else 0
        checks["reward_risk"] = reward_risk
        if reward_risk + 1e-9 < 1.5:
            return RiskDecision(False, "Ratio beneficio/riesgo inferior a 1.5.", checks)

        return RiskDecision(True, "Orden aprobada por limites iniciales.", checks)
