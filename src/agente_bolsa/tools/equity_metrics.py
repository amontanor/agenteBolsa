"""Provider-neutral equity metrics shared by presentation and notifications."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def daily_equity_change(
    current_equity: Any,
    previous_close_equity: Any,
    *,
    previous_close_at: str | None = None,
    as_of: str | None = None,
    source: str = "Alpaca account.last_equity",
    cashflow_note: str = "Variación de equity sin ajuste por flujos externos.",
) -> dict[str, Any]:
    """Calculate the canonical previous-close-to-now equity variation.

    ``previous_close_equity`` is deliberately required.  Callers must not
    silently replace Alpaca's official ``last_equity`` with exposure,
    position percentages, trade history, or an opening interval.
    """

    current = _finite(current_equity)
    previous = _finite(previous_close_equity)
    reason: str | None = None
    if current is None:
        reason = "current_equity_unavailable"
    elif previous is None:
        reason = "previous_close_equity_unavailable"
    elif previous <= 0:
        reason = "previous_close_equity_invalid"

    if reason is not None:
        return {
            "status": "unavailable",
            "reason": reason,
            "daily_equity_pl": None,
            "daily_equity_return": None,
            "pl": None,
            "pl_pct": None,
            "current_equity": current,
            "previous_close_equity": previous,
            "window_start": previous_close_at,
            "window_end": as_of,
            "source": source if previous is not None else None,
            "cashflow_note": cashflow_note,
        }

    amount = round(current - previous, 2)
    return_pct = (current - previous) / previous
    return {
        "status": "available",
        "reason": None,
        "daily_equity_pl": amount,
        "daily_equity_return": return_pct,
        "pl": amount,
        "pl_pct": return_pct,
        "current_equity": current,
        "previous_close_equity": previous,
        "window_start": previous_close_at,
        "window_end": as_of,
        "source": source,
        "cashflow_note": cashflow_note,
    }


def position_intraday_pl_reconciliation(positions: Iterable[Any] | None) -> dict[str, Any]:
    """Return a secondary, coverage-aware sum of position intraday P/L."""

    items = list(positions or [])
    values: list[float] = []
    for position in items:
        value = position.get("unrealized_intraday_pl") if isinstance(position, Mapping) else getattr(position, "unrealized_intraday_pl", None)
        finite = _finite(value)
        if finite is not None:
            values.append(finite)
    known = len(values)
    total = len(items)
    status = "complete" if known == total else "partial" if known else "unavailable"
    return {
        "amount": round(sum(values), 4) if values else None if total else 0.0,
        "known": known,
        "total": total,
        "status": status,
        "source": "portfolio_snapshot",
    }

