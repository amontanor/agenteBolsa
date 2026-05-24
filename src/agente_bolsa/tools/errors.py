"""Typed operational errors for robust job diagnostics."""

from __future__ import annotations


class AgenteBolsaError(RuntimeError):
    """Base class for operational errors."""


class MarketDataError(AgenteBolsaError):
    """Base class for market data failures."""


class MarketDataFetchError(MarketDataError):
    """Raised when upstream market data cannot be fetched."""


class MarketDataValidationError(MarketDataError):
    """Raised when upstream market data is incomplete or invalid."""


class LLMResponseError(AgenteBolsaError):
    """Raised when an LLM response is malformed or unusable."""


class ReportBuildError(AgenteBolsaError):
    """Raised when a report cannot be built deterministically."""
