"""Adaptive parameter tuning based on measured signal outcomes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .signal_learning import build_learning_status


ADAPTIVE_PARAMETERS = {
    "ENTRY_QUALITY_MIN_SCORE": {
        "settings_attr": "entry_quality_min_score",
        "min": 10,
        "max": 18,
        "direction": "balanced",
    },
    "ENTRY_QUALITY_MAX_RSI": {
        "settings_attr": "entry_quality_max_rsi",
        "min": 75.0,
        "max": 90.0,
        "direction": "balanced",
    },
    "ENTRY_QUALITY_MAX_SMA20_DISTANCE": {
        "settings_attr": "entry_quality_max_sma20_distance",
        "min": 0.06,
        "max": 0.20,
        "direction": "balanced",
    },
    "MAX_DAILY_BUY_ORDERS": {
        "settings_attr": "max_daily_buy_orders",
        "min": 1,
        "max": 2,
        "direction": "conservative_decrease",
    },
    "MAX_ORDERS_PER_CYCLE": {
        "settings_attr": "max_orders_per_cycle",
        "min": 1,
        "max": 3,
        "direction": "conservative_decrease",
    },
    "LLM_EXIT_EXCEPTION_MIN_CONFIDENCE": {
        "settings_attr": "llm_exit_exception_min_confidence",
        "min": 0.90,
        "max": 0.99,
        "direction": "conservative_increase",
    },
    "LLM_EXIT_EXCEPTION_MIN_DRAWDOWN": {
        "settings_attr": "llm_exit_exception_min_drawdown",
        "min": 0.05,
        "max": 0.15,
        "direction": "conservative_increase",
    },
    "ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE": {
        "settings_attr": "entry_quality_extended_sma20_distance",
        "min": 0.05,
        "max": 0.12,
        "direction": "conservative_decrease",
    },
    "ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN": {
        "settings_attr": "entry_quality_extended_min_relative_return",
        "min": 0.0,
        "max": 0.05,
        "direction": "conservative_increase",
    },
    "ENTRY_QUALITY_EXTENDED_MIN_VOLUME_Z": {
        "settings_attr": "entry_quality_extended_min_volume_z",
        "min": 0.0,
        "max": 1.5,
        "direction": "conservative_increase",
    },
}


def adaptive_config_path(settings: Settings) -> Path:
    return settings.state_dir / "adaptive_config.json"


def load_adaptive_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "parameters": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("version", 1)
            payload.setdefault("parameters", {})
            return payload
    except json.JSONDecodeError:
        pass
    return {"version": 1, "parameters": {}, "warnings": ["adaptive_config invalido; ignorado"]}


def save_adaptive_config(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["as_of"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    payload["path"] = str(path)
    return payload


def active_adaptive_overrides(settings: Settings) -> dict[str, Any]:
    payload = load_adaptive_config(adaptive_config_path(settings))
    overrides: dict[str, Any] = {}
    for name, item in payload.get("parameters", {}).items():
        meta = ADAPTIVE_PARAMETERS.get(name)
        if not meta or item.get("status") != "active":
            continue
        value = item.get("proposed")
        if value is None:
            continue
        bounded = _bounded_value(name, value)
        if bounded is not None:
            overrides[meta["settings_attr"]] = bounded
    return overrides


def _bounded_value(name: str, value: Any) -> Any | None:
    meta = ADAPTIVE_PARAMETERS.get(name)
    if not meta:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    numeric = max(float(meta["min"]), min(float(meta["max"]), numeric))
    if name in {"ENTRY_QUALITY_MIN_SCORE", "MAX_DAILY_BUY_ORDERS", "MAX_ORDERS_PER_CYCLE"}:
        return int(numeric)
    return numeric


def _current_value(settings: Settings, name: str) -> Any:
    meta = ADAPTIVE_PARAMETERS[name]
    return getattr(settings, str(meta["settings_attr"]))


def _tag(report: dict[str, Any], tag: str) -> dict[str, Any] | None:
    for item in [*report.get("best_indicators", []), *report.get("worst_indicators", [])]:
        if item.get("tag") == tag:
            return item
    return None


def _weak(item: dict[str, Any] | None, *, min_resolved: int, max_win_rate: float, max_avg_return: float) -> bool:
    if not item:
        return False
    if int(item.get("resolved") or 0) < min_resolved:
        return False
    win_rate = item.get("win_rate")
    avg_return = item.get("avg_return_5d")
    if win_rate is None or avg_return is None:
        return False
    return float(win_rate) <= max_win_rate and float(avg_return) <= max_avg_return


def _proposal(
    *,
    name: str,
    settings: Settings,
    proposed: Any,
    reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    current = _current_value(settings, name)
    return {
        "name": name,
        "current": current,
        "proposed": _bounded_value(name, proposed),
        "status": "shadow",
        "reason": reason,
        "evidence": evidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "expires_after_sessions": 5,
        "auto_apply": False,
    }


def _latest_entry_quality_calibration(store: Store) -> dict[str, Any]:
    latest = store.latest_learning_daily_summary(kind="daily_learning")
    payload = (latest or {}).get("payload", {}) or {}
    digest = payload.get("digest", {}) or {}
    calibration = digest.get("entry_quality_filter_calibration_3d", {}) or {}
    return {
        "session_date": (latest or {}).get("session_date"),
        "calibration": calibration,
    }


def _entry_quality_calibration_proposals(settings: Settings, store: Store) -> list[dict[str, Any]]:
    latest = _latest_entry_quality_calibration(store)
    calibration = latest.get("calibration", {}) or {}
    matured = int(calibration.get("matured") or 0)
    missed_winners = int(calibration.get("missed_winners") or 0)
    avoided_losers = int(calibration.get("avoided_losers") or 0)
    avg_return = calibration.get("avg_return")
    try:
        avg_return_value = float(avg_return)
    except (TypeError, ValueError):
        avg_return_value = None
    if matured < 3 or avg_return_value is None:
        return []

    evidence = {
        "source": "daily_learning.entry_quality_filter_calibration_3d",
        "session_date": latest.get("session_date"),
        "calibration": calibration,
    }
    proposals = []
    if missed_winners > avoided_losers and avg_return_value > 0:
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_RSI",
                settings=settings,
                proposed=float(settings.entry_quality_max_rsi) + 2.0,
                reason="Entry-quality esta vetando mas ganadores maduros que perdedores; relajar RSI maximo en shadow.",
                evidence=evidence,
            )
        )
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_SMA20_DISTANCE",
                settings=settings,
                proposed=float(settings.entry_quality_max_sma20_distance) + 0.02,
                reason="Entry-quality muestra coste de oportunidad positivo; probar mas tolerancia de extension SMA20 en shadow.",
                evidence=evidence,
            )
        )
    elif avoided_losers > missed_winners and avg_return_value < 0:
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_RSI",
                settings=settings,
                proposed=float(settings.entry_quality_max_rsi) - 2.0,
                reason="Entry-quality esta evitando mas perdedores que ganadores; probar RSI maximo mas estricto en shadow.",
                evidence=evidence,
            )
        )
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_SMA20_DISTANCE",
                settings=settings,
                proposed=float(settings.entry_quality_max_sma20_distance) - 0.02,
                reason="Entry-quality evita perdedores en entradas bloqueadas; probar extension SMA20 maxima mas estricta en shadow.",
                evidence=evidence,
            )
        )
    return proposals


def propose_adaptive_parameters(
    settings: Settings,
    store: Store,
    *,
    since_date: str = "2026-04-01",
    min_resolved: int = 10,
) -> dict[str, Any]:
    learning = build_learning_status(store, since_date=since_date)
    proposals = []

    rsi_extreme = _tag(learning, "rsi:gt85")
    if _weak(rsi_extreme, min_resolved=min_resolved, max_win_rate=0.40, max_avg_return=0.0):
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_RSI",
                settings=settings,
                proposed=float(settings.entry_quality_max_rsi) - 3,
                reason="RSI extremo esta mostrando baja tasa de acierto y retorno medio negativo.",
                evidence=rsi_extreme or {},
            )
        )

    sma_extended = _tag(learning, "sma20_dist:gt12pct")
    if _weak(sma_extended, min_resolved=min_resolved, max_win_rate=0.40, max_avg_return=0.0):
        proposals.append(
            _proposal(
                name="ENTRY_QUALITY_MAX_SMA20_DISTANCE",
                settings=settings,
                proposed=float(settings.entry_quality_max_sma20_distance) - 0.02,
                reason="Entradas demasiado extendidas sobre SMA20 muestran resultados debiles.",
                evidence=sma_extended or {},
            )
        )

    approved = int(learning.get("decisions", {}).get("approved_buy", 0) or 0)
    losing_verdicts = sum(
        int(learning.get("verdicts", {}).get(name, 0) or 0)
        for name in ("loser_open", "loser_stop_loss")
    )
    resolved = sum(
        int(value)
        for key, value in learning.get("verdicts", {}).items()
        if key not in {"pending", None}
    )
    if approved >= min_resolved and resolved and losing_verdicts / resolved >= 0.60:
        proposals.append(
            _proposal(
                name="MAX_DAILY_BUY_ORDERS",
                settings=settings,
                proposed=max(1, int(settings.max_daily_buy_orders) - 1),
                reason="Muchas compras aprobadas terminan debiles; se propone reducir entradas diarias.",
                evidence={
                    "approved_buy": approved,
                    "resolved": resolved,
                    "losing_verdicts": losing_verdicts,
                    "loss_rate": round(losing_verdicts / resolved, 4),
                },
            )
        )

    proposals.extend(_entry_quality_calibration_proposals(settings, store))

    return {
        "since_date": since_date,
        "signals": learning.get("signals", 0),
        "learning": learning,
        "proposals": proposals,
    }


def update_adaptive_config(
    settings: Settings,
    store: Store,
    *,
    since_date: str = "2026-04-01",
    min_resolved: int = 10,
) -> dict[str, Any]:
    path = adaptive_config_path(settings)
    config = load_adaptive_config(path)
    parameters = config.setdefault("parameters", {})
    generated = propose_adaptive_parameters(
        settings,
        store,
        since_date=since_date,
        min_resolved=min_resolved,
    )

    changed = []
    for proposal in generated["proposals"]:
        name = proposal["name"]
        existing = parameters.get(name, {})
        if existing.get("status") in {"active", "promoted"}:
            continue
        parameters[name] = {**existing, **proposal, "status": existing.get("status", "shadow")}
        changed.append(name)

    config["last_tuning"] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "since_date": since_date,
        "min_resolved": min_resolved,
        "proposals_generated": len(generated["proposals"]),
        "changed": changed,
        "signals": generated.get("signals", 0),
    }
    saved = save_adaptive_config(path, config)
    return {
        "path": str(path),
        "changed": changed,
        "generated": generated,
        "config": saved,
    }


def _active_parameter(
    *,
    name: str,
    settings: Settings,
    proposed: Any,
    reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": name,
        "current": _current_value(settings, name),
        "proposed": _bounded_value(name, proposed),
        "status": "active",
        "reason": reason,
        "evidence": evidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "expires_after_sessions": 3,
        "auto_apply": True,
    }


def promote_post_market_improvements(settings: Settings, report: dict[str, Any]) -> dict[str, Any]:
    """Promote conservative post-market learnings into active adaptive overrides."""

    path = adaptive_config_path(settings)
    config = load_adaptive_config(path)
    parameters = config.setdefault("parameters", {})
    promoted: list[str] = []
    improvements = report.get("proposed_improvements", []) or []

    for item in improvements:
        improvement_id = item.get("id")
        priority = str(item.get("priority") or "").lower()
        evidence = {
            "improvement": item,
            "summary": report.get("summary", {}),
            "session_date": report.get("session_date"),
        }
        if improvement_id == "prefer_stop_take_exits" and priority == "high":
            for name, value in {
                "LLM_EXIT_EXCEPTION_MIN_CONFIDENCE": 0.95,
                "LLM_EXIT_EXCEPTION_MIN_DRAWDOWN": 0.08,
            }.items():
                parameters[name] = _active_parameter(
                    name=name,
                    settings=settings,
                    proposed=value,
                    reason="Post-mercado detecto ventas LLM no vinculadas a stop/take; se endurecen excepciones.",
                    evidence=evidence,
                )
                promoted.append(name)
        elif improvement_id == "limit_daily_entries" and priority == "high":
            suggested = item.get("suggested_config", {}) or {}
            value = suggested.get("MAX_ORDERS_PER_CYCLE", 2)
            parameters["MAX_ORDERS_PER_CYCLE"] = _active_parameter(
                name="MAX_ORDERS_PER_CYCLE",
                settings=settings,
                proposed=value,
                reason="Post-mercado detecto demasiada dispersion; se limita actividad por ciclo.",
                evidence=evidence,
            )
            promoted.append("MAX_ORDERS_PER_CYCLE")
        elif improvement_id == "add_entry_quality_filters":
            for name, value in {
                "ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE": 0.08,
                "ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN": 0.02,
                "ENTRY_QUALITY_EXTENDED_MIN_VOLUME_Z": 0.0,
            }.items():
                parameters[name] = _active_parameter(
                    name=name,
                    settings=settings,
                    proposed=value,
                    reason="Post-mercado detecto entradas extendidas; se exige confirmacion adicional.",
                    evidence=evidence,
                )
                promoted.append(name)

    config["last_post_market_promotion"] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "session_date": report.get("session_date"),
        "promoted": promoted,
    }
    if promoted:
        saved = save_adaptive_config(path, config)
    else:
        saved = config
    return {
        "path": str(path),
        "promoted": promoted,
        "config": saved,
    }


def adaptive_status(settings: Settings) -> dict[str, Any]:
    path = adaptive_config_path(settings)
    config = load_adaptive_config(path)
    rows = []
    for name, meta in ADAPTIVE_PARAMETERS.items():
        item = config.get("parameters", {}).get(name, {})
        rows.append(
            {
                "name": name,
                "current": _current_value(settings, name),
                "proposed": item.get("proposed"),
                "status": item.get("status", "none"),
                "reason": item.get("reason"),
                "evidence": item.get("evidence", {}),
                "settings_attr": meta["settings_attr"],
            }
        )
    return {
        "path": str(path),
        "exists": path.exists(),
        "active_overrides": active_adaptive_overrides(settings),
        "parameters": rows,
        "last_tuning": config.get("last_tuning", {}),
        "warnings": config.get("warnings", []),
    }
