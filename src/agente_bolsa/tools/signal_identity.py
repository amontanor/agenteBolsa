"""Canonical signal and immutable capture identity helpers.

The producer owns both the logical ``signal_id`` and the immutable
``signal_capture_id``. Consumers carry these values verbatim and never
reconstruct them from a symbol, date, ranking or the latest row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


def _slug(value: Any) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").upper()).strip("_")


def _date_text(value: Any) -> str:
    text = str(value or "")
    return text[:10] if text else datetime.now(timezone.utc).date().isoformat()


def canonical_signal_id(source: str, candidate: Mapping[str, Any]) -> str:
    """Build the stable ID only at signal production time."""
    return ":".join(
        (
            str(source),
            _date_text(
                candidate.get("signal_date")
                or candidate.get("last_date")
                or (candidate.get("technical_state") or {}).get("last_date")
            ),
            _slug(candidate.get("signal_strategy_name") or candidate.get("strategy_name") or "unknown"),
            _slug(candidate.get("symbol")),
        )
    )


def canonical_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Read producer identity without manufacturing a replacement."""
    return {
        "signal_id": str(candidate.get("signal_id") or "").strip() or None,
        "signal_capture_id": str(candidate.get("signal_capture_id") or "").strip() or None,
        "signal_source_run_id": str(candidate.get("signal_source_run_id") or "").strip() or None,
        "signal_date": str(
            candidate.get("signal_date")
            or candidate.get("last_date")
            or (candidate.get("technical_state") or {}).get("last_date")
            or ""
        ).strip()
        or None,
        "symbol": str(candidate.get("symbol") or "").upper().strip() or None,
        "signal_strategy_name": str(candidate.get("signal_strategy_name") or candidate.get("strategy_name") or "").strip() or None,
        "signal_strategy_version": str(candidate.get("signal_strategy_version") or candidate.get("strategy_version") or "").strip() or None,
    }


SIGNAL_CAPTURE_SCHEMA_VERSION = "p-l37b.signal-capture.v1"
SIGNAL_IDENTITY_SCHEMA_VERSION = SIGNAL_CAPTURE_SCHEMA_VERSION


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _capture_hash_payload(
    *,
    signal_id: str,
    signal_source_run_id: str,
    signal_date: str,
    symbol: str,
    strategy_name: str,
    strategy_version: str,
) -> dict[str, str]:
    return {
        "schema_version": SIGNAL_CAPTURE_SCHEMA_VERSION,
        "signal_id": signal_id,
        "signal_source_run_id": signal_source_run_id,
        "signal_date": signal_date,
        "symbol": symbol,
        "strategy_name": strategy_name,
        "strategy_version": strategy_version,
    }


def signal_capture_id_for_values(
    *,
    signal_id: Any,
    signal_source_run_id: Any,
    signal_date: Any,
    symbol: Any,
    strategy_name: Any,
    strategy_version: Any,
) -> str | None:
    """Return a deterministic capture ID, or ``None`` for incomplete identity."""

    values = {
        "signal_id": str(signal_id or "").strip(),
        "signal_source_run_id": str(signal_source_run_id or "").strip(),
        "signal_date": str(signal_date or "").strip()[:10],
        "symbol": str(symbol or "").upper().strip(),
        "strategy_name": str(strategy_name or "").strip(),
        "strategy_version": str(strategy_version or "").strip(),
    }
    if not all(values.values()):
        return None
    payload = _capture_hash_payload(**values)
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"capture_{digest[:32]}"


def build_signal_capture(
    candidate: Mapping[str, Any],
    *,
    source_run_id: Any,
    captured_at: Any = None,
) -> dict[str, Any] | None:
    """Build the producer-owned capture payload.

    ``captured_at`` is descriptive only and deliberately excluded from the
    hash and ID. Missing or ambiguous identity returns ``None`` instead of
    inventing an ``UNKNOWN`` value.
    """

    identity = canonical_identity(candidate)
    source = identity["signal_source_run_id"] or str(source_run_id or "").strip() or None
    # A producer without a concrete capture date has incomplete identity.  Do
    # not let the general legacy date normalizer manufacture a capture for it.
    signal_date = identity["signal_date"]
    signal_capture_id = signal_capture_id_for_values(
        signal_id=identity["signal_id"],
        signal_source_run_id=source,
        signal_date=signal_date,
        symbol=identity["symbol"],
        strategy_name=identity["signal_strategy_name"],
        strategy_version=identity["signal_strategy_version"],
    )
    if not signal_capture_id or not source or not signal_date:
        return None
    payload = _capture_hash_payload(
        signal_id=str(identity["signal_id"]),
        signal_source_run_id=str(source),
        signal_date=str(signal_date)[:10],
        symbol=str(identity["symbol"]),
        strategy_name=str(identity["signal_strategy_name"]),
        strategy_version=str(identity["signal_strategy_version"]),
    )
    content_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:32]
    return {
        "signal_capture_id": signal_capture_id,
        **payload,
        "captured_at": str(captured_at or datetime.now(timezone.utc).isoformat()),
        "content_hash": content_hash,
    }


def signal_identity_block(capture: Mapping[str, Any]) -> dict[str, Any]:
    """Create the versioned feature block for one new capture."""

    capture_id = str(capture.get("signal_capture_id") or "").strip()
    return {
        "schema_version": SIGNAL_IDENTITY_SCHEMA_VERSION,
        "latest_signal_capture_id": capture_id or None,
        "captures": {capture_id: json.loads(json.dumps(dict(capture), default=str))} if capture_id else {},
        "conflicts": [],
    }


def merge_signal_identity_blocks(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """Merge captures append-only and report ``attached|idempotent|conflict``."""

    current = json.loads(json.dumps(dict(existing or {}), default=str))
    current.setdefault("schema_version", SIGNAL_IDENTITY_SCHEMA_VERSION)
    captures = current.setdefault("captures", {})
    if not isinstance(captures, dict):
        captures = {}
        current["captures"] = captures
    current.setdefault("conflicts", [])
    incoming_captures = dict((incoming or {}).get("captures") or {})
    status = "idempotent"
    for capture_id, raw_capture in incoming_captures.items():
        if not capture_id or not isinstance(raw_capture, Mapping):
            continue
        candidate_capture = json.loads(json.dumps(dict(raw_capture), default=str))
        existing_capture = captures.get(capture_id)
        if existing_capture is None:
            captures[capture_id] = candidate_capture
            status = "attached"
            continue
        if existing_capture.get("content_hash") == candidate_capture.get("content_hash"):
            continue
        conflict = {
            "signal_capture_id": capture_id,
            "existing_content_hash": existing_capture.get("content_hash"),
            "incoming_content_hash": candidate_capture.get("content_hash"),
        }
        if conflict not in current["conflicts"]:
            current["conflicts"].append(conflict)
        status = "conflict"
    latest = str((incoming or {}).get("latest_signal_capture_id") or "").strip()
    if latest and latest in captures and status != "conflict":
        current["latest_signal_capture_id"] = latest
    elif not current.get("latest_signal_capture_id") and captures:
        current["latest_signal_capture_id"] = next(reversed(captures))
    return current, status


def resolve_signal_capture(
    store: Any,
    signal_capture_id: str,
    *,
    signal_id: str | None = None,
) -> dict[str, Any]:
    """Resolve one capture by exact ID without symbol/date fallback."""

    capture_id = str(signal_capture_id or "").strip()
    if not capture_id:
        return {"status": "missing", "signal_capture_id": None}
    rows = list(store.signal_outcomes_containing_capture(capture_id))
    if not rows:
        if signal_id and store.signal_outcome_by_id(str(signal_id)):
            return {"status": "legacy_without_capture_history", "signal_capture_id": capture_id, "signal_id": signal_id}
        return {"status": "missing", "signal_capture_id": capture_id}
    matches: list[dict[str, Any]] = []
    for row in rows:
        features = dict(row.get("features") or {})
        block = dict(features.get("signal_identity") or {})
        capture = dict((block.get("captures") or {}).get(capture_id) or {})
        if not capture:
            continue
        expected_id = signal_capture_id_for_values(
            signal_id=capture.get("signal_id"),
            signal_source_run_id=capture.get("signal_source_run_id"),
            signal_date=capture.get("signal_date"),
            symbol=capture.get("symbol"),
            strategy_name=capture.get("strategy_name"),
            strategy_version=capture.get("strategy_version"),
        )
        if expected_id != capture_id:
            return {"status": "conflict", "signal_capture_id": capture_id, "row": row, "capture": capture}
        expected_hash = hashlib.sha256(
            _canonical_json(
                _capture_hash_payload(
                    signal_id=str(capture.get("signal_id") or ""),
                    signal_source_run_id=str(capture.get("signal_source_run_id") or ""),
                    signal_date=str(capture.get("signal_date") or "")[:10],
                    symbol=str(capture.get("symbol") or "").upper(),
                    strategy_name=str(capture.get("strategy_name") or ""),
                    strategy_version=str(capture.get("strategy_version") or ""),
                )
            ).encode("utf-8")
        ).hexdigest()[:32]
        row_features = dict(row.get("features") or {})
        row_strategy = row_features.get("signal_strategy_name") or row_features.get("strategy_name")
        row_version = row_features.get("signal_strategy_version") or row_features.get("strategy_version")
        if (
            capture.get("content_hash") != expected_hash
            or capture.get("signal_id") != row.get("signal_id")
            or capture.get("signal_date") != row.get("signal_date")
            or str(capture.get("symbol") or "").upper() != str(row.get("symbol") or "").upper()
            or capture.get("strategy_name") != row_strategy
            or capture.get("strategy_version") != row_version
        ):
            return {"status": "conflict", "signal_capture_id": capture_id, "row": row, "capture": capture}
        matches.append({"row": row, "capture": capture})
    if not matches:
        return {"status": "missing", "signal_capture_id": capture_id}
    if len({item["row"].get("signal_id") for item in matches}) != 1:
        return {"status": "ambiguous", "signal_capture_id": capture_id, "matches": matches}
    match = matches[0]
    return {
        "status": "exact_match",
        "signal_capture_id": capture_id,
        "signal_id": match["row"].get("signal_id"),
        "signal_source_run_id": match["capture"].get("signal_source_run_id"),
        "capture": match["capture"],
        "row": match["row"],
    }
