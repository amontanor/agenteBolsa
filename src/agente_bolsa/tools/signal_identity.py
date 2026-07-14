"""Canonical, transport-only signal identity helpers.

The producer owns the concrete value.  Consumers must carry it verbatim and
must never reconstruct it from a symbol or an inferred strategy.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


def _slug(value: Any) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").upper()).strip("_")


def _date_text(value: Any) -> str:
    text = str(value or "")
    return text[:10] if text else datetime.now(timezone.utc).date().isoformat()


def canonical_signal_id(source: str, candidate: Mapping[str, Any]) -> str:
    """Build the stable ID only at signal production time."""
    return ":".join(
        (
            str(source),
            _date_text(candidate.get("last_date") or (candidate.get("technical_state") or {}).get("last_date")),
            _slug(candidate.get("strategy_name") or "unknown"),
            _slug(candidate.get("symbol")),
        )
    )


def canonical_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Read producer identity without manufacturing a replacement."""
    return {
        "signal_id": str(candidate.get("signal_id") or "").strip() or None,
        "signal_source_run_id": str(candidate.get("signal_source_run_id") or "").strip() or None,
        "signal_strategy_name": str(candidate.get("signal_strategy_name") or candidate.get("strategy_name") or "").strip() or None,
        "signal_strategy_version": str(candidate.get("signal_strategy_version") or candidate.get("strategy_version") or "").strip() or None,
    }
