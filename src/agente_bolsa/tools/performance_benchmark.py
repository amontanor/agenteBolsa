"""Benchmark diario prospectivo de cartera (P-L40B).

Este módulo es deliberadamente observacional: consume el ``PortfolioSnapshot``
ya obtenido por el job post-market y lee exclusivamente la caché local de
mercado. No consulta broker ni red, no captura posiciones intradía y no cambia
ninguna decisión de trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pandas as pd

from .market_data import _cache_paths, _request_key

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings
    from ..storage import Store


SCHEMA_VERSION = "p-l40b.performance-benchmark.v1"
UNKNOWN_PRICE_BASIS = "unknown"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stable_hash(payload: dict[str, Any]) -> str:
    stable = deepcopy(payload)
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    stable.pop("revision", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _xnys_schedule(start: str, end: str):
    try:
        import pandas_market_calendars as mcal

        return mcal.get_calendar("XNYS").schedule(start_date=start, end_date=end)
    except Exception:
        return None


def xnys_sessions_between(start: str, end: str) -> list[str]:
    schedule = _xnys_schedule(start, end)
    if schedule is not None:
        return [str(item.date()) for item in schedule.index]
    # Fallback solo para mantener el lector determinista si la dependencia no
    # está instalada; no pretende conocer festivos históricos.
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
        if (first + timedelta(days=offset)).weekday() < 5
    ]


def previous_xnys_session(session_date: str) -> str | None:
    current = date.fromisoformat(session_date)
    start = (current - timedelta(days=14)).isoformat()
    sessions = [item for item in xnys_sessions_between(start, session_date) if item < session_date]
    return sessions[-1] if sessions else None


def _session_close(session_date: str) -> datetime | None:
    schedule = _xnys_schedule(session_date, session_date)
    if schedule is None or schedule.empty:
        return None
    return schedule.iloc[0]["market_close"].to_pydatetime().astimezone(timezone.utc)


def session_status(session_date: str, *, now: datetime | None = None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        target = date.fromisoformat(session_date)
    except ValueError:
        return "unavailable", ["invalid_session_date"]
    if target.isoformat() not in xnys_sessions_between(session_date, session_date):
        return "unavailable", ["not_xnys_session"]
    close = _session_close(session_date)
    if close is None:
        # Sin horario oficial no se puede afirmar que el cierre efectivo haya
        # ocurrido: el benchmark debe fallar cerrado, no asumir días hábiles.
        return "unavailable", ["xnys_close_unavailable"]
    else:
        current_value = now or datetime.now(timezone.utc)
        current = (
            current_value.replace(tzinfo=timezone.utc)
            if current_value.tzinfo is None
            else current_value.astimezone(timezone.utc)
        )
        if close > current:
            return "unavailable", ["session_not_closed"]
    return "closed", warnings


def derive_account_snapshot(portfolio: Any) -> dict[str, Any]:
    """Deriva campos de cuenta desde una única foto ya disponible."""

    warnings: list[str] = []
    if portfolio is None:
        return {
            "equity": None,
            "previous_equity": None,
            "cash": None,
            "buying_power": None,
            "long_market_value": None,
            "short_market_value": None,
            "gross_exposure_usd": None,
            "net_exposure_usd": None,
            "gross_exposure_eod_pct": None,
            "net_exposure_eod_pct": None,
            "position_count": None,
            "unrealized_pl": None,
            "warnings": ["portfolio_snapshot_unavailable"],
        }
    equity = _finite(getattr(portfolio, "portfolio_value", None))
    if equity is None or equity <= 0:
        warnings.append("invalid_equity")
        equity = None
    cash = _finite(getattr(portfolio, "cash", None))
    buying_power = _finite(getattr(portfolio, "buying_power", None))
    if cash is None:
        warnings.append("cash_unavailable")
    if buying_power is None:
        warnings.append("buying_power_unavailable")

    long_value = 0.0
    short_value = 0.0
    gross_value = 0.0
    valid_positions = 0
    unrealized_values: list[float] = []
    invalid_side = False
    seen_symbols: set[str] = set()
    for position in getattr(portfolio, "positions", None) or []:
        market_value = _finite(getattr(position, "market_value", None))
        if market_value is None:
            warnings.append("position_market_value_unavailable")
            continue
        valid_positions += 1
        absolute_value = abs(market_value)
        gross_value += absolute_value
        symbol = str(getattr(position, "symbol", "") or "").strip().upper()
        if symbol and symbol in seen_symbols:
            warnings.append("duplicate_position_symbol")
        if symbol:
            seen_symbols.add(symbol)
        side = str(getattr(position, "side", "") or "").strip().lower()
        if side in {"long", "buy"}:
            long_value += absolute_value
        elif side in {"short", "sell"}:
            short_value += absolute_value
        else:
            invalid_side = True
            warnings.append("position_side_invalid")
        unrealized = _finite(getattr(position, "unrealized_pl", None))
        if unrealized is not None:
            unrealized_values.append(unrealized)

    gross = gross_value
    net = None if invalid_side else long_value - short_value
    gross_pct = gross / equity if equity is not None else None
    net_pct = net / equity if equity is not None and net is not None else None
    return {
        "equity": equity,
        "previous_equity": None,
        "cash": cash,
        "buying_power": buying_power,
        "long_market_value": long_value if valid_positions or getattr(portfolio, "positions", None) == [] else None,
        "short_market_value": short_value if valid_positions or getattr(portfolio, "positions", None) == [] else None,
        "gross_exposure_usd": gross if valid_positions or getattr(portfolio, "positions", None) == [] else None,
        "net_exposure_usd": net,
        "gross_exposure_eod_pct": gross_pct,
        "net_exposure_eod_pct": net_pct,
        "position_count": valid_positions,
        "unrealized_pl": sum(unrealized_values) if unrealized_values else None,
        "warnings": sorted(set(warnings)),
    }


def _extract_close_series(frame: pd.DataFrame, symbol: str) -> tuple[pd.Series, str | None]:
    """Extrae Close/Adj Close en formas planas y MultiIndex de yfinance."""

    if frame is None or frame.empty:
        return pd.Series(dtype=float), None
    symbol = symbol.upper()
    columns = frame.columns
    selected: pd.Series | None = None
    selected_name: str | None = None
    if not isinstance(columns, pd.MultiIndex):
        normalized = [(index, str(name).strip().lower()) for index, name in enumerate(columns)]
        for wanted, canonical in (("adj close", "Adj Close"), ("close", "Close")):
            matches = [index for index, name in normalized if name == wanted]
            if len(matches) > 1:
                return pd.Series(dtype=float), None
            if matches:
                selected = frame.iloc[:, matches[0]]
                selected_name = canonical
                break
    else:
        matches_by_price: dict[str, list[int]] = {"Adj Close": [], "Close": []}
        for index, column in enumerate(columns):
            parts = {str(part).strip() for part in (column if isinstance(column, tuple) else (column,))}
            lower_parts = {part.lower() for part in parts}
            if symbol.lower() in lower_parts:
                for price in matches_by_price:
                    if price.lower() in lower_parts:
                        matches_by_price[price].append(index)
        selected_name = next((price for price in ("Adj Close", "Close") if len(matches_by_price[price]) == 1), None)
        if selected_name is not None:
            selected = frame.iloc[:, matches_by_price[selected_name][0]]
        elif any(len(matches) > 1 for matches in matches_by_price.values()):
            return pd.Series(dtype=float), None
        if selected is None and len(columns) == 1:
            column = columns[0]
            parts = {str(part).strip() for part in (column if isinstance(column, tuple) else (column,))}
            lower_parts = {part.lower() for part in parts}
            if lower_parts.intersection({"adj close", "close"}):
                selected = frame.iloc[:, 0]
                selected_name = "Adj Close" if "adj close" in lower_parts else "Close"
    if selected is None:
        return pd.Series(dtype=float), None
    return pd.to_numeric(selected, errors="coerce"), selected_name


def _bar_by_date(series: pd.Series, wanted: str) -> tuple[float | None, str | None]:
    matches: list[tuple[float, str]] = []
    for timestamp, raw in series.items():
        try:
            parsed = pd.Timestamp(timestamp)
            # Aware bars may be UTC timestamps for the NYSE close. Resolve
            # their market date in America/New_York; using UTC can move a
            # 20:00 ET close into the following calendar day.
            bar_date = parsed.tz_convert(ZoneInfo("America/New_York")).date() if parsed.tzinfo is not None else parsed.date()
        except Exception:
            continue
        if bar_date.isoformat() == wanted:
            value = _finite(raw)
            if value is None or value <= 0:
                return None, None
            matches.append((value, parsed.isoformat()))
    if len(matches) == 1:
        return matches[0]
    return None, None


def _future_bar_present(series: pd.Series, session_date: str) -> bool:
    target = date.fromisoformat(session_date)
    for timestamp in series.index:
        try:
            parsed = pd.Timestamp(timestamp)
            bar_date = (
                parsed.tz_convert(ZoneInfo("America/New_York")).date()
                if parsed.tzinfo is not None
                else parsed.date()
            )
        except (TypeError, ValueError):
            continue
        if bar_date > target:
            return True
    return False


def _price_basis(meta: dict[str, Any], selected_name: str | None) -> str:
    explicit = str(meta.get("price_basis") or "").strip().lower()
    if explicit in {"adjusted_ohlc", "close_unadjusted", UNKNOWN_PRICE_BASIS}:
        return explicit
    if bool(meta.get("auto_adjust")) and str(meta.get("source") or "").lower() == "yfinance":
        return "adjusted_ohlc"
    if selected_name == "Adj Close":
        return "adjusted_ohlc" if bool(meta.get("adjusted")) else UNKNOWN_PRICE_BASIS
    if selected_name == "Close" and str(meta.get("source") or "").lower() in {"fmp", "close"}:
        return "close_unadjusted"
    return UNKNOWN_PRICE_BASIS


def _cache_candidates(settings: Settings, previous: str, session_date: str) -> list[tuple[Path, dict[str, Any]]]:
    cache_root = Path(settings.data_dir) / "cache" / "market_data"
    if not cache_root.exists():
        return []
    start = (date.fromisoformat(previous) - timedelta(days=2)).isoformat()
    end = (date.fromisoformat(session_date) + timedelta(days=1)).isoformat()
    requested = str(getattr(settings, "market_data_provider", "auto") or "auto").lower()
    providers = [requested]
    if requested == "auto":
        providers.extend(["fmp" if getattr(settings, "fmp_api_key", None) else "yfinance", "yfinance", "fmp"])
    candidates: list[tuple[Path, dict[str, Any]]] = []
    seen_paths: set[Path] = set()

    def add_candidate(data_path: Path, meta: dict[str, Any]) -> None:
        if data_path in seen_paths:
            return
        seen_paths.add(data_path)
        candidates.append((data_path, meta))

    for provider in dict.fromkeys(providers):
        key = _request_key([getattr(settings, "benchmark_symbol", "SPY")], start, end, provider=provider)
        data_path, meta_path = _cache_paths(cache_root, key)
        if data_path.exists() and meta_path.exists():
            try:
                add_candidate(data_path, json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
    for meta_path in cache_root.glob("market_data_*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        symbols = {str(item).upper() for item in meta.get("requested_symbols", [])}
        if getattr(settings, "benchmark_symbol", "SPY").upper() not in symbols:
            continue
        data_path = meta_path.with_suffix(".pkl")
        if data_path.exists():
            add_candidate(data_path, meta)

    def created_sort_key(item: tuple[Path, dict[str, Any]]) -> tuple[float, str]:
        created = _metadata_timestamp(item[1].get("created_at"))
        return (created.timestamp() if created is not None else float("-inf"), item[0].name)

    # The filename/hash is only a deterministic tie-breaker.  It is never the
    # authority for choosing a mutable same-day bar.
    return sorted(candidates, key=created_sort_key, reverse=True)


def _metadata_timestamp(value: Any) -> datetime | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(timezone.utc)
    else:
        parsed = parsed.tz_convert(timezone.utc)
    return parsed.to_pydatetime()


def _canonical_cache_metadata(
    meta: dict[str, Any],
    *,
    previous: str,
    session_date: str,
    now: datetime,
    selected_name: str | None,
) -> tuple[bool, str | None, list[str], datetime | None]:
    """Valida autoridad temporal y semántica sin inferir un cierre por el nombre."""

    warnings: list[str] = []
    symbol = str(meta.get("symbol") or "").upper()
    requested_symbols = {str(item).upper() for item in meta.get("requested_symbols", [])}
    if symbol and symbol != "SPY":
        warnings.append("benchmark_symbol_mismatch")
    if requested_symbols and "SPY" not in requested_symbols:
        warnings.append("benchmark_symbol_not_requested")
    if not symbol and not requested_symbols:
        warnings.append("benchmark_symbol_unavailable")
    if not str(meta.get("source") or "").strip():
        warnings.append("benchmark_source_unavailable")
    interval = str(meta.get("interval") or meta.get("timeframe") or "").strip().lower()
    if interval not in {"1d", "daily", "day"}:
        warnings.append("daily_interval_unavailable")
    try:
        start = date.fromisoformat(str(meta.get("start") or ""))
        end = date.fromisoformat(str(meta.get("end") or ""))
        if start > date.fromisoformat(previous) or end < date.fromisoformat(session_date):
            warnings.append("cache_range_does_not_cover_session")
    except ValueError:
        warnings.append("cache_range_unavailable")

    created_at = _metadata_timestamp(meta.get("created_at"))
    if created_at is None:
        warnings.append("cache_created_at_unavailable")
    elif created_at > now:
        warnings.append("cache_created_at_future")

    basis = _price_basis(meta, selected_name)
    if basis not in {"adjusted_ohlc", "close_unadjusted"}:
        warnings.append("price_basis_unknown")
    elif basis == "close_unadjusted" and selected_name != "Close":
        warnings.append("price_basis_field_mismatch")

    authority = str(meta.get("eod_authority") or meta.get("eod_finality") or "").strip().lower()
    explicit_finality = authority in {
        "confirmed",
        "eod_final",
        "next_session_confirmed",
        "post_session_final",
    }
    if created_at is not None and created_at <= now:
        # A post-session UTC date is a conservative temporal boundary, not a
        # guessed market-close hour. Same-day caches remain provisional unless
        # durable finality is explicitly supplied.
        if created_at.date() > date.fromisoformat(session_date):
            authority = authority or "post_session_cache"
        elif not explicit_finality:
            warnings.append("same_day_cache_not_eod")
    if not authority:
        warnings.append("eod_authority_unavailable")

    return not warnings, authority or None, sorted(set(warnings)), created_at


def load_cached_spy_observation(settings: Settings, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    try:
        previous = previous_xnys_session(session_date)
    except (TypeError, ValueError):
        return {"status": "unavailable", "warnings": ["invalid_session_date"]}
    if previous is None:
        return {"status": "unavailable", "warnings": ["missing_previous_xnys_session"]}
    status, status_warnings = session_status(session_date, now=now)
    if status != "closed":
        return {"status": "unavailable", "warnings": status_warnings}
    symbol = str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper()
    captured_now = now or datetime.now(timezone.utc)
    captured_now = (
        captured_now.replace(tzinfo=timezone.utc)
        if captured_now.tzinfo is None
        else captured_now.astimezone(timezone.utc)
    )
    rejected_reasons: set[str] = set()
    for data_path, meta in _cache_candidates(settings, previous, session_date):
        try:
            frame = pd.read_pickle(data_path)
        except Exception:
            continue
        series, selected_name = _extract_close_series(frame, symbol)
        if series.empty:
            continue
        previous_close, previous_as_of = _bar_by_date(series, previous)
        close, as_of = _bar_by_date(series, session_date)
        warnings = list(status_warnings)
        if _future_bar_present(series, session_date):
            warnings.append("future_spy_bar")
        if previous_close is None:
            warnings.append("missing_previous_spy_session")
        if close is None:
            warnings.append("missing_spy_session")
        basis = _price_basis(meta, selected_name)
        valid_meta, eod_authority, meta_warnings, created_at = _canonical_cache_metadata(
            meta,
            previous=previous,
            session_date=session_date,
            now=captured_now,
            selected_name=selected_name,
        )
        warnings.extend(meta_warnings)
        valid_meta = valid_meta and not warnings
        daily_return = close / previous_close - 1.0 if close is not None and previous_close else None
        if daily_return is None:
            warnings.append("spy_close_pair_unavailable")
        if not valid_meta or daily_return is None:
            rejected_reasons.update(warnings)
            continue
        return {
            "status": "available",
            "previous_close": previous_close,
            "close": close,
            "daily_return": daily_return,
            "price_basis": basis,
            "source": meta.get("source"),
            "instrument_label": "SPY (ETF S&P 500)",
            "as_of": as_of or previous_as_of,
            "cache_created_at": created_at.isoformat() if created_at else None,
            "eod_authority": eod_authority,
            "interval": str(meta.get("interval") or meta.get("timeframe") or "1d"),
            "data_quality": "available",
            "warnings": sorted(set(warnings)),
        }
    return {
        "status": "unavailable",
        "previous_close": None,
        "close": None,
        "daily_return": None,
        "price_basis": None,
        "source": None,
        "instrument_label": "SPY (ETF S&P 500)",
        "as_of": None,
        "cache_created_at": None,
        "eod_authority": None,
        "data_quality": "unavailable",
        "warnings": sorted(rejected_reasons or {"spy_cache_unavailable"}),
    }


def overlay_eod_benchmark(
    row: Mapping[str, Any],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Proyecta una observación EOD posterior sin mutar ni reescribir el row.

    El benchmark almacenado se conserva bajo ``stored_benchmark`` para
    auditoría. La proyección solo puede mejorar la vista si la caché pasa la
    autoridad EOD; de lo contrario elimina el precio no verificable y deja la
    comparación pendiente.
    """

    projected = deepcopy(dict(row))
    payload = deepcopy(projected.get("payload") or {})
    contract = deepcopy(payload.get("performance_benchmark") or {})
    if not contract:
        return projected
    session_date = str(projected.get("session_date") or contract.get("session_date") or "")[:10]
    stored_benchmark = deepcopy(contract.get("benchmark") or {})
    observation = load_cached_spy_observation(settings, session_date, now=now)
    read_at = now or datetime.now(timezone.utc)
    read_at = read_at.astimezone(timezone.utc) if read_at.tzinfo else read_at.replace(tzinfo=timezone.utc)
    account = contract.get("account") or {}
    equity = _finite(account.get("equity"))
    previous_equity = _finite(account.get("previous_equity"))
    account_return = equity / previous_equity - 1.0 if equity is not None and previous_equity and previous_equity > 0 else None
    warnings = list(observation.get("warnings") or [])
    if observation.get("status") == "available":
        spy_return = _finite(observation.get("daily_return"))
        benchmark = {
            **stored_benchmark,
            "symbol": str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper(),
            "instrument_label": observation.get("instrument_label") or "SPY (ETF S&P 500)",
            "previous_close": _finite(observation.get("previous_close")),
            "close": _finite(observation.get("close")),
            "daily_return": spy_return,
            "price_basis": observation.get("price_basis"),
            "source": observation.get("source"),
            "as_of": observation.get("as_of"),
            "cache_created_at": observation.get("cache_created_at"),
            "eod_authority": observation.get("eod_authority"),
            "interval": observation.get("interval"),
            "comparison_status": "comparable",
            "data_quality": "available",
        }
        comparison_status = "available" if account_return is not None and spy_return is not None else "partial"
        comparison = {
            **(contract.get("comparison") or {}),
            "excess_return_total": (
                account_return - spy_return
                if account_return is not None and spy_return is not None
                else None
            ),
        }
    else:
        spy_return = None
        benchmark = {
            **stored_benchmark,
            "instrument_label": "SPY (ETF S&P 500)",
            "previous_close": None,
            "close": None,
            "daily_return": None,
            "price_basis": None,
            "source": None,
            "as_of": None,
            "cache_created_at": None,
            "eod_authority": None,
            "comparison_status": "unavailable",
            "data_quality": "unavailable",
        }
        comparison_status = "unavailable"
        comparison = {**(contract.get("comparison") or {}), "excess_return_total": None}
    contract["benchmark"] = benchmark
    contract["comparison"] = comparison
    contract["eod_overlay"] = {
        "status": "available" if comparison_status == "available" else comparison_status,
        "stored_benchmark": stored_benchmark,
        "warnings": sorted(set(warnings)),
        "consumer_read_at": read_at.isoformat(),
    }
    contract["data_quality"] = {
        "status": "available" if comparison_status == "available" else "partial" if account_return is not None else "unavailable",
        "warnings": sorted(set(warnings)),
    }
    payload["performance_benchmark"] = contract
    projected["payload"] = payload
    projected["performance_benchmark"] = contract
    projected["eod_overlay_status"] = comparison_status
    projected["eod_overlay_spy_return"] = spy_return
    return projected


def _previous_equity(store: Store, session_date: str) -> tuple[str | None, float | None]:
    previous = previous_xnys_session(session_date)
    if previous is None:
        return None, None
    rows = store.performance_daily(limit=0)
    for row in rows:
        if row.get("session_date") == previous:
            value = _finite(row.get("equity"))
            if value is not None and value > 0:
                return previous, value
            payload = row.get("payload") or {}
            benchmark = payload.get("performance_benchmark") or {}
            return previous, _finite((benchmark.get("account") or {}).get("equity"))
    return previous, None


def _drawdown(values: list[float]) -> float | None:
    clean = [item for item in values if _finite(item) is not None and float(item) > 0]
    if not clean:
        return None
    peak = clean[0]
    worst = 0.0
    for value in clean:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst


def build_performance_benchmark(
    store: Store,
    settings: Settings,
    session_date: str,
    portfolio: Any,
    *,
    now: datetime | None = None,
    spy_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye la observación nueva y los campos legacy para una sesión."""

    captured_value = now or datetime.now(timezone.utc)
    captured_dt = (
        captured_value.replace(tzinfo=timezone.utc)
        if captured_value.tzinfo is None
        else captured_value.astimezone(timezone.utc)
    )
    captured_at = captured_dt.isoformat()
    status, status_warnings = session_status(session_date, now=now)
    account = derive_account_snapshot(portfolio)
    previous_session, previous_equity = _previous_equity(store, session_date)
    account["previous_equity"] = previous_equity
    warnings = list(status_warnings) + list(account.pop("warnings", []))
    if previous_equity is None:
        warnings.append("missing_previous_xnys_session" if previous_session else "no_previous_xnys_session")
    if status != "closed":
        spy_observation = {"status": "unavailable", "warnings": list(status_warnings)}
    elif spy_observation is None:
        spy_observation = load_cached_spy_observation(settings, session_date, now=now)
    spy = dict(spy_observation or {})
    observation_as_of = spy.get("as_of")
    if observation_as_of:
        try:
            parsed_as_of = pd.Timestamp(observation_as_of)
            parsed_as_of = (
                parsed_as_of.tz_localize(timezone.utc)
                if parsed_as_of.tzinfo is None
                else parsed_as_of.tz_convert(timezone.utc)
            )
            if parsed_as_of.to_pydatetime() > captured_dt:
                warnings.append("spy_observation_after_capture")
                spy = {"status": "unavailable", "warnings": ["spy_observation_after_capture"]}
        except Exception:
            warnings.append("spy_observation_timestamp_invalid")
    if spy.get("status") == "available" and not spy.get("eod_authority"):
        warnings.append("eod_authority_unavailable")
        spy = {
            "status": "unavailable",
            "warnings": ["eod_authority_unavailable"],
        }
    if spy.get("status") == "available":
        invalid_authority_fields: list[str] = []
        if spy.get("price_basis") not in {"adjusted_ohlc", "close_unadjusted"}:
            invalid_authority_fields.append("price_basis_unknown")
        if not str(spy.get("source") or "").strip():
            invalid_authority_fields.append("benchmark_source_unavailable")
        if not spy.get("as_of"):
            invalid_authority_fields.append("benchmark_as_of_unavailable")
        if invalid_authority_fields:
            warnings.extend(invalid_authority_fields)
            spy = {"status": "unavailable", "warnings": invalid_authority_fields}
    warnings.extend(list(spy.get("warnings") or []))
    account_daily_return = None
    if _finite(account.get("equity")) is not None and previous_equity and previous_equity > 0:
        account_daily_return = account["equity"] / previous_equity - 1.0
    spy_daily_return = None
    if str(spy.get("status") or "").lower() == "available":
        previous_close = _finite(spy.get("previous_close"))
        close = _finite(spy.get("close"))
        if previous_close is not None and previous_close > 0 and close is not None and close > 0:
            spy_daily_return = close / previous_close - 1.0
            provided_return = _finite(spy.get("daily_return"))
            if provided_return is not None and abs(provided_return - spy_daily_return) > 1e-12:
                warnings.append("spy_daily_return_mismatch")
    excess = account_daily_return - spy_daily_return if account_daily_return is not None and spy_daily_return is not None else None
    benchmark = {
        "symbol": str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper(),
        "instrument_label": spy.get("instrument_label") or "SPY (ETF S&P 500)",
        "previous_close": _finite(spy.get("previous_close")),
        "close": _finite(spy.get("close")),
        "daily_return": spy_daily_return,
        "price_basis": spy.get("price_basis"),
        "source": spy.get("source"),
        "as_of": spy.get("as_of"),
        "cache_created_at": spy.get("cache_created_at"),
        "eod_authority": spy.get("eod_authority"),
        "interval": spy.get("interval"),
        "comparison_status": "comparable"
        if spy.get("status") == "available" and spy.get("eod_authority")
        else "unavailable",
        "data_quality": spy.get("data_quality") or "unavailable",
    }
    account["daily_return"] = account_daily_return
    account["session_average_gross_exposure"] = None
    account["external_flows"] = None
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session_date,
        "xnys_session_status": status,
        "captured_at": captured_at,
        "revision": 1,
        "account": {
            "equity": account.get("equity"),
            "previous_equity": previous_equity,
            "daily_return": account_daily_return,
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
            "long_market_value": account.get("long_market_value"),
            "short_market_value": account.get("short_market_value"),
            "gross_exposure_usd": account.get("gross_exposure_usd"),
            "net_exposure_usd": account.get("net_exposure_usd"),
            "gross_exposure_eod_pct": account.get("gross_exposure_eod_pct"),
            "net_exposure_eod_pct": account.get("net_exposure_eod_pct"),
            "session_average_gross_exposure": None,
            "position_count": account.get("position_count"),
            "external_flows": None,
        },
        "pnl": {
            "realized": None,
            "unrealized": account.get("unrealized_pl"),
            "fees": None,
            "residual": None,
        },
        "benchmark": benchmark,
        "comparison": {
            "excess_return_total": excess,
            "exposure_matched_spy_return": None,
            "excess_return_exposure_matched": None,
            "cash_drag": None,
        },
        "drawdown": {
            "account": _drawdown([row.get("equity") for row in store.performance_daily(limit=0)] + [account.get("equity")]),
            "spy": None,
            "exposure_matched_spy": None,
            "convention": "non_positive_fraction",
        },
        "data_quality": {
            "status": "available"
            if status == "closed" and account_daily_return is not None and spy_daily_return is not None and not warnings
            else "partial"
            if status == "closed"
            else "unavailable",
            "warnings": sorted(set(warnings)),
        },
        "exposure_observation_type": "eod_snapshot",
        "temporal_exposure_status": "unavailable",
    }
    contract["content_hash"] = _stable_hash(contract)
    return contract


def build_daily_performance_item(
    store: Store,
    settings: Settings,
    session_date: str,
    portfolio: Any,
    *,
    now: datetime | None = None,
    spy_observation: dict[str, Any] | None = None,
    canonical_telemetry: Mapping[str, Any] | None = None,
    canonical_eod_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combina el payload legacy con el bloque P-L40B sin llamadas externas."""

    contract = build_performance_benchmark(
        store,
        settings,
        session_date,
        portfolio,
        now=now,
        spy_observation=spy_observation,
    )
    account = contract["account"]
    benchmark = contract["benchmark"]
    from .performance_baseline import build_daily_performance

    legacy = build_daily_performance(
        store,
        settings,
        session_date,
        equity=account.get("equity"),
        spy_pct=benchmark.get("daily_return"),
        portfolio=portfolio,
        canonical_telemetry=canonical_telemetry,
    )
    legacy["pnl_pct"] = account.get("daily_return")
    legacy["spy_pct"] = benchmark.get("daily_return")
    legacy["alpha_vs_spy"] = contract["comparison"].get("excess_return_total")
    legacy["alpha"] = contract["comparison"].get("excess_return_total")
    legacy["avg_exposure"] = account.get("gross_exposure_eod_pct")
    legacy["performance_benchmark"] = contract
    if canonical_eod_snapshot is not None:
        # Consumer-only projection: the PMR passes the already-built object;
        # performance does not rebuild the accounting snapshot.
        legacy["canonical_eod_account_snapshot"] = canonical_eod_snapshot
    payload = dict(legacy)
    payload.pop("payload", None)
    return {
        "session_date": session_date,
        "payload": payload,
        "performance_benchmark": contract,
        "equity": account.get("equity"),
        "pnl_pct": account.get("daily_return"),
        "spy_pct": benchmark.get("daily_return"),
        "alpha": contract["comparison"].get("excess_return_total"),
        "hit_rate_20": legacy.get("hit_rate_20"),
        "sharpe_60": legacy.get("sharpe_60"),
        "max_dd": legacy.get("max_dd"),
        "iq_score": legacy.get("iq_score"),
    }


def _latest_closed_xnys_session(now: datetime | None = None) -> str | None:
    current_value = now or datetime.now(timezone.utc)
    current = (
        current_value.replace(tzinfo=timezone.utc)
        if current_value.tzinfo is None
        else current_value.astimezone(timezone.utc)
    )
    market_date = current.astimezone(ZoneInfo("America/New_York")).date()
    start = (market_date - timedelta(days=14)).isoformat()
    end = market_date.isoformat()
    for session_date in reversed(xnys_sessions_between(start, end)):
        status, _warnings = session_status(session_date, now=current)
        if status == "closed":
            return session_date
    return None


def benchmark_summary(
    rows: list[dict[str, Any]],
    *,
    conflict_count: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    contracts = []
    legacy = 0
    legacy_empty_payload = 0
    legacy_missing_spy = 0
    conflicts = 0 if conflict_count is None else int(conflict_count)
    for row in rows:
        payload = row.get("payload") or {}
        contract = payload.get("performance_benchmark")
        if isinstance(contract, dict):
            contracts.append(contract)
            if conflict_count is None and contract.get("data_quality", {}).get("status") == "conflict":
                conflicts += 1
        else:
            legacy += 1
            if not payload:
                legacy_empty_payload += 1
            if row.get("spy_pct") is None:
                legacy_missing_spy += 1
    latest = contracts[-1] if contracts else {}
    latest_session = latest.get("session_date")
    expected_session = _latest_closed_xnys_session(now)
    if not latest_session or not expected_session:
        freshness_status = "unavailable"
    elif latest_session == expected_session:
        freshness_status = "fresh"
    elif latest_session < expected_session:
        freshness_status = "stale"
    else:
        freshness_status = "unavailable"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": latest.get("data_quality", {}).get("status", "unavailable") if latest else "unavailable",
        "latest_session": latest_session,
        "rows": len(contracts),
        "legacy_rows": legacy,
        "conflicts": conflicts,
        "legacy_empty_payload": legacy_empty_payload,
        "legacy_missing_spy": legacy_missing_spy,
        "account_daily_return": (latest.get("account") or {}).get("daily_return"),
        "spy_daily_return": (latest.get("benchmark") or {}).get("daily_return"),
        "excess_return_total": (latest.get("comparison") or {}).get("excess_return_total"),
        "gross_exposure_eod_pct": (latest.get("account") or {}).get("gross_exposure_eod_pct"),
        "session_average_gross_exposure": (latest.get("account") or {}).get("session_average_gross_exposure"),
        "exposure_matched_status": "unavailable",
        "freshness": {
            "session_date": latest_session,
            "expected_session": expected_session,
            "status": freshness_status,
        },
    }
