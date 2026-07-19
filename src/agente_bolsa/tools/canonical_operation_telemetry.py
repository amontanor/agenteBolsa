"""Canonical, read-only operation telemetry for P-L48B.

The producer in this module is deliberately observational.  It reads the
already persisted local lineage and broker-order payloads, creates one
operation per exact ``broker_order_id`` and never calls a broker, reconciler,
selector or learning stage.  Persistence is a separate short append-only
operation so a telemetry failure cannot change the post-market pipeline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..storage import Store


SCHEMA_VERSION = "p-l48b.canonical-operation-telemetry.v1"
EVENT_TYPE = "canonical_operation_telemetry"
EVENT_ID_PREFIX = "canonical_operation_telemetry:"
AGED_SIGNAL_SECONDS = 900.0
_MISSING = object()

_EXIT_ORIGINS = {
    "stop_loss": "automatic_stop_loss",
    "take_profit": "automatic_take_profit",
    "trailing_stop": "automatic_trailing_stop",
    "time_stop_v2": "automatic_time_stop",
    "manual": "manual",
    "manual_exit": "manual",
}

_RECONCILIATION_STATES = {
    "submitted",
    "pending_local",
    "position_observed_without_exact_order_link",
    "reconciled_filled",
    "reconciled_rejected",
    "reconciliation_unavailable",
    "conflict",
}


def _safe(value: Any) -> Any:
    """Return JSON-compatible data without carrying post-decision fields."""

    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _stable_hash(payload: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(_safe(body), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _find_value(value: Any, names: Sequence[str]) -> Any:
    """Find an exact field in known nested lineage blocks.

    This is intentionally key based.  It never joins records by symbol, date,
    or list position.
    """

    wanted = {str(name) for name in names}
    if isinstance(value, Mapping):
        for name in names:
            if name in value and value[name] not in (None, ""):
                return value[name]
        for item in value.values():
            found = _find_value(item, tuple(wanted))
            if found is not _MISSING:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_value(item, tuple(wanted))
            if found is not _MISSING:
                return found
    return _MISSING


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_timestamp(value: Any, *, captured_at: datetime, warnings: list[str], field: str) -> datetime | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        warnings.append(f"invalid_timestamp:{field}")
        return None
    if parsed.tzinfo is None:
        warnings.append(f"naive_timestamp:{field}")
        return None
    parsed = parsed.astimezone(timezone.utc)
    if parsed > captured_at:
        warnings.append(f"future_timestamp:{field}")
        return None
    return parsed


def _iso(parsed: datetime | None) -> str | None:
    return parsed.isoformat() if parsed is not None else None


def _bps(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old == 0 or not all(math.isfinite(item) for item in (old, new)):
        return None
    return round((new / old - 1.0) * 10_000.0, 6)


def normalize_exit_origin(raw_trigger: Any) -> str:
    return _EXIT_ORIGINS.get(str(raw_trigger or "").strip().lower(), "unknown_exit_origin")


def _freshness(
    source: Mapping[str, Any],
    *,
    signal: Mapping[str, Any] | None,
    recommendation: Mapping[str, Any] | None,
    plan: Mapping[str, Any] | None,
    captured_at: datetime,
) -> dict[str, Any]:
    warnings: list[str] = []
    signal_features = _mapping((signal or {}).get("features"))
    recommendation_payload = _mapping((recommendation or {}).get("payload"))
    plan_payload = _mapping((plan or {}).get("payload"))
    execution = _mapping(source.get("execution_quality_snapshot"))
    timestamps = _mapping(execution.get("timestamps"))
    prices = _mapping(execution.get("prices"))

    raw_values = {
        "signal_at": _first_present(source.get("signal_at"), (signal or {}).get("created_at")),
        "signal_price": _first_present(source.get("signal_price"), signal_features.get("signal_price"), signal_features.get("entry_price")),
        "recommendation_at": _first_present(source.get("recommendation_at"), (recommendation or {}).get("created_at")),
        "recommendation_price": _first_present(source.get("recommendation_price"), recommendation_payload.get("recommendation_price")),
        "plan_created_at": _first_present(source.get("plan_created_at"), (plan or {}).get("created_at")),
        "plan_price": _first_present(source.get("plan_price"), plan_payload.get("plan_price"), plan_payload.get("entry_price")),
        "submitted_at": _first_present(source.get("submitted_at"), timestamps.get("submitted_at"), _find_value(source, ("submitted_at",))),
        "first_fill_at": _first_present(source.get("first_fill_at"), timestamps.get("first_fill_at"), _find_value(source, ("first_fill_at",))),
        "fill_price": _first_present(source.get("fill_price"), prices.get("fill_price"), prices.get("average_fill_price")),
    }
    # Recommendation/plan prices must be explicit; do not copy signal price.
    result: dict[str, Any] = {key: raw_values[key] for key in raw_values}
    parsed: dict[str, datetime | None] = {}
    for field in ("signal_at", "recommendation_at", "plan_created_at", "submitted_at", "first_fill_at"):
        parsed[field] = _parse_timestamp(raw_values[field], captured_at=captured_at, warnings=warnings, field=field)
        result[field] = _iso(parsed[field]) if parsed[field] is not None else None
        if raw_values[field] is None:
            warnings.append(f"missing:{field}")
    for field in ("signal_price", "recommendation_price", "plan_price", "fill_price"):
        number = _number(raw_values[field])
        if raw_values[field] is not None and number is None:
            warnings.append(f"invalid:{field}")
        result[field] = number

    signal_at = parsed["signal_at"]
    for field, output in (
        ("recommendation_at", "signal_to_recommendation_seconds"),
        ("plan_created_at", "signal_to_plan_seconds"),
        ("submitted_at", "signal_to_submit_seconds"),
        ("first_fill_at", "signal_to_fill_seconds"),
    ):
        result[output] = None
        if signal_at is not None and parsed[field] is not None:
            seconds = (parsed[field] - signal_at).total_seconds()
            if seconds < 0:
                warnings.append(f"inverted:{field}")
            else:
                result[output] = round(seconds, 6)
    result["signal_to_plan_bps"] = _bps(result["signal_price"], result["plan_price"])
    result["signal_to_fill_bps"] = _bps(result["signal_price"], result["fill_price"])
    quote_at = _find_value(execution, ("quote_at", "price_observed_at", "market_price_at"))
    result["price_refresh_status"] = "verified" if quote_at is not _MISSING and _parse_timestamp(quote_at, captured_at=captured_at, warnings=warnings, field="quote_at") else "unverified"
    if result["signal_to_plan_seconds"] is not None:
        result["freshness_status"] = "aged_signal" if result["signal_to_plan_seconds"] > AGED_SIGNAL_SECONDS else "fresh_signal"
    else:
        result["freshness_status"] = "unavailable"
    result["warnings"] = sorted(set(warnings))
    return result


def _source_rows(source_data: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        [dict(item) for item in source_data.get("broker_orders", []) if isinstance(item, Mapping)],
        [dict(item) for item in source_data.get("order_plans", []) if isinstance(item, Mapping)],
        [dict(item) for item in source_data.get("trade_recommendations", source_data.get("recommendations", [])) if isinstance(item, Mapping)],
        [dict(item) for item in source_data.get("signal_outcomes", source_data.get("signals", [])) if isinstance(item, Mapping)],
        [dict(item) for item in source_data.get("fill_fragments", []) if isinstance(item, Mapping)],
    )


def _load_source_data(store: Store, session_date: str) -> dict[str, Any]:
    try:
        with store.read_connection() as conn:
            rows = conn.execute(
                "SELECT broker_order_id, plan_id, cycle_id, symbol, side, status, payload_json, created_at FROM broker_orders WHERE substr(created_at, 1, 10) = ? ORDER BY created_at, broker_order_id",
                (session_date,),
            ).fetchall()
            broker_orders = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                broker_orders.append({
                    "broker_order_id": row["broker_order_id"], "plan_id": row["plan_id"], "cycle_id": row["cycle_id"],
                    "symbol": row["symbol"], "side": row["side"], "status": row["status"], "created_at": row["created_at"],
                    **(_mapping(payload)),
                })
        memories = store.trade_memory(limit=50000, since_date=session_date)
        fragments: list[dict[str, Any]] = []
        for memory in memories:
            broker_order_id = _find_value(memory, ("broker_order_id",))
            if broker_order_id is _MISSING or not _text(broker_order_id):
                continue
            fragments.append(
                {
                    "broker_order_id": str(broker_order_id),
                    "fragment_id": _text(_find_value(memory, ("fragment_id", "fill_fragment_id"))) or _text(memory.get("memory_id")),
                    "qty": _number(_find_value(memory, ("qty", "filled_qty"))),
                    "source": "trade_memory",
                }
            )
        return {
            "broker_orders": broker_orders,
            "order_plans": [item for item in store.order_plans(limit=50000) if str(item.get("created_at") or "")[:10] == session_date],
            "trade_recommendations": [item for item in store.trade_recommendations(limit=50000) if str(item.get("created_at") or "")[:10] == session_date],
            "signal_outcomes": [item for item in store.signal_outcomes(limit=50000, since_date=session_date) if item.get("signal_date") == session_date],
            "fill_fragments": fragments,
            "agent_events": store.agent_events(limit=50000),
        }
    finally:
        store.close_read_connection()


def _lineage_maps(source_data: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    orders, plans, recommendations, signals, _ = _source_rows(source_data)
    def by_id(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        return {str(item[key]): item for item in rows if _text(item.get(key))}
    return by_id(plans, "plan_id"), by_id(recommendations, "recommendation_id"), by_id(signals, "signal_id"), {
        str(item.get("broker_order_id")): item for item in orders if _text(item.get("broker_order_id"))
    }


def _normalize_rejections(source_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[Mapping[str, Any]] = [item for item in source_data.get("rejected_order_plans", []) if isinstance(item, Mapping)]
    for event in source_data.get("agent_events", []) or []:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event_type") or "").lower()
        payload = _mapping(event.get("payload"))
        if "rejected_order_plan" in event_type or payload.get("reason_code") == "duplicate_symbol_cycle_guard":
            rows.append(payload | {"observed_at": payload.get("observed_at") or event.get("created_at")})
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = [row.get(key) for key in ("cycle_id", "signal_id", "candidate_id")]
        result.append(
            {
                "cycle_id": _text(row.get("cycle_id")),
                "signal_id": _text(row.get("signal_id")),
                "candidate_id": _text(row.get("candidate_id")),
                "recommendation_id": _text(row.get("recommendation_id")),
                "plan_id": _text(row.get("plan_id")),
                "reason_code": _text(row.get("reason_code")),
                "observed_at": _text(row.get("observed_at")),
                "identity_quality": "verified" if all(_text(value) for value in identity) else "partial",
            }
        )
    return result


def _operation_for_order(
    order: Mapping[str, Any],
    *,
    plans: Mapping[str, Mapping[str, Any]],
    recommendations: Mapping[str, Mapping[str, Any]],
    signals: Mapping[str, Mapping[str, Any]],
    fragments: Mapping[str, list[Mapping[str, Any]]],
    captured_at: datetime,
) -> dict[str, Any]:
    payload = _mapping(order.get("payload")) | {key: value for key, value in order.items() if key not in {"payload"}}
    broker = _mapping(order.get("broker_order"))
    execution = _mapping(order.get("execution_quality_snapshot")) or _mapping(payload.get("execution_quality_snapshot"))
    plan_id = _text(order.get("plan_id") or _find_value(payload, ("plan_id",)))
    plan = plans.get(plan_id or "")
    recommendation_id = _text(_find_value(payload, ("recommendation_id",)))
    plan_payload = _mapping((plan or {}).get("payload"))
    if recommendation_id is None:
        recommendation_id = _text(_find_value(plan_payload, ("recommendation_id",)))
    recommendation = recommendations.get(recommendation_id or "")
    recommendation_payload = _mapping((recommendation or {}).get("payload"))
    # Exact plan/recommendation payloads enrich the operation; the order row
    # remains authoritative when it contains an explicit field.
    payload = plan_payload | recommendation_payload | payload
    signal_id = _text(_find_value(execution, ("signal_id",)) or _find_value(payload, ("signal_id",)))
    signal = signals.get(signal_id or "")
    candidate_id = _text(_find_value(execution, ("candidate_id",)) or _find_value(payload, ("candidate_id",)))
    source_plan_id = _text(_find_value(payload, ("source_plan_id",)))
    cycle_id = _text(order.get("cycle_id") or _find_value(payload, ("cycle_id",)))
    raw_trigger = _find_value(payload, ("raw_exit_trigger", "exit_trigger", "trigger"))
    if raw_trigger is _MISSING:
        raw_trigger = None
    side = _text(order.get("side") or broker.get("side"))
    side = side.lower() if side else None
    status = _text(order.get("status") or _find_value(payload, ("status",)))
    status_lower = (status or "").lower()
    reconciliation = _mapping(payload.get("broker_order_reconciled"))
    reconciliation_status = _text(payload.get("reconciliation_status") or reconciliation.get("reconciliation_status"))
    if reconciliation_status not in _RECONCILIATION_STATES:
        if bool(payload.get("position_observed_without_exact_order_link")) or (
            bool(payload.get("position_observed")) and status_lower in {"pending", "pending_new", "new", "accepted"}
        ):
            reconciliation_status = "position_observed_without_exact_order_link"
        elif status_lower.endswith("filled") or status_lower == "filled":
            reconciliation_status = "reconciled_filled"
        elif status_lower in {"pending", "pending_new", "new", "accepted", "submitted"}:
            reconciliation_status = "pending_local"
        elif status_lower in {"rejected", "cancelled", "canceled"}:
            reconciliation_status = "reconciled_rejected"
        else:
            reconciliation_status = "reconciliation_unavailable"
    order_fragments = list(fragments.get(str(order.get("broker_order_id") or ""), []))
    fragment_ids = [_text(item.get("fragment_id")) for item in order_fragments]
    duplicate_fragments = len(fragment_ids) - len({item for item in fragment_ids if item}) if fragment_ids else 0
    warnings: list[str] = []
    if duplicate_fragments > 0:
        warnings.append("duplicate_fill_fragments")
    freshness = _freshness({**payload, "execution_quality_snapshot": execution}, signal=signal, recommendation=recommendation, plan=plan, captured_at=captured_at)
    warnings.extend(freshness.get("warnings") or [])
    operation = {
        "broker_order_id": _text(order.get("broker_order_id")),
        "client_order_id": _text(order.get("client_order_id") or broker.get("client_order_id") or _find_value(payload, ("client_order_id",))),
        "side": side,
        "symbol": _text(order.get("symbol") or broker.get("symbol")),
        "submitted_qty": _number(_find_value(payload, ("submitted_qty", "qty"))),
        "filled_qty": _number(_find_value(reconciliation, ("filled_qty",)) or _find_value(execution, ("filled", "filled_qty"))),
        "average_fill_price": _number(_find_value(payload, ("average_fill_price", "fill_price")) or _find_value(execution, ("average_fill_price",))),
        "status": status,
        "cycle_id": cycle_id,
        "signal_capture_id": _text(_find_value(execution, ("signal_capture_id",)) or _find_value(payload, ("signal_capture_id",))),
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "plan_id": plan_id,
        "source_plan_id": source_plan_id,
        "strategy": _text(_find_value(payload, ("strategy", "strategy_name"))),
        "decision_source": _text(_find_value(payload, ("decision_source",))),
        "capacity_fill_reason_code": _text(_find_value(payload, ("capacity_fill_reason_code",))),
        "micro_experiment": _find_value(payload, ("micro_experiment",)) if _find_value(payload, ("micro_experiment",)) is not _MISSING else None,
        "size_multiplier": _number(_find_value(payload, ("size_multiplier",))),
        "setup_edge_3d_raw": _number(_find_value(payload, ("setup_edge_3d_raw",))),
        "operational_penalty": _number(_find_value(payload, ("operational_penalty",))),
        "expected_edge_3d": _number(_find_value(payload, ("expected_edge_3d",))),
        "raw_exit_trigger": _text(raw_trigger),
        "normalized_exit_origin": normalize_exit_origin(raw_trigger),
        "fill_fragment_count": len(order_fragments) if order_fragments else None,
        "reconciliation_status": reconciliation_status,
        "reconciliation_quality": _text(payload.get("reconciliation_quality")) or ("verified" if reconciliation_status == "reconciled_filled" else "partial"),
        "freshness": freshness,
        "lineage_quality": "verified" if signal_id or _text(_find_value(execution, ("signal_capture_id",))) else "partial",
        "warnings": sorted(set(warnings)),
    }
    return operation


def _unavailable_snapshot(session_date: str, *, captured_at: datetime, warning: str) -> dict[str, Any]:
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session_date,
        "captured_at": captured_at.isoformat(),
        "revision": 1,
        "status": "unavailable",
        "content_hash": None,
        "denominators": {key: None for key in ("broker_order_count", "buy_order_count", "sell_order_count", "fill_fragment_count", "signal_count", "candidate_count", "recommendation_count", "plan_count")},
        "execution": {key: None for key in ("filled_count", "pending_count", "rejected_count", "cancelled_count", "position_observed_without_exact_order_link_count", "reconciliation_unavailable_count", "conflict_count")},
        "exits": {"automatic_exit_count": None, "manual_exit_count": None, "unknown_exit_origin_count": None, "by_normalized_origin": {}},
        "freshness": {"operations_with_signal": None, "operations_with_verified_price_refresh": None, "aged_signal_count": None, "unavailable_count": None},
        "operations": [],
        "rejections": [],
        "data_quality_warnings": [warning],
    }
    snapshot["content_hash"] = _stable_hash(snapshot)
    return snapshot


def build_canonical_operation_telemetry(
    store: Store | None,
    session_date: str,
    *,
    captured_at: datetime | None = None,
    source_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one canonical snapshot from local sources only."""

    capture = captured_at or datetime.now(timezone.utc)
    if capture.tzinfo is None:
        capture = capture.replace(tzinfo=timezone.utc)
    capture = capture.astimezone(timezone.utc)
    try:
        data = dict(source_data) if source_data is not None else _load_source_data(store, session_date) if store is not None else {}
        orders, plans_rows, recommendations_rows, signals_rows, fragments_rows = _source_rows(data)
        plans = {str(item["plan_id"]): item for item in plans_rows if _text(item.get("plan_id"))}
        recommendations = {str(item["recommendation_id"]): item for item in recommendations_rows if _text(item.get("recommendation_id"))}
        signals = {str(item["signal_id"]): item for item in signals_rows if _text(item.get("signal_id"))}
        fragments: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for fragment in fragments_rows:
            order_id = _text(fragment.get("broker_order_id"))
            if order_id:
                fragments[order_id].append(fragment)
        by_order: dict[str, Mapping[str, Any]] = {}
        duplicate_order_ids: set[str] = set()
        duplicate_client_ids = [str(item.get("client_order_id")) for item in orders if _text(item.get("client_order_id"))]
        for order in orders:
            order_id = _text(order.get("broker_order_id"))
            if not order_id:
                continue
            if order_id in by_order:
                duplicate_order_ids.add(order_id)
                continue
            by_order[order_id] = order
        operations = [_operation_for_order(order, plans=plans, recommendations=recommendations, signals=signals, fragments=fragments, captured_at=capture) for order in by_order.values()]
        operations.sort(key=lambda item: str(item.get("broker_order_id") or ""))
        rejections = _normalize_rejections(data)
        warnings: list[str] = []
        if duplicate_order_ids:
            warnings.append("duplicate_broker_order_id:" + ",".join(sorted(duplicate_order_ids)))
        duplicate_clients = sorted({value for value, count in Counter(duplicate_client_ids).items() if count > 1})
        if duplicate_clients:
            warnings.append("duplicate_client_order_id:" + ",".join(duplicate_clients))
        signal_ids = [str(item.get("signal_id")) for item in signals_rows if _text(item.get("signal_id"))]
        candidate_ids = [_text(_find_value(item, ("candidate_id",))) for item in signals_rows + recommendations_rows + plans_rows]
        candidate_available = all(item is not None for item in candidate_ids) if candidate_ids else False
        denominator = {
            "broker_order_count": len(operations),
            "buy_order_count": sum(1 for item in operations if item.get("side") == "buy"),
            "sell_order_count": sum(1 for item in operations if item.get("side") == "sell"),
            "fill_fragment_count": len(fragments_rows) if fragments_rows else (0 if operations and all(item.get("fill_fragment_count") == 0 for item in operations) else None),
            "signal_count": len(set(signal_ids)) if signals_rows else None,
            "candidate_count": len({item for item in candidate_ids if item}) if candidate_available else None,
            "recommendation_count": len({str(item["recommendation_id"]) for item in recommendations_rows if _text(item.get("recommendation_id"))}) if recommendations_rows else None,
            "plan_count": len({str(item["plan_id"]) for item in plans_rows if _text(item.get("plan_id"))}) if plans_rows else None,
        }
        # Sanitised fixtures and legacy stores may expose a domain count
        # without carrying every source row.  Preserve that explicit source
        # value; never infer a missing domain as zero.
        for key in ("signal_count", "candidate_count", "recommendation_count", "plan_count"):
            if denominator[key] is None and data.get(key) is not None:
                try:
                    denominator[key] = int(data[key])
                except (TypeError, ValueError):
                    warnings.append(f"invalid_denominator:{key}")
        execution = {
            "filled_count": sum(1 for item in operations if item.get("reconciliation_status") == "reconciled_filled"),
            "pending_count": sum(1 for item in operations if item.get("reconciliation_status") in {"pending_local", "submitted"}),
            "rejected_count": sum(1 for item in operations if item.get("reconciliation_status") == "reconciled_rejected" and str(item.get("status") or "").lower() == "rejected"),
            "cancelled_count": sum(1 for item in operations if str(item.get("status") or "").lower() in {"cancelled", "canceled"}),
            "position_observed_without_exact_order_link_count": sum(1 for item in operations if item.get("reconciliation_status") == "position_observed_without_exact_order_link"),
            "reconciliation_unavailable_count": sum(1 for item in operations if item.get("reconciliation_status") == "reconciliation_unavailable"),
            "conflict_count": sum(1 for item in operations if item.get("reconciliation_status") == "conflict"),
        }
        exits_by_origin = Counter(str(item.get("normalized_exit_origin")) for item in operations if item.get("side") == "sell")
        automatic = sum(value for key, value in exits_by_origin.items() if key.startswith("automatic_"))
        exits = {
            "automatic_exit_count": automatic,
            "manual_exit_count": int(exits_by_origin.get("manual", 0)),
            "unknown_exit_origin_count": int(exits_by_origin.get("unknown_exit_origin", 0)),
            "by_normalized_origin": dict(sorted(exits_by_origin.items())),
        }
        freshness = {
            "operations_with_signal": sum(1 for item in operations if item.get("signal_id") or item.get("signal_capture_id")),
            "operations_with_verified_price_refresh": sum(1 for item in operations if item.get("freshness", {}).get("price_refresh_status") == "verified"),
            "aged_signal_count": sum(1 for item in operations if item.get("freshness", {}).get("freshness_status") == "aged_signal"),
            "unavailable_count": sum(1 for item in operations if item.get("freshness", {}).get("freshness_status") == "unavailable"),
        }
        status = "available" if operations and all(item.get("broker_order_id") for item in operations) else "partial" if operations else "unavailable"
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "session_date": session_date,
            "captured_at": capture.isoformat(),
            "revision": 1,
            "status": status,
            "content_hash": None,
            "denominators": denominator,
            "execution": execution,
            "exits": exits,
            "freshness": freshness,
            "operations": operations,
            "rejections": rejections,
            "data_quality_warnings": sorted(set(warnings)),
        }
        snapshot["content_hash"] = _stable_hash(snapshot)
        return snapshot
    except Exception as exc:  # telemetry must be fail-open for pipeline callers
        return _unavailable_snapshot(session_date, captured_at=capture, warning=f"producer_failed:{type(exc).__name__}")


def persist_canonical_operation_telemetry(store: Store, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    event_id = EVENT_ID_PREFIX + str(snapshot.get("session_date") or "unknown")
    return store.record_canonical_operation_telemetry(dict(snapshot), event_id=event_id)


def read_canonical_operation_telemetry(store: Store, session_date: str) -> dict[str, Any]:
    event = store.canonical_operation_telemetry_event(session_date)
    if event is None:
        return {"status": "collecting", "schema_version": SCHEMA_VERSION, "session_date": session_date, "denominators": None, "execution": None, "exits": None, "freshness": None, "operations": [], "rejections": [], "data_quality_warnings": []}
    payload = dict(event.get("payload") or {})
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("content_hash") != _stable_hash(payload):
        return {"status": "legacy_without_canonical_telemetry", "schema_version": SCHEMA_VERSION, "session_date": session_date, "denominators": None, "operations": [], "data_quality_warnings": ["invalid_canonical_event"]}
    return payload


def canonical_operation_telemetry_digest(store: Store, session_date: str | None = None) -> dict[str, Any]:
    if session_date:
        payload = read_canonical_operation_telemetry(store, session_date)
        return {"status": payload.get("status", "collecting"), "session_date": session_date, "denominators": payload.get("denominators"), "execution": payload.get("execution"), "exits": payload.get("exits"), "freshness": payload.get("freshness"), "content_hash": payload.get("content_hash")}
    try:
        events = [item for item in store.agent_events(event_type_prefix=EVENT_TYPE, limit=50000) if item.get("event_id", "").startswith(EVENT_ID_PREFIX)]
    finally:
        store.close_read_connection()
    if not events:
        return {"status": "collecting", "session_date": None, "denominators": None, "execution": None, "exits": None, "freshness": None, "canonical_events": 0}
    latest = sorted(events, key=lambda item: str(item.get("created_at") or ""))[-1]
    payload = read_canonical_operation_telemetry(store, str((latest.get("payload") or {}).get("session_date") or ""))
    return {"status": payload.get("status", "collecting"), "session_date": payload.get("session_date"), "denominators": payload.get("denominators"), "execution": payload.get("execution"), "exits": payload.get("exits"), "freshness": payload.get("freshness"), "canonical_events": len(events), "content_hash": payload.get("content_hash")}
