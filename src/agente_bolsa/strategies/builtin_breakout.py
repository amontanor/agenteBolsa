"""Estrategia base: breakout/momentum (T1.2).

PRIMERA estrategia del registro. Es un refactor PURO de la logica de candidatos
que vivia en `technical_study.py`: extrae el mismo bucle por simbolo detras de la
interfaz `Strategy`, sin cambiar su comportamiento. Sobre un snapshot fijo, los
candidatos generados son identicos a los del codigo previo (test de regresion).
"""

from __future__ import annotations

from typing import Any

from ..tools.technical_analysis import add_basic_technical_features
from ..tools.technical_state_validator import validate_symbol_technical_state
from .base import CandidateSignal, MarketContext, Strategy


def _symbol_frame(data: Any, symbol: str, multi_symbol: bool):
    if multi_symbol:
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _float(value: Any, precision: int = 4) -> float | None:
    import pandas as pd

    if pd.isna(value):
        return None
    return round(float(value), precision)


def build_breakout_candidate(
    symbol: str,
    features: Any,
    benchmark_return_20d: float | None,
) -> CandidateSignal:
    """Construye un candidato para un simbolo (logica identica a la previa)."""

    candidate = validate_symbol_technical_state(symbol, features)
    symbol_return_20d = _float((candidate.get("technical_state", {}) or {}).get("return_20d"))
    candidate["relative_return_20d"] = (
        round(symbol_return_20d - benchmark_return_20d, 4)
        if symbol_return_20d is not None and benchmark_return_20d is not None
        else None
    )
    return candidate


class BreakoutMomentumStrategy(Strategy):
    name = "builtin_breakout"
    version = "1"
    status = "ACTIVE"
    required_history_days = 420

    def __init__(self) -> None:
        self.last_warnings: list[str] = []

    def generate_candidates(self, context: MarketContext) -> list[CandidateSignal]:
        self.last_warnings = []
        candidates: list[CandidateSignal] = []
        if context.data is None:
            return candidates
        for symbol in context.symbols:
            try:
                frame = _symbol_frame(context.data, symbol, context.multi_symbol)
                if frame.empty:
                    self.last_warnings.append(f"{symbol}: sin datos")
                    continue
                features = add_basic_technical_features(frame)
                candidate = build_breakout_candidate(symbol, features, context.benchmark_return_20d)
                candidates.append(candidate)
            except Exception as exc:  # noqa: BLE001 - un simbolo malo no bloquea el scan.
                self.last_warnings.append(f"{symbol}: {exc}")
        return candidates


def get_strategy() -> Strategy:
    """Factory que el registry usa para instanciar la estrategia."""

    return BreakoutMomentumStrategy()
