"""Append-only ledger of external cash flows (deposits/withdrawals).

P-L136: the P-L52B EOD contract accepts an `external_flow_ledger` but no
producer ever supplied one, so EOD stayed `unavailable`. This module is
that producer: validated flows persisted via the append-only event
contract (same idempotent/conflict semantics), readable by window. It
never touches trading, risk, orders or configuration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "p-l136.cash-flow-ledger.v1"
EVENT_TYPE = "cash_flow"
KINDS = {"deposit": 1.0, "withdrawal": -1.0}


def _parse_moment(value: Any) -> str | None:
    """Normalize to an aware UTC ISO instant; None when ambiguous."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(timezone.utc).isoformat()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_cash_flow(
    store: Any,
    *,
    flow_id: str,
    kind: str,
    amount: float,
    currency: str = "USD",
    occurred_at: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Validate and append a cash flow; invalid input is rejected unwritten."""

    normalized_id = str(flow_id or "").strip()
    normalized_kind = str(kind or "").strip().lower()
    normalized_currency = str(currency or "").strip().upper()
    moment = _parse_moment(occurred_at)
    if not normalized_id:
        return {"status": "rejected", "reason": "flow_id_required"}
    if normalized_kind not in KINDS:
        return {"status": "rejected", "reason": "kind_must_be_deposit_or_withdrawal"}
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not (float(amount) > 0):
        return {"status": "rejected", "reason": "amount_must_be_positive"}
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        return {"status": "rejected", "reason": "currency_must_be_iso3"}
    if moment is None:
        return {"status": "rejected", "reason": "occurred_at_must_be_aware_iso"}
    signed = round(float(amount) * KINDS[normalized_kind], 10)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "flow_id": normalized_id,
        "kind": normalized_kind,
        "amount": signed,
        "currency": normalized_currency,
        "occurred_at": moment,
        "note": str(note or "").strip() or None,
    }
    payload["content_hash"] = _content_hash(payload)
    return store.record_append_only_event(
        event_id=f"{EVENT_TYPE}:{normalized_id}",
        event_type=EVENT_TYPE,
        cycle_id=None,
        payload=payload,
    )


def read_cash_flow_ledger(
    store: Any,
    *,
    start: str | None = None,
    end: str | None = None,
    currency: str = "USD",
    limit: int = 5000,
) -> dict[str, Any]:
    """Read flows in [start, end), in the EOD producer's row shape."""

    wanted = str(currency or "").strip().upper() or "USD"
    events = store.agent_events(event_type_prefix=EVENT_TYPE, limit=limit)
    flows: list[dict[str, Any]] = []
    conflicts = 0
    for event in events:
        if str(event.get("event_type") or "").endswith("_conflict"):
            conflicts += 1
            continue
        payload = event.get("payload") or {}
        if payload.get("schema_version") != SCHEMA_VERSION:
            continue
        if str(payload.get("currency") or "").upper() != wanted:
            continue
        occurred = str(payload.get("occurred_at") or "")
        if start is not None and occurred < str(start):
            continue
        if end is not None and occurred >= str(end):
            continue
        flows.append(
            {
                "flow_id": payload.get("flow_id"),
                "amount": payload.get("amount"),
                "currency": wanted,
                "occurred_at": occurred,
                "kind": payload.get("kind"),
            }
        )
    flows.sort(key=lambda item: (str(item["occurred_at"]), str(item["flow_id"])))
    total = round(sum(float(item["amount"]) for item in flows), 10) if flows else 0.0
    return {
        "flows": flows,
        "count": len(flows),
        "total": total,
        "currency": wanted,
        "conflicts": conflicts,
        "coverage": {"status": "exact", "count": len(flows)},
    }
