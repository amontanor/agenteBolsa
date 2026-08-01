"""Adaptive parameter tuning based on measured signal outcomes."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.market_calendar import MarketCalendar
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

AUTO_APPLY_BLOCKED_REASON = "adaptive_auto_apply_not_authorized"


def _auto_apply_authorized(settings: Any) -> bool:
    """Return True only for the literal boolean authorization value.

    Configuration parsing may coerce values for normal application settings, but
    this boundary is intentionally stricter: missing, null, strings and numbers
    are never authorization.
    """

    value = getattr(settings, "allow_auto_apply_improvements", None)
    return type(value) is bool and value is True


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


def save_adaptive_config(
    path: Path,
    payload: dict[str, Any],
    *,
    settings: Settings | Any | None = None,
) -> dict[str, Any]:
    """Persist adaptive configuration only behind the fail-closed policy gate."""

    if not _auto_apply_authorized(settings):
        return {
            **payload,
            "path": str(path),
            "status": "blocked_by_policy",
            "reason_code": AUTO_APPLY_BLOCKED_REASON,
            "write_performed": False,
            "blocked_by_policy": True,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = dict(payload)
    saved["as_of"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    saved["path"] = str(path)
    saved["write_performed"] = True
    return saved


def _session_date(value: str | date | None) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _individual_auto_apply_authorized(item: dict[str, Any]) -> bool:
    """Require the canonical per-record authorization fields.

    ``auto_apply`` is a legacy request field.  It is never sufficient on its
    own; when present alongside the canonical fields it must be a consistent
    literal boolean, otherwise the record is ambiguous and ignored.
    """

    requested = item.get("requested_auto_apply")
    authorized = item.get("authorized_auto_apply")
    if type(requested) is not bool or type(authorized) is not bool:
        return False
    if not requested or not authorized:
        return False
    if "auto_apply" in item:
        legacy = item.get("auto_apply")
        if type(legacy) is not bool or legacy is not requested or legacy is not authorized:
            return False
    return True


def _override_expiry_is_valid(
    settings: Settings,
    item: dict[str, Any],
    *,
    current_session_date: str | date | None,
    calendar: MarketCalendar | None = None,
) -> bool:
    """Evaluate session-based expiry without using file timestamps.

    A missing or non-canonical session identity is deliberately unavailable.
    The exchange schedule is required; the weekday fallback is not safe for
    authorization-sensitive expiry.
    """

    expires_after = item.get("expires_after_sessions")
    if type(expires_after) is not int or expires_after < 1:
        return False
    current = _session_date(current_session_date)
    evidence = item.get("evidence")
    created = _session_date(evidence.get("session_date") if isinstance(evidence, dict) else None)
    if created is None or current is None or current < created:
        return False
    try:
        calendar = calendar or MarketCalendar(
            getattr(settings, "market_calendar", "XNYS"),
            getattr(settings, "local_timezone", "Europe/Madrid"),
        )
        schedule = calendar.session_schedule(created.isoformat(), current.isoformat())
        if schedule is None:
            return False
        session_dates = {
            index.date() if hasattr(index, "date") else index
            for index in schedule.index
        }
    except Exception:
        return False
    if created not in session_dates or current not in session_dates:
        return False
    elapsed_sessions = sum(created < session for session in session_dates if session <= current)
    return elapsed_sessions < expires_after


def active_adaptive_overrides(
    settings: Settings,
    *,
    current_session_date: str | date | None = None,
) -> dict[str, Any]:
    """Return only globally and individually authorized, unexpired overrides.

    The normal Settings loader does not provide a session identity, so records
    with session-based expiry remain unavailable there.  This is intentional:
    an uncertain expiry must never alter active Settings.  Auditors and
    post-market callers may pass the canonical XNYS session explicitly.
    """

    if not _auto_apply_authorized(settings):
        return {}
    calendar = None
    if current_session_date is None:
        try:
            calendar = MarketCalendar(
                getattr(settings, "market_calendar", "XNYS"),
                getattr(settings, "local_timezone", "Europe/Madrid"),
            )
            market_status = calendar.status()
            current_session_date = market_status.session_date if market_status.is_open else None
        except Exception:
            current_session_date = None
    payload = load_adaptive_config(adaptive_config_path(settings))
    overrides: dict[str, Any] = {}
    for name, item in payload.get("parameters", {}).items():
        meta = ADAPTIVE_PARAMETERS.get(name)
        if not meta or not isinstance(item, dict) or item.get("status") != "active":
            continue
        if not _individual_auto_apply_authorized(item):
            continue
        if not _override_expiry_is_valid(
            settings,
            item,
            current_session_date=current_session_date,
            calendar=calendar,
        ):
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
    if getattr(settings, "system_freeze_mode", False):
        return {"status": "blocked", "reason": "system_freeze", "changed": []}
    path = adaptive_config_path(settings)
    if not _auto_apply_authorized(settings):
        return {
            "path": str(path),
            "status": "blocked_by_policy",
            "reason_code": AUTO_APPLY_BLOCKED_REASON,
            "changed": [],
            "generated": None,
            "write_performed": False,
            "blocked_by_policy": True,
            "config": load_adaptive_config(path),
        }
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
    saved = save_adaptive_config(path, config, settings=settings)
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
        "requested_auto_apply": True,
        "authorized_auto_apply": True,
    }


def promote_post_market_improvements(settings: Settings, report: dict[str, Any]) -> dict[str, Any]:
    """Promote conservative post-market learnings into active adaptive overrides."""

    path = adaptive_config_path(settings)
    config = load_adaptive_config(path)
    improvements = report.get("proposed_improvements", []) or []
    if not _auto_apply_authorized(settings):
        return {
            "path": str(path),
            "status": "blocked_by_policy",
            "reason_code": AUTO_APPLY_BLOCKED_REASON,
            "promoted": [],
            "requested_promotions": len(improvements),
            "blocked_promotion_attempts": 1 if improvements else 0,
            "write_performed": False,
            "blocked_by_policy": True,
            "config": config,
        }
    parameters = config.setdefault("parameters", {})
    promoted: list[str] = []

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
        saved = save_adaptive_config(path, config, settings=settings)
    else:
        saved = config
    return {
        "path": str(path),
        "status": "promoted" if promoted else "no_changes",
        "promoted": promoted,
        "blocked_promotion_attempts": 0,
        "write_performed": bool(promoted),
        "config": saved,
    }


def _classify_override(base: Any, effective: Any, direction: str) -> str:
    if base is None or effective is None:
        return "unavailable"
    try:
        if float(base) == float(effective):
            return "equivalent"
        if direction == "conservative_decrease":
            return "stricter" if float(effective) < float(base) else "looser"
        if direction == "conservative_increase":
            return "stricter" if float(effective) > float(base) else "looser"
    except (TypeError, ValueError):
        return "unavailable"
    return "unavailable"


def adaptive_governance_status(
    settings: Settings,
    *,
    blocked_promotion_attempts: int | None = None,
) -> dict[str, Any]:
    """Read-only governance signal and inventory for adaptive overrides."""

    path = adaptive_config_path(settings)
    payload = load_adaptive_config(path)
    parameters = payload.get("parameters", {}) or {}
    try:
        base_settings = Settings()
    except Exception:
        base_settings = settings
    rows: list[dict[str, Any]] = []
    active_count = 0
    unauthorized_count = 0
    critical_count = 0
    for name, item in parameters.items():
        if not isinstance(item, dict) or item.get("status") != "active":
            continue
        meta = ADAPTIVE_PARAMETERS.get(name)
        if not meta:
            rows.append(
                {
                    "name": name,
                    "status": "active",
                    "classification": "unavailable",
                    "governance": "preexisting_unauthorized",
                    "producer": item.get("producer"),
                    "created_at": item.get("created_at"),
                    "base": None,
                    "effective": item.get("proposed"),
                }
            )
            active_count += 1
            unauthorized_count += 1
            continue
        effective = _bounded_value(name, item.get("proposed"))
        base = getattr(base_settings, str(meta["settings_attr"]), None)
        classification = _classify_override(base, effective, str(meta.get("direction") or ""))
        unauthorized = not _auto_apply_authorized(settings)
        governance = "preexisting_unauthorized" if unauthorized else "authorized"
        evidence = item.get("evidence") or {}
        producer = item.get("producer")
        if not producer and isinstance(evidence.get("improvement"), dict):
            producer = "post_market_review.promote_post_market_improvements"
        if unauthorized:
            unauthorized_count += 1
        if unauthorized and classification == "looser":
            governance = "critical_existing_unauthorized_override"
            critical_count += 1
        rows.append(
            {
                "name": name,
                "status": "active",
                "classification": classification,
                "governance": governance,
                "producer": producer or evidence.get("source"),
                "created_at": item.get("created_at") or evidence.get("session_date"),
                "base": base,
                "effective": effective,
                "settings_attr": meta["settings_attr"],
            }
        )
        active_count += 1
    if critical_count:
        status = "critical"
    elif unauthorized_count:
        status = "degraded_governance"
    elif not path.exists() and not blocked_promotion_attempts:
        status = "collecting"
    else:
        status = "healthy"
    return {
        "adaptive_auto_apply_authorized": _auto_apply_authorized(settings),
        "blocked_promotion_attempts": (
            int(blocked_promotion_attempts) if blocked_promotion_attempts is not None else None
        ),
        "active_override_count": active_count,
        "unauthorized_or_legacy_active_override_count": unauthorized_count,
        "status": status,
        "path": str(path),
        "overrides": rows,
        "warnings": list(payload.get("warnings", []) or []),
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
        "governance": adaptive_governance_status(settings),
    }
