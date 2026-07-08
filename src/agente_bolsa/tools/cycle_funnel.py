"""Embudo del ciclo de mercado (B2).

Ensambla, para el ultimo `market_cycle`, el embudo completo:
universo -> candidatos -> finalistas -> recomendaciones -> review determinista ->
review adversarial -> gate de entry-quality -> gate de backtest -> planes de orden ->
ordenes enviadas/fills, con los MOTIVOS de rechazo en cada etapa.

Es SOLO lectura: lee el ultimo evento `paper_auto_trade_completed` (que ya lleva todo
el embudo en su payload) y el ultimo estudio tecnico (universo/candidatos). No toca el
flujo del ciclo. Sirve para responder de un vistazo "por que no se compro hoy".
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from ..config import Settings

LATEST_CYCLE_FUNNEL_EVENT_TYPES = (
    "trade_execution_summary",
    "paper_auto_trade_completed",
    "paper_auto_trade_blocked",
    "scheduled_market_cycle_skipped",
)


def _load_latest_study(settings: Settings) -> dict[str, Any]:
    try:
        path = settings.data_dir / "reports" / "latest_closed_market_technical_study.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - best-effort
        return {}


def _load_study_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - best-effort read-only.
        return {}


def _as_decision_list(value: Any) -> list[dict[str, Any]]:
    """Normaliza un gate/review a lista de decisiones {symbol, approved/passed, reason}."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("decisions", "results", "items", "candidates", "evaluated"):
            inner = value.get(key)
            if isinstance(inner, list):
                return [v for v in inner if isinstance(v, dict)]
    return []


def _is_ok(item: dict[str, Any]) -> bool:
    if "approved" in item:
        return bool(item.get("approved"))
    if "passed" in item:
        return bool(item.get("passed"))
    if "blocked" in item:
        return not bool(item.get("blocked"))
    return True


def _reason_of(item: dict[str, Any]) -> str:
    reason = item.get("reason") or item.get("block_reason") or item.get("rejection_reason")
    if not reason:
        reasons = item.get("reasons")
        if isinstance(reasons, list) and reasons:
            reason = reasons[0]
    return str(reason or "sin motivo")


def _decode_event_payload(event: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    try:
        payload = json.loads(event.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_cycle_funnel_event(store: Any) -> dict[str, Any] | None:
    if hasattr(store, "latest_events"):
        for event in store.latest_events(200):
            if event.get("event_type") in LATEST_CYCLE_FUNNEL_EVENT_TYPES:
                return event
    if hasattr(store, "latest_event_of_type"):
        return store.latest_event_of_type(list(LATEST_CYCLE_FUNNEL_EVENT_TYPES))
    return None


def _event_status(event_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    message = str(payload.get("message") or "").strip()
    operational_kill_switch = payload.get("operational_kill_switch") or {}
    reasons = [str(item).strip() for item in operational_kill_switch.get("reasons", []) if str(item).strip()]
    if event_type == "scheduled_market_cycle_skipped":
        return "skipped", message or "mercado cerrado"
    if event_type == "paper_auto_trade_blocked":
        return "blocked", message or str(payload.get("blocked") or "auto_paper_trade_blocked")
    if event_type == "trade_execution_summary":
        if payload.get("submitted"):
            return "orders_submitted", message or "ordenes enviadas"
        if operational_kill_switch.get("kill_switch_active"):
            return "blocked", "; ".join(reasons[:2]) or message or "operational_kill_switch"
        if payload.get("failed"):
            return "failed", message or "fallo en auto paper trading"
        if payload.get("pending_plans"):
            return "pending_plans", message or "planes pendientes"
        return "completed_without_orders", message or "sin ordenes"
    return "completed", message or "paper_auto_trade_completed"


def _summarize(value: Any) -> dict[str, Any]:
    items = _as_decision_list(value)
    total = len(items)
    blocked = [it for it in items if not _is_ok(it)]
    reasons = Counter(_reason_of(it) for it in blocked)
    return {
        "total": total,
        "approved": total - len(blocked),
        "blocked": len(blocked),
        "blocked_reasons": dict(reasons.most_common(5)),
        "blocked_symbols": [str(it.get("symbol") or "?") for it in blocked][:10],
    }


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distance_sma20(candidate: dict[str, Any]) -> float | None:
    technical = candidate.get("technical_state") or {}
    existing = _num(technical.get("distance_sma20"))
    if existing is not None:
        return existing
    close = _num(technical.get("close"))
    sma20 = _num(technical.get("sma_20"))
    if close is None or not sma20:
        return None
    return (close - sma20) / sma20


def _quartiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "q1": None, "median": None, "q3": None, "max": None}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    lower = ordered[:mid] if n > 1 else ordered
    upper = ordered[mid + (n % 2) :] if n > 1 else ordered
    return {
        "min": round(ordered[0], 4),
        "q1": round(median(lower), 4),
        "median": round(median(ordered), 4),
        "q3": round(median(upper), 4),
        "max": round(ordered[-1], 4),
    }


def build_shadow_scoreboard_from_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        run_id = report.get("run_id")
        as_of = report.get("as_of")
        by_strategy: dict[str, dict[str, Any]] = {}
        for candidate in report.get("shadow_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            strategy = str(candidate.get("strategy_name") or "unknown")
            item = by_strategy.setdefault(strategy, {"count": 0, "distance_sma20": [], "rsi_14": []})
            item["count"] += 1
            distance = _distance_sma20(candidate)
            if distance is not None:
                item["distance_sma20"].append(distance)
            rsi = _num((candidate.get("technical_state") or {}).get("rsi_14"))
            if rsi is not None:
                item["rsi_14"].append(rsi)
        for strategy, item in sorted(by_strategy.items()):
            rows.append(
                {
                    "run_id": run_id,
                    "as_of": as_of,
                    "strategy_name": strategy,
                    "shadow_candidates": item["count"],
                    "distance_sma20": _quartiles(item["distance_sma20"]),
                    "rsi_14": _quartiles(item["rsi_14"]),
                }
            )
        if not by_strategy:
            rows.append(
                {
                    "run_id": run_id,
                    "as_of": as_of,
                    "strategy_name": "(sin shadow)",
                    "shadow_candidates": 0,
                    "distance_sma20": _quartiles([]),
                    "rsi_14": _quartiles([]),
                }
            )
    return {"cycles": len(reports), "rows": rows}


def build_shadow_scoreboard(settings: Settings, limit: int = 10) -> dict[str, Any]:
    reports_dir = settings.data_dir / "reports"
    paths = sorted(
        [
            path
            for path in reports_dir.glob("closed_market_technical_study_*.json")
            if path.name != "latest_closed_market_technical_study.json"
            and not path.name.endswith(".manifest.json")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: max(1, int(limit))]
    reports = [report for report in (_load_study_file(path) for path in paths) if report]
    return build_shadow_scoreboard_from_reports(reports)


def _fmt(value: Any, *, percent: bool = False) -> str:
    number = _num(value)
    if number is None:
        return "n/d"
    if percent:
        return f"{number * 100:.1f}%"
    return f"{number:.1f}"


def format_shadow_scoreboard(scoreboard: dict[str, Any]) -> str:
    rows = scoreboard.get("rows") or []
    lines = [
        f"SHADOW SCOREBOARD  ultimos {scoreboard.get('cycles', 0)} reportes tecnicos",
        "-" * 108,
        (
            f"{'run_id':<18}{'strategy':<20}{'n':>5}"
            f"{'dist min':>10}{'dist p50':>10}{'dist max':>10}"
            f"{'rsi min':>9}{'rsi p50':>9}{'rsi max':>9}"
        ),
    ]
    for row in rows:
        dist = row.get("distance_sma20") or {}
        rsi = row.get("rsi_14") or {}
        lines.append(
            f"{str(row.get('run_id') or 'n/d'):<18}{str(row.get('strategy_name') or 'n/d'):<20}"
            f"{int(row.get('shadow_candidates') or 0):>5}"
            f"{_fmt(dist.get('min'), percent=True):>10}{_fmt(dist.get('median'), percent=True):>10}{_fmt(dist.get('max'), percent=True):>10}"
            f"{_fmt(rsi.get('min')):>9}{_fmt(rsi.get('median')):>9}{_fmt(rsi.get('max')):>9}"
        )
    if not rows:
        lines.append("(sin reportes)")
    return "\n".join(lines)


def build_cycle_funnel(store: Any, settings: Settings) -> dict[str, Any]:
    event = _latest_cycle_funnel_event(store)
    payload = _decode_event_payload(event)
    study = _load_latest_study(settings)
    event_type = str((event or {}).get("event_type") or "")
    status, status_reason = _event_status(event_type, payload)

    rejected_plans = payload.get("rejected_order_plans") or []
    plan_reasons = Counter(
        str((p or {}).get("reason") or (p or {}).get("rejection_reason") or "sin motivo")
        for p in rejected_plans
        if isinstance(p, dict)
    )

    recommendations = payload.get("recommendations")
    funnel = {
        "run_id": (event or {}).get("cycle_id"),
        "as_of": (event or {}).get("created_at"),
        "event_type": event_type or None,
        "status": status,
        "status_reason": status_reason,
        "stages": {
            "universo": study.get("symbols_scanned"),
            "con_datos": study.get("symbols_with_data"),
            "candidatos": len(study.get("all_candidates") or []) or None,
            "top_longs": len(study.get("top_longs") or []) or None,
            "recomendaciones": (len(recommendations) if isinstance(recommendations, list) else None),
            "review_determinista": _summarize(payload.get("deterministic_review")),
            "review_adversarial": _summarize(payload.get("adversarial_review")),
            "gate_entry_quality": _summarize(payload.get("entry_quality_gate")),
            "gate_backtest": _summarize(payload.get("backtest_gate")),
            "planes_rechazados": {
                "total": len(rejected_plans),
                "reasons": dict(plan_reasons.most_common(5)),
            },
            "enviadas": len(payload.get("submitted") or []),
            "fallidas": len(payload.get("failed") or []),
        },
        "setup_counts": study.get("setup_counts"),
        "limites": {
            "max_orders_per_cycle": payload.get("effective_max_orders_per_cycle"),
            "max_daily_buy_orders": payload.get("effective_max_daily_buy_orders"),
        },
    }
    funnel["cuello"] = _identify_bottleneck(
        funnel["stages"],
        status=status,
        status_reason=status_reason,
        event_type=event_type,
    )
    return funnel


def _identify_bottleneck(
    stages: dict[str, Any],
    *,
    status: str | None = None,
    status_reason: str | None = None,
    event_type: str | None = None,
) -> str:
    """Devuelve la primera etapa donde la cuenta cae a 0 / todo se bloquea."""
    if event_type == "scheduled_market_cycle_skipped":
        return f"market_cycle_skipped: {status_reason or 'sin motivo'}"
    if status == "blocked":
        return f"flujo_bloqueado: {status_reason or 'sin motivo'}"
    if status == "failed":
        return f"flujo_fallido: {status_reason or 'sin motivo'}"
    if (stages.get("enviadas") or 0) > 0:
        return "ninguno: se enviaron ordenes"
    rec = stages.get("recomendaciones")
    if rec is not None and rec == 0:
        return "decision: el LLM/fallback no propuso ninguna compra"
    for name in ("review_determinista", "review_adversarial", "gate_entry_quality", "gate_backtest"):
        s = stages.get(name) or {}
        if s.get("total", 0) > 0 and s.get("approved", 0) == 0:
            reasons = ", ".join(f"{k} ({v})" for k, v in (s.get("blocked_reasons") or {}).items())
            return f"{name}: bloqueo total. Motivos: {reasons or 'n/d'}"
    if (stages.get("planes_rechazados") or {}).get("total", 0) > 0:
        reasons = ", ".join(
            f"{k} ({v})" for k, v in ((stages.get("planes_rechazados") or {}).get("reasons") or {}).items()
        )
        return f"planes_de_orden: todos rechazados. Motivos: {reasons or 'n/d'}"
    if (stages.get("candidatos") or 0) == 0:
        return "scan: 0 candidatos generados"
    return "no determinado (sin ordenes pero sin bloqueo total claro)"


def format_cycle_funnel(funnel: dict[str, Any]) -> str:
    s = funnel.get("stages", {})
    lines = []
    lines.append(f"EMBUDO DEL CICLO  run_id={funnel.get('run_id') or 'n/d'}  ({funnel.get('as_of') or 'n/d'})")
    lines.append("-" * 64)
    lines.append(
        f"  {'fuente':<22} {funnel.get('event_type') or 'n/d'}"
        f"  | estado={funnel.get('status') or 'n/d'}"
    )
    if funnel.get("status_reason"):
        lines.append(f"  {'motivo':<22} {funnel.get('status_reason')}")

    def gate_line(label: str, key: str) -> str:
        g = s.get(key) or {}
        extra = ""
        if g.get("blocked"):
            rs = ", ".join(f"{k} x{v}" for k, v in (g.get("blocked_reasons") or {}).items())
            extra = f"  [bloqueadas {g.get('blocked')}: {rs}]"
        return f"  {label:<22} aprob {g.get('approved', 0)}/{g.get('total', 0)}{extra}"

    lines.append(f"  {'universo':<22} {s.get('universo') or 'n/d'}  (con datos: {s.get('con_datos') or 'n/d'})")
    lines.append(f"  {'candidatos':<22} {s.get('candidatos') or 0}")
    lines.append(f"  {'top_longs':<22} {s.get('top_longs') or 0}")
    rec = s.get("recomendaciones")
    lines.append(f"  {'recomendaciones (buy)':<22} {rec if rec is not None else 'n/d'}")
    lines.append(gate_line("review determinista", "review_determinista"))
    lines.append(gate_line("review adversarial", "review_adversarial"))
    lines.append(gate_line("gate entry-quality", "gate_entry_quality"))
    lines.append(gate_line("gate backtest", "gate_backtest"))
    rp = s.get("planes_rechazados") or {}
    if rp.get("total"):
        rs = ", ".join(f"{k} x{v}" for k, v in (rp.get("reasons") or {}).items())
        lines.append(f"  {'planes rechazados':<22} {rp.get('total')}  [{rs}]")
    lines.append(f"  {'ORDENES enviadas':<22} {s.get('enviadas') or 0}  (fallidas: {s.get('fallidas') or 0})")
    lines.append("-" * 64)
    lines.append(f"  CUELLO: {funnel.get('cuello')}")
    if funnel.get("setup_counts"):
        lines.append(f"  setups: {funnel.get('setup_counts')}")
    return "\n".join(lines)


def _cycle_outcome_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Resumen de una ronda: nº de recomendaciones, bloqueos por etapa+motivo, enviadas."""
    recs = payload.get("recommendations")
    n_rec = len(recs) if isinstance(recs, list) else None
    submitted = len(payload.get("submitted") or [])
    reasons: Counter = Counter()
    for stage, key in (
        ("determinista", "deterministic_review"),
        ("adversarial", "adversarial_review"),
        ("entry_quality", "entry_quality_gate"),
        ("backtest", "backtest_gate"),
    ):
        for item in _as_decision_list(payload.get(key)):
            if not _is_ok(item):
                reasons[f"{stage}: {_reason_of(item)}"] += 1
    for plan in payload.get("rejected_order_plans") or []:
        if isinstance(plan, dict):
            motivo = plan.get("reason") or plan.get("rejection_reason") or "sin motivo"
            reasons[f"plan: {motivo}"] += 1
    operational_kill_switch = payload.get("operational_kill_switch") or {}
    if operational_kill_switch.get("kill_switch_active"):
        for reason in operational_kill_switch.get("reasons") or ["kill_switch_activo"]:
            reasons[f"operational_kill_switch: {reason}"] += 1
    return {"recommendations": n_rec, "submitted": submitted, "reasons": reasons}


def build_cycle_funnel_history(store: Any, settings: Settings, limit: int = 20) -> dict[str, Any]:
    """Agrega los ultimos `limit` ciclos con el ultimo evento observable por ciclo."""
    limit = max(1, int(limit))
    raw = store.latest_events(max(limit * 50, 200))
    events: list[dict[str, Any]] = []
    seen_cycle_ids: set[str] = set()
    for event in raw:
        event_type = str(event.get("event_type") or "")
        cycle_id = str(event.get("cycle_id") or "")
        if event_type not in LATEST_CYCLE_FUNNEL_EVENT_TYPES or not cycle_id or cycle_id in seen_cycle_ids:
            continue
        seen_cycle_ids.add(cycle_id)
        events.append(event)
        if len(events) >= limit:
            break

    agg_reasons: Counter = Counter()
    cycles = 0
    with_orders = 0
    total_rec = 0
    total_sub = 0
    per_cycle: list[dict[str, Any]] = []
    for event in events:
        try:
            payload = json.loads(event.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        outcome = _cycle_outcome_from_payload(payload)
        cycles += 1
        if outcome["submitted"] > 0:
            with_orders += 1
        total_rec += outcome["recommendations"] or 0
        total_sub += outcome["submitted"]
        agg_reasons.update(outcome["reasons"])
        per_cycle.append(
            {
                "run_id": event.get("cycle_id"),
                "as_of": event.get("created_at"),
                "recomendaciones": outcome["recommendations"],
                "enviadas": outcome["submitted"],
            }
        )
    return {
        "cycles_analizados": cycles,
        "ciclos_con_ordenes": with_orders,
        "total_recomendaciones": total_rec,
        "total_enviadas": total_sub,
        "motivos_rechazo_top": dict(agg_reasons.most_common(12)),
        "por_ciclo": per_cycle,
    }


def format_cycle_funnel_history(agg: dict[str, Any]) -> str:
    n = agg.get("cycles_analizados", 0)
    lines = [
        f"EMBUDO AGREGADO  ultimos {n} ciclos observables",
        "-" * 64,
        f"  ciclos con ordenes : {agg.get('ciclos_con_ordenes', 0)}/{n}",
        f"  recomendaciones    : {agg.get('total_recomendaciones', 0)}  (enviadas: {agg.get('total_enviadas', 0)})",
        "  motivos de rechazo (agregados, etapa: motivo):",
    ]
    motivos = agg.get("motivos_rechazo_top") or {}
    if not motivos:
        lines.append("    (ninguno)")
    for k, v in motivos.items():
        lines.append(f"    {v:>4}x  {k}")
    return "\n".join(lines)
