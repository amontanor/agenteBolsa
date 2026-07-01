"""Data models for Telegram radar research artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TelegramPost:
    message_id: int
    posted_at: str | None
    author: str | None
    text: str
    links: list[str]
    raw_html_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelegramExtraction:
    message_id: int
    extraction_status: str
    is_opportunity: bool
    tickers: list[str]
    direction: str
    thesis: str
    timeframe: str | None
    confidence: float
    unresolved_mentions: list[str] = field(default_factory=list)
    ticker_coverage: list[dict[str, Any]] = field(default_factory=list)
    llm_error: str | None = None
    llm_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelegramGateVerdict:
    message_id: int
    ticker: str
    posted_at: str | None
    direction: str
    our_gate: str
    reasons: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelegramScorecardRow:
    message_id: int
    ticker: str
    posted_at: str | None
    direction: str
    horizon_days: int
    cost_bps: float
    in_universe: bool
    out_of_coverage: bool
    status: str
    entry_date: str | None
    exit_date: str | None
    ticker_return: float | None
    spy_return: float | None
    signal_return_net: float | None
    excess_vs_spy: float | None
    beta_adjusted_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
