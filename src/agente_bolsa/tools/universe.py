"""Symbol universe loaders."""

from __future__ import annotations

import json
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


FALLBACK_SP500_LARGE_CAPS = [
    "MSFT", "NVDA", "AAPL", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "TSLA", "BRK-B",
    "JPM", "LLY", "V", "MA", "NFLX", "XOM", "COST", "WMT", "UNH", "ORCL",
    "JNJ", "HD", "PG", "BAC", "ABBV", "KO", "PM", "CRM", "CVX", "CSCO",
    "GE", "IBM", "WFC", "ABT", "MCD", "LIN", "DIS", "MRK", "NOW", "ACN",
    "T", "ISRG", "AMD", "VZ", "INTU", "GS", "TXN", "RTX", "PEP", "BKNG",
    "CAT", "QCOM", "AXP", "SPGI", "TMO", "BA", "BSX", "MS", "AMGN", "HON",
    "C", "PGR", "NEE", "UNP", "LOW", "DHR", "TJX", "GILD", "SYK", "ADP",
    "DE", "BLK", "PANW", "LMT", "COP", "MDT", "CB", "SCHW", "UPS", "ETN",
    "MMC", "BMY", "ADI", "MU", "AMAT", "SBUX", "ELV", "PLD", "FI", "MDLZ",
    "KLAC", "ANET", "SO", "ICE", "LRCX", "WM", "REGN", "GEV", "PH", "HCA",
    "SHW", "MO", "EQIX", "MCO", "APH", "TT", "CI", "CME", "CVS", "DUK",
    "MMM", "TDG", "AON", "CMG", "WELL", "SNPS", "CDNS", "ZTS", "ITW", "CL",
    "NOC", "USB", "ORLY", "MSI", "MAR", "EOG", "APD", "GD", "EMR", "FDX",
    "PYPL", "CEG", "ECL", "CTAS", "PNC", "CSX", "TGT", "RSG", "WMB", "AJG",
    "FCX", "COF", "BK", "HWM", "AZO", "NXPI", "SLB", "NSC", "GM", "MPC",
    "CARR", "AFL", "O", "TRV", "JCI", "AEP", "HLT", "PSX", "TFC", "URI",
    "VLO", "SRE", "D", "NEM", "MET", "PCAR", "ALL", "ROST", "COR", "KMB",
    "SPG", "PSA", "MNST", "AMP", "DHI", "GWW", "OKE", "FICO", "OXY", "PAYX",
    "MCK", "RCL", "FTNT", "KMI", "DFS", "FAST", "EA", "LHX", "HIG", "PRU",
    "CCI", "PEG", "KR", "KVUE", "TEL", "FIS", "AIG", "VST", "EW", "EXC",
    "IDXX", "CTVA", "YUM", "CMI", "CHTR", "CTSH", "MSCI", "ROK", "XEL", "AME",
    "IR", "VRSK", "OTIS", "ED", "TRGP", "PWR", "HES", "BKR", "FANG", "DAL",
    "GLW", "DD", "MPWR", "GEHC", "ACGL", "IQV", "GRMN", "NUE", "ODFL", "LEN",
    "MLM", "STZ", "CBRE", "WAB", "SYY", "XYL", "EFX", "HSY", "KDP", "HPQ",
    "MTB", "EIX", "HPE", "VMC", "EXR", "RJF", "AVB", "WEC", "FITB", "DTE",
    "RMD", "BRO", "TSCO", "ADM", "CAH", "NDAQ", "SYF", "PCG", "A", "STT",
    "CSGP", "EBAY", "MCHP", "HUM", "GIS", "ANSS", "DVN", "EQR", "KEYS", "TROW",
    "CHD", "WDC", "LYB", "DOW", "PPG", "ON", "BR", "WST", "IRM", "AWK",
    "HST", "TYL", "NTAP", "HBAN", "EXPE", "GPN", "HAL", "IFF", "WY", "WAT",
    "CDW", "BIIB", "WTW", "GDDY", "VLTO", "CPAY", "DOV", "ETR", "PHM", "VICI",
    "RF", "WBD", "SBAC", "STE", "ES", "FSLR", "TPR", "ZBH", "PPL", "FE",
    "CINF", "LDOS", "NTRS",
]


def load_sp500_symbols() -> list[str]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas es necesario para cargar el universo S&P 500.") from exc

    sources = [
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    ]
    for url in sources:
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "agente-bolsa/0.1"
                    )
                },
            )
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
            if url.endswith(".csv"):
                frame = pd.read_csv(StringIO(text))
            else:
                frame = pd.read_html(StringIO(text))[0]
            symbols = [
                str(symbol).replace(".", "-").upper()
                for symbol in frame["Symbol"].tolist()
            ]
            return sorted(set(symbols))
        except (KeyError, ValueError, URLError, TimeoutError, OSError):
            continue

    return FALLBACK_SP500_LARGE_CAPS.copy()


def _market_cap(symbol: str) -> tuple[str, int]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        fast_info = getattr(ticker, "fast_info", {}) or {}
        cap = fast_info.get("market_cap") or fast_info.get("marketCap")
        if not cap:
            info = getattr(ticker, "info", {}) or {}
            cap = info.get("marketCap")
        return symbol, int(cap or 0)
    except Exception:
        return symbol, 0


def _read_cache(
    cache_path: Path,
    max_age_hours: int = 24,
    *,
    allow_stale: bool = False,
) -> list[dict[str, Any]] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        if not allow_stale and datetime.now(timezone.utc) - created_at > timedelta(hours=max_age_hours):
            return None
        return payload.get("items", [])
    except (KeyError, ValueError, OSError, json.JSONDecodeError):
        return None


def _write_cache(cache_path: Path, items: list[dict[str, Any]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"created_at": datetime.now(timezone.utc).isoformat(), "items": items},
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )


def load_sp500_top_by_market_cap(limit: int = 300, cache_dir: Path | None = None) -> list[str]:
    cache_path = (cache_dir or Path("data/cache")) / "sp500_market_caps.json"
    cached = _read_cache(cache_path)
    if cached:
        return [item["symbol"] for item in cached[:limit]]

    symbols = load_sp500_symbols()
    stale_cache = _read_cache(cache_path, allow_stale=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(_market_cap, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, cap = future.result()
            results.append({"symbol": symbol, "market_cap": cap})

    if not any(item["market_cap"] for item in results) and stale_cache:
        return [item["symbol"] for item in stale_cache[:limit]]

    results = sorted(results, key=lambda item: item["market_cap"], reverse=True)
    _write_cache(cache_path, results)
    return [item["symbol"] for item in results[:limit]]


def _merge_recent_overlay(base_symbols: list[str], cache_dir: Path | None, *, report_name: str) -> list[str]:
    reports_dir = ((cache_dir or Path("data/cache")).parent / "reports")
    overlay_path = reports_dir / report_name
    if not overlay_path.exists():
        return base_symbols
    try:
        payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base_symbols
    extras: list[str] = []
    for key in ("confirmed", "watch", "top_longs"):
        for item in payload.get(key, [])[:25]:
            symbol = str((item or {}).get("symbol") or "").upper().strip()
            if symbol:
                extras.append(symbol)
    result = []
    seen: set[str] = set()
    for symbol in [*base_symbols, *extras]:
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def _merge_recent_overlays(
    base_symbols: list[str],
    cache_dir: Path | None,
    *,
    report_names: list[str],
    prepend_extras: bool = False,
) -> list[str]:
    extras: list[str] = []
    reports_dir = ((cache_dir or Path("data/cache")).parent / "reports")
    for report_name in report_names:
        overlay_path = reports_dir / report_name
        if not overlay_path.exists():
            continue
        try:
            payload = json.loads(overlay_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("confirmed", "watch", "top_longs", "alerts"):
            for item in payload.get(key, [])[:25]:
                symbol = str((item or {}).get("symbol") or "").upper().strip()
                if symbol:
                    extras.append(symbol)
    ordered = [*extras, *base_symbols] if prepend_extras else [*base_symbols, *extras]
    result: list[str] = []
    seen: set[str] = set()
    for symbol in ordered:
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def resolve_study_universe(
    config_value: str,
    default_symbols: list[str],
    max_symbols: int = 0,
    cache_dir: Path | None = None,
) -> list[str]:
    value = config_value.strip().lower()
    if value in {"default", "configured", "universe"}:
        symbols = default_symbols
    elif value in {"sp500_top250", "sp500_top_250", "sp500-largest-250"}:
        symbols = load_sp500_top_by_market_cap(limit=max_symbols or 250, cache_dir=cache_dir)
    elif value in {"sp500_top300", "sp500_top_300", "sp500-largest-300"}:
        symbols = load_sp500_top_by_market_cap(limit=max_symbols or 300, cache_dir=cache_dir)
    elif value == "sp500":
        symbols = load_sp500_symbols()
    elif value in {"sp500_plus_recent_breakouts", "sp500+recent_breakouts"}:
        symbols = _merge_recent_overlay(load_sp500_symbols(), cache_dir, report_name="latest_breakout_scan.json")
    elif value in {"sp500_plus_recent_leaders", "sp500+recent_leaders"}:
        symbols = _merge_recent_overlay(
            load_sp500_symbols(),
            cache_dir,
            report_name="latest_closed_market_technical_study.json",
        )
    elif value in {"sp500_plus_intraday_focus", "sp500+intraday_focus", "intraday_focus"}:
        symbols = _merge_recent_overlays(
            load_sp500_symbols(),
            cache_dir,
            report_names=[
                "latest_breakout_scan.json",
                "latest_closed_market_technical_study.json",
            ],
            prepend_extras=True,
        )
    else:
        symbols = [symbol.strip().upper() for symbol in config_value.split(",") if symbol.strip()]

    if max_symbols > 0:
        return symbols[:max_symbols]
    return symbols
