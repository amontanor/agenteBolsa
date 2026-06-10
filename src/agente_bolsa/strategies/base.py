"""Interfaz base de estrategias plugables (T1.2).

Un `Strategy` produce candidatos (`CandidateSignal`) a partir de un contexto de
mercado. `CandidateSignal` reutiliza el formato de candidato de
`technical_study.py` (mismas claves: symbol, direction, score, setup_quality,
technical_state, risk_plan, ...) para que los gates y `signal_learning` sigan
funcionando sin cambios. Por eso no es una clase rigida sino un alias de `dict`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Un candidato es el mismo dict que produce validate_symbol_technical_state.
CandidateSignal = dict[str, Any]


@dataclass(frozen=True)
class MarketContext:
    """Datos compartidos que una estrategia necesita para generar candidatos.

    `data` es el DataFrame de precios diarios (posiblemente multi-simbolo) ya
    descargado por el pipeline; `market_state` es el estado de mercado/regimen.
    """

    symbols: list[str]
    data: Any = None
    multi_symbol: bool = False
    benchmark_return_20d: float | None = None
    market_state: dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    """Contrato minimo de una estrategia."""

    #: Identificador estable de la estrategia.
    name: str = "strategy"
    #: Version semantica o incremental.
    version: str = "1"
    #: ACTIVE | SHADOW | RETIRED (lo fija el registry desde strategy_versions).
    status: str = "ACTIVE"
    #: Dias de historia que necesita para calcular sus features.
    required_history_days: int = 420

    @abstractmethod
    def generate_candidates(self, context: MarketContext) -> list[CandidateSignal]:
        """Devuelve la lista de candidatos para el universo del contexto."""

    def exit_rules(self, position: dict[str, Any]) -> dict[str, Any]:
        """Plan de salida por defecto: stop/take del propio candidato."""

        return {
            "policy": "atr_stop_or_time",
            "time_stop_sessions": 10,
            "source": self.name,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "required_history_days": self.required_history_days,
        }
