"""Transaction cost model for strategy validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionCostModel:
    commission_bps: float = 3.0
    slippage_bps: float = 5.0

    @property
    def round_trip_bps(self) -> float:
        return 2 * (self.commission_bps + self.slippage_bps)

    def one_way_cost(self, notional: float) -> float:
        return notional * ((self.commission_bps + self.slippage_bps) / 10_000)

    def round_trip_cost(self, notional: float) -> float:
        return notional * (self.round_trip_bps / 10_000)

    def net_return(self, gross_return: float) -> float:
        return gross_return - (self.round_trip_bps / 10_000)
