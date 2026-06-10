"""Estrategias plugables (T1.2).

Una estrategia es un artefacto versionado que produce candidatos de trading
detras de una interfaz comun, en vez de logica entrelazada en el pipeline.
"""

from .base import CandidateSignal, MarketContext, Strategy

__all__ = ["Strategy", "CandidateSignal", "MarketContext"]
