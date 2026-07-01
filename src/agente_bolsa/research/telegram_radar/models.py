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
