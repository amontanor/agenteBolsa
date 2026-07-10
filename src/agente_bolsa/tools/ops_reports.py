"""Operational reports for weekly review, data quality, and backups."""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .daily_learning import load_daily_learning_context
from .live_readiness import build_live_readiness_report
from .market_data import download_daily_prices_with_metadata
from .operational_health import load_operational_block_context
from .reporting import write_json_report
from .retention import latest_report_path
from .trade_decision import _select_deterministic_candidates
from .trade_history import build_trade_history
from .universe import resolve_study_universe


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        return {"available": True, "path": str(path), "payload": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {"available": False, "path": str(path)}


def _market_data_anomalies(
    prices: pd.DataFrame,
    meta: dict[str, Any],
    symbols: list[str],
) -> list[dict[str, Any]]:
    """Describe anomalías observadas sin alterar barras ni decisiones operativas.

    Reglas conservadoras: solo una barra OHLC inválida en la fecha más reciente
    observada del símbolo se clasifica como bloqueante para el escaneo. Volumen
    inválido y barras históricas son advertencias; gaps extremos son informativos.
    Los avisos antiguos sin fila verificable se conservan como ``unavailable``.
    """
    provider = meta.get("source") or "unavailable"
    cache = {
        "cache_hit": bool(meta.get("cache_hit")),
        "cache_key": meta.get("cache_key"),
        "cache_age_seconds": meta.get("cache_age_seconds"),
    }
    multi_symbol = isinstance(prices.columns, pd.MultiIndex)
    anomalies: list[dict[str, Any]] = []
    detailed_symbols: set[str] = set()

    for symbol in sorted({str(item).upper() for item in symbols if str(item).strip()}):
        try:
            frame = prices[symbol].copy() if multi_symbol else prices.copy()
        except KeyError:
            continue
        if frame.empty:
            continue
        frame = frame.dropna(how="all")
        if frame.empty:
            continue
        detailed_symbols.add(symbol)
        latest_date = max(str(index)[:10] for index in frame.index)
        previous_close: float | None = None
        for index, row in frame.sort_index(kind="stable").iterrows():
            date_text = str(index)[:10]
            values = {field: pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0] for field in ("Open", "High", "Low", "Close", "Volume")}
            open_, high, low, close, volume = (values[field] for field in ("Open", "High", "Low", "Close", "Volume"))
            ohlc_invalid: list[str] = []
            for field, value in (("open", open_), ("high", high), ("low", low), ("close", close)):
                if pd.isna(value) or not math.isfinite(float(value)) or float(value) <= 0:
                    ohlc_invalid.append(field)
            if not ohlc_invalid:
                if float(high) < float(low):
                    ohlc_invalid.extend(["high", "low"])
                if float(high) < max(float(open_), float(close)):
                    ohlc_invalid.append("high")
                if float(low) > min(float(open_), float(close)):
                    ohlc_invalid.append("low")
            if ohlc_invalid:
                affects_scan = date_text == latest_date
                anomalies.append(
                    {
                        "symbol": symbol,
                        "date": date_text,
                        "invalid_fields": sorted(set(ohlc_invalid)),
                        "invalidity_class": "ohlc_invalid",
                        "severity": "bloqueante" if affects_scan else "advertencia",
                        "provider": provider,
                        "cache": cache,
                        "affects_operational_scan": affects_scan,
                    }
                )
            if not pd.isna(volume) and (not math.isfinite(float(volume)) or float(volume) < 0):
                anomalies.append(
                    {
                        "symbol": symbol,
                        "date": date_text,
                        "invalid_fields": ["volume"],
                        "invalidity_class": "volume_invalid",
                        "severity": "advertencia",
                        "provider": provider,
                        "cache": cache,
                        "affects_operational_scan": False,
                    }
                )
            if previous_close is not None and not pd.isna(open_) and previous_close != 0 and abs(float(open_) - previous_close) / abs(previous_close) > 0.35:
                anomalies.append(
                    {
                        "symbol": symbol,
                        "date": date_text,
                        "invalid_fields": ["open", "close"],
                        "invalidity_class": "suspicious_gap",
                        "severity": "informativa",
                        "provider": provider,
                        "cache": cache,
                        "affects_operational_scan": False,
                    }
                )
            if not pd.isna(close) and math.isfinite(float(close)) and float(close) > 0:
                previous_close = float(close)

    # La metadata histórica solo trae contadores/texto; no se atribuye una causa.
    for alert in meta.get("validation_alerts") or []:
        text = str(alert)
        symbol = text.split(":", 1)[0].strip().upper() if ":" in text else "unavailable"
        if symbol in detailed_symbols:
            continue
        anomalies.append(
            {
                "symbol": symbol or "unavailable",
                "date": "unavailable",
                "invalid_fields": [],
                "invalidity_class": "unavailable",
                "severity": "informativa",
                "provider": provider,
                "cache": cache,
                "affects_operational_scan": "unavailable",
            }
        )

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in anomalies:
        key = (
            item["symbol"], item["date"], tuple(item["invalid_fields"]), item["invalidity_class"],
            item["provider"], item["cache"].get("cache_key"),
        )
        unique.setdefault(key, item)
    return [unique[key] for key in sorted(unique)]


def _benchmark_return(symbol: str, start: str, end: str, settings: Settings) -> dict[str, Any]:
    try:
        frame, meta = download_daily_prices_with_metadata(
            [symbol],
            start=start,
            end=end,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "available": False, "reason": str(exc)}
    if frame.empty or "Close" not in frame.columns:
        return {"symbol": symbol, "available": False, "reason": "sin cierres validos", "market_data": meta}
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < 2:
        return {"symbol": symbol, "available": False, "reason": "muestra insuficiente", "market_data": meta}
    total_return = (float(close.iloc[-1]) / float(close.iloc[0])) - 1.0
    return {
        "symbol": symbol,
        "available": True,
        "period": {"from": str(close.index[0])[:10], "to": str(close.index[-1])[:10]},
        "total_return": round(total_return, 4),
        "market_data": meta,
    }


def build_market_data_quality_report(
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    universe_name: str | None = None,
    max_symbols: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    selected_universe = universe_name or settings.closed_market_study_universe
    symbols = resolve_study_universe(
        selected_universe,
        settings.universe,
        max_symbols or settings.closed_market_study_max_symbols,
        settings.data_dir / "cache",
    )
    if not symbols:
        raise RuntimeError("El universo resuelto esta vacio; no se puede auditar market data.")
    today = datetime.now(timezone.utc).date()
    start_value = start or (today - timedelta(days=30)).isoformat()
    end_value = end or (today + timedelta(days=1)).isoformat()
    warnings: list[str] = []
    try:
        prices, meta = download_daily_prices_with_metadata(
            symbols,
            start=start_value,
            end=end_value,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        prices = pd.DataFrame()
        meta = {
            "source": settings.market_data_provider,
            "requested_count": len(symbols),
            "symbols_with_data_count": 0,
            "coverage_ratio": 0.0,
            "cache_hit": False,
            "validation_alerts": [],
            "missing_symbols_count": len(symbols),
            "error": str(exc),
        }
        warnings.append(f"Descarga de mercado fallida: {exc}")
    anomalies = _market_data_anomalies(prices, meta, symbols)
    alerts = list(meta.get("validation_alerts") or [])
    if meta.get("missing_symbols_count"):
        alerts.append(f"Faltan {meta['missing_symbols_count']} simbolos sobre {meta.get('requested_count', 0)}")
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "universe": selected_universe,
            "requested_symbols": meta.get("requested_count", 0),
            "symbols_with_data": meta.get("symbols_with_data_count", 0),
            "coverage_ratio": meta.get("coverage_ratio", 0.0),
            "provider_used": meta.get("source"),
            "cache_hit": bool(meta.get("cache_hit")),
            "cache_age_seconds": meta.get("cache_age_seconds"),
            "alerts": len(alerts),
            "anomalies_unique": len(anomalies),
            "real_blockers": sum(1 for item in anomalies if item["severity"] == "bloqueante"),
            "blockers": int(meta.get("coverage_ratio", 0.0) < 0.95 or bool(meta.get("missing_symbols_count"))),
        },
        "period": {"from": start_value, "to": end_value},
        "market_data": meta,
        "anomalies": anomalies,
        "alerts": alerts,
        "warnings": warnings,
        "sample_rows": int(len(prices)),
        "required_action": (
            "Revisar las anomalías bloqueantes antes del siguiente escaneo operativo."
            if any(item["severity"] == "bloqueante" for item in anomalies)
            else "Revisar advertencias de calidad de datos; no bloquean el escaneo operativo."
            if anomalies
            else "Revisar simbolos faltantes antes de confiar en el scan operativo."
            if alerts
            else "Cobertura suficiente para paper trading conservador."
        ),
    }
    return write_json_report(
        report,
        reports_dir,
        "market_data_quality",
        run_id,
        latest_filename="latest_market_data_quality.json",
        manifest={"universe": selected_universe, "requested_symbols": symbols[:25]},
    )


def _latest_ohlcv_by_symbol(frame: pd.DataFrame, symbols: list[str]) -> dict[str, dict[str, Any]]:
    multi_symbol = isinstance(frame.columns, pd.MultiIndex)
    rows: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        try:
            symbol_frame = frame[symbol].copy() if multi_symbol else frame.copy()
        except KeyError:
            continue
        symbol_frame = symbol_frame.dropna(how="all")
        if symbol_frame.empty or "Close" not in symbol_frame.columns:
            continue
        latest = symbol_frame.dropna(subset=["Close"]).iloc[-1]
        rows[symbol] = {
            "date": str(symbol_frame.dropna(subset=["Close"]).index[-1])[:10],
            "open": _safe_float(latest.get("Open")),
            "high": _safe_float(latest.get("High")),
            "low": _safe_float(latest.get("Low")),
            "close": _safe_float(latest.get("Close")),
            "volume": _safe_float(latest.get("Volume")),
        }
    return rows


def build_market_data_reconciliation_report(
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    tolerance_pct: float = 0.01,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    start_value = start or (today - timedelta(days=10)).isoformat()
    end_value = end or (today + timedelta(days=1)).isoformat()
    selected_symbols = sorted({str(item).upper() for item in (symbols or settings.universe[:5]) if str(item).strip()})
    primary_provider = settings.market_data_provider
    primary_resolved = "fmp" if primary_provider == "auto" and settings.fmp_api_key else primary_provider
    alternate_provider = "yfinance" if primary_resolved == "fmp" else "fmp"
    downloads: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for label, provider in {"primary": primary_provider, "alternate": alternate_provider}.items():
        try:
            frame, meta = download_daily_prices_with_metadata(
                selected_symbols,
                start=start_value,
                end=end_value,
                provider=provider,
                fmp_api_key=settings.fmp_api_key,
            )
            downloads[label] = {
                "provider": provider,
                "meta": meta,
                "latest": _latest_ohlcv_by_symbol(frame, selected_symbols),
                "available": True,
            }
        except Exception as exc:  # noqa: BLE001
            downloads[label] = {"provider": provider, "available": False, "error": str(exc), "latest": {}, "meta": {}}
            warnings.append(f"{label}:{provider}: {exc}")

    discrepancies: list[dict[str, Any]] = []
    primary_latest = downloads.get("primary", {}).get("latest", {}) or {}
    alternate_latest = downloads.get("alternate", {}).get("latest", {}) or {}
    for symbol in selected_symbols:
        first = primary_latest.get(symbol)
        second = alternate_latest.get(symbol)
        if not first or not second:
            discrepancies.append({"symbol": symbol, "kind": "missing_provider_comparison", "severity": "WARN"})
            continue
        close_a = _safe_float(first.get("close"))
        close_b = _safe_float(second.get("close"))
        if close_a <= 0 or close_b <= 0:
            discrepancies.append({"symbol": symbol, "kind": "invalid_close", "severity": "BLOCK"})
            continue
        diff_pct = abs(close_a - close_b) / max(close_a, close_b)
        if diff_pct > tolerance_pct:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "kind": "close_discrepancy",
                    "severity": "BLOCK" if diff_pct > tolerance_pct * 3 else "WARN",
                    "primary_close": close_a,
                    "alternate_close": close_b,
                    "diff_pct": round(diff_pct, 4),
                }
            )

    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": start_value, "to": end_value},
        "symbols": selected_symbols,
        "providers": {
            "primary": downloads.get("primary", {}),
            "alternate": downloads.get("alternate", {}),
        },
        "summary": {
            "symbols": len(selected_symbols),
            "primary_provider": primary_provider,
            "alternate_provider": alternate_provider,
            "discrepancies": len(discrepancies),
            "blockers": sum(1 for item in discrepancies if item.get("severity") == "BLOCK"),
            "ready_for_live_data_use": not any(item.get("severity") == "BLOCK" for item in discrepancies)
            and bool(downloads.get("primary", {}).get("available")),
        },
        "discrepancies": discrepancies,
        "warnings": warnings,
    }
    return write_json_report(
        report,
        reports_dir,
        "market_data_reconciliation",
        run_id,
        latest_filename="latest_market_data_reconciliation.json",
        manifest={"symbols": selected_symbols, "primary_provider": primary_provider, "alternate_provider": alternate_provider},
    )


def build_weekly_trading_review(
    settings: Settings,
    store: Store,
    reports_dir: Path,
    run_id: str,
    *,
    since_date: str,
    end_date: str | None = None,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    try:
        history = build_trade_history(settings, limit=1000, start_date=since_date)
    except Exception as exc:  # noqa: BLE001
        history = {"current_statistics": {}, "days": [], "warnings": [str(exc)]}
        warnings.append(f"No se pudo leer trade history: {exc}")
    observations = store.learning_observations(since_date=since_date, end_date=end_date, limit=5000)
    signals = store.signal_outcomes(limit=5000, since_date=since_date)
    benchmark = _benchmark_return(settings.benchmark_symbol, since_date, end_date or datetime.now(timezone.utc).date().isoformat(), settings)
    if not benchmark.get("available"):
        warnings.append(f"Benchmark no disponible: {benchmark.get('reason')}")
    relevant_days = [
        day
        for day in (history.get("days") or [])
        if str(day.get("date") or "") >= since_date and (not end_date or str(day.get("date") or "") <= end_date)
    ]
    approved_buy = sum(1 for item in observations if item.get("approved_buy"))
    blocked_entry = sum(1 for item in observations if item.get("blocked_entry_quality"))
    blocked_backtest = sum(1 for item in observations if item.get("blocked_backtest"))
    executed_buy = sum(1 for item in observations if item.get("executed_buy"))
    positive_blocked = sum(
        1
        for item in observations
        if (item.get("blocked_entry_quality") or item.get("blocked_backtest"))
        and _safe_float((item.get("outcome") or {}).get("return_5d"), default=-999.0) > 0
    )
    negative_blocked = sum(
        1
        for item in observations
        if (item.get("blocked_entry_quality") or item.get("blocked_backtest"))
        and _safe_float((item.get("outcome") or {}).get("return_5d"), default=999.0) <= 0
    )
    recent_digest = load_daily_learning_context(settings.data_dir)
    latest_quality = _read_json(reports_dir / "latest_market_data_quality.json")
    latest_health = _read_json(reports_dir / "latest_operational_health.json")
    latest_readiness = _read_json(reports_dir / "latest_live_readiness.json")
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": {"from": since_date, "to": end_date or datetime.now(timezone.utc).date().isoformat()},
        "summary": {
            "trade_days": len(relevant_days),
            "signals": len(signals),
            "observations": len(observations),
            "approved_buy": approved_buy,
            "blocked_entry_quality": blocked_entry,
            "blocked_backtest": blocked_backtest,
            "executed_buy": executed_buy,
            "positive_blocked": positive_blocked,
            "negative_blocked": negative_blocked,
            "benchmark_symbol": settings.benchmark_symbol,
            "benchmark_return": benchmark.get("total_return"),
        },
        "performance": {
            "current_statistics": history.get("current_statistics", {}),
            "days": relevant_days,
        },
        "gates": {
            "approved_buy": approved_buy,
            "blocked_entry_quality": blocked_entry,
            "blocked_backtest": blocked_backtest,
            "executed_buy": executed_buy,
            "opportunity_cost": {
                "blocked_then_positive": positive_blocked,
                "blocked_then_non_positive": negative_blocked,
            },
        },
        "benchmark": benchmark,
        "learning": {
            "latest_digest": recent_digest,
        },
        "operational": {
            "block_context": load_operational_block_context(settings.data_dir),
            "latest_market_data_quality": latest_quality,
            "latest_operational_health": latest_health,
            "latest_live_readiness": latest_readiness,
        },
        "warnings": warnings,
    }
    return write_json_report(
        report,
        reports_dir,
        "weekly_trading_review",
        run_id,
        latest_filename="latest_weekly_trading_review.json",
        manifest={"since_date": since_date, "end_date": end_date},
    )


def build_selection_bandwidth_review(
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    base_limit: int = 8,
    shadow_limit: int = 12,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest_path = latest_report_path(
        settings.data_dir,
        "closed_market_technical_study",
        "latest_closed_market_technical_study.json",
    )
    if latest_path is None or not latest_path.exists():
        raise RuntimeError("No existe latest_closed_market_technical_study.json para revisar el ancho de seleccion.")
    report = json.loads(latest_path.read_text(encoding="utf-8"))
    all_candidates = list(report.get("all_candidates", []) or [])
    daily_learning_digest = load_daily_learning_context(settings.data_dir)
    operational_context = load_operational_block_context(settings.data_dir)
    # Block context is operationally useful, but selection penalties live in the health response context.
    # If the block report is stale or unavailable, this remains conservative.
    try:
        from .operational_health import load_operational_response_context

        response_context = load_operational_response_context(settings.data_dir)
    except Exception:  # noqa: BLE001
        response_context = {}
    base_selected, base_metadata = _select_deterministic_candidates(
        all_candidates,
        daily_learning_digest,
        response_context,
        limit=base_limit,
    )
    shadow_selected, shadow_metadata = _select_deterministic_candidates(
        all_candidates,
        daily_learning_digest,
        response_context,
        limit=shadow_limit,
    )
    base_symbols = {str(item.get("symbol") or "").upper() for item in base_selected if item.get("symbol")}
    added = [
        {
            "symbol": item.get("symbol"),
            "score": item.get("score"),
            "selection_score": item.get("selection_score"),
            "selection_rank": item.get("selection_rank"),
            "setup_name": item.get("setup_name"),
            "selection_reason": item.get("selection_reason"),
            "blocked_auto_buy": item.get("blocked_auto_buy"),
        }
        for item in shadow_selected
        if str(item.get("symbol") or "").upper() not in base_symbols
    ]
    bandwidth_gain = max(0, len(shadow_selected) - len(base_selected))
    review = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source_report": {
            "path": str(latest_path),
            "run_id": report.get("run_id"),
            "study_as_of": report.get("as_of"),
            "symbols_scanned": report.get("symbols_scanned"),
            "symbols_with_data": report.get("symbols_with_data"),
        },
        "summary": {
            "base_limit": base_limit,
            "shadow_limit": shadow_limit,
            "eligible_candidates": base_metadata.get("eligible"),
            "base_selected": len(base_selected),
            "shadow_selected": len(shadow_selected),
            "additional_candidates_if_promoted": bandwidth_gain,
        },
        "base_selected_symbols": [item.get("symbol") for item in base_selected],
        "shadow_selected_symbols": [item.get("symbol") for item in shadow_selected],
        "additional_shadow_candidates": added,
        "selection_metadata": {
            "base": base_metadata,
            "shadow": shadow_metadata,
        },
        "operational": {
            "block_context": operational_context,
        },
        "required_action": (
            "Mantener en shadow y revisar si los candidatos extra son tecnicamente claros antes de ampliar el ancho de seleccion."
            if added
            else "Sin candidatos extra claros; no ampliar ancho de seleccion."
        ),
    }
    return write_json_report(
        review,
        reports_dir,
        "selection_bandwidth_review",
        run_id,
        latest_filename="latest_selection_bandwidth_review.json",
        manifest={"base_limit": base_limit, "shadow_limit": shadow_limit, "source_report": str(latest_path)},
    )


def backup_database(settings: Settings, reports_dir: Path, run_id: str) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    source = settings.database_path
    if not source.exists():
        raise RuntimeError(f"No existe la base SQLite en {source}.")
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"agente_bolsa_{run_id}.sqlite3"
    shutil.copy2(source, target)
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "source": str(source),
            "backup_path": str(target),
            "size_bytes": target.stat().st_size,
        },
        "restore_instructions": [
            "Detener procesos que escriban sobre SQLite antes de restaurar.",
            f"Renombrar {source} a un fichero de seguridad si se quiere conservar.",
            f"Copiar {target} sobre {source}.",
            "Ejecutar status o SQLite pragma quick_check antes de reanudar schedule.",
        ],
    }
    return write_json_report(
        report,
        reports_dir,
        "database_backup",
        run_id,
        latest_filename="latest_database_backup.json",
        manifest={"source": str(source), "backup_path": str(target)},
    )


def audit_live_readiness_in_paper_mode(settings: Settings, store: Store, reports_dir: Path, run_id: str, *, since_date: str) -> dict[str, Any]:
    return build_live_readiness_report(settings, store, reports_dir, run_id, since_date=since_date)
