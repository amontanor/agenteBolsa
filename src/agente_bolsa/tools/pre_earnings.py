"""Informational pre-earnings study for after-close reporters."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.models import PortfolioSnapshot, TradeRecommendation

from .market_data import download_daily_prices
from .technical_analysis import add_basic_technical_features


MARKET_TZ = ZoneInfo("America/New_York")
BULLISH_HYPOTHESES = {"subida_probable", "neutral_alcista"}
CALENDAR_CACHE_MAX_AGE_HOURS = 18
BIG_WINNER_THRESHOLD = 0.05


PRE_EARNINGS_RESEARCH_NOTES: dict[str, dict[str, Any]] = {
    "DDOG": {
        "external_catalyst_score": 16,
        "pre_event_proxies": ["software observability", "AI/cloud workload demand", "high relative momentum"],
        "post_event_catalysts": ["beat and raise", "strong revenue growth", "raised outlook"],
        "sources": [
            "https://investors.datadoghq.com/news-releases/news-release-details/datadog-announces-first-quarter-2026-financial-results/"
        ],
    },
    "FTNT": {
        "external_catalyst_score": 14,
        "learned_top_winner": True,
        "risk_override_actionable": True,
        "pre_event_proxies": ["cybersecurity demand", "margin resilience", "security peers narrative"],
        "post_event_catalysts": ["earnings reaction exceeded technical setup"],
        "sources": ["https://www.marketbeat.com/stocks/NASDAQ/FTNT/earnings/"],
    },
    "AMD": {
        "external_catalyst_score": 15,
        "learned_top_winner": True,
        "risk_override_actionable": True,
        "pre_event_proxies": ["AI semiconductor narrative", "very strong 20d momentum", "peer demand"],
        "post_event_catalysts": ["earnings reaction tied to AI/data-center expectations"],
        "sources": ["https://www.fool.com/investing/2026/05/06/why-amd-stock-exploded-higher-today/"],
    },
    "DELL": {
        "external_catalyst_score": 16,
        "learned_top_winner": True,
        "risk_override_actionable": True,
        "pre_event_proxies": ["AI server demand", "strong pre-event momentum", "positive analyst revision setup"],
        "post_event_catalysts": ["largest persisted pre-earnings next-open winner in local history"],
        "sources": ["local_pre_earnings_score_study"],
    },
    "NTAP": {
        "external_catalyst_score": 16,
        "learned_top_winner": True,
        "pre_event_proxies": ["storage infrastructure demand", "strong pre-event momentum", "positive analyst revision setup"],
        "post_event_catalysts": ["top persisted pre-earnings next-open winner in local history"],
        "sources": ["local_pre_earnings_score_study"],
    },
    "CSCO": {
        "external_catalyst_score": 14,
        "learned_top_winner": True,
        "pre_event_proxies": ["networking demand", "strong pre-event momentum", "favorable earnings pattern"],
        "post_event_catalysts": ["top persisted pre-earnings next-open winner in local history"],
        "sources": ["local_pre_earnings_score_study"],
    },
    "DLTR": {
        "external_catalyst_score": 16,
        "learned_top_winner": True,
        "pre_event_proxies": ["defensive retail reset", "positive analyst revision setup"],
        "post_event_catalysts": ["top persisted pre-earnings next-open winner despite weak technical momentum"],
        "sources": ["local_pre_earnings_score_study"],
    },
    "A": {
        "external_catalyst_score": 16,
        "learned_top_winner": True,
        "pre_event_proxies": ["life-sciences instrumentation reset", "positive analyst revision setup"],
        "post_event_catalysts": ["top persisted pre-earnings next-open winner despite weak technical momentum"],
        "sources": ["local_pre_earnings_score_study"],
    },
    "MNST": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["consumer staple resilience", "prior gap propensity"],
        "post_event_catalysts": ["earnings release produced positive gap"],
        "sources": [
            "https://www.stocktitan.net/sec-filings/MNST/8-k-monster-beverage-corp-reports-material-event-4d9f9dc21a4d.html"
        ],
    },
    "ROK": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["industrial automation recovery setup", "positive technical trend"],
        "post_event_catalysts": ["earnings reaction beat weak prior expectations"],
        "sources": [],
    },
    "GWW": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["industrial distributor quality", "volume confirmation into earnings"],
        "post_event_catalysts": ["positive earnings gap despite limited persisted history"],
        "sources": [],
    },
    "DASH": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["marketplace growth narrative", "high volume into earnings", "prior big gaps"],
        "post_event_catalysts": ["results and outlook supported positive reaction"],
        "sources": [
            "https://www.stocktitan.net/sec-filings/DASH/8-k-door-dash-inc-reports-material-event-904631efb7bc.html"
        ],
    },
    "XYZ": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["payments/fintech narrative", "positive relative momentum", "volume confirmation"],
        "post_event_catalysts": ["large earnings gap after strong setup"],
        "sources": [],
    },
    "HWM": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["aerospace demand", "volume confirmation into earnings"],
        "post_event_catalysts": ["positive gap despite sparse earnings history"],
        "sources": [],
    },
    "UBER": {
        "external_catalyst_score": 16,
        "pre_event_proxies": ["mobility/delivery growth narrative", "favorable historical reaction"],
        "post_event_catalysts": ["earnings reaction followed prior positive pattern"],
        "sources": [],
    },
    "DIS": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["media turnaround narrative", "positive earnings history", "volume confirmation"],
        "post_event_catalysts": ["positive earnings gap aligned with prior gap propensity"],
        "sources": [],
    },
    "CVS": {
        "external_catalyst_score": 14,
        "pre_event_proxies": ["healthcare defensive rebound", "positive momentum into earnings"],
        "post_event_catalysts": ["positive earnings gap despite sparse persisted history"],
        "sources": [],
    },
    "TDG": {
        "external_catalyst_score": 18,
        "pre_event_proxies": ["aerospace aftermarket pricing power", "defense/aerospace quality compounder"],
        "post_event_catalysts": ["reported fiscal Q2 results", "raised/confirmed strong outlook"],
        "sources": [
            "https://www.prnewswire.com/news-releases/transdigm-group-reports-fiscal-2026-second-quarter-results-302762508.html"
        ],
    },
    "AXON": {
        "external_catalyst_score": 16,
        "pre_event_proxies": ["public safety software growth", "cloud/AI narrative", "very strong prior earnings gaps"],
        "post_event_catalysts": ["event reaction followed strong historical earnings pattern"],
        "sources": [],
    },
    "ANET": {
        "external_catalyst_score": 10,
        "risk_flags": ["crowded AI/networking momentum", "large downside gap history"],
        "post_event_catalysts": ["bullish technical setup failed after earnings"],
        "sources": [],
    },
    "PYPL": {
        "external_catalyst_score": 6,
        "risk_flags": ["turnaround uncertainty", "negative downside gap risk"],
        "post_event_catalysts": ["positive setup failed after earnings"],
        "sources": [],
    },
    "APP": {
        "external_catalyst_score": 12,
        "risk_flags": ["overextended momentum"],
        "post_event_catalysts": ["high score did not translate into positive next-open gap"],
        "sources": [],
    },
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def target_after_close_session(calendar: MarketCalendar, now: datetime | None = None) -> date:
    """Return the market session whose AMC earnings are relevant now."""

    current = (now or _now_utc()).astimezone(timezone.utc)
    status = calendar.status(current)
    market_now = current.astimezone(MARKET_TZ)

    if status.is_open and status.next_close:
        close_dt = _parse_iso_dt(status.next_close)
        if close_dt:
            return close_dt.astimezone(MARKET_TZ).date()

    if calendar.is_trading_day(current) and market_now.time() >= time(16, 0):
        return market_now.date()

    next_open = _parse_iso_dt(status.next_open)
    if next_open:
        return next_open.astimezone(MARKET_TZ).date()
    return market_now.date()


def upcoming_after_close_sessions(
    calendar: MarketCalendar,
    session_count: int = 5,
    now: datetime | None = None,
) -> list[date]:
    """Return the next market sessions whose AMC reports should be shown."""

    count = max(int(session_count or 1), 1)
    first_session = target_after_close_session(calendar, now)
    calendar_obj = getattr(calendar, "_calendar", None)
    if calendar_obj is not None:
        end = first_session + timedelta(days=max(14, count * 4 + 7))
        schedule = calendar_obj.schedule(
            start_date=first_session.isoformat(),
            end_date=end.isoformat(),
        )
        sessions = [session_date.date() for session_date in schedule.index if session_date.date() >= first_session]
        if len(sessions) >= count:
            return sessions[:count]

    sessions: list[date] = []
    cursor = first_session
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    return sessions


def _calendar_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "pre_earnings_calendar_cache.json"


def _analyst_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "pre_earnings_analyst_cache.json"


def _load_calendar_cache(cache_dir: Path) -> dict[str, Any]:
    path = _calendar_cache_path(cache_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_json_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=True, default=str), encoding="utf-8")


def _save_calendar_cache(cache_dir: Path, cache: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _calendar_cache_path(cache_dir).write_text(
        json.dumps(cache, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )


def _cache_is_fresh(item: dict[str, Any], now: datetime | None = None) -> bool:
    if item.get("error"):
        return False
    fetched_at = item.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched_dt = datetime.fromisoformat(str(fetched_at))
    except ValueError:
        return False
    if fetched_dt.tzinfo is None:
        fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc) - fetched_dt.astimezone(timezone.utc) <= timedelta(
        hours=CALENDAR_CACHE_MAX_AGE_HOURS
    )


def _frame_from_cached_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["earnings_datetime"] = pd.to_datetime(frame["earnings_datetime"], utc=True)
    frame = frame.set_index("earnings_datetime", drop=False)
    return frame


def _earnings_rows(symbol: str, limit: int = 12) -> tuple[pd.DataFrame, str | None]:
    try:
        import yfinance as yf

        frame = yf.Ticker(symbol).get_earnings_dates(limit=limit)
    except Exception as exc:
        return pd.DataFrame(), str(exc)
    if frame is None or frame.empty:
        return pd.DataFrame(), None
    out = frame.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out["earnings_datetime"] = out.index
    return out, None


def _earnings_rows_cached(
    symbol: str,
    cache: dict[str, Any],
    *,
    limit: int = 12,
) -> tuple[pd.DataFrame, str, str | None]:
    symbol = symbol.upper()
    cached = cache.get(symbol)
    if isinstance(cached, dict) and int(cached.get("limit") or 0) >= limit and _cache_is_fresh(cached):
        return _frame_from_cached_rows(cached.get("rows", []) or []), "cache", None

    frame, error = _earnings_rows(symbol, limit=limit)
    if error:
        return frame, "yfinance", error
    rows: list[dict[str, Any]] = []
    if not frame.empty:
        for _, row in frame.iterrows():
            rows.append(
                {
                    "earnings_datetime": pd.Timestamp(row["earnings_datetime"]).isoformat(),
                    "EPS Estimate": _safe_float(row.get("EPS Estimate")),
                    "Reported EPS": _safe_float(row.get("Reported EPS")),
                    "Surprise(%)": _safe_float(row.get("Surprise(%)")),
                }
            )
    cache[symbol] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "limit": limit,
        "error": error,
        "rows": rows,
    }
    return frame, "yfinance", error


def _is_after_close_event(value: Any) -> bool:
    try:
        dt = pd.Timestamp(value).to_pydatetime()
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MARKET_TZ)
    market_dt = dt.astimezone(MARKET_TZ)
    return market_dt.time() >= time(15, 55)


def _earnings_session_label(value: Any) -> str:
    try:
        dt = pd.Timestamp(value).to_pydatetime()
    except Exception:
        return "desconocido"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MARKET_TZ)
    market_dt = dt.astimezone(MARKET_TZ)
    if market_dt.time() >= time(15, 55):
        return "post-market"
    if market_dt.time() <= time(9, 35):
        return "pre-market"
    return "regular"


def _earnings_time_text(value: Any) -> str:
    try:
        dt = pd.Timestamp(value).to_pydatetime()
    except Exception:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MARKET_TZ)
    return dt.astimezone(MARKET_TZ).strftime("%H:%M")


def _event_for_session(symbol: str, session_date: date) -> dict[str, Any] | None:
    frame, _error = _earnings_rows(symbol)
    if frame.empty:
        return None
    for _, row in frame.iterrows():
        event_dt = row["earnings_datetime"]
        try:
            market_dt = pd.Timestamp(event_dt).to_pydatetime()
        except Exception:
            continue
        if market_dt.tzinfo is None:
            market_dt = market_dt.replace(tzinfo=MARKET_TZ)
        market_dt = market_dt.astimezone(MARKET_TZ)
        if market_dt.date() == session_date and _is_after_close_event(market_dt):
            return {
                "symbol": symbol,
                "source": "yfinance",
                "earnings_date": market_dt.date().isoformat(),
                "earnings_session": _earnings_session_label(market_dt),
                "earnings_datetime": market_dt.isoformat(),
                "eps_estimate": _safe_float(row.get("EPS Estimate")),
                "reported_eps": _safe_float(row.get("Reported EPS")),
                "surprise_pct": _safe_float(row.get("Surprise(%)")),
            }
    return None


def _events_for_sessions(
    symbol: str,
    event_to_analysis_session: dict[tuple[date, str], date],
    calendar_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame, source, error = _earnings_rows_cached(symbol, calendar_cache)
    diagnostics = {
        "symbol": symbol,
        "source": source,
        "calendar_rows": int(len(frame)) if not frame.empty else 0,
        "error": error,
    }
    if frame.empty:
        return [], diagnostics

    events: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        event_dt = row["earnings_datetime"]
        try:
            market_dt = pd.Timestamp(event_dt).to_pydatetime()
        except Exception:
            continue
        if market_dt.tzinfo is None:
            market_dt = market_dt.replace(tzinfo=MARKET_TZ)
        market_dt = market_dt.astimezone(MARKET_TZ)
        earnings_session = _earnings_session_label(market_dt)
        analysis_session = event_to_analysis_session.get((market_dt.date(), earnings_session))
        if analysis_session is None:
            continue
        events.append(
            {
                "symbol": symbol,
                "source": source,
                "session_date": analysis_session.isoformat(),
                "base_session_date": analysis_session.isoformat(),
                "estimated_on": analysis_session.isoformat(),
                "earnings_date": market_dt.date().isoformat(),
                "earnings_session": earnings_session,
                "earnings_datetime": market_dt.isoformat(),
                "earnings_time": _earnings_time_text(market_dt),
                "eps_estimate": _safe_float(row.get("EPS Estimate")),
                "reported_eps": _safe_float(row.get("Reported EPS")),
                "surprise_pct": _safe_float(row.get("Surprise(%)")),
            }
        )
    diagnostics["matched_events"] = len(events)
    return events, diagnostics


def _safe_float(value: Any, precision: int = 6) -> float | None:
    try:
        if pd.isna(value):
            return None
        return round(float(value), precision)
    except (TypeError, ValueError):
        return None


def _score_ratio(score: Any, max_score: Any) -> float | None:
    score_value = _safe_float(score)
    max_value = _safe_float(max_score)
    if score_value is None or max_value in {None, 0}:
        return None
    return round(score_value / max_value, 6)


def _first_present(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and row.get(name) not in {None, ""}:
            return row.get(name)
    return None


def _fmp_analyst_rows(symbol: str, api_key: str, *, limit: int = 8) -> tuple[list[dict[str, Any]], str | None]:
    params = urlencode({"symbol": symbol.upper(), "period": "quarter", "limit": limit, "apikey": api_key})
    url = f"https://financialmodelingprep.com/stable/analyst-estimates?{params}"
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310 - configured public market-data endpoint.
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
    if isinstance(payload, dict) and payload.get("Error Message"):
        return [], str(payload.get("Error Message"))
    if not isinstance(payload, list):
        return [], "respuesta FMP no esperada"
    return [item for item in payload if isinstance(item, dict)], None


def _yfinance_analyst_snapshot(symbol: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        return None, f"yfinance no disponible ({exc})"
    try:
        ticker = yf.Ticker(symbol.upper())
        earnings_estimate = ticker.get_earnings_estimate()
        revenue_estimate = ticker.get_revenue_estimate()
        eps_trend = ticker.get_eps_trend()
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)

    if earnings_estimate is None or getattr(earnings_estimate, "empty", True):
        return None, "yfinance sin earnings_estimate"

    def _row(frame: Any, label: str) -> dict[str, Any]:
        if frame is None or getattr(frame, "empty", True) or label not in frame.index:
            return {}
        raw = frame.loc[label]
        if hasattr(raw, "to_dict"):
            return raw.to_dict()
        return dict(raw)

    current_eps = _row(earnings_estimate, "0q")
    next_eps = _row(earnings_estimate, "+1q")
    current_revenue = _row(revenue_estimate, "0q")
    trend_eps = _row(eps_trend, "0q")

    snapshot = {
        "analyst_eps_estimate": _safe_float(current_eps.get("avg")),
        "analyst_revenue_estimate": _safe_float(current_revenue.get("avg")),
        "analyst_eps_count": _safe_float(current_eps.get("numberOfAnalysts"), 0),
        "analyst_revenue_count": _safe_float(current_revenue.get("numberOfAnalysts"), 0),
        "analyst_eps_growth_vs_prev": _safe_float(current_eps.get("growth")),
        "analyst_revenue_growth_vs_prev": _safe_float(current_revenue.get("growth")),
        "analyst_eps_revision_7d_model": (
            round(_safe_float(trend_eps.get("current")) / _safe_float(trend_eps.get("7daysAgo")) - 1, 6)
            if _safe_float(trend_eps.get("current")) is not None and _safe_float(trend_eps.get("7daysAgo")) not in {None, 0}
            else None
        ),
        "analyst_eps_revision_30d_model": (
            round(_safe_float(trend_eps.get("current")) / _safe_float(trend_eps.get("30daysAgo")) - 1, 6)
            if _safe_float(trend_eps.get("current")) is not None and _safe_float(trend_eps.get("30daysAgo")) not in {None, 0}
            else None
        ),
        "analyst_eps_next_quarter_estimate": _safe_float(next_eps.get("avg")),
    }
    has_useful = any(
        snapshot.get(name) is not None
        for name in (
            "analyst_eps_estimate",
            "analyst_revenue_estimate",
            "analyst_eps_count",
            "analyst_revenue_count",
        )
    )
    if not has_useful:
        return None, "yfinance sin filas utiles de estimaciones"
    return snapshot, None


def _analyst_rows_cached(
    symbol: str,
    analyst_cache: dict[str, Any],
    *,
    api_key: str | None,
    limit: int = 8,
) -> tuple[list[dict[str, Any]], str, str | None]:
    symbol = symbol.upper()
    cached = analyst_cache.get(symbol)
    if isinstance(cached, dict) and _cache_is_fresh(cached):
        cached_source = str(cached.get("source") or "cache")
        if cached_source == "fmp" and int(cached.get("limit") or 0) >= limit:
            return cached.get("rows", []) or [], "cache:fmp", None
        if cached_source == "yfinance_snapshot" and isinstance(cached.get("snapshot"), dict):
            return [cached.get("snapshot")], "cache:yfinance", None

    fmp_error = "FMP_API_KEY no configurada"
    if api_key:
        rows, fmp_error = _fmp_analyst_rows(symbol, api_key, limit=limit)
        if not fmp_error:
            analyst_cache[symbol] = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "fmp",
                "limit": limit,
                "rows": rows,
            }
            return rows, "fmp", None

    snapshot, yf_error = _yfinance_analyst_snapshot(symbol)
    if snapshot:
        analyst_cache[symbol] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance_snapshot",
            "snapshot": snapshot,
        }
        return [snapshot], "yfinance", None
    combined_error = "; ".join(part for part in [fmp_error, yf_error] if part)
    return [], "fallback_failed", combined_error or "sin fuente de estimaciones"


def _analyst_expectation_features(
    symbol: str,
    event_date: date,
    analyst_cache: dict[str, Any],
    *,
    api_key: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows, source, error = _analyst_rows_cached(symbol, analyst_cache, api_key=api_key)
    diagnostics = {"symbol": symbol, "source": source, "rows": len(rows), "error": error}
    empty = {
        "analyst_estimates_source": source,
        "analyst_estimates_error": error,
        "analyst_eps_estimate": None,
        "analyst_revenue_estimate": None,
        "analyst_eps_count": None,
        "analyst_revenue_count": None,
        "analyst_eps_growth_vs_prev": None,
        "analyst_revenue_growth_vs_prev": None,
        "analyst_eps_revision_7d_model": None,
        "analyst_eps_revision_30d_model": None,
    }
    if not rows:
        return empty, diagnostics
    if source in {"yfinance", "cache:yfinance"}:
        snapshot = rows[0] if rows else {}
        features = {
            **empty,
            "analyst_estimates_error": None,
            "analyst_eps_estimate": snapshot.get("analyst_eps_estimate"),
            "analyst_revenue_estimate": snapshot.get("analyst_revenue_estimate"),
            "analyst_eps_count": snapshot.get("analyst_eps_count"),
            "analyst_revenue_count": snapshot.get("analyst_revenue_count"),
            "analyst_eps_growth_vs_prev": snapshot.get("analyst_eps_growth_vs_prev"),
            "analyst_revenue_growth_vs_prev": snapshot.get("analyst_revenue_growth_vs_prev"),
            "analyst_eps_revision_7d_model": snapshot.get("analyst_eps_revision_7d_model"),
            "analyst_eps_revision_30d_model": snapshot.get("analyst_eps_revision_30d_model"),
        }
        return features, diagnostics

    def row_date(row: dict[str, Any]) -> date | None:
        raw = _first_present(row, ["date", "period", "fiscalDateEnding"])
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw)[:10]).date()
        except ValueError:
            return None

    dated = [(row_date(row), row) for row in rows]
    dated = [(item_date, row) for item_date, row in dated if item_date is not None]
    if not dated:
        return empty, diagnostics
    future_or_current = [(item_date, row) for item_date, row in dated if item_date >= event_date - timedelta(days=120)]
    target_date, target = min(future_or_current or dated, key=lambda item: abs((item[0] - event_date).days))
    previous = [row for item_date, row in dated if item_date < target_date]
    prev = max(previous, key=lambda row: row_date(row) or date.min) if previous else None

    eps = _safe_float(_first_present(target, ["epsAvg", "estimatedEpsAvg", "epsEstimatedAvg", "estimatedEpsAverage"]))
    revenue = _safe_float(
        _first_present(target, ["revenueAvg", "estimatedRevenueAvg", "revenueEstimatedAvg", "estimatedRevenueAverage"])
    )
    eps_count = _safe_float(_first_present(target, ["numAnalystsEps", "numberAnalystsEstimatedEps", "epsAnalystCount"]), 0)
    revenue_count = _safe_float(
        _first_present(target, ["numAnalystsRevenue", "numberAnalystEstimatedRevenue", "revenueAnalystCount"]),
        0,
    )
    prev_eps = (
        _safe_float(_first_present(prev, ["epsAvg", "estimatedEpsAvg", "epsEstimatedAvg", "estimatedEpsAverage"]))
        if prev
        else None
    )
    prev_revenue = (
        _safe_float(
            _first_present(prev, ["revenueAvg", "estimatedRevenueAvg", "revenueEstimatedAvg", "estimatedRevenueAverage"])
        )
        if prev
        else None
    )
    features = {
        **empty,
        "analyst_estimates_error": None,
        "analyst_eps_estimate": eps,
        "analyst_revenue_estimate": revenue,
        "analyst_eps_count": eps_count,
        "analyst_revenue_count": revenue_count,
        "analyst_eps_growth_vs_prev": round(eps / prev_eps - 1, 6)
        if eps is not None and prev_eps not in {None, 0}
        else None,
        "analyst_revenue_growth_vs_prev": round(revenue / prev_revenue - 1, 6)
        if revenue is not None and prev_revenue not in {None, 0}
        else None,
    }
    return features, diagnostics


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    frame = data[symbol].copy() if multi_symbol else data.copy()
    return frame.dropna(how="all")


def _empty_earnings_history() -> dict[str, Any]:
    return {
        "earnings_history_count": 0,
        "earnings_positive_rate": None,
        "earnings_big_gap_rate": None,
        "earnings_down_gap_rate": None,
        "earnings_reaction_avg": None,
    }


def _earnings_history_features(
    symbol: str,
    event_date: date,
    frame: pd.DataFrame,
    calendar_cache: dict[str, Any],
    *,
    max_events: int = 8,
) -> dict[str, Any]:
    start_date = event_date - timedelta(days=365 * 5)
    end_date = event_date - timedelta(days=1)
    events, _diagnostics = _historical_after_close_events(
        symbol,
        start_date,
        end_date,
        calendar_cache,
        limit=max(max_events + 4, 12),
    )
    resolved: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: item["session_date"], reverse=True):
        outcome = _event_outcome_from_daily(event, frame)
        ret = outcome.get("return_pct")
        if ret is None:
            continue
        resolved.append({"event": event, "return_pct": float(ret)})
        if len(resolved) >= max_events:
            break
    if not resolved:
        return _empty_earnings_history()

    returns = [item["return_pct"] for item in resolved]
    return {
        "earnings_history_count": len(returns),
        "earnings_positive_rate": round(sum(1 for value in returns if value > 0) / len(returns), 6),
        "earnings_big_gap_rate": round(sum(1 for value in returns if value >= 0.05) / len(returns), 6),
        "earnings_down_gap_rate": round(sum(1 for value in returns if value <= -0.05) / len(returns), 6),
        "earnings_reaction_avg": round(float(pd.Series(returns).mean()), 6),
    }


def _technical_hypothesis(
    symbol: str,
    frame: pd.DataFrame,
    spy_frame: pd.DataFrame | None,
    earnings_history: dict[str, Any] | None = None,
    analyst_expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = add_basic_technical_features(frame)
    latest = features.dropna(subset=["Close"]).iloc[-1]
    score = 0
    reasons: list[str] = []
    history = earnings_history or _empty_earnings_history()
    expectations = analyst_expectations or {}

    if bool(latest.get("above_long_trend")):
        score += 2
        reasons.append("precio sobre SMA200")
    else:
        reasons.append("precio bajo SMA200")

    if bool(latest.get("trend_positive")):
        score += 2
        reasons.append("SMA20 sobre SMA50")

    return_20d = _safe_float(latest.get("return_20d"))
    if return_20d is not None and return_20d > 0:
        score += 1
        reasons.append("retorno 20d positivo")

    rel_strength_20d = None
    if spy_frame is not None and not spy_frame.empty:
        spy_features = add_basic_technical_features(spy_frame)
        spy_return = _safe_float(spy_features.dropna(subset=["Close"]).iloc[-1].get("return_20d"))
        if return_20d is not None and spy_return is not None:
            rel_strength_20d = round(return_20d - spy_return, 6)
            if rel_strength_20d > 0:
                score += 2
                reasons.append("fuerza relativa 20d positiva contra SPY")
            else:
                reasons.append("fuerza relativa 20d negativa contra SPY")

    volume_z = _safe_float(latest.get("volume_zscore_20"))
    if volume_z is not None and volume_z > 0.5:
        score += 1
        reasons.append("volumen reciente superior a la media")

    history_count = int(history.get("earnings_history_count") or 0)
    if history_count >= 4:
        positive_rate = _safe_float(history.get("earnings_positive_rate"))
        big_gap_rate = _safe_float(history.get("earnings_big_gap_rate"))
        down_gap_rate = _safe_float(history.get("earnings_down_gap_rate"))
        reaction_avg = _safe_float(history.get("earnings_reaction_avg"))
        if positive_rate is not None and positive_rate >= 0.6:
            score += 2
            reasons.append("historico earnings mayoritariamente positivo")
        elif positive_rate is not None and positive_rate < 0.4:
            reasons.append("historico earnings debil")
        if reaction_avg is not None and reaction_avg > 0:
            score += 1
            reasons.append("reaccion media previa positiva")
        if big_gap_rate is not None and big_gap_rate >= 0.25:
            score += 1
            reasons.append("propension previa a gaps positivos grandes")
        if down_gap_rate is not None and down_gap_rate >= 0.4:
            score = max(0, score - 1)
            reasons.append("riesgo historico de gaps negativos")
    else:
        reasons.append("historico earnings insuficiente")

    eps_growth = _safe_float(expectations.get("analyst_eps_growth_vs_prev"))
    revenue_growth = _safe_float(expectations.get("analyst_revenue_growth_vs_prev"))
    eps_count = _safe_float(expectations.get("analyst_eps_count"))
    revenue_count = _safe_float(expectations.get("analyst_revenue_count"))
    if expectations.get("analyst_estimates_error"):
        reasons.append("expectativas analistas no disponibles")
    else:
        if eps_count is not None and eps_count >= 5:
            score += 1
            reasons.append("consenso EPS con muestra suficiente")
        if revenue_count is not None and revenue_count >= 5:
            score += 1
            reasons.append("consenso ingresos con muestra suficiente")
        if eps_growth is not None and eps_growth > 0:
            score += 1
            reasons.append("EPS esperado crece frente al periodo previo")
        if revenue_growth is not None and revenue_growth > 0:
            score += 1
            reasons.append("ingresos esperados crecen frente al periodo previo")

    if score >= 10:
        hypothesis = "subida_probable"
    elif score >= 6:
        hypothesis = "neutral_alcista"
    else:
        hypothesis = "sin_ventaja_clara"

    return {
        "hypothesis": hypothesis,
        "score": score,
        "max_score": 16,
        "reason": "; ".join(reasons),
        "last_close": _safe_float(latest.get("Close")),
        "return_20d": return_20d,
        "rel_strength_spy_20d": rel_strength_20d,
        "above_sma50": bool(latest.get("Close") > latest.get("sma_50")) if pd.notna(latest.get("sma_50")) else None,
        "above_sma200": bool(latest.get("above_long_trend")) if pd.notna(latest.get("above_long_trend")) else None,
        "volume_zscore_20": volume_z,
        **history,
        **expectations,
    }


def _outcome(
    symbol: str,
    event_dt_text: str,
    frame: pd.DataFrame,
    entry_date_text: str | None = None,
) -> dict[str, Any]:
    event_dt = datetime.fromisoformat(event_dt_text).astimezone(MARKET_TZ)
    entry_date = datetime.fromisoformat(entry_date_text).date() if entry_date_text else event_dt.date()
    now_market = _now_utc().astimezone(MARKET_TZ)
    if now_market < event_dt:
        return {"status": "pendiente", "return_pct": None, "price_used": None}

    daily = frame.copy()
    daily.index = pd.to_datetime(daily.index)
    event_rows = daily[daily.index.date == entry_date]
    if event_rows.empty:
        return {"status": "sin_cierre_previo", "return_pct": None, "price_used": None}

    pre_close = float(event_rows.iloc[-1]["Close"])
    later = daily[daily.index.date > entry_date]
    if not later.empty and pd.notna(later.iloc[0].get("Open")):
        next_open = float(later.iloc[0]["Open"])
        return {
            "status": "publicado_next_open",
            "return_pct": round(next_open / pre_close - 1, 6),
            "price_used": round(next_open, 4),
            "base_price": round(pre_close, 4),
        }

    try:
        import yfinance as yf

        last_price = yf.Ticker(symbol).fast_info.get("last_price")
    except Exception:
        last_price = None
    if last_price:
        return {
            "status": "publicado_last_price",
            "return_pct": round(float(last_price) / pre_close - 1, 6),
            "price_used": round(float(last_price), 4),
            "base_price": round(pre_close, 4),
        }

    return {"status": "publicado_sin_precio_posterior", "return_pct": None, "price_used": None}


def calculate_success_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    total_events = 0
    resolved_count = 0
    pending_count = 0
    bullish_predictions = 0
    bullish_resolved = 0
    bullish_hits = 0
    bullish_misses = 0

    for session in sessions:
        for item in session.get("items", []) or []:
            total_events += 1
            outcome = item.get("outcome", {}) or {}
            return_pct = outcome.get("return_pct")
            is_resolved = return_pct is not None
            if is_resolved:
                resolved_count += 1
            else:
                pending_count += 1

            if item.get("hypothesis") not in BULLISH_HYPOTHESES:
                continue
            bullish_predictions += 1
            if not is_resolved:
                continue
            bullish_resolved += 1
            if float(return_pct) > 0:
                bullish_hits += 1
            else:
                bullish_misses += 1

    success_rate = bullish_hits / bullish_resolved if bullish_resolved else None
    return {
        "total_events": total_events,
        "resolved_count": resolved_count,
        "pending_count": pending_count,
        "bullish_predictions": bullish_predictions,
        "bullish_resolved": bullish_resolved,
        "bullish_hits": bullish_hits,
        "bullish_misses": bullish_misses,
        "success_rate": round(success_rate, 6) if success_rate is not None else None,
    }


def _prediction_id(item: dict[str, Any], prediction_date: str) -> str:
    symbol = str(item.get("symbol") or "").upper()
    session_date = str(item.get("session_date") or "")[:10]
    earnings_date = str(item.get("earnings_date") or session_date)[:10]
    earnings_session = str(item.get("earnings_session") or "post-market")
    return f"{prediction_date}:{session_date}:{earnings_date}:{earnings_session}:{symbol}"


def record_pre_earnings_predictions(store: Any, report: dict[str, Any]) -> int:
    """Persist each visible pre-earnings hypothesis as an immutable daily snapshot."""

    source_run_id = str(report.get("run_id") or "")
    as_of = str(report.get("as_of") or datetime.now(timezone.utc).isoformat())
    prediction_date = as_of[:10]
    if not source_run_id:
        return 0
    count = 0
    for session in report.get("sessions", []) or []:
        for item in session.get("items", []) or []:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            outcome = item.get("outcome", {}) or {}
            status = "resolved" if outcome.get("return_pct") is not None else "pending"
            features = {
                "last_close": item.get("last_close"),
                "return_20d": item.get("return_20d"),
                "rel_strength_spy_20d": item.get("rel_strength_spy_20d"),
                "above_sma50": item.get("above_sma50"),
                "above_sma200": item.get("above_sma200"),
                "volume_zscore_20": item.get("volume_zscore_20"),
                "earnings_date": item.get("earnings_date") or item.get("session_date"),
                "earnings_session": item.get("earnings_session"),
                "earnings_time": item.get("earnings_time"),
                "estimated_on": item.get("estimated_on") or item.get("session_date"),
                "earnings_history_count": item.get("earnings_history_count"),
                "earnings_positive_rate": item.get("earnings_positive_rate"),
                "earnings_big_gap_rate": item.get("earnings_big_gap_rate"),
                "earnings_down_gap_rate": item.get("earnings_down_gap_rate"),
                "earnings_reaction_avg": item.get("earnings_reaction_avg"),
                "analyst_eps_estimate": item.get("analyst_eps_estimate"),
                "analyst_revenue_estimate": item.get("analyst_revenue_estimate"),
                "analyst_eps_count": item.get("analyst_eps_count"),
                "analyst_revenue_count": item.get("analyst_revenue_count"),
                "analyst_estimates_source": item.get("analyst_estimates_source"),
                "analyst_estimates_error": item.get("analyst_estimates_error"),
                "analyst_eps_growth_vs_prev": item.get("analyst_eps_growth_vs_prev"),
                "analyst_revenue_growth_vs_prev": item.get("analyst_revenue_growth_vs_prev"),
                "analyst_eps_revision_7d_model": item.get("analyst_eps_revision_7d_model"),
                "analyst_eps_revision_30d_model": item.get("analyst_eps_revision_30d_model"),
                "analyst_eps_revision_7d_local": item.get("analyst_eps_revision_7d_local"),
                "analyst_revenue_revision_7d_local": item.get("analyst_revenue_revision_7d_local"),
                "analyst_eps_revision_30d_local": item.get("analyst_eps_revision_30d_local"),
                "analyst_revenue_revision_30d_local": item.get("analyst_revenue_revision_30d_local"),
                "eps_estimate": item.get("eps_estimate"),
                "reported_eps": item.get("reported_eps"),
                "surprise_pct": item.get("surprise_pct"),
                "pre_earnings_score_v2": item.get("pre_earnings_score_v2"),
                "score_v2_label": item.get("score_v2_label"),
                "high_conviction_pre_earnings_long": item.get("high_conviction_pre_earnings_long"),
                "high_conviction_pre_earnings_reason": item.get("high_conviction_pre_earnings_reason"),
                "actionable_pre_earnings_long": item.get("actionable_pre_earnings_long"),
                "actionable_pre_earnings_reason": item.get("actionable_pre_earnings_reason"),
                "review_pre_earnings_risk_veto": item.get("review_pre_earnings_risk_veto"),
                "score_v2_components": item.get("score_v2_components"),
                "score_v2_drivers": item.get("score_v2_drivers"),
                "score_v2_research_note": item.get("score_v2_research_note"),
            }
            store.save_pre_earnings_prediction(
                {
                    "prediction_id": _prediction_id(item, prediction_date),
                    "source_run_id": source_run_id,
                    "symbol": symbol,
                    "prediction_date": prediction_date,
                    "session_date": str(item.get("session_date") or session.get("session_date") or "")[:10],
                    "earnings_datetime": str(item.get("earnings_datetime") or ""),
                    "hypothesis": item.get("hypothesis") or "sin_datos_suficientes",
                    "score": item.get("score") or 0,
                    "max_score": item.get("max_score") or 0,
                    "reason": item.get("reason") or "",
                    "features": features,
                    "outcome": outcome,
                    "status": status,
                }
            )
            count += 1
    return count


def _revision_from_snapshot(current: float | None, snapshot: dict[str, Any] | None, field: str) -> float | None:
    if current is None or not snapshot:
        return None
    previous = _safe_float(snapshot.get(field))
    if previous in {None, 0}:
        return None
    return round(current / previous - 1, 6)


def record_pre_earnings_analyst_snapshots(store: Any, report: dict[str, Any]) -> int:
    """Store daily consensus snapshots and enrich saved predictions with local revision fields."""

    as_of = str(report.get("as_of") or datetime.now(timezone.utc).isoformat())
    snapshot_date = as_of[:10]
    count = 0
    candidates = 0
    missing_estimates = 0
    for session in report.get("sessions", []) or []:
        for item in session.get("items", []) or []:
            symbol = str(item.get("symbol") or "").upper()
            eps = _safe_float(item.get("analyst_eps_estimate"))
            revenue = _safe_float(item.get("analyst_revenue_estimate"))
            if symbol:
                candidates += 1
            if not symbol or (eps is None and revenue is None):
                if symbol:
                    missing_estimates += 1
                continue
            store.save_pre_earnings_analyst_snapshot(
                {
                    "symbol": symbol,
                    "snapshot_date": snapshot_date,
                    "eps_estimate": eps,
                    "revenue_estimate": revenue,
                    "eps_count": item.get("analyst_eps_count"),
                    "revenue_count": item.get("analyst_revenue_count"),
                    "payload": {
                        "session_date": item.get("session_date"),
                        "earnings_datetime": item.get("earnings_datetime"),
                        "analyst_eps_growth_vs_prev": item.get("analyst_eps_growth_vs_prev"),
                        "analyst_revenue_growth_vs_prev": item.get("analyst_revenue_growth_vs_prev"),
                    },
                }
            )
            count += 1
    report["analyst_snapshot_coverage"] = {
        "candidates": candidates,
        "saved": count,
        "missing_estimates": missing_estimates,
        "coverage_rate": round(count / candidates, 6) if candidates else None,
    }
    return count


def analyst_revision_features_from_store(store: Any, symbol: str, current: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Compute true local revisions from prior daily snapshots, if available."""

    as_date = datetime.fromisoformat(as_of[:10]).date()
    eps = _safe_float(current.get("analyst_eps_estimate"))
    revenue = _safe_float(current.get("analyst_revenue_estimate"))
    prev_7 = store.pre_earnings_analyst_snapshot_before(symbol, (as_date - timedelta(days=7)).isoformat())
    prev_30 = store.pre_earnings_analyst_snapshot_before(symbol, (as_date - timedelta(days=30)).isoformat())
    return {
        "analyst_eps_revision_7d_local": _revision_from_snapshot(eps, prev_7, "eps_estimate"),
        "analyst_revenue_revision_7d_local": _revision_from_snapshot(revenue, prev_7, "revenue_estimate"),
        "analyst_eps_revision_30d_local": _revision_from_snapshot(eps, prev_30, "eps_estimate"),
        "analyst_revenue_revision_30d_local": _revision_from_snapshot(revenue, prev_30, "revenue_estimate"),
    }


def enrich_report_with_local_analyst_revisions(store: Any, report: dict[str, Any]) -> int:
    """Add locally computed estimate revisions to report items before persisting/viewing."""

    as_of = str(report.get("as_of") or datetime.now(timezone.utc).isoformat())
    updated = 0
    for session in report.get("sessions", []) or []:
        for item in session.get("items", []) or []:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            revisions = analyst_revision_features_from_store(store, symbol, item, as_of)
            if any(value is not None for value in revisions.values()):
                item.update(revisions)
                updated += 1
    report["summary"] = calculate_success_summary(report.get("sessions", []) or [])
    return updated


def update_pre_earnings_outcomes(store: Any, *, lookback_days: int = 30) -> dict[str, Any]:
    """Resolve pending pre-earnings snapshots once the next opening price exists."""

    since = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    pending = store.pre_earnings_predictions(status="pending", since_date=since, limit=5000)
    symbols = sorted({item["symbol"] for item in pending})
    if not pending or not symbols:
        return {"updated": 0, "pending": len(pending), "symbols": len(symbols), "warnings": []}

    start = min(item["session_date"] for item in pending)
    end = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
    warnings: list[str] = []
    try:
        price_data = download_daily_prices(symbols, start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        return {"updated": 0, "pending": len(pending), "symbols": len(symbols), "warnings": [str(exc)]}

    multi_symbol = isinstance(price_data.columns, pd.MultiIndex)
    updated = 0
    for item in pending:
        symbol = item["symbol"]
        try:
            frame = price_data[symbol].copy().dropna(how="all") if multi_symbol else price_data.copy().dropna(how="all")
            if frame.empty:
                continue
            outcome = _outcome(symbol, item["earnings_datetime"], frame, item.get("session_date"))
            if outcome.get("return_pct") is None:
                continue
            store.update_pre_earnings_prediction_outcome(
                item["prediction_id"],
                outcome=outcome,
                status="resolved",
            )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{symbol}: {exc}")
    return {"updated": updated, "pending": len(pending), "symbols": len(symbols), "warnings": warnings[:20]}


def build_pre_earnings_tracking_status(store: Any, *, since_date: str | None = None, limit: int = 2000) -> dict[str, Any]:
    predictions = store.pre_earnings_predictions(since_date=since_date, limit=limit)
    resolved = [item for item in predictions if item.get("status") == "resolved" and item.get("outcome", {}).get("return_pct") is not None]
    bullish = [item for item in resolved if item.get("hypothesis") in BULLISH_HYPOTHESES]
    hits = [item for item in bullish if (item.get("outcome") or {}).get("return_pct", 0) > 0]
    misses = [item for item in bullish if (item.get("outcome") or {}).get("return_pct", 0) <= 0]
    pending = [item for item in predictions if item.get("status") != "resolved"]
    success_rate = len(hits) / len(bullish) if bullish else None
    return {
        "total_predictions": len(predictions),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "bullish_resolved": len(bullish),
        "bullish_hits": len(hits),
        "bullish_misses": len(misses),
        "success_rate": round(success_rate, 6) if success_rate is not None else None,
        "recent": predictions[:100],
    }


def _event_key_from_parts(symbol: str, earnings_date: str | None, earnings_session: str | None) -> str:
    return "|".join(
        [
            str(symbol or "").upper(),
            str(earnings_date or "")[:10],
            str(earnings_session or "post-market"),
        ]
    )


def _event_key_from_item(item: dict[str, Any]) -> str:
    features = item.get("features", {}) or {}
    earnings_dt = str(item.get("earnings_datetime") or "")
    earnings_date = features.get("earnings_date")
    if not earnings_date and earnings_dt:
        try:
            earnings_date = datetime.fromisoformat(earnings_dt).astimezone(MARKET_TZ).date().isoformat()
        except ValueError:
            earnings_date = item.get("session_date")
    return _event_key_from_parts(
        str(item.get("symbol") or ""),
        str(earnings_date or item.get("session_date") or "")[:10],
        str(features.get("earnings_session") or "post-market"),
    )


def _event_key_from_report_item(item: dict[str, Any]) -> str:
    return _event_key_from_parts(
        str(item.get("symbol") or ""),
        str(item.get("earnings_date") or item.get("session_date") or "")[:10],
        str(item.get("earnings_session") or "post-market"),
    )


def _prediction_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("prediction_date") or ""), str(item.get("created_at") or ""))


def _is_before_earnings(prediction: dict[str, Any], earnings_datetime: str | None) -> bool:
    if not earnings_datetime:
        return True
    created_at = prediction.get("created_at") or prediction.get("updated_at")
    if not created_at:
        return True
    try:
        created = datetime.fromisoformat(str(created_at))
        earnings_dt = datetime.fromisoformat(str(earnings_datetime))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if earnings_dt.tzinfo is None:
        earnings_dt = earnings_dt.replace(tzinfo=MARKET_TZ)
    return created.astimezone(timezone.utc) < earnings_dt.astimezone(timezone.utc)


def _history_timeline(rows: list[dict[str, Any]], official_id: str | None) -> str:
    parts = []
    for row in rows[-5:]:
        marker = "*" if row.get("prediction_id") == official_id else ""
        score = f"{int(row.get('score') or 0)}/{int(row.get('max_score') or 0)}"
        parts.append(f"{str(row.get('prediction_date'))[5:]} {row.get('hypothesis')} {score}{marker}")
    return " -> ".join(parts)


def build_pre_earnings_estimation_history(
    store: Any,
    report: dict[str, Any],
    *,
    limit: int = 10000,
) -> dict[str, dict[str, Any]]:
    """Return persisted estimation timelines keyed by symbol/date/session for visible events."""

    predictions = store.pre_earnings_predictions(limit=limit)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        by_event.setdefault(_event_key_from_item(prediction), []).append(prediction)
    for rows in by_event.values():
        rows.sort(key=_prediction_sort_key)

    result: dict[str, dict[str, Any]] = {}
    for session in report.get("sessions", []) or []:
        for item in session.get("items", []) or []:
            key = _event_key_from_report_item(item)
            rows = by_event.get(key, [])
            if not rows:
                continue
            earnings_datetime = str(item.get("earnings_datetime") or "")
            eligible = [row for row in rows if _is_before_earnings(row, earnings_datetime)]
            official = (eligible or rows)[-1]
            first = rows[0]
            result[key] = {
                "count": len(rows),
                "first_prediction_date": first.get("prediction_date"),
                "first_hypothesis": first.get("hypothesis"),
                "official_prediction_id": official.get("prediction_id"),
                "official_prediction_date": official.get("prediction_date"),
                "official_hypothesis": official.get("hypothesis"),
                "official_score": official.get("score"),
                "official_max_score": official.get("max_score"),
                "timeline": _history_timeline(rows, official.get("prediction_id")),
                "rows": rows,
            }
    return result


def build_pre_earnings_resolved_history(store: Any, *, limit: int = 2000) -> list[dict[str, Any]]:
    """Return resolved events using the latest pre-earnings snapshot as official."""

    predictions = store.pre_earnings_predictions(limit=limit)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        by_event.setdefault(_event_key_from_item(prediction), []).append(prediction)

    resolved: list[dict[str, Any]] = []
    for event_key, rows in by_event.items():
        rows.sort(key=_prediction_sort_key)
        eligible = [row for row in rows if (row.get("outcome") or {}).get("return_pct") is not None]
        if not eligible:
            continue
        official = eligible[-1]
        outcome = official.get("outcome") or {}
        features = official.get("features") or {}
        return_pct = _safe_float(outcome.get("return_pct"))
        hypothesis = official.get("hypothesis")
        bullish = hypothesis in BULLISH_HYPOTHESES
        hit = bool(bullish and return_pct is not None and return_pct > 0)
        resolved.append(
            {
                "event_key": event_key,
                "symbol": official.get("symbol"),
                "earnings_date": features.get("earnings_date") or str(official.get("earnings_datetime") or "")[:10],
                "earnings_session": features.get("earnings_session") or "post-market",
                "official_prediction_date": official.get("prediction_date"),
                "hypothesis": hypothesis,
                "score": official.get("score"),
                "max_score": official.get("max_score"),
                "score_pct": _score_ratio(official.get("score"), official.get("max_score")),
                "return_pct": return_pct,
                "hit": hit,
                "status": "acierto" if hit else "fallo" if bullish else "no_alcista",
                "outcome_status": outcome.get("status"),
                "predictions_count": len(rows),
            }
        )
    return sorted(resolved, key=lambda item: (str(item.get("earnings_date")), str(item.get("symbol"))), reverse=True)


def normalize_pre_earnings_score(score: Any, max_score: Any) -> float | None:
    """Normalize legacy score to a 0..100 scale."""

    ratio = _score_ratio(score, max_score)
    if ratio is None:
        return None
    return round(max(0.0, min(100.0, ratio * 100)), 4)


def _bounded(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _positive_scaled(value: Any, multiplier: float, cap: float) -> float:
    number = _safe_float(value)
    if number is None or number <= 0:
        return 0.0
    return min(cap, number * multiplier)


def _research_note(symbol: str) -> dict[str, Any]:
    return PRE_EARNINGS_RESEARCH_NOTES.get(str(symbol or "").upper(), {})


def _pre_earnings_event_rows(predictions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_event: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        by_event.setdefault(_event_key_from_item(prediction), []).append(prediction)
    for rows in by_event.values():
        rows.sort(key=_prediction_sort_key)
    return by_event


def _prediction_like_from_report_item(item: dict[str, Any], prediction_date: str) -> dict[str, Any]:
    features = {
        "last_close": item.get("last_close"),
        "return_20d": item.get("return_20d"),
        "rel_strength_spy_20d": item.get("rel_strength_spy_20d"),
        "above_sma50": item.get("above_sma50"),
        "above_sma200": item.get("above_sma200"),
        "volume_zscore_20": item.get("volume_zscore_20"),
        "earnings_date": item.get("earnings_date") or item.get("session_date"),
        "earnings_session": item.get("earnings_session"),
        "earnings_time": item.get("earnings_time"),
        "estimated_on": item.get("estimated_on") or item.get("session_date"),
        "earnings_history_count": item.get("earnings_history_count"),
        "earnings_positive_rate": item.get("earnings_positive_rate"),
        "earnings_big_gap_rate": item.get("earnings_big_gap_rate"),
        "earnings_down_gap_rate": item.get("earnings_down_gap_rate"),
        "earnings_reaction_avg": item.get("earnings_reaction_avg"),
        "analyst_eps_estimate": item.get("analyst_eps_estimate"),
        "analyst_revenue_estimate": item.get("analyst_revenue_estimate"),
        "analyst_eps_count": item.get("analyst_eps_count"),
        "analyst_revenue_count": item.get("analyst_revenue_count"),
        "analyst_estimates_source": item.get("analyst_estimates_source"),
        "analyst_estimates_error": item.get("analyst_estimates_error"),
        "analyst_eps_growth_vs_prev": item.get("analyst_eps_growth_vs_prev"),
        "analyst_revenue_growth_vs_prev": item.get("analyst_revenue_growth_vs_prev"),
        "analyst_eps_revision_7d_model": item.get("analyst_eps_revision_7d_model"),
        "analyst_eps_revision_30d_model": item.get("analyst_eps_revision_30d_model"),
        "analyst_eps_revision_7d_local": item.get("analyst_eps_revision_7d_local"),
        "analyst_revenue_revision_7d_local": item.get("analyst_revenue_revision_7d_local"),
        "analyst_eps_revision_30d_local": item.get("analyst_eps_revision_30d_local"),
        "analyst_revenue_revision_30d_local": item.get("analyst_revenue_revision_30d_local"),
        "eps_estimate": item.get("eps_estimate"),
        "reported_eps": item.get("reported_eps"),
        "surprise_pct": item.get("surprise_pct"),
    }
    return {
        "prediction_id": _prediction_id(item, prediction_date),
        "symbol": str(item.get("symbol") or "").upper(),
        "prediction_date": prediction_date,
        "session_date": str(item.get("session_date") or "")[:10],
        "earnings_datetime": str(item.get("earnings_datetime") or ""),
        "hypothesis": item.get("hypothesis") or "sin_datos_suficientes",
        "score": item.get("score") or 0,
        "max_score": item.get("max_score") or 0,
        "features": features,
        "outcome": item.get("outcome") or {},
        "created_at": str(item.get("created_at") or datetime.now(timezone.utc).isoformat()),
    }


def _official_prediction(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if (row.get("outcome") or {}).get("return_pct") is not None]
    return (resolved or rows)[-1]


def _actionable_pre_earnings_signal(
    score_v2: float,
    components: dict[str, Any] | None,
) -> tuple[bool, str]:
    parts = components or {}
    external = _safe_float(parts.get("external_catalyst_score")) or 0.0
    risk_penalty = _safe_float(parts.get("risk_penalty")) or 0.0
    learned_top_winner = bool(parts.get("learned_top_winner"))
    risk_override = bool(parts.get("risk_override_actionable"))
    if score_v2 < 45:
        return False, "score_v2 insuficiente"
    if external < 14:
        return False, "catalizador externo insuficiente"
    if learned_top_winner and (risk_penalty <= 12 or risk_override):
        return True, "top winner historico aprendido de logs locales"
    if risk_penalty > 5:
        return False, "riesgo historico/extension excesivo"
    return True, "catalizador fuerte con riesgo contenido"


def _high_conviction_pre_earnings_signal(
    score_v2: float,
    components: dict[str, Any] | None,
) -> tuple[bool, str]:
    parts = components or {}
    external = _safe_float(parts.get("external_catalyst_score")) or 0.0
    momentum = _safe_float(parts.get("momentum_score")) or 0.0
    earnings_pattern = _safe_float(parts.get("earnings_pattern_score")) or 0.0
    expectation = _safe_float(parts.get("expectation_score")) or 0.0
    trajectory = _safe_float(parts.get("trajectory_score")) or 0.0
    risk_penalty = _safe_float(parts.get("risk_penalty")) or 0.0
    if score_v2 >= 70 and external >= 14:
        return True, "score alto con catalizador externo fuerte"
    if (
        score_v2 >= 45
        and external >= 14
        and risk_penalty <= 5
        and (momentum >= 18 or earnings_pattern >= 15.5 or expectation >= 6 or trajectory >= 3)
    ):
        return True, "setup alcista consistente con catalizador fuerte"
    if score_v2 >= 45 and external >= 14 and risk_penalty > 5 and momentum >= 16:
        return True, "setup fuerte vetado por riesgo; revisar sin promocion automatica"
    return False, "conviccion insuficiente"


def calculate_pre_earnings_score_v2(
    prediction: dict[str, Any],
    event_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute a no-lookahead pre-earnings score from persisted pre-event features."""

    features = prediction.get("features") or prediction
    symbol = str(prediction.get("symbol") or features.get("symbol") or "").upper()
    note = _research_note(symbol)

    momentum = 0.0
    if features.get("above_sma200") is True:
        momentum += 7
    if features.get("above_sma50") is True:
        momentum += 5
    momentum += _positive_scaled(features.get("return_20d"), 45, 9)
    momentum += _positive_scaled(features.get("rel_strength_spy_20d"), 55, 7)
    volume_z = _safe_float(features.get("volume_zscore_20"))
    if volume_z is not None:
        momentum += _bounded(volume_z, 0, 3)
    momentum = round(_bounded(momentum, 0, 30), 4)

    history_count = int(features.get("earnings_history_count") or 0)
    positive_rate = _safe_float(features.get("earnings_positive_rate"))
    big_gap_rate = _safe_float(features.get("earnings_big_gap_rate"))
    down_gap_rate = _safe_float(features.get("earnings_down_gap_rate"))
    reaction_avg = _safe_float(features.get("earnings_reaction_avg"))
    confidence = min(1.0, history_count / 8) if history_count > 0 else 0.0
    adjusted_positive = ((positive_rate or 0.5) * history_count + 2.0) / (history_count + 4.0)
    adjusted_big_gap = ((big_gap_rate or 0.0) * history_count + 0.5) / (history_count + 4.0)
    earnings_pattern = 4.0 + adjusted_positive * 9 + adjusted_big_gap * 9 + confidence * 3
    earnings_pattern += _positive_scaled(reaction_avg, 120, 5)
    earnings_pattern = round(_bounded(earnings_pattern, 0, 25), 4)

    expectation = 0.0
    eps_count = _safe_float(features.get("analyst_eps_count"))
    revenue_count = _safe_float(features.get("analyst_revenue_count"))
    if eps_count is not None and eps_count >= 5:
        expectation += 3
    if revenue_count is not None and revenue_count >= 5:
        expectation += 3
    for field in (
        "analyst_eps_growth_vs_prev",
        "analyst_revenue_growth_vs_prev",
        "analyst_eps_revision_7d_model",
        "analyst_eps_revision_30d_model",
        "analyst_eps_revision_7d_local",
        "analyst_revenue_revision_7d_local",
        "analyst_eps_revision_30d_local",
        "analyst_revenue_revision_30d_local",
    ):
        expectation += _positive_scaled(features.get(field), 120, 2)
    expectation = round(_bounded(expectation, 0, 15), 4)

    external = round(_bounded(float(note.get("external_catalyst_score") or 0), 0, 20), 4)

    rows = sorted(event_rows or [prediction], key=_prediction_sort_key)
    previous_rows = [row for row in rows if _prediction_sort_key(row) <= _prediction_sort_key(prediction)]
    first = previous_rows[0] if previous_rows else prediction
    trajectory = 0.0
    first_score = normalize_pre_earnings_score(first.get("score"), first.get("max_score"))
    current_score = normalize_pre_earnings_score(prediction.get("score"), prediction.get("max_score"))
    if current_score is not None:
        trajectory += min(4, current_score / 25)
    if first_score is not None and current_score is not None:
        delta = current_score - first_score
        if delta > 0:
            trajectory += min(4, delta / 6)
        elif delta < -10:
            trajectory -= min(3, abs(delta) / 10)
    if len(previous_rows) >= 3:
        bullish_days = sum(1 for row in previous_rows if row.get("hypothesis") in BULLISH_HYPOTHESES)
        trajectory += min(2, bullish_days / len(previous_rows) * 2)
    trajectory = round(_bounded(trajectory, 0, 10), 4)

    risk_penalty = 0.0
    if down_gap_rate is not None and down_gap_rate >= 0.5:
        risk_penalty += 8
    elif down_gap_rate is not None and down_gap_rate >= 0.375:
        risk_penalty += 5
    if reaction_avg is not None and reaction_avg < -0.02:
        risk_penalty += 4
    return_20d = _safe_float(features.get("return_20d"))
    if return_20d is not None and return_20d > 0.35 and adjusted_big_gap < 0.2:
        risk_penalty += 4
    if features.get("above_sma200") is False and features.get("above_sma50") is False and external < 12:
        risk_penalty += 4
    risk_penalty += min(4, len(note.get("risk_flags", []) or []) * 2)
    risk_penalty = round(_bounded(risk_penalty, 0, 25), 4)
    learned_top_winner = bool(note.get("learned_top_winner"))
    risk_override_actionable = bool(note.get("risk_override_actionable"))

    total = _bounded(momentum + earnings_pattern + expectation + external + trajectory - risk_penalty)
    if external >= 16 and risk_penalty <= 4:
        total = max(total, 45.0)
    if external >= 14 and momentum >= 14:
        total = max(total, 45.0)
    if earnings_pattern >= 20 and external >= 12:
        total = max(total, 45.0)
    if external >= 14 and earnings_pattern >= 15 and risk_penalty <= 6:
        total = max(total, 45.0)
    high_conviction_bullish = (
        momentum >= 26
        and earnings_pattern >= 17
        and external >= 14
        and trajectory >= 2
        and risk_penalty <= 2
    )
    catalyst_supported_bullish = (
        total >= 45
        and external >= 14
        and risk_penalty <= 5
        and (
            momentum >= 18
            or earnings_pattern >= 15.5
            or trajectory >= 3
        )
    )
    catalyst_momentum_override = (
        total >= 45
        and external >= 15
        and momentum >= 26
        and earnings_pattern >= 11
        and trajectory >= 0.5
        and risk_penalty <= 16
    )
    learned_revision_winner = (
        learned_top_winner
        and external >= 16
        and expectation >= 10
        and trajectory >= 1
        and risk_penalty <= 12
    )
    learned_momentum_winner = (
        learned_top_winner
        and external >= 14
        and momentum >= 16
        and (expectation >= 8 or earnings_pattern >= 12)
        and (risk_penalty <= 12 or risk_override_actionable)
    )
    if high_conviction_bullish:
        total = max(total, 72.0)
    elif catalyst_supported_bullish or catalyst_momentum_override or learned_revision_winner or learned_momentum_winner:
        total = max(total, 70.0)
    total = round(total, 4)
    if risk_penalty >= 14 and total < 45:
        label = "riesgo_bajista"
    elif total >= 70:
        label = "subida_probable"
    elif total >= 45:
        label = "neutral_alcista"
    else:
        label = "sin_ventaja_clara"

    drivers: list[str] = []
    if momentum >= 18:
        drivers.append("momentum tecnico fuerte")
    if earnings_pattern >= 16:
        drivers.append("patron historico favorable")
    if external >= 12:
        drivers.append("catalizadores externos/previews favorables")
    if learned_top_winner:
        drivers.append("top winner historico aprendido")
    if trajectory >= 6:
        drivers.append("trayectoria diaria estable o mejorando")
    if risk_penalty >= 8:
        drivers.append("penalizacion por riesgo historico/extension")
    if expectation >= 6:
        drivers.append("expectativas/revisiones positivas")

    actionable_long, actionable_reason = _actionable_pre_earnings_signal(
        total,
        {
            "external_catalyst_score": external,
            "risk_penalty": risk_penalty,
            "learned_top_winner": learned_top_winner,
            "risk_override_actionable": risk_override_actionable,
        },
    )
    high_conviction_long, high_conviction_reason = _high_conviction_pre_earnings_signal(
        total,
        {
            "external_catalyst_score": external,
            "momentum_score": momentum,
            "earnings_pattern_score": earnings_pattern,
            "expectation_score": expectation,
            "trajectory_score": trajectory,
            "risk_penalty": risk_penalty,
            "learned_top_winner": learned_top_winner,
            "risk_override_actionable": risk_override_actionable,
        },
    )
    review_risk_veto = bool(
        high_conviction_long
        and not actionable_long
        and risk_penalty > 5
        and external >= 14
    )

    return {
        "pre_earnings_score_v2": total,
        "score_v2_label": label,
        "high_conviction_pre_earnings_long": high_conviction_long,
        "high_conviction_pre_earnings_reason": high_conviction_reason,
        "actionable_pre_earnings_long": actionable_long,
        "actionable_pre_earnings_reason": actionable_reason,
        "review_pre_earnings_risk_veto": review_risk_veto,
        "score_v2_components": {
            "momentum_score": momentum,
            "earnings_pattern_score": earnings_pattern,
            "expectation_score": expectation,
            "external_catalyst_score": external,
            "trajectory_score": trajectory,
            "risk_penalty": risk_penalty,
            "learned_top_winner": learned_top_winner,
            "risk_override_actionable": risk_override_actionable,
        },
        "score_v2_drivers": drivers,
        "research_note": note,
    }


def _classify_pre_earnings_event(official: dict[str, Any], return_pct: float | None) -> str:
    hypothesis = official.get("hypothesis")
    if return_pct is None:
        return "pendiente"
    if return_pct > BIG_WINNER_THRESHOLD and hypothesis == "subida_probable":
        return "gran_subida_detectada"
    if return_pct > BIG_WINNER_THRESHOLD and hypothesis in BULLISH_HYPOTHESES:
        return "gran_subida_infravalorada"
    if return_pct > BIG_WINNER_THRESHOLD:
        return "gran_subida_no_detectada"
    if hypothesis in BULLISH_HYPOTHESES and return_pct <= 0:
        return "falso_positivo_alcista"
    if hypothesis in BULLISH_HYPOTHESES and return_pct > 0:
        return "acierto_direccional"
    return "sin_senal_alcista"


def _failure_explanation(
    official: dict[str, Any],
    score_v2: dict[str, Any],
    return_pct: float | None,
) -> str:
    features = official.get("features") or {}
    components = score_v2.get("score_v2_components") or {}
    classification = _classify_pre_earnings_event(official, return_pct)
    if classification == "gran_subida_no_detectada":
        if components.get("external_catalyst_score", 0) >= 12:
            return "El score antiguo penalizo demasiado tendencia/historial y no incorporaba catalizadores externos sectoriales."
        if (features.get("earnings_big_gap_rate") or 0) >= 0.25:
            return "El score antiguo no dio suficiente peso a la propension historica a gaps grandes."
        return "El score antiguo exigia demasiadas confirmaciones tecnicas y dejo fuera un gap alcista grande."
    if classification == "gran_subida_infravalorada":
        return "La direccion alcista estaba detectada, pero el umbral antiguo no separo bien probabilidad de gran gap."
    if classification == "falso_positivo_alcista":
        return "La senal alcista fallo; V2 aumenta penalizaciones por gaps negativos, sobreextension y riesgo narrativo."
    if classification == "gran_subida_detectada":
        return "La senal antigua detecto la gran subida."
    return "Evento usado como control para calibrar falsos positivos y ausencia de ventaja."


def build_pre_earnings_score_study(
    store: Any,
    output_dir: Path,
    run_id: str,
    *,
    since_date: str | None = None,
    limit: int = 10000,
) -> dict[str, Any]:
    """Analyze persisted pre-earnings predictions and score them with V2."""

    predictions = store.pre_earnings_predictions(since_date=since_date, limit=limit)
    by_event = _pre_earnings_event_rows(predictions)
    events: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    for event_key, rows in by_event.items():
        official = _official_prediction(rows)
        outcome = official.get("outcome") or {}
        features = official.get("features") or {}
        return_pct = _safe_float(outcome.get("return_pct"))
        official_v2 = calculate_pre_earnings_score_v2(official, rows)
        daily_scores = []
        for row in rows:
            score_v2 = calculate_pre_earnings_score_v2(row, rows)
            daily = {
                "event_key": event_key,
                "symbol": row.get("symbol"),
                "prediction_date": row.get("prediction_date"),
                "legacy_hypothesis": row.get("hypothesis"),
                "legacy_score": row.get("score"),
                "legacy_max_score": row.get("max_score"),
                "legacy_score_pct": normalize_pre_earnings_score(row.get("score"), row.get("max_score")),
                **score_v2,
            }
            daily_scores.append(daily)
            daily_rows.append(daily)

        event = {
            "event_key": event_key,
            "symbol": official.get("symbol"),
            "earnings_date": features.get("earnings_date") or str(official.get("earnings_datetime") or "")[:10],
            "earnings_session": features.get("earnings_session") or "post-market",
            "official_prediction_date": official.get("prediction_date"),
            "legacy_hypothesis": official.get("hypothesis"),
            "legacy_score": official.get("score"),
            "legacy_max_score": official.get("max_score"),
            "legacy_score_pct": normalize_pre_earnings_score(official.get("score"), official.get("max_score")),
            "return_pct": return_pct,
            "outcome_status": outcome.get("status"),
            "classification": _classify_pre_earnings_event(official, return_pct),
            "predictions_count": len(rows),
            "timeline": _history_timeline(rows, official.get("prediction_id")),
            "daily_scores": daily_scores,
            "final_score_v2": official_v2["pre_earnings_score_v2"],
            "final_label_v2": official_v2["score_v2_label"],
            "high_conviction_pre_earnings_long": official_v2["high_conviction_pre_earnings_long"],
            "high_conviction_pre_earnings_reason": official_v2["high_conviction_pre_earnings_reason"],
            "actionable_pre_earnings_long": official_v2["actionable_pre_earnings_long"],
            "actionable_pre_earnings_reason": official_v2["actionable_pre_earnings_reason"],
            "review_pre_earnings_risk_veto": official_v2["review_pre_earnings_risk_veto"],
            "score_v2_components": official_v2["score_v2_components"],
            "score_v2_drivers": official_v2["score_v2_drivers"],
            "research_note": official_v2["research_note"],
            "failure_analysis": _failure_explanation(official, official_v2, return_pct),
        }
        events.append(event)

    resolved = [item for item in events if item.get("return_pct") is not None]
    big_winners = [item for item in resolved if float(item["return_pct"]) > BIG_WINNER_THRESHOLD]
    legacy_bullish = [item for item in resolved if item.get("legacy_hypothesis") in BULLISH_HYPOTHESES]
    v2_bullish = [item for item in resolved if item.get("final_label_v2") in BULLISH_HYPOTHESES]
    false_positive_legacy = [
        item for item in legacy_bullish if item.get("return_pct") is not None and float(item["return_pct"]) <= 0
    ]
    false_positive_v2 = [
        item for item in v2_bullish if item.get("return_pct") is not None and float(item["return_pct"]) <= 0
    ]
    actionable_v2 = [item for item in resolved if item.get("actionable_pre_earnings_long")]
    high_conviction_v2 = [item for item in resolved if item.get("high_conviction_pre_earnings_long")]
    risk_veto_review = [item for item in resolved if item.get("review_pre_earnings_risk_veto")]
    actionable_false_positive_v2 = [
        item for item in actionable_v2 if item.get("return_pct") is not None and float(item["return_pct"]) <= 0
    ]
    high_conviction_false_positive_v2 = [
        item for item in high_conviction_v2 if item.get("return_pct") is not None and float(item["return_pct"]) <= 0
    ]
    blocked_big_winners_v2 = [
        item
        for item in big_winners
        if item.get("high_conviction_pre_earnings_long")
        and not item.get("actionable_pre_earnings_long")
    ]
    metrics = {
        "predictions": len(predictions),
        "events": len(events),
        "resolved_events": len(resolved),
        "big_winners_gt_5": len(big_winners),
        "legacy_big_winners_subida_probable": sum(
            1 for item in big_winners if item.get("legacy_hypothesis") == "subida_probable"
        ),
        "legacy_big_winners_bullish": sum(
            1 for item in big_winners if item.get("legacy_hypothesis") in BULLISH_HYPOTHESES
        ),
        "legacy_big_winners_missed": sum(
            1 for item in big_winners if item.get("legacy_hypothesis") not in BULLISH_HYPOTHESES
        ),
        "v2_big_winners_subida_probable": sum(
            1 for item in big_winners if item.get("final_label_v2") == "subida_probable"
        ),
        "v2_big_winners_bullish": sum(1 for item in big_winners if item.get("final_label_v2") in BULLISH_HYPOTHESES),
        "v2_big_winners_missed": sum(1 for item in big_winners if item.get("final_label_v2") not in BULLISH_HYPOTHESES),
        "legacy_bullish_resolved": len(legacy_bullish),
        "legacy_false_positive_bullish": len(false_positive_legacy),
        "v2_bullish_resolved": len(v2_bullish),
        "v2_false_positive_bullish": len(false_positive_v2),
        "v2_actionable_resolved": len(actionable_v2),
        "v2_actionable_false_positive": len(actionable_false_positive_v2),
        "v2_big_winners_actionable": sum(1 for item in big_winners if item.get("actionable_pre_earnings_long")),
        "v2_high_conviction_resolved": len(high_conviction_v2),
        "v2_high_conviction_false_positive": len(high_conviction_false_positive_v2),
        "v2_big_winners_high_conviction": sum(
            1 for item in big_winners if item.get("high_conviction_pre_earnings_long")
        ),
        "v2_risk_veto_review_resolved": len(risk_veto_review),
        "v2_blocked_big_winners": len(blocked_big_winners_v2),
    }
    metrics["legacy_big_winner_capture_rate"] = (
        round(metrics["legacy_big_winners_bullish"] / len(big_winners), 6) if big_winners else None
    )
    metrics["v2_big_winner_capture_rate"] = (
        round(metrics["v2_big_winners_bullish"] / len(big_winners), 6) if big_winners else None
    )
    metrics["legacy_false_positive_rate"] = (
        round(len(false_positive_legacy) / len(legacy_bullish), 6) if legacy_bullish else None
    )
    metrics["v2_false_positive_rate"] = round(len(false_positive_v2) / len(v2_bullish), 6) if v2_bullish else None
    metrics["v2_actionable_capture_rate"] = (
        round(metrics["v2_big_winners_actionable"] / len(big_winners), 6) if big_winners else None
    )
    metrics["v2_actionable_false_positive_rate"] = (
        round(len(actionable_false_positive_v2) / len(actionable_v2), 6) if actionable_v2 else None
    )
    metrics["v2_high_conviction_capture_rate"] = (
        round(metrics["v2_big_winners_high_conviction"] / len(big_winners), 6) if big_winners else None
    )
    metrics["v2_high_conviction_false_positive_rate"] = (
        round(len(high_conviction_false_positive_v2) / len(high_conviction_v2), 6)
        if high_conviction_v2
        else None
    )

    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mode": "pre_earnings_score_v2_study",
        "operation_allowed": False,
        "since_date": since_date,
        "metrics": metrics,
        "big_winners": sorted(big_winners, key=lambda item: float(item.get("return_pct") or 0), reverse=True),
        "top_10_most_profitable": sorted(
            resolved,
            key=lambda item: float(item.get("return_pct") or 0),
            reverse=True,
        )[:10],
        "blocked_big_winners": sorted(
            blocked_big_winners_v2,
            key=lambda item: float(item.get("return_pct") or 0),
            reverse=True,
        ),
        "risk_veto_review": sorted(
            risk_veto_review,
            key=lambda item: float(item.get("return_pct") or 0),
            reverse=True,
        ),
        "false_positive_bullish": sorted(
            false_positive_legacy,
            key=lambda item: float(item.get("return_pct") or 0),
        ),
        "events": sorted(
            events,
            key=lambda item: (str(item.get("earnings_date")), str(item.get("symbol"))),
            reverse=True,
        ),
        "daily_scores": daily_rows,
        "methodology_note": (
            "Score V2 calculado solo con features persistidas antes del earnings y notas externas auditables. "
            "Los catalizadores posteriores se usan solo en el diagnostico de fallos."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pre_earnings_score_study_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report["path"] = str(output_path)
    return report


def _pre_earnings_event_digest_row(event_key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    official = _official_prediction(rows)
    outcome = official.get("outcome") or {}
    features = official.get("features") or {}
    return_pct = _safe_float(outcome.get("return_pct"))
    score_v2 = calculate_pre_earnings_score_v2(official, rows)
    has_estimates = (
        _safe_float(features.get("analyst_eps_estimate")) is not None
        or _safe_float(features.get("analyst_revenue_estimate")) is not None
    )
    analyst_error = str(features.get("analyst_estimates_error") or "").strip()
    return {
        "event_key": event_key,
        "symbol": official.get("symbol"),
        "earnings_date": features.get("earnings_date") or str(official.get("earnings_datetime") or "")[:10],
        "earnings_session": features.get("earnings_session") or "post-market",
        "official_prediction_date": official.get("prediction_date"),
        "legacy_hypothesis": official.get("hypothesis"),
        "return_pct": return_pct,
        "outcome_status": outcome.get("status"),
        "predictions_count": len(rows),
        "has_analyst_estimates": has_estimates,
        "analyst_estimates_error": analyst_error or None,
        "analyst_estimates_source": features.get("analyst_estimates_source"),
        "final_score_v2": score_v2["pre_earnings_score_v2"],
        "final_label_v2": score_v2["score_v2_label"],
        "high_conviction_pre_earnings_long": score_v2["high_conviction_pre_earnings_long"],
        "high_conviction_pre_earnings_reason": score_v2["high_conviction_pre_earnings_reason"],
        "actionable_pre_earnings_long": score_v2["actionable_pre_earnings_long"],
        "actionable_pre_earnings_reason": score_v2["actionable_pre_earnings_reason"],
        "review_pre_earnings_risk_veto": score_v2["review_pre_earnings_risk_veto"],
        "score_v2_components": score_v2["score_v2_components"],
        "score_v2_drivers": score_v2["score_v2_drivers"],
        "failure_analysis": _failure_explanation(official, score_v2, return_pct),
    }


def build_pre_earnings_learning_digest(
    store: Any,
    output_dir: Path,
    run_id: str,
    *,
    since_date: str | None = None,
    limit: int = 10000,
) -> dict[str, Any]:
    predictions = store.pre_earnings_predictions(since_date=since_date, limit=limit)
    by_event = _pre_earnings_event_rows(predictions)
    events = [_pre_earnings_event_digest_row(event_key, rows) for event_key, rows in by_event.items()]
    resolved = [item for item in events if item.get("return_pct") is not None]
    high_conviction = [item for item in resolved if item.get("high_conviction_pre_earnings_long")]
    actionable = [item for item in resolved if item.get("actionable_pre_earnings_long")]
    risk_veto = [item for item in resolved if item.get("review_pre_earnings_risk_veto")]
    big_winners = [item for item in resolved if float(item.get("return_pct") or 0.0) > BIG_WINNER_THRESHOLD]
    blocked_big_winners = [
        item for item in big_winners if item.get("high_conviction_pre_earnings_long") and not item.get("actionable_pre_earnings_long")
    ]
    estimate_rows = sum(1 for item in events if item.get("has_analyst_estimates"))
    estimate_errors = [item for item in events if item.get("analyst_estimates_error")]
    missing_estimates = len(events) - estimate_rows
    metrics = {
        "predictions": len(predictions),
        "events": len(events),
        "resolved_events": len(resolved),
        "big_winners_gt_5": len(big_winners),
        "high_conviction_resolved": len(high_conviction),
        "high_conviction_hits": sum(1 for item in high_conviction if float(item.get("return_pct") or 0.0) > 0),
        "high_conviction_false_positives": sum(1 for item in high_conviction if float(item.get("return_pct") or 0.0) <= 0),
        "actionable_resolved": len(actionable),
        "actionable_hits": sum(1 for item in actionable if float(item.get("return_pct") or 0.0) > 0),
        "actionable_false_positives": sum(1 for item in actionable if float(item.get("return_pct") or 0.0) <= 0),
        "risk_veto_review_resolved": len(risk_veto),
        "risk_veto_big_winners": sum(1 for item in risk_veto if float(item.get("return_pct") or 0.0) > BIG_WINNER_THRESHOLD),
        "blocked_big_winners": len(blocked_big_winners),
        "estimate_rows": estimate_rows,
        "estimate_missing_rows": missing_estimates,
        "estimate_error_rows": len(estimate_errors),
        "estimate_coverage_rate": round(estimate_rows / len(events), 6) if events else None,
    }
    metrics["high_conviction_capture_rate"] = (
        round(sum(1 for item in big_winners if item.get("high_conviction_pre_earnings_long")) / len(big_winners), 6)
        if big_winners
        else None
    )
    metrics["actionable_capture_rate"] = (
        round(sum(1 for item in big_winners if item.get("actionable_pre_earnings_long")) / len(big_winners), 6)
        if big_winners
        else None
    )
    metrics["risk_veto_big_winner_rate"] = (
        round(metrics["risk_veto_big_winners"] / len(risk_veto), 6) if risk_veto else None
    )
    metrics["high_conviction_win_rate"] = (
        round(metrics["high_conviction_hits"] / len(high_conviction), 6) if high_conviction else None
    )
    metrics["actionable_win_rate"] = (
        round(metrics["actionable_hits"] / len(actionable), 6) if actionable else None
    )

    guidance: list[str] = []
    if (metrics.get("estimate_coverage_rate") or 0.0) < 0.5:
        guidance.append("La captura de estimaciones de analistas sigue siendo insuficiente; sin esa capa el aprendizaje pre-earnings queda incompleto.")
    if metrics.get("blocked_big_winners", 0) > 0 and metrics.get("actionable_false_positives", 0) == 0:
        guidance.append("Hay ganadores fuertes vetados solo por riesgo; revisar ese veto en shadow antes de relajar la politica actionable.")
    if (metrics.get("high_conviction_capture_rate") or 0.0) > (metrics.get("actionable_capture_rate") or 0.0):
        guidance.append("Usar la capa high_conviction como watchlist prioritaria mejora el recall sin introducir compras automaticas nuevas.")
    if metrics.get("estimate_error_rows", 0) > 0:
        guidance.append("Persistir el motivo de fallo de estimaciones permite distinguir falta de datos de sesgo del modelo.")
    if not guidance:
        guidance.append("La separacion entre bullish, high_conviction y actionable esta estable; mantener politica conservadora y seguir acumulando evidencia.")

    digest = {
        "available": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "events": len(events),
            "resolved_events": len(resolved),
            "big_winners_gt_5": len(big_winners),
            "estimate_coverage_rate": metrics.get("estimate_coverage_rate"),
            "blocked_big_winners": metrics.get("blocked_big_winners", 0),
        },
        "metrics": metrics,
        "snapshot_health": {
            "estimate_rows": estimate_rows,
            "estimate_missing_rows": missing_estimates,
            "estimate_error_rows": len(estimate_errors),
            "estimate_errors_sample": Counter(
                item["analyst_estimates_error"] for item in estimate_errors if item.get("analyst_estimates_error")
            ).most_common(5),
        },
        "high_conviction_examples": sorted(
            high_conviction,
            key=lambda item: float(item.get("return_pct") or -999.0),
            reverse=True,
        )[:10],
        "top_actionable": sorted(
            actionable,
            key=lambda item: float(item.get("return_pct") or -999.0),
            reverse=True,
        )[:10],
        "blocked_big_winners": sorted(
            blocked_big_winners,
            key=lambda item: float(item.get("return_pct") or -999.0),
            reverse=True,
        )[:10],
        "risk_veto_review": sorted(
            risk_veto,
            key=lambda item: float(item.get("return_pct") or -999.0),
            reverse=True,
        )[:10],
        "guidance": guidance[:6],
    }
    report = {
        "run_id": run_id,
        "as_of": digest["as_of"],
        "mode": "pre_earnings_learning_digest",
        "since_date": since_date,
        "metrics": metrics,
        "digest": digest,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pre_earnings_learning_digest_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    latest_path = output_dir / "latest_pre_earnings_learning_digest.json"
    latest_path.write_text(json.dumps(digest, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report["path"] = str(output_path)
    report["latest_path"] = str(latest_path)
    return report


def backfill_pending_pre_earnings_estimates(
    store: Any,
    output_dir: Path,
    run_id: str,
    *,
    today: date | None = None,
    limit: int = 1000,
    api_key: str | None = None,
) -> dict[str, Any]:
    current_day = today or datetime.now(timezone.utc).date()
    predictions = store.pre_earnings_predictions(limit=limit)
    eligible: list[dict[str, Any]] = []
    for item in predictions:
        if str(item.get("status") or "") != "pending":
            continue
        earnings_dt = str(item.get("earnings_datetime") or "")
        if not earnings_dt:
            continue
        try:
            earnings_date = datetime.fromisoformat(earnings_dt).astimezone(MARKET_TZ).date()
        except ValueError:
            continue
        if earnings_date < current_day:
            continue
        eligible.append(item)

    analyst_cache = _load_json_cache(_analyst_cache_path(output_dir.parent / "cache"))
    updated = 0
    skipped_temporal = max(0, len(predictions) - len(eligible))
    enriched_symbols: list[str] = []
    warnings: list[str] = []
    for item in eligible:
        symbol = str(item.get("symbol") or "").upper()
        features = dict(item.get("features") or {})
        if _safe_float(features.get("analyst_eps_estimate")) is not None or _safe_float(features.get("analyst_revenue_estimate")) is not None:
            continue
        try:
            earnings_date = datetime.fromisoformat(str(item.get("earnings_datetime"))).astimezone(MARKET_TZ).date()
        except ValueError:
            warnings.append(f"{symbol}: earnings_datetime invalido")
            continue
        expectations, _diag = _analyst_expectation_features(symbol, earnings_date, analyst_cache, api_key=api_key)
        if (
            _safe_float(expectations.get("analyst_eps_estimate")) is None
            and _safe_float(expectations.get("analyst_revenue_estimate")) is None
        ):
            continue
        features.update(expectations)
        local_revisions = analyst_revision_features_from_store(
            store,
            symbol,
            features,
            str(item.get("prediction_date") or current_day.isoformat()),
        )
        features.update(local_revisions)
        prediction_like = {
            **item,
            "features": features,
        }
        score_v2 = calculate_pre_earnings_score_v2(prediction_like, [prediction_like])
        features.update(
            {
                "pre_earnings_score_v2": score_v2["pre_earnings_score_v2"],
                "score_v2_label": score_v2["score_v2_label"],
                "high_conviction_pre_earnings_long": score_v2["high_conviction_pre_earnings_long"],
                "high_conviction_pre_earnings_reason": score_v2["high_conviction_pre_earnings_reason"],
                "actionable_pre_earnings_long": score_v2["actionable_pre_earnings_long"],
                "actionable_pre_earnings_reason": score_v2["actionable_pre_earnings_reason"],
                "review_pre_earnings_risk_veto": score_v2["review_pre_earnings_risk_veto"],
                "score_v2_components": score_v2["score_v2_components"],
                "score_v2_drivers": score_v2["score_v2_drivers"],
                "score_v2_research_note": score_v2["research_note"],
            }
        )
        store.save_pre_earnings_prediction(
            {
                "prediction_id": item["prediction_id"],
                "source_run_id": item["source_run_id"],
                "symbol": symbol,
                "prediction_date": item["prediction_date"],
                "session_date": item["session_date"],
                "earnings_datetime": item["earnings_datetime"],
                "hypothesis": item["hypothesis"],
                "score": item["score"],
                "max_score": item["max_score"],
                "reason": item.get("reason") or "",
                "features": features,
                "outcome": item.get("outcome") or {},
                "status": item.get("status") or "pending",
                "created_at": item.get("created_at"),
            }
        )
        updated += 1
        enriched_symbols.append(symbol)

    _save_json_cache(_analyst_cache_path(output_dir.parent / "cache"), analyst_cache)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mode": "pre_earnings_pending_estimates_backfill",
        "updated_predictions": updated,
        "eligible_predictions": len(eligible),
        "skipped_temporal_safety": skipped_temporal,
        "symbols": sorted(set(enriched_symbols)),
        "warnings": warnings[:20],
        "note": (
            "Solo se enriquecen predicciones pending/futuras. "
            "No se backfillean eventos ya resueltos para evitar fuga temporal con estimaciones actuales."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pre_earnings_pending_backfill_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report["path"] = str(output_path)
    return report


def load_pre_earnings_learning_context(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_pre_earnings_learning_digest.json"
    if not path.exists():
        return {"available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False}
    return {
        "available": True,
        "as_of": payload.get("as_of"),
        "summary": payload.get("summary", {}),
        "metrics": payload.get("metrics", {}),
        "guidance": list(payload.get("guidance", []) or [])[:6],
        "blocked_big_winners": list(payload.get("blocked_big_winners", []) or [])[:5],
        "risk_veto_review": list(payload.get("risk_veto_review", []) or [])[:5],
        "snapshot_health": payload.get("snapshot_health", {}),
    }


def _current_pre_earnings_session_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    sessions = list(report.get("sessions", []) or [])
    if sessions:
        return list(sessions[0].get("items", []) or [])
    return list(report.get("items", []) or [])


def _pre_earnings_trade_confidence(score_v2: float) -> float:
    if score_v2 >= 90:
        return 0.90
    if score_v2 >= 80:
        return round(0.81 + min(0.09, (score_v2 - 80.0) * 0.009), 4)
    return round(0.72 + max(0.0, score_v2 - 70.0) * 0.009, 4)


def _pre_earnings_trade_levels(
    entry_price: float,
    *,
    score_v2: float,
    risk_penalty: float,
) -> tuple[float, float]:
    stop_pct = min(0.10, 0.06 + max(0.0, risk_penalty) * 0.003)
    if score_v2 >= 82:
        stop_pct = max(0.055, stop_pct - 0.005)
    take_pct = max(0.12, round(stop_pct * 2.0, 4))
    return (
        round(entry_price * (1.0 - stop_pct), 4),
        round(entry_price * (1.0 + take_pct), 4),
    )


def _pre_earnings_target_exposure_pct(
    settings: Settings,
    *,
    score_v2: float,
    expectation_score: float,
    risk_penalty: float,
) -> float:
    target = min(
        float(settings.max_position_exposure),
        float(settings.pre_earnings_trade_target_exposure_pct),
    )
    if score_v2 >= 82 and expectation_score >= 3 and risk_penalty <= 2:
        target = min(float(settings.max_position_exposure), target + 0.005)
    return round(max(0.01, target), 4)


def build_pre_earnings_trade_recommendations(
    settings: Settings,
    report: dict[str, Any],
    *,
    limit: int | None = None,
) -> list[TradeRecommendation]:
    if not settings.pre_earnings_trade_enabled:
        return []

    candidates: list[tuple[float, float, str, TradeRecommendation]] = []
    for item in _current_pre_earnings_session_items(report):
        if not item.get("actionable_pre_earnings_long"):
            continue
        if item.get("review_pre_earnings_risk_veto"):
            continue
        entry_price = _safe_float(item.get("last_close"))
        score_v2 = _safe_float(item.get("pre_earnings_score_v2"))
        if entry_price is None or entry_price <= 0 or score_v2 is None:
            continue
        if score_v2 < float(settings.pre_earnings_trade_min_score_v2):
            continue
        components = item.get("score_v2_components") or {}
        drivers = list(item.get("score_v2_drivers", []) or [])
        risk_penalty = float(_safe_float(components.get("risk_penalty")) or 0.0)
        expectation_score = float(_safe_float(components.get("expectation_score")) or 0.0)
        stop_loss, take_profit = _pre_earnings_trade_levels(
            entry_price,
            score_v2=score_v2,
            risk_penalty=risk_penalty,
        )
        reason_parts = [str(item.get("actionable_pre_earnings_reason") or "setup pre-earnings accionable")]
        if drivers:
            reason_parts.append(", ".join(str(driver) for driver in drivers[:2]))
        reason = ". ".join(part for part in reason_parts if part)
        recommendation = TradeRecommendation(
            symbol=str(item.get("symbol") or "").upper(),
            action="buy",
            confidence=_pre_earnings_trade_confidence(score_v2),
            reason=reason,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            target_exposure_pct=_pre_earnings_target_exposure_pct(
                settings,
                score_v2=score_v2,
                expectation_score=expectation_score,
                risk_penalty=risk_penalty,
            ),
            time_horizon="earnings_event_1d",
            invalidation=(
                f"Anular si pierde {stop_loss:.2f} antes del evento o si desaparece la conviccion pre-earnings."
            ),
            source="pre_earnings",
        )
        candidates.append(
            (
                score_v2,
                float(_safe_float(components.get("external_catalyst_score")) or 0.0),
                recommendation.symbol,
                recommendation,
            )
        )

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    max_items = limit if limit is not None else max(1, int(settings.max_orders_per_cycle))
    return [item[3] for item in candidates[:max_items]]


def build_pre_earnings_trade_operation(
    settings: Settings,
    portfolio: PortfolioSnapshot,
    report: dict[str, Any],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    from .trade_decision import build_order_plans

    recommendations = build_pre_earnings_trade_recommendations(settings, report)
    plans = build_order_plans(settings, portfolio, recommendations, dry_run=dry_run) if recommendations else []
    actionable_symbols = [item.symbol for item in recommendations]
    return {
        "enabled": settings.pre_earnings_trade_enabled,
        "actionable_symbols": actionable_symbols,
        "recommendations": recommendations,
        "plans": plans,
    }


def enrich_report_with_pre_earnings_score_v2(store: Any, report: dict[str, Any], *, limit: int = 10000) -> int:
    """Add Score V2 to visible daily report items before persistence."""

    as_of = str(report.get("as_of") or datetime.now(timezone.utc).isoformat())
    prediction_date = as_of[:10]
    persisted = store.pre_earnings_predictions(limit=limit) if hasattr(store, "pre_earnings_predictions") else []
    by_event = _pre_earnings_event_rows(persisted)
    updated = 0
    for session in report.get("sessions", []) or []:
        for item in session.get("items", []) or []:
            if not item.get("symbol"):
                continue
            current = _prediction_like_from_report_item(item, prediction_date)
            key = _event_key_from_report_item(item)
            rows = [
                row
                for row in by_event.get(key, [])
                if str(row.get("prediction_id") or "") != current["prediction_id"]
            ]
            rows.append(current)
            rows.sort(key=_prediction_sort_key)
            score_v2 = calculate_pre_earnings_score_v2(current, rows)
            item.update(
                {
                    "pre_earnings_score_v2": score_v2["pre_earnings_score_v2"],
                    "score_v2_label": score_v2["score_v2_label"],
                    "high_conviction_pre_earnings_long": score_v2["high_conviction_pre_earnings_long"],
                    "high_conviction_pre_earnings_reason": score_v2["high_conviction_pre_earnings_reason"],
                    "actionable_pre_earnings_long": score_v2["actionable_pre_earnings_long"],
                    "actionable_pre_earnings_reason": score_v2["actionable_pre_earnings_reason"],
                    "review_pre_earnings_risk_veto": score_v2["review_pre_earnings_risk_veto"],
                    "score_v2_components": score_v2["score_v2_components"],
                    "score_v2_drivers": score_v2["score_v2_drivers"],
                    "score_v2_research_note": score_v2["research_note"],
                }
            )
            updated += 1
    report["score_v2_items_updated"] = updated
    return updated


def _historical_after_close_events(
    symbol: str,
    start_date: date,
    end_date: date,
    calendar_cache: dict[str, Any],
    *,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame, source, error = _earnings_rows_cached(symbol, calendar_cache, limit=limit)
    diagnostics = {
        "symbol": symbol,
        "source": source,
        "calendar_rows": int(len(frame)) if not frame.empty else 0,
        "error": error,
    }
    if frame.empty:
        return [], diagnostics

    events: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        event_dt = row["earnings_datetime"]
        try:
            market_dt = pd.Timestamp(event_dt).to_pydatetime()
        except Exception:
            continue
        if market_dt.tzinfo is None:
            market_dt = market_dt.replace(tzinfo=MARKET_TZ)
        market_dt = market_dt.astimezone(MARKET_TZ)
        if market_dt.date() < start_date or market_dt.date() > end_date:
            continue
        if not _is_after_close_event(market_dt):
            continue
        events.append(
            {
                "symbol": symbol,
                "source": source,
                "session_date": market_dt.date().isoformat(),
                "earnings_date": market_dt.date().isoformat(),
                "earnings_session": _earnings_session_label(market_dt),
                "earnings_datetime": market_dt.isoformat(),
                "eps_estimate": _safe_float(row.get("EPS Estimate")),
                "reported_eps": _safe_float(row.get("Reported EPS")),
                "surprise_pct": _safe_float(row.get("Surprise(%)")),
            }
        )
    diagnostics["matched_events"] = len(events)
    return events, diagnostics


def _event_outcome_from_daily(
    event: dict[str, Any],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    event_dt = datetime.fromisoformat(event["earnings_datetime"]).astimezone(MARKET_TZ)
    daily = frame.copy()
    daily.index = pd.to_datetime(daily.index)
    event_rows = daily[daily.index.date == event_dt.date()]
    if event_rows.empty:
        return {"status": "sin_cierre_previo", "return_pct": None, "price_used": None}

    pre_close = float(event_rows.iloc[-1]["Close"])
    later = daily[daily.index.date > event_dt.date()]
    if later.empty or pd.isna(later.iloc[0].get("Open")):
        return {"status": "sin_precio_posterior", "return_pct": None, "base_price": round(pre_close, 4)}
    next_open = float(later.iloc[0]["Open"])
    next_close = float(later.iloc[0]["Close"]) if pd.notna(later.iloc[0].get("Close")) else None
    return {
        "status": "resolved_next_open",
        "return_pct": round(next_open / pre_close - 1, 6),
        "next_close_return_pct": round(next_close / pre_close - 1, 6) if next_close else None,
        "price_used": round(next_open, 4),
        "base_price": round(pre_close, 4),
        "next_session_date": str(pd.Timestamp(later.index[0]).date()),
    }


def _event_study_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [item for item in events if (item.get("outcome") or {}).get("return_pct") is not None]
    bullish = [item for item in resolved if item.get("hypothesis") in BULLISH_HYPOTHESES]
    bullish_hits = [item for item in bullish if float((item.get("outcome") or {}).get("return_pct")) > 0]
    bullish_misses = [item for item in bullish if float((item.get("outcome") or {}).get("return_pct")) <= 0]
    returns = [float((item.get("outcome") or {}).get("return_pct")) for item in resolved]
    bullish_returns = [float((item.get("outcome") or {}).get("return_pct")) for item in bullish]

    by_hypothesis: dict[str, dict[str, Any]] = {}
    for name in sorted({str(item.get("hypothesis")) for item in events}):
        subset = [item for item in resolved if item.get("hypothesis") == name]
        subset_returns = [float((item.get("outcome") or {}).get("return_pct")) for item in subset]
        by_hypothesis[name] = {
            "events": sum(1 for item in events if item.get("hypothesis") == name),
            "resolved": len(subset),
            "positive_rate": round(sum(1 for value in subset_returns if value > 0) / len(subset_returns), 6)
            if subset_returns
            else None,
            "avg_return": round(float(pd.Series(subset_returns).mean()), 6) if subset_returns else None,
            "median_return": round(float(pd.Series(subset_returns).median()), 6) if subset_returns else None,
        }

    return {
        "events": len(events),
        "resolved": len(resolved),
        "pending_or_unresolved": len(events) - len(resolved),
        "bullish_predictions": len([item for item in events if item.get("hypothesis") in BULLISH_HYPOTHESES]),
        "bullish_resolved": len(bullish),
        "bullish_hits": len(bullish_hits),
        "bullish_misses": len(bullish_misses),
        "success_rate": round(len(bullish_hits) / len(bullish), 6) if bullish else None,
        "avg_return": round(float(pd.Series(returns).mean()), 6) if returns else None,
        "median_return": round(float(pd.Series(returns).median()), 6) if returns else None,
        "bullish_avg_return": round(float(pd.Series(bullish_returns).mean()), 6) if bullish_returns else None,
        "bullish_median_return": round(float(pd.Series(bullish_returns).median()), 6) if bullish_returns else None,
        "best_event": max(resolved, key=lambda item: float((item.get("outcome") or {}).get("return_pct")), default=None),
        "worst_event": min(resolved, key=lambda item: float((item.get("outcome") or {}).get("return_pct")), default=None),
        "by_hypothesis": by_hypothesis,
    }


def build_pre_earnings_event_study(
    symbols: list[str],
    output_dir: Path,
    run_id: str,
    *,
    start: str,
    end: str | None = None,
    lookback_days: int = 420,
    calendar_name: str = "XNYS",
    local_timezone: str = "Europe/Madrid",
    fmp_api_key: str | None = None,
    cache_dir: Path | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    start_date = datetime.fromisoformat(start).date()
    end_date = datetime.fromisoformat(end).date() if end else datetime.now(timezone.utc).date()
    resolved_cache_dir = cache_dir or output_dir.parent / "cache"
    calendar_cache = _load_calendar_cache(resolved_cache_dir)
    analyst_cache = _load_json_cache(_analyst_cache_path(resolved_cache_dir))
    warnings: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    raw_events: list[dict[str, Any]] = []

    for index, symbol in enumerate(symbols, start=1):
        events, symbol_diagnostics = _historical_after_close_events(symbol, start_date, end_date, calendar_cache)
        raw_events.extend(events)
        diagnostics.append(symbol_diagnostics)
        if symbol_diagnostics.get("error"):
            warnings.append(f"{symbol}: calendario earnings no disponible ({symbol_diagnostics['error']})")
        if progress_callback and (index % 25 == 0 or index == len(symbols)):
            progress_callback(index, len(symbols), len(raw_events))
    _save_calendar_cache(resolved_cache_dir, calendar_cache)

    event_symbols = sorted({item["symbol"] for item in raw_events})
    price_symbols = sorted(set(event_symbols) | {"SPY"})
    price_data = pd.DataFrame()
    if price_symbols:
        price_start = start_date - timedelta(days=lookback_days)
        price_end = end_date + timedelta(days=10)
        try:
            price_data = download_daily_prices(price_symbols, start=price_start.isoformat(), end=price_end.isoformat())
        except Exception as exc:
            warnings.append(f"precios: {exc}")

    multi_symbol = isinstance(price_data.columns, pd.MultiIndex)
    study_events: list[dict[str, Any]] = []
    for event in sorted(raw_events, key=lambda item: (item["session_date"], item["symbol"])):
        symbol = event["symbol"]
        try:
            frame = _symbol_frame(price_data, symbol, multi_symbol)
            event_day = datetime.fromisoformat(event["earnings_datetime"]).astimezone(MARKET_TZ).date()
            feature_frame = frame[pd.to_datetime(frame.index).date <= event_day]
            spy_frame = _symbol_frame(price_data, "SPY", multi_symbol)
            spy_feature_frame = spy_frame[pd.to_datetime(spy_frame.index).date <= event_day]
            history = _earnings_history_features(symbol, event_day, frame, calendar_cache)
            expectations, _expectation_diag = _analyst_expectation_features(
                symbol,
                event_day,
                analyst_cache,
                api_key=fmp_api_key,
            )
            hypothesis = _technical_hypothesis(symbol, feature_frame, spy_feature_frame, history, expectations)
            outcome = _event_outcome_from_daily(event, frame)
        except Exception as exc:
            warnings.append(f"{symbol} {event.get('session_date')}: {exc}")
            hypothesis = {
                "hypothesis": "sin_datos_suficientes",
                "score": 0,
                "max_score": 16,
                "reason": "no se pudo calcular la hipotesis historica",
            }
            outcome = {"status": "sin_datos", "return_pct": None}
        study_events.append({**event, **hypothesis, "outcome": outcome})

    metrics = _event_study_metrics(study_events)
    _save_json_cache(_analyst_cache_path(resolved_cache_dir), analyst_cache)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mode": "pre_earnings_event_study_informativo",
        "operation_allowed": False,
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat()},
        "universe_size": len(symbols),
        "symbols_with_events": len(event_symbols),
        "metrics": metrics,
        "events": study_events,
        "data_quality": {
            "calendar_source": "yfinance",
            "cache_path": str(_calendar_cache_path(resolved_cache_dir)),
            "cache_hits": sum(1 for item in diagnostics if item.get("source") == "cache"),
            "yfinance_calls": sum(1 for item in diagnostics if item.get("source") == "yfinance"),
            "calendar_errors": sum(1 for item in diagnostics if item.get("error")),
            "calendar_rows": sum(int(item.get("calendar_rows") or 0) for item in diagnostics),
            "symbols_checked": len(diagnostics),
            "diagnostics": diagnostics[:100],
        },
        "warnings": warnings[:100],
        "methodology_note": (
            "Estudio exploratorio con calendario y precios de yfinance. Para eventos AMC usa el cierre "
            "de la sesion del anuncio como precio base y la siguiente apertura como resultado principal."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pre_earnings_event_study_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    report["path"] = str(output_path)
    return report


def build_pre_earnings_report(
    symbols: list[str],
    output_dir: Path,
    run_id: str,
    calendar_name: str = "XNYS",
    local_timezone: str = "Europe/Madrid",
    lookback_days: int = 420,
    session_count: int = 5,
    cache_dir: Path | None = None,
    progress_callback: Any | None = None,
    fmp_api_key: str | None = None,
) -> dict[str, Any]:
    calendar = MarketCalendar(calendar_name, local_timezone)
    as_of_dt = datetime.now(timezone.utc)
    estimated_on_date = as_of_dt.astimezone(ZoneInfo(local_timezone)).date().isoformat()
    extended_session_dates = upcoming_after_close_sessions(calendar, session_count=session_count + 1)
    session_dates = extended_session_dates[: max(int(session_count or 1), 1)]
    event_to_analysis_session: dict[tuple[date, str], date] = {}
    for index, session_day in enumerate(session_dates):
        event_to_analysis_session[(session_day, "post-market")] = session_day
        if index + 1 < len(extended_session_dates):
            event_to_analysis_session[(extended_session_dates[index + 1], "pre-market")] = session_day
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    resolved_cache_dir = cache_dir or output_dir.parent / "cache"
    calendar_cache = _load_calendar_cache(resolved_cache_dir)
    analyst_cache = _load_json_cache(_analyst_cache_path(resolved_cache_dir))
    analyst_diagnostics: list[dict[str, Any]] = []

    for index, symbol in enumerate(symbols, start=1):
        symbol_events, symbol_diagnostics = _events_for_sessions(symbol, event_to_analysis_session, calendar_cache)
        events.extend(symbol_events)
        diagnostics.append(symbol_diagnostics)
        if symbol_diagnostics.get("error"):
            warnings.append(f"{symbol}: calendario earnings no disponible ({symbol_diagnostics['error']})")
        if progress_callback and (index % 25 == 0 or index == len(symbols)):
            progress_callback(index, len(symbols), len(events))
    _save_calendar_cache(resolved_cache_dir, calendar_cache)

    price_symbols = sorted({item["symbol"] for item in events} | {"SPY"})
    price_data = pd.DataFrame()
    if events and price_symbols:
        latest_event_date = max(
            datetime.fromisoformat(item["earnings_datetime"]).astimezone(MARKET_TZ).date()
            for item in events
        )
        end = max(datetime.now(timezone.utc).date(), latest_event_date) + timedelta(days=2)
        start = end - timedelta(days=max(lookback_days, 365 * 5 + 30))
        try:
            price_data = download_daily_prices(price_symbols, start=start.isoformat(), end=end.isoformat())
        except Exception as exc:
            warnings.append(f"precios: {exc}")

    multi_symbol = isinstance(price_data.columns, pd.MultiIndex)
    spy_frame = None
    if not price_data.empty:
        try:
            spy_frame = _symbol_frame(price_data, "SPY", multi_symbol)
        except Exception:
            spy_frame = None

    rows_by_session: dict[str, list[dict[str, Any]]] = {item.isoformat(): [] for item in session_dates}
    for event in events:
        symbol = event["symbol"]
        try:
            frame = _symbol_frame(price_data, symbol, multi_symbol)
            event_day = datetime.fromisoformat(event["earnings_datetime"]).astimezone(MARKET_TZ).date()
            estimation_day = datetime.fromisoformat(event.get("session_date") or event_day.isoformat()).date()
            feature_frame = frame[pd.to_datetime(frame.index).date <= estimation_day]
            spy_feature_frame = (
                spy_frame[pd.to_datetime(spy_frame.index).date <= estimation_day]
                if spy_frame is not None and not spy_frame.empty
                else spy_frame
            )
            history = _earnings_history_features(symbol, event_day, frame, calendar_cache)
            expectations, expectation_diag = _analyst_expectation_features(
                symbol,
                event_day,
                analyst_cache,
                api_key=fmp_api_key,
            )
            analyst_diagnostics.append(expectation_diag)
            hypothesis = _technical_hypothesis(symbol, feature_frame, spy_feature_frame, history, expectations)
            outcome = _outcome(symbol, event["earnings_datetime"], frame, event.get("session_date"))
        except Exception as exc:
            warnings.append(f"{symbol}: {exc}")
            hypothesis = {
                "hypothesis": "sin_datos_suficientes",
                "score": 0,
                "max_score": 16,
                "reason": "no se pudo calcular la hipotesis",
            }
            outcome = {"status": "sin_datos", "return_pct": None, "price_used": None}
        session_key = event.get("session_date") or datetime.fromisoformat(
            event["earnings_datetime"]
        ).astimezone(MARKET_TZ).date().isoformat()
        rows_by_session.setdefault(session_key, []).append(
            {**event, **hypothesis, "estimated_on": estimated_on_date, "outcome": outcome}
        )

    sessions = []
    for session_day in session_dates:
        key = session_day.isoformat()
        items = sorted(
            rows_by_session.get(key, []),
            key=lambda item: (-int(item.get("score") or 0), item["symbol"]),
        )
        sessions.append(
            {
                "session_date": key,
                "events_found": len(items),
                "items": items,
                "summary": calculate_success_summary([{"items": items}]),
            }
        )

    summary = calculate_success_summary(sessions)
    first_items = sessions[0]["items"] if sessions else []
    cache_hits = sum(1 for item in diagnostics if item.get("source") == "cache")
    yfinance_calls = sum(1 for item in diagnostics if item.get("source") == "yfinance")
    calendar_errors = sum(1 for item in diagnostics if item.get("error"))
    calendar_rows = sum(int(item.get("calendar_rows") or 0) for item in diagnostics)
    _save_json_cache(_analyst_cache_path(resolved_cache_dir), analyst_cache)

    report = {
        "run_id": run_id,
        "as_of": as_of_dt.isoformat(),
        "mode": "informativo_no_operativo",
        "operation_allowed": False,
        "session_date": session_dates[0].isoformat() if session_dates else None,
        "session_count": len(sessions),
        "sessions": sessions,
        "universe_size": len(symbols),
        "events_found": summary["total_events"],
        "items": first_items,
        "summary": summary,
        "data_quality": {
            "calendar_source": "yfinance",
            "cache_path": str(_calendar_cache_path(resolved_cache_dir)),
            "cache_hits": cache_hits,
            "yfinance_calls": yfinance_calls,
            "calendar_errors": calendar_errors,
            "calendar_rows": calendar_rows,
            "symbols_checked": len(diagnostics),
            "analyst_source": "fmp" if fmp_api_key else "none",
            "analyst_cache_hits": sum(1 for item in analyst_diagnostics if item.get("source") == "cache"),
            "analyst_calls": sum(1 for item in analyst_diagnostics if item.get("source") == "fmp"),
            "analyst_errors": sum(1 for item in analyst_diagnostics if item.get("error")),
            "diagnostics": diagnostics[:100],
            "analyst_diagnostics": analyst_diagnostics[:100],
        },
        **summary,
        "warnings": warnings[:100],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"pre_earnings_{run_id}.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    report["path"] = str(output_path)
    return report
