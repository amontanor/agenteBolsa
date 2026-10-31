"""P-L186: ventana de earnings compartida por el largo y el corto.

El calendario procede del ultimo report ``pre_earnings`` ya publicado. Ausencia
de dato significa ``unavailable``: nunca se asume "sin earnings".
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def earnings_days_by_symbol(data_dir: Path) -> dict[str, int]:
    path = Path(data_dir) / "reports" / "latest_pre_earnings.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    today = date.today()
    result: dict[str, int] = {}
    for item in payload.get("predictions", []) or payload.get("symbols", []) or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        earnings_date = str(item.get("earnings_date") or item.get("date") or "")
        if not symbol or len(earnings_date) < 10:
            continue
        try:
            days = (date.fromisoformat(earnings_date[:10]) - today).days
        except ValueError:
            continue
        if days >= 0:
            result[symbol] = days
    return result


def earnings_blackout(
    symbol: str,
    *,
    days_by_symbol: dict[str, int],
    blackout_days: int,
) -> dict[str, Any]:
    """Return the short-entry blackout evidence for one symbol.

    ``known=False`` means the calendar did not cover the symbol. The caller
    decides whether an unknown calendar blocks; the default policy for shorts is
    to require explicit knowledge only when the report exists.
    """

    days = days_by_symbol.get(str(symbol or "").upper())
    if days is None:
        return {"known": False, "days_to_earnings": None, "blackout": False}
    return {
        "known": True,
        "days_to_earnings": days,
        "blackout": days <= max(0, int(blackout_days)),
    }
