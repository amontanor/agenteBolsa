"""Par de cierres SPY con autoridad EOD por sesion XNYS (P-L121).

Observacional y read-only salvo la escritura del recibo por el job
post-sesion. Reutiliza la autoridad EOD de P-L71
(`load_cached_spy_observation`): nunca interpola, nunca reescribe historico
y nunca inventa una sesion ausente. Sin par real de cierres de sesiones
XNYS estrictamente consecutivas, el recibo queda `unavailable` con razones
explicitas; los cierres ausentes son `None`, jamas cero.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .performance_benchmark import (
    load_cached_spy_observation,
    previous_xnys_session,
    session_status,
    xnys_sessions_between,
)

SPY_EOD_RECEIPT_SCHEMA = "p-l121.spy-eod-close.v1"
RECEIPT_PREFIX = "spy_eod_close_"


def _cache_root(settings: Any) -> Path:
    return Path(settings.data_dir) / "cache" / "market_data"


def _stable_hash(payload: dict[str, Any]) -> str:
    stable = deepcopy(payload)
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    stable.pop("receipt_path", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _unavailable(
    session_date: str, previous: str | None, reasons: list[str], *, captured_at: str
) -> dict[str, Any]:
    receipt = {
        "schema_version": SPY_EOD_RECEIPT_SCHEMA,
        "session_date": session_date,
        "previous_session": previous,
        "previous_close": None,
        "close": None,
        "daily_return": None,
        "price_basis": None,
        "interval": "1d",
        "source": None,
        "bars_as_of": None,
        "cache_created_at": None,
        "eod_authority": None,
        "comparison_status": "unavailable",
        "reason_codes": sorted(set(reasons)),
        "captured_at": captured_at,
    }
    receipt["content_hash"] = _stable_hash(receipt)
    return receipt


def build_spy_eod_receipt(settings: Any, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Construye el recibo del par de cierres sin escribir nada."""
    captured = _now(now)
    captured_at = captured.isoformat()
    try:
        previous = previous_xnys_session(session_date)
    except (TypeError, ValueError):
        return _unavailable(session_date, None, ["invalid_session_date"], captured_at=captured_at)
    if previous is None:
        return _unavailable(session_date, None, ["missing_previous_xnys_session"], captured_at=captured_at)
    status, status_warnings = session_status(session_date, now=captured)
    if status != "closed":
        return _unavailable(session_date, previous, list(status_warnings), captured_at=captured_at)
    observation = load_cached_spy_observation(settings, session_date, now=captured)
    if str(observation.get("status")) != "available" or observation.get("daily_return") is None:
        reasons = list(observation.get("warnings") or ["spy_close_pair_unavailable"])
        return _unavailable(session_date, previous, reasons, captured_at=captured_at)
    receipt = {
        "schema_version": SPY_EOD_RECEIPT_SCHEMA,
        "session_date": session_date,
        "previous_session": previous,
        "previous_close": observation.get("previous_close"),
        "close": observation.get("close"),
        "daily_return": observation.get("daily_return"),
        "price_basis": observation.get("price_basis"),
        "interval": observation.get("interval") or "1d",
        "source": observation.get("source"),
        "bars_as_of": observation.get("as_of"),
        "cache_created_at": observation.get("cache_created_at"),
        "eod_authority": observation.get("eod_authority"),
        "comparison_status": "comparable",
        "reason_codes": [],
        "captured_at": captured_at,
    }
    receipt["content_hash"] = _stable_hash(receipt)
    return receipt


def capture_spy_eod_receipt(settings: Any, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Construye y persiste el recibo. Fail-open: nunca lanza por I/O."""
    receipt = build_spy_eod_receipt(settings, session_date, now=now)
    root = _cache_root(settings)
    stem = f"{RECEIPT_PREFIX}{session_date.replace('-', '')}_{receipt['content_hash'][:8]}"
    path = root / f"{stem}.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"persisted": False, "reason": f"receipt_write_failed:{type(exc).__name__}", "receipt": receipt, "path": None}
    return {"persisted": True, "receipt": receipt, "path": str(path)}


def load_spy_eod_receipt(settings: Any, session_date: str) -> dict[str, Any] | None:
    """Lee el recibo mas reciente y lo valida; `None` si no hay valido."""
    root = _cache_root(settings)
    stem = f"{RECEIPT_PREFIX}{session_date.replace('-', '')}_"
    candidates = sorted(root.glob(f"{stem}*.json")) if root.exists() else []
    for path in reversed(candidates):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        if receipt.get("schema_version") != SPY_EOD_RECEIPT_SCHEMA:
            continue
        if str(receipt.get("session_date") or "") != session_date:
            continue
        if receipt.get("content_hash") != _stable_hash(receipt):
            continue
        receipt["receipt_path"] = str(path)
        return receipt
    return None


def spy_eod_coverage(settings: Any, start: str, end: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Cobertura de recibos comparables sobre sesiones XNYS (solo ficheros)."""
    del now
    sessions = xnys_sessions_between(start, end)
    by_session: list[dict[str, Any]] = []
    comparable = 0
    for session_date in sessions:
        receipt = load_spy_eod_receipt(settings, session_date)
        ok = receipt is not None and receipt.get("comparison_status") == "comparable"
        comparable += 1 if ok else 0
        by_session.append(
            {
                "session_date": session_date,
                "comparison_status": receipt.get("comparison_status") if receipt else "unavailable",
                "eod_authority": receipt.get("eod_authority") if receipt else None,
                "reason_codes": list(receipt.get("reason_codes") or []) if receipt else ["receipt_missing"],
            }
        )
    total = len(sessions)
    return {
        "start": start,
        "end": end,
        "denominator": "xnys_sessions",
        "sessions_total": total,
        "sessions_comparable": comparable,
        "sessions_unavailable": total - comparable,
        "provisional": comparable < total,
        "by_session": by_session,
    }

def receipt_as_observation(receipt: dict[str, Any]) -> dict[str, Any]:
    """Expone un recibo comparable con la forma de `load_cached_spy_observation`."""
    return {
        "status": "available",
        "previous_close": receipt.get("previous_close"),
        "close": receipt.get("close"),
        "daily_return": receipt.get("daily_return"),
        "price_basis": receipt.get("price_basis"),
        "source": receipt.get("source"),
        "instrument_label": "SPY (ETF S&P 500)",
        "as_of": receipt.get("bars_as_of"),
        "cache_created_at": receipt.get("cache_created_at"),
        "eod_authority": receipt.get("eod_authority"),
        "interval": receipt.get("interval") or "1d",
        "data_quality": "available",
        "warnings": [],
    }
