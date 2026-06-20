"""Market data helpers with cache, retries and validation."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .errors import MarketDataFetchError, MarketDataValidationError


_LAST_DOWNLOAD_METADATA: dict[str, Any] = {}
MAX_REASONABLE_DAILY_GAP_PCT = 0.60


def _yfinance_import_error_message(exc: Exception) -> str:
    missing_name = str(getattr(exc, "name", "") or "")
    if missing_name == "yfinance":
        return "yfinance no esta instalado. Ejecuta `pip install -r requirements.txt`."
    dependency = f" dependencia {missing_name!r}" if missing_name else " una dependencia"
    return (
        f"yfinance esta instalado, pero fallo al importar{dependency}: "
        f"{exc.__class__.__name__}: {exc}. "
        "Reinstala dependencias binarias con "
        "`pip install --force-reinstall cffi curl_cffi yfinance`."
    )


def _date_text(value: str | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def _settings_market_data_defaults() -> tuple[str, str | None]:
    try:
        from agente_bolsa.config import get_settings

        settings = get_settings()
        return str(settings.market_data_provider or "auto"), settings.fmp_api_key
    except Exception:
        return "auto", None


def _normalize_provider(provider: str | None, fmp_api_key: str | None) -> tuple[str, str | None]:
    default_provider, default_fmp_api_key = _settings_market_data_defaults()
    requested = str(provider or default_provider or "auto").strip().lower()
    api_key = fmp_api_key if fmp_api_key is not None else default_fmp_api_key
    if requested not in {"auto", "yfinance", "fmp"}:
        requested = "auto"
    if requested == "auto":
        return ("fmp", api_key) if api_key else ("yfinance", api_key)
    return requested, api_key


def _request_key(
    symbols: list[str],
    start: str | datetime,
    end: str | datetime | None,
    *,
    provider: str,
) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "symbols": sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()}),
            "start": _date_text(start),
            "end": _date_text(end),
        },
        sort_keys=True,
    )
    return sha1(payload.encode("utf-8")).hexdigest()[:16]


def _cache_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    return cache_dir / f"market_data_{key}.pkl", cache_dir / f"market_data_{key}.json"


def _cache_max_age_seconds(end: str | datetime | None) -> int | None:
    end_text = _date_text(end)
    if not end_text:
        return 2 * 60 * 60
    try:
        end_date = date.fromisoformat(end_text)
    except ValueError:
        return 2 * 60 * 60
    if end_date < datetime.now(timezone.utc).date():
        return None
    return 2 * 60 * 60


def _read_cache(
    cache_dir: Path,
    key: str,
    *,
    max_age_seconds: int | None,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    data_path, meta_path = _cache_paths(cache_dir, key)
    if not data_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(meta.get("created_at")))
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        if max_age_seconds is not None and age_seconds > max_age_seconds:
            return None
        frame = pd.read_pickle(data_path)
        meta["cache_hit"] = True
        meta["cache_age_seconds"] = round(age_seconds, 2)
        return frame, meta
    except Exception:
        return None


def _write_cache(cache_dir: Path, key: str, frame: pd.DataFrame, meta: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _cache_paths(cache_dir, key)
    frame.to_pickle(data_path)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=True), encoding="utf-8")


def _symbol_frame(data: pd.DataFrame, symbol: str, multi_symbol: bool) -> pd.DataFrame:
    if multi_symbol:
        if symbol not in data.columns.get_level_values(0):
            return pd.DataFrame()
        return data[symbol].copy().dropna(how="all")
    return data.copy().dropna(how="all")


def _validate_market_data(data: pd.DataFrame, symbols: list[str]) -> dict[str, Any]:
    if data is None or data.empty:
        raise MarketDataValidationError("la descarga devolvio un DataFrame vacio")

    normalized = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    multi_symbol = isinstance(data.columns, pd.MultiIndex)
    delivered: list[str] = []
    missing: list[str] = []
    bars_by_symbol: dict[str, int] = {}
    invalid_bars_by_symbol: dict[str, int] = {}
    suspicious_gap_bars_by_symbol: dict[str, int] = {}
    negative_volume_bars_by_symbol: dict[str, int] = {}
    alerts: list[str] = []
    for symbol in normalized:
        frame = _symbol_frame(data, symbol, multi_symbol)
        if frame.empty or "Close" not in frame.columns or frame["Close"].dropna().empty:
            missing.append(symbol)
            continue
        close = pd.to_numeric(frame.get("Close"), errors="coerce")
        open_ = pd.to_numeric(frame.get("Open"), errors="coerce")
        high = pd.to_numeric(frame.get("High"), errors="coerce")
        low = pd.to_numeric(frame.get("Low"), errors="coerce")
        volume = pd.to_numeric(frame.get("Volume"), errors="coerce")
        invalid_mask = (
            close.isna()
            | open_.isna()
            | high.isna()
            | low.isna()
            | (close <= 0)
            | (open_ <= 0)
            | (high <= 0)
            | (low <= 0)
            | (high < low)
            | (high < close)
            | (high < open_)
            | (low > close)
            | (low > open_)
        )
        volume_invalid_mask = volume.notna() & (volume < 0)
        gap_reference = close.shift(1)
        gap_mask = gap_reference.notna() & ((open_ - gap_reference).abs() / gap_reference.abs() > MAX_REASONABLE_DAILY_GAP_PCT)
        invalid_count = int(invalid_mask.sum())
        suspicious_gap_count = int(gap_mask.sum())
        negative_volume_count = int(volume_invalid_mask.sum())
        invalid_bars_by_symbol[symbol] = invalid_count
        suspicious_gap_bars_by_symbol[symbol] = suspicious_gap_count
        negative_volume_bars_by_symbol[symbol] = negative_volume_count
        if invalid_count >= len(frame):
            alerts.append(f"{symbol}: todas las barras son invalidas")
            missing.append(symbol)
            continue
        delivered.append(symbol)
        bars_by_symbol[symbol] = int(frame["Close"].dropna().shape[0])
        if invalid_count:
            alerts.append(f"{symbol}: {invalid_count} barras invalidas")
        if suspicious_gap_count:
            alerts.append(f"{symbol}: {suspicious_gap_count} gaps extremos")
        if negative_volume_count:
            alerts.append(f"{symbol}: {negative_volume_count} barras con volumen negativo")

    if not delivered:
        raise MarketDataValidationError("ningun simbolo solicitado tiene barras validas")

    requested_count = len(normalized)
    coverage_ratio = round(len(delivered) / requested_count, 4) if requested_count else 0.0
    return {
        "requested_symbols": normalized,
        "requested_count": requested_count,
        "symbols_with_data": delivered,
        "symbols_with_data_count": len(delivered),
        "missing_symbols": missing,
        "missing_symbols_count": len(missing),
        "bars_by_symbol": bars_by_symbol,
        "coverage_ratio": coverage_ratio,
        "invalid_bars_by_symbol": invalid_bars_by_symbol,
        "suspicious_gap_bars_by_symbol": suspicious_gap_bars_by_symbol,
        "negative_volume_bars_by_symbol": negative_volume_bars_by_symbol,
        "validation_alerts": alerts,
        "multi_symbol": multi_symbol,
    }


def _fmp_history_frame(symbol: str, payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("historical", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adjClose": "Adj Close",
        "volume": "Volume",
    }
    frame = frame.rename(columns=rename_map)
    if "date" not in frame.columns:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], utc=False)
    frame = frame.set_index("date").sort_index()
    keep = [column for column in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if column in frame.columns]
    return frame[keep].apply(pd.to_numeric, errors="coerce")


def _download_from_fmp(
    symbols: list[str],
    start: str | datetime,
    end: str | datetime | None,
    *,
    api_key: str,
    timeout_seconds: float = 30.0,
) -> pd.DataFrame:
    frames: dict[str, pd.DataFrame] = {}
    for symbol in sorted({str(item).upper() for item in symbols if str(item).strip()}):
        query = urlencode(
            {
                "from": _date_text(start),
                "to": _date_text(end),
                "apikey": api_key,
            }
        )
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?{query}"
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        frames[symbol] = _fmp_history_frame(symbol, payload)

    non_empty = {symbol: frame for symbol, frame in frames.items() if not frame.empty}
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return next(iter(non_empty.values()))
    return pd.concat(non_empty, axis=1)


def get_last_download_metadata() -> dict[str, Any]:
    return dict(_LAST_DOWNLOAD_METADATA)


def download_daily_prices_with_metadata(
    symbols: list[str],
    start: str | datetime,
    end: str | datetime | None = None,
    *,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
    max_retries: int = 2,
    retry_delay_seconds: float = 1.0,
    provider: str | None = None,
    fmp_api_key: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    normalized = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
    if not normalized:
        raise MarketDataValidationError("lista de simbolos vacia")
    selected_provider, resolved_fmp_api_key = _normalize_provider(provider, fmp_api_key)

    cache_root = cache_dir or Path("data/cache/market_data")
    cache_key = _request_key(normalized, start, end, provider=selected_provider)
    max_age_seconds = _cache_max_age_seconds(end)
    if not force_refresh:
        cached = _read_cache(cache_root, cache_key, max_age_seconds=max_age_seconds)
        if cached is not None:
            frame, meta = cached
            global _LAST_DOWNLOAD_METADATA
            _LAST_DOWNLOAD_METADATA = dict(meta)
            return frame, dict(meta)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            if selected_provider == "fmp":
                if not resolved_fmp_api_key:
                    raise MarketDataFetchError("FMP_API_KEY no configurada para provider=fmp")
                data = _download_from_fmp(
                    normalized,
                    start,
                    end,
                    api_key=resolved_fmp_api_key,
                )
            else:
                try:
                    import yfinance as yf
                except Exception as exc:
                    raise RuntimeError(_yfinance_import_error_message(exc)) from exc
                data = yf.download(
                    tickers=" ".join(normalized),
                    start=start,
                    end=end,
                    auto_adjust=True,
                    progress=False,
                    group_by="ticker",
                    threads=True,
                )
            validation = _validate_market_data(data, normalized)
            meta = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": selected_provider,
                "provider_requested": provider or "default",
                "cache_key": cache_key,
                "cache_hit": False,
                "attempt": attempt,
                "start": _date_text(start),
                "end": _date_text(end),
                **validation,
            }
            _write_cache(cache_root, cache_key, data, meta)
            _LAST_DOWNLOAD_METADATA = dict(meta)
            return data, meta
        except MarketDataValidationError as exc:
            last_error = exc
        except Exception as exc:
            last_error = MarketDataFetchError(str(exc))
        if attempt <= max_retries:
            time.sleep(retry_delay_seconds)

    raise last_error or MarketDataFetchError("fallo desconocido al descargar precios")


def download_daily_prices(
    symbols: list[str],
    start: str | datetime,
    end: str | datetime | None = None,
    *,
    cache_dir: Path | None = None,
    provider: str | None = None,
    fmp_api_key: str | None = None,
) -> pd.DataFrame:
    data, _meta = download_daily_prices_with_metadata(
        symbols,
        start,
        end,
        cache_dir=cache_dir,
        provider=provider,
        fmp_api_key=fmp_api_key,
    )
    return data
