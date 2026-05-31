"""Operational reports for weekly review, data quality, and backups."""

from __future__ import annotations

import json
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
            "blockers": int(meta.get("coverage_ratio", 0.0) < 0.95 or bool(meta.get("missing_symbols_count"))),
        },
        "period": {"from": start_value, "to": end_value},
        "market_data": meta,
        "alerts": alerts,
        "warnings": warnings,
        "sample_rows": int(len(prices)),
        "required_action": (
            "Revisar simbolos faltantes y anomalias antes de confiar en el scan operativo."
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
