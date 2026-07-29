"""Canonical opening-to-opening account and SPY performance.

The contract is observational.  It never drives trading and never substitutes
an approximate close or a civil UTC date for an exact XNYS opening timestamp.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pandas as pd

from .performance_benchmark import xnys_sessions_between

if TYPE_CHECKING:
    from ..config import Settings
    from ..storage import Store


SCHEMA_VERSION = "p-l72.session-open-snapshot.v1"
EVENT_TYPE = "session_open_snapshot"
EVENT_ID_PREFIX = "session_open_snapshot:"
MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stable_hash(payload: Mapping[str, Any]) -> str:
    stable = deepcopy(dict(payload))
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _timestamp(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return parsed.astimezone(timezone.utc)


def _session_open_at(session_date: str) -> datetime:
    local = datetime.combine(date.fromisoformat(session_date), time(9, 30), tzinfo=MARKET_TIMEZONE)
    return local.astimezone(timezone.utc)


def _expected_open_session(now: datetime) -> str | None:
    current = now.astimezone(timezone.utc)
    market_date = current.astimezone(MARKET_TIMEZONE).date()
    start = (market_date - timedelta(days=14)).isoformat()
    sessions = xnys_sessions_between(start, market_date.isoformat())
    opened = [session for session in sessions if _session_open_at(session) <= current]
    return opened[-1] if opened else None


def _is_next_xnys_session(start: str, end: str) -> bool:
    sessions = xnys_sessions_between(start, end)
    return len(sessions) == 2 and sessions == [start, end]


def extract_exact_open_snapshots(history: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract only exact 09:30 America/New_York equity observations."""

    by_session: dict[str, dict[str, Any]] = {}
    for raw_timestamp, raw_equity in zip(
        history.get("timestamp") or [],
        history.get("equity") or [],
        strict=False,
    ):
        observed_at = _timestamp(raw_timestamp)
        equity = _finite(raw_equity)
        if observed_at is None or equity is None or equity <= 0:
            continue
        market_time = observed_at.astimezone(MARKET_TIMEZONE)
        if (market_time.hour, market_time.minute, market_time.second) != (9, 30, 0):
            continue
        session_date = market_time.date().isoformat()
        candidate = {
            "session_date": session_date,
            "equity": equity,
            "observed_at": observed_at.isoformat(),
            "source": "alpaca_portfolio_history_15Min",
        }
        previous = by_session.get(session_date)
        if previous is None or str(candidate["observed_at"]) < str(previous["observed_at"]):
            by_session[session_date] = candidate
    return [by_session[key] for key in sorted(by_session)]


def build_session_open_snapshot(observation: Mapping[str, Any], *, captured_at: datetime | None = None) -> dict[str, Any]:
    del captured_at  # agent_events.created_at is the capture time; content remains idempotent.
    session_date = str(observation.get("session_date") or "")
    observed_at = _timestamp(observation.get("observed_at"))
    equity = _finite(observation.get("equity"))
    if not session_date or observed_at is None or equity is None or equity <= 0:
        raise ValueError("exact session opening observation required")
    market_time = observed_at.astimezone(MARKET_TIMEZONE)
    if market_time.date().isoformat() != session_date or (market_time.hour, market_time.minute, market_time.second) != (9, 30, 0):
        raise ValueError("observation is not the exact XNYS opening")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"{EVENT_ID_PREFIX}{session_date}",
        "session_date": session_date,
        "equity": equity,
        "observed_at": observed_at.isoformat(),
        "source": str(observation.get("source") or "alpaca_portfolio_history_15Min"),
    }
    payload["content_hash"] = _stable_hash(payload)
    return payload


def persist_session_open_snapshot(store: Store, payload: Mapping[str, Any]) -> dict[str, Any]:
    return store.record_append_only_event(
        event_id=str(payload["event_id"]),
        event_type=EVENT_TYPE,
        cycle_id=str(payload["session_date"]),
        payload=dict(payload),
    )


def read_session_open_snapshots(store: Store) -> list[dict[str, Any]]:
    canonical: dict[str, dict[str, Any]] = {}
    for event in store.agent_events(event_type_prefix=EVENT_TYPE, limit=5000):
        if event.get("event_type") != EVENT_TYPE:
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
            continue
        session_date = str(payload.get("session_date") or "")
        if str(event.get("event_id") or "") != f"{EVENT_ID_PREFIX}{session_date}":
            continue
        if _stable_hash(payload) != payload.get("content_hash"):
            continue
        try:
            canonical[session_date] = build_session_open_snapshot(payload)
        except ValueError:
            continue
    return [canonical[key] for key in sorted(canonical)]


def merge_account_open_snapshots(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge exact observations; persisted evidence wins over ephemeral history."""

    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for item in source:
            session_date = str(item.get("session_date") or "")
            equity = _finite(item.get("equity"))
            observed_at = _timestamp(item.get("observed_at"))
            if not session_date or equity is None or observed_at is None:
                continue
            merged[session_date] = {
                "session_date": session_date,
                "equity": equity,
                "observed_at": observed_at.isoformat(),
                "source": str(item.get("source") or "unavailable"),
            }
    return [merged[key] for key in sorted(merged)]


def _meta_time(value: Any) -> datetime | None:
    parsed = _timestamp(value)
    return parsed


def _field_series(frame: pd.DataFrame, symbol: str, field: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    wanted_symbol = symbol.upper()
    wanted_field = field.lower()
    matches: list[int] = []
    for index, column in enumerate(frame.columns):
        parts = column if isinstance(column, tuple) else (column,)
        normalized = {str(part).strip().lower() for part in parts}
        if wanted_field not in normalized:
            continue
        if isinstance(frame.columns, pd.MultiIndex) and wanted_symbol.lower() not in normalized:
            continue
        matches.append(index)
    if len(matches) != 1:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame.iloc[:, matches[0]], errors="coerce")


def load_cached_spy_open_observations(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read exact adjusted SPY opens and the newest local price, without network."""

    cache_root = Path(settings.data_dir) / "cache" / "market_data"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    symbol = str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper()
    opens: dict[str, dict[str, Any]] = {}
    current_price: dict[str, Any] | None = None
    for meta_path in cache_root.glob("market_data_*.json") if cache_root.exists() else []:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        symbols = {str(item).upper() for item in meta.get("requested_symbols", [])}
        explicit_symbol = str(meta.get("symbol") or "").upper()
        if symbol not in symbols and explicit_symbol != symbol:
            continue
        created_at = _meta_time(meta.get("created_at"))
        if created_at is None or created_at > current:
            continue
        data_path = meta_path.with_suffix(".pkl")
        try:
            frame = pd.read_pickle(data_path)
        except Exception:
            continue
        interval = str(meta.get("interval") or meta.get("timeframe") or "").lower()
        if interval and interval not in {"1d", "daily", "day"}:
            continue
        if not interval:
            try:
                index = pd.DatetimeIndex(frame.index)
                inferred_daily = len(index) > 1 and all(
                    timestamp.hour == timestamp.minute == timestamp.second == 0
                    for timestamp in index[-min(len(index), 20) :]
                )
            except Exception:
                inferred_daily = False
            if not inferred_daily:
                continue
        basis = str(meta.get("price_basis") or "").lower()
        if not basis and str(meta.get("source") or "").lower() == "yfinance":
            # Historical cache metadata predates P-L71, but the producer has
            # used yfinance(auto_adjust=True) continuously since May 2026.
            basis = "adjusted_ohlc"
        if basis != "adjusted_ohlc":
            continue
        open_series = _field_series(frame, symbol, "Open")
        close_series = _field_series(frame, symbol, "Close")
        source = str(meta.get("source") or "")
        for raw_index, raw_value in open_series.items():
            value = _finite(raw_value)
            try:
                index = pd.Timestamp(raw_index)
            except Exception:
                continue
            if value is None or value <= 0 or pd.isna(index):
                continue
            session_date = (
                index.tz_convert(MARKET_TIMEZONE).date().isoformat()
                if index.tzinfo is not None
                else index.date().isoformat()
            )
            candidate = {
                "session_date": session_date,
                "price": value,
                "observed_at": _session_open_at(session_date).isoformat(),
                "source": source,
                "price_basis": basis,
                "cache_created_at": created_at.isoformat(),
            }
            previous = opens.get(session_date)
            if previous is None or str(candidate["cache_created_at"]) > str(previous["cache_created_at"]):
                opens[session_date] = candidate
        for raw_index, raw_value in close_series.items():
            value = _finite(raw_value)
            try:
                index = pd.Timestamp(raw_index)
            except Exception:
                continue
            if value is None or value <= 0 or pd.isna(index):
                continue
            # A daily cache row is indexed at the civil session date.  Its
            # actual observation time is the cache capture, not midnight.
            observed_at = created_at.isoformat()
            candidate = {
                "price": value,
                "observed_at": observed_at,
                "session_date": (
                    index.tz_convert(MARKET_TIMEZONE).date().isoformat()
                    if index.tzinfo is not None
                    else index.date().isoformat()
                ),
                "source": source,
                "price_basis": basis,
                "cache_created_at": created_at.isoformat(),
            }
            if current_price is None or (str(candidate["session_date"]), str(candidate["cache_created_at"])) > (
                str(current_price["session_date"]),
                str(current_price["cache_created_at"]),
            ):
                current_price = candidate
    return {
        "opens": [opens[key] for key in sorted(opens)],
        "current": current_price,
        "instrument": "SPY (ETF S&P 500)",
    }


def build_open_to_open_rows(
    account_opens: list[dict[str, Any]],
    spy_market: Mapping[str, Any],
    *,
    current_equity: Any = None,
    current_equity_at: datetime | None = None,
    include_current: bool = True,
) -> list[dict[str, Any]]:
    account = {str(item.get("session_date")): item for item in account_opens}
    spy = {str(item.get("session_date")): item for item in spy_market.get("opens") or []}
    sessions = sorted(set(account).intersection(spy))
    rows: list[dict[str, Any]] = []
    for start, end in zip(sessions, sessions[1:], strict=False):
        if not _is_next_xnys_session(start, end):
            continue
        account_start = _finite(account[start].get("equity"))
        account_end = _finite(account[end].get("equity"))
        spy_start = _finite(spy[start].get("price"))
        spy_end = _finite(spy[end].get("price"))
        if None in {account_start, account_end, spy_start, spy_end} or not account_start or not spy_start:
            continue
        if spy[start].get("price_basis") != spy[end].get("price_basis"):
            continue
        rows.append(
            {
                "session_date": start,
                "end_session_date": end,
                "status": "final",
                "system_pct": account_end / account_start - 1.0,
                "system_delta": account_end - account_start,
                "spy_pct": spy_end / spy_start - 1.0,
                "system_start_at": account[start].get("observed_at"),
                "system_end_at": account[end].get("observed_at"),
                "spy_start_at": spy[start].get("observed_at"),
                "spy_end_at": spy[end].get("observed_at"),
                "system_source": account[start].get("source"),
                "spy_source": spy[start].get("source"),
                "price_basis": spy[start].get("price_basis"),
            }
        )
    current_at = (current_equity_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expected_session = _expected_open_session(current_at)
    latest_session = sessions[-1] if sessions and sessions[-1] == expected_session else None
    current_spy = spy_market.get("current") or {}
    current_equity_value = _finite(current_equity)
    current_spy_value = _finite(current_spy.get("price"))
    current_spy_at = _timestamp(current_spy.get("observed_at"))
    if (
        include_current
        and latest_session
        and current_equity_value is not None
        and current_spy_value is not None
        and _finite(account[latest_session].get("equity"))
        and _finite(spy[latest_session].get("price"))
        and current_spy.get("price_basis") == spy[latest_session].get("price_basis")
        and current_spy_at is not None
        and _session_open_at(latest_session) <= current_spy_at <= current_at
    ):
        account_start = float(account[latest_session]["equity"])
        spy_start = float(spy[latest_session]["price"])
        rows.append(
            {
                "session_date": latest_session,
                "end_session_date": None,
                "status": "in_progress",
                "system_pct": current_equity_value / account_start - 1.0,
                "system_delta": current_equity_value - account_start,
                "spy_pct": current_spy_value / spy_start - 1.0,
                "system_start_at": account[latest_session].get("observed_at"),
                "system_end_at": current_at.isoformat(),
                "spy_start_at": spy[latest_session].get("observed_at"),
                "spy_end_at": current_spy.get("observed_at"),
                "system_source": account[latest_session].get("source"),
                "spy_source": current_spy.get("source"),
                "price_basis": current_spy.get("price_basis"),
            }
        )
    return rows


def build_current_account_interval(
    account_opens: list[dict[str, Any]],
    *,
    current_equity: Any,
    current_equity_at: datetime,
) -> dict[str, Any] | None:
    current_value = _finite(current_equity)
    expected_session = _expected_open_session(current_equity_at)
    account = {str(item.get("session_date")): item for item in account_opens}
    opening = account.get(expected_session or "")
    opening_value = _finite((opening or {}).get("equity"))
    if opening is None or opening_value is None or opening_value <= 0 or current_value is None:
        return None
    return {
        "session_date": expected_session,
        "status": "in_progress",
        "opening_equity": opening_value,
        "current_equity": current_value,
        "system_pct": current_value / opening_value - 1.0,
        "system_delta": current_value - opening_value,
        "system_start_at": opening.get("observed_at"),
        "system_end_at": current_equity_at.astimezone(timezone.utc).isoformat(),
        "system_source": opening.get("source"),
    }


def opening_performance_context(
    settings: Settings,
    store: Store,
    *,
    intraday_history: Mapping[str, Any] | None = None,
    current_equity: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    persisted = read_session_open_snapshots(store)
    ephemeral = extract_exact_open_snapshots(intraday_history or {})
    account_opens = merge_account_open_snapshots(ephemeral, persisted)
    spy_market = load_cached_spy_open_observations(settings, now=now)
    rows = build_open_to_open_rows(
        account_opens,
        spy_market,
        current_equity=current_equity,
        current_equity_at=current,
    )
    account_current = build_current_account_interval(
        account_opens,
        current_equity=current_equity,
        current_equity_at=current,
    )
    final_count = sum(row.get("status") == "final" for row in rows)
    expected_final_count = max(
        len(xnys_sessions_between(account_opens[0]["session_date"], account_opens[-1]["session_date"])) - 1,
        0,
    ) if account_opens else 0
    return {
        "schema_version": "p-l72.opening-performance.v1",
        "rows": rows,
        "account_open_count": len(account_opens),
        "spy_open_count": len(spy_market.get("opens") or []),
        "exact_comparison_count": len(rows),
        "final_comparison_count": final_count,
        "omitted_session_count": max(expected_final_count - final_count, 0),
        "account_current": account_current,
        "current": rows[-1] if rows and rows[-1]["status"] == "in_progress" else None,
    }
