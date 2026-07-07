"""Shared data models for the trading agent system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True)
class AgentEvent:
    agent: str
    event_type: str
    payload: dict[str, Any]
    cycle_id: str | None = None
    event_id: str = field(default_factory=lambda: new_id("evt"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class Hypothesis:
    name: str
    description: str
    symbols: list[str]
    entry_rule: str
    exit_rule: str
    invalidation_rule: str
    horizon: str
    status: str = "research"
    hypothesis_id: str = field(default_factory=lambda: new_id("hyp"))
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    checks: dict[str, Any]


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float
    current_price: float
    unrealized_pl: float
    unrealized_plpc: float
    side: str = "long"


@dataclass(frozen=True)
class OrderSnapshot:
    order_id: str
    symbol: str
    side: str
    qty: float | None
    notional: float | None
    order_type: str
    status: str
    submitted_at: str | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    account_id: str
    status: str
    currency: str
    cash: float
    portfolio_value: float
    buying_power: float
    positions: list[PositionSnapshot]
    open_orders: list[OrderSnapshot]


@dataclass(frozen=True)
class TradeRecommendation:
    symbol: str
    action: str
    confidence: float
    reason: str
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    target_exposure_pct: float | None = None
    time_horizon: str | None = None
    invalidation: str | None = None
    source: str = "llm"
    aggressiveness_profile: str | None = None
    micro_experiment: bool = False
    size_multiplier: float = 1.0
    backtest_soft_override: bool = False
    soft_override_reasons: list[str] = field(default_factory=list)
    cohort: str | None = None


@dataclass(frozen=True)
class OrderPlan:
    symbol: str
    side: str
    notional: float
    qty: float | None
    entry_price: float
    stop_loss: float
    take_profit: float
    recommendation: TradeRecommendation
    risk_decision: RiskDecision
    dry_run: bool = True
    aggressiveness_profile: str | None = None
    micro_experiment: bool = False
    size_multiplier: float = 1.0
    backtest_soft_override: bool = False
    soft_override_reasons: list[str] = field(default_factory=list)
    cohort: str | None = None
