"""Exact BUY-lot provenance carrier for future protective exits.

The carrier is local decision metadata.  It is never passed to the broker and
it contains no outcome, P/L or future-looking field.  Missing provenance is
represented explicitly so a protective exit can remain fail-open while P-L51
stays unavailable.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "p-l51c.exit-lot-provenance.v1"
CARRIER_FIELD = "exit_lot_provenance"
UNAVAILABLE_ORDER_STATUSES = frozenset({"pending", "pending_new", "accepted", "rejected", "cancelled", "canceled"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _hash(payload: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(payload))
    body.pop("captured_at", None)
    body.pop("content_hash", None)
    encoded = json.dumps(_safe(body), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _captured_at(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _canonical_fills(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        fill_id = _text(item.get("fill_id") or item.get("fill_fragment_id"))
        quantity = _number(item.get("qty"))
        if fill_id is None or quantity is None or quantity <= 0:
            return None
        result.append({"fill_id": fill_id, "qty": quantity})
    return sorted(result, key=lambda item: item["fill_id"])


def _quality(reasons: list[str]) -> str:
    conflict_prefixes = ("duplicate", "allocation_exceeds", "qty_", "source_plan", "unknown_buy")
    return "conflict" if any(reason.startswith(conflict_prefixes) for reason in reasons) else "unavailable"


def _lot_identity(lot: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return _text(lot.get("position_identity")), _text(lot.get("lot_identity"))


def _source_plan_id(sell_plan: Mapping[str, Any]) -> str | None:
    payload = sell_plan.get("payload") or {}
    risk = payload.get("risk_decision") or {}
    checks = risk.get("checks") or {}
    return _text(checks.get("source_plan_id") or payload.get("source_plan_id") or sell_plan.get("source_plan_id"))


def build_exit_lot_provenance(
    sell_plan: Mapping[str, Any],
    buy_lots: list[Mapping[str, Any]],
    *,
    explicit_allocations: list[Mapping[str, Any]] | None = None,
    order_status: str = "planned",
    captured_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Build one deterministic carrier from exact BUY lots only.

    Without explicit allocations the builder accepts only one BUY lot whose
    exact plan is the SELL source plan.  It never chooses FIFO or a lot by
    symbol/date.  Multi-lot exits must provide ``explicit_allocations``.
    """

    payload = dict(sell_plan.get("payload") or {})
    sell_quantity = _number(payload.get("qty"))
    source_plan = _source_plan_id(sell_plan)
    lots = [dict(item) for item in buy_lots if isinstance(item, Mapping)]
    lots_by_order = {str(item.get("broker_order_id")): item for item in lots if _text(item.get("broker_order_id"))}
    reasons: list[str] = []
    raw_allocations = explicit_allocations

    if raw_allocations is None and source_plan is not None:
        matches = [
            item
            for item in lots
            if source_plan in {_text(item.get("source_plan_id")), _text(item.get("order_plan_id"))}
        ]
        if len(matches) == 1 and sell_quantity is not None:
            lot = matches[0]
            open_quantity = _number(lot.get("open_qty"))
            if open_quantity is not None and sell_quantity <= open_quantity + 1e-9:
                raw_allocations = [
                    {
                        "buy_broker_order_id": lot.get("broker_order_id"),
                        "buy_plan_id": lot.get("order_plan_id") or lot.get("source_plan_id"),
                        "allocated_qty": sell_quantity,
                        "available_open_qty_at_decision": open_quantity,
                        "canonical_buy_fill_ids": lot.get("canonical_buy_fill_ids"),
                        "position_identity": lot.get("position_identity"),
                        "lot_identity": lot.get("lot_identity"),
                    }
                ]
            elif open_quantity is None:
                reasons.append("open_qty_unavailable")
            else:
                reasons.append("allocation_exceeds_open_qty")
        elif len(matches) != 1:
            reasons.append("ambiguous_source_plan_lot")
    if raw_allocations is None:
        reasons.append("missing_allocations")
    elif not raw_allocations:
        reasons.append("missing_allocations")
    if sell_quantity is None or sell_quantity <= 0:
        reasons.append("qty_sell_unavailable")
    if str(order_status or "").lower() in UNAVAILABLE_ORDER_STATUSES:
        reasons.append("sell_order_not_filled")

    declared_plan_ids = {
        _text(item.get("buy_plan_id"))
        for item in raw_allocations or []
        if isinstance(item, Mapping) and _text(item.get("buy_plan_id"))
    }
    carrier_source_plan = source_plan if len(declared_plan_ids) <= 1 else None
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    allocated_total = 0.0
    for raw in raw_allocations or []:
        if not isinstance(raw, Mapping):
            reasons.append("incomplete_allocation")
            continue
        buy_order_id = _text(raw.get("buy_broker_order_id"))
        buy_plan_id = _text(raw.get("buy_plan_id"))
        allocated_quantity = _number(raw.get("allocated_qty"))
        available_quantity = _number(raw.get("available_open_qty_at_decision"))
        fills = _canonical_fills(raw.get("canonical_buy_fill_ids"))
        fill_key = ",".join(item["fill_id"] for item in fills or [])
        identity_key = (buy_order_id or "", buy_plan_id or "", fill_key)
        if identity_key in seen:
            reasons.append("duplicate_allocation")
        seen.add(identity_key)
        lot = lots_by_order.get(buy_order_id or "")
        if buy_order_id is None or buy_plan_id is None or allocated_quantity is None or available_quantity is None:
            reasons.append("incomplete_allocation")
            continue
        if lot is None:
            reasons.append("unknown_buy_broker_order_id")
            continue
        exact_buy_plan = _text(lot.get("order_plan_id") or lot.get("source_plan_id"))
        if exact_buy_plan != buy_plan_id:
            reasons.append("source_plan_or_buy_plan_mismatch")
        if available_quantity <= 0 or allocated_quantity <= 0 or allocated_quantity > available_quantity + 1e-9:
            reasons.append("allocation_exceeds_open_qty")
        if fills is not None and allocated_quantity > sum(item["qty"] for item in fills) + 1e-9:
            reasons.append("allocation_exceeds_canonical_fill_qty")
        if carrier_source_plan and carrier_source_plan not in {_text(lot.get("source_plan_id")), exact_buy_plan}:
            reasons.append("source_plan_id_mismatch")
        position_identity, lot_identity = _lot_identity(lot)
        normalized.append(
            {
                "buy_broker_order_id": buy_order_id,
                "buy_plan_id": buy_plan_id,
                "allocated_qty": allocated_quantity,
                "available_open_qty_at_decision": available_quantity,
                "canonical_buy_fill_ids": fills,
                "position_identity": _text(raw.get("position_identity")) or position_identity,
                "lot_identity": _text(raw.get("lot_identity")) or lot_identity,
            }
        )
        allocated_total += allocated_quantity

    normalized.sort(key=lambda item: (item["buy_broker_order_id"], item["buy_plan_id"], json.dumps(item["canonical_buy_fill_ids"], sort_keys=True)))
    if sell_quantity is not None and normalized and abs(allocated_total - sell_quantity) > 1e-9:
        reasons.append("qty_allocation_mismatch")
    if reasons and any(reason in {"incomplete_allocation", "unknown_buy_broker_order_id", "duplicate_allocation", "allocation_exceeds_open_qty", "qty_allocation_mismatch", "source_plan_id_mismatch", "source_plan_or_buy_plan_mismatch"} for reason in reasons):
        normalized = []

    position_ids = {item["position_identity"] for item in normalized if item.get("position_identity")}
    lot_ids = {item["lot_identity"] for item in normalized if item.get("lot_identity")}
    carrier: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sell_plan_id": _text(sell_plan.get("plan_id")),
        "source_plan_id": carrier_source_plan,
        "allocations": normalized or None,
        "position_identity": next(iter(position_ids)) if len(position_ids) == 1 else None,
        "lot_identity": next(iter(lot_ids)) if len(lot_ids) == 1 else None,
        "captured_at": _captured_at(captured_at),
        "content_hash": None,
        "provenance_quality": "exact" if not reasons else _quality(reasons),
        "reason_codes": list(dict.fromkeys(reasons)),
    }
    carrier["content_hash"] = _hash(carrier)
    return carrier


def carrier_to_trade_attribution(carrier: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project only complete carrier allocations into the P-L51 contract."""

    if carrier.get("provenance_quality") != "exact" or not isinstance(carrier.get("allocations"), list):
        return None
    projected: list[dict[str, Any]] = []
    for allocation in carrier["allocations"]:
        if not isinstance(allocation, Mapping):
            return None
        buy_order_id = _text(allocation.get("buy_broker_order_id"))
        buy_plan_id = _text(allocation.get("buy_plan_id"))
        lot_id = _text(allocation.get("lot_identity"))
        fills = allocation.get("canonical_buy_fill_ids")
        allocated_quantity = _number(allocation.get("allocated_qty"))
        if not buy_order_id or not buy_plan_id or not lot_id or not isinstance(fills, list) or not fills or allocated_quantity is None:
            return None
        fill_quantity = sum(_number(item.get("qty")) or 0.0 for item in fills if isinstance(item, Mapping))
        if not math.isclose(fill_quantity, allocated_quantity, rel_tol=0.0, abs_tol=1e-9):
            return None
        source_plan_id = _text(carrier.get("source_plan_id")) or buy_plan_id
        for fill in fills:
            if not isinstance(fill, Mapping):
                return None
            fill_id = _text(fill.get("fill_id"))
            quantity = _number(fill.get("qty"))
            if not fill_id or quantity is None or quantity <= 0:
                return None
            projected.append(
                {
                    "buy_broker_order_id": buy_order_id,
                    "buy_plan_id": buy_plan_id,
                    "entry_plan_id": buy_plan_id,
                    "source_plan_id": source_plan_id,
                    "lot_id": lot_id,
                    "fill_fragment_id": fill_id,
                    "qty": quantity,
                }
            )
    return {"source_plan_id": _text(carrier.get("source_plan_id")), "allocations": projected}


def carrier_content_hash(carrier: Mapping[str, Any]) -> str:
    return _hash(carrier)


def unavailable_exit_lot_provenance(
    sell_plan: Mapping[str, Any],
    reason: str,
    *,
    captured_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Create an unavailable carrier without invoking the normal builder."""

    carrier: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sell_plan_id": _text(sell_plan.get("plan_id")),
        "source_plan_id": _source_plan_id(sell_plan),
        "allocations": None,
        "position_identity": None,
        "lot_identity": None,
        "captured_at": _captured_at(captured_at),
        "content_hash": None,
        "provenance_quality": "unavailable",
        "reason_codes": [reason],
    }
    carrier["content_hash"] = _hash(carrier)
    return carrier
