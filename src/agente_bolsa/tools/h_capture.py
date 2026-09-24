"""Shadow-only prospective prediction and outcome capture.

This module builds immutable payloads for the existing ``agent_events`` ledger.
It never infers a prediction from score, confidence, ``captured_at`` or a
legacy outcome. A producer that does not expose an explicit prediction emits
an ``unavailable`` capture instead.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

H_CAPTURE_SCHEMA_VERSION = "p-l117n1.h-capture.v1"
PREDICTION_EVENT_TYPE = "h_capture_prediction"
OUTCOME_EVENT_TYPE = "h_capture_outcome"
CALENDAR_NAME = "XNYS"
SHADOW_MODE = "shadow"
AUTHORITY = "none"

_LINEAGE_FIELDS = (
    "cycle_id",
    "agent_run_id",
    "agent_name",
    "signal_id",
    "signal_capture_id",
    "signal_source_run_id",
    "candidate_id",
    "source_event_id",
    "source_event_content_hash",
)
_REQUIRED_LINEAGE_FIELDS = (
    "cycle_id",
    "agent_run_id",
    "signal_id",
    "signal_capture_id",
    "signal_source_run_id",
    "candidate_id",
    "source_event_id",
    "source_event_content_hash",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _utc_text(value: Any) -> tuple[str | None, str]:
    if value is None or value == "":
        return None, "unavailable"
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None, "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "invalid"
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "available"


def _finite_number(value: Any) -> tuple[float | None, str]:
    if value is None or isinstance(value, bool):
        return None, "unavailable"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, "invalid"
    if not math.isfinite(parsed):
        return None, "invalid"
    return parsed, "available"


def _probability(value: Any) -> tuple[float | None, str]:
    parsed, status = _finite_number(value)
    if parsed is None:
        return None, status
    if not 0.0 <= parsed <= 1.0:
        return None, "invalid"
    return parsed, "available"


def _positive_int(value: Any) -> tuple[int | None, str]:
    if value is None or value == "":
        return None, "unavailable"
    if type(value) is not int or value <= 0:
        return None, "invalid"
    return value, "available"


def _mapping_copy(value: Any) -> tuple[dict[str, Any] | None, str]:
    if value is None:
        return None, "unavailable"
    if not isinstance(value, Mapping):
        return None, "invalid"
    try:
        return json.loads(_canonical_json(dict(value))), "available"
    except (TypeError, ValueError):
        return None, "invalid"


def _normalise_lineage(lineage: Mapping[str, Any] | None) -> dict[str, str | None]:
    source = lineage if isinstance(lineage, Mapping) else {}
    return {field: _text(source.get(field)) for field in _LINEAGE_FIELDS}


def _lineage_status(lineage: Mapping[str, str | None]) -> tuple[str, list[str]]:
    missing = [field for field in _REQUIRED_LINEAGE_FIELDS if not lineage.get(field)]
    if not missing:
        return "complete", []
    present = any(lineage.get(field) for field in _REQUIRED_LINEAGE_FIELDS)
    return ("partial" if present else "unavailable"), missing


def _stable_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"content_hash", "capture_observed_at", "observed_at"}
    }


def _finish_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["content_hash"] = _hash_payload(_stable_event_payload(payload))
    return payload


def _stable_lineage(lineage: Mapping[str, str | None]) -> dict[str, str | None]:
    # Source content is evidence, not event identity. If it changes for the
    # same source event, Store must expose a conflict.
    return {key: value for key, value in lineage.items() if key != "source_event_content_hash"}


def _event_id(prefix: str, stable_key: Mapping[str, Any]) -> str:
    return f"{prefix}:{_hash_payload(stable_key)[:32]}"


def _prediction_stable_key(payload: Mapping[str, Any]) -> dict[str, Any]:
    lineage = payload.get("lineage")
    return {
        "schema_version": payload.get("schema_version") or H_CAPTURE_SCHEMA_VERSION,
        "event_type": PREDICTION_EVENT_TYPE,
        "producer_stage": _text(payload.get("producer_stage")) or "unavailable",
        "calendar_name": _text(payload.get("calendar_name")) or CALENDAR_NAME,
        "lineage": _stable_lineage(lineage if isinstance(lineage, Mapping) else {}),
        "prediction_at": payload.get("prediction_at"),
        "event_definition": payload.get("event_definition"),
        "horizon_sessions": payload.get("horizon_sessions"),
        "event_parameters": payload.get("event_parameters"),
    }


def _outcome_semantic_key(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version") or H_CAPTURE_SCHEMA_VERSION,
        "event_type": OUTCOME_EVENT_TYPE,
        "prediction_event_id": _text(payload.get("prediction_event_id")),
        "prediction_content_hash": _text(payload.get("prediction_content_hash")),
        "outcome_matured_at": payload.get("outcome_matured_at"),
        "outcome_maturity_session_date": payload.get("outcome_maturity_session_date"),
    }


def _outcome_observation_key(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_outcome_semantic_key(payload),
        "outcome_status": payload.get("outcome_status"),
        "outcome_value": payload.get("outcome_value"),
        "observed_data_hash": _text(payload.get("observed_data_hash")),
        "reason": payload.get("unavailable_reason")
        if payload.get("outcome_status") == "unavailable"
        else ("horizon_not_reached" if payload.get("outcome_status") == "collecting" else None),
    }


def validate_h_capture_event(
    row: Mapping[str, Any],
    *,
    expected_event_type: str,
) -> bool:
    """Validate the stored row identity and hash before it becomes evidence."""

    if not isinstance(row, Mapping):
        return False
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return False
    event_id = _text(row.get("event_id"))
    row_type = _text(row.get("event_type"))
    payload_type = _text(payload.get("event_type"))
    if (
        not event_id
        or row_type != expected_event_type
        or payload_type != expected_event_type
        or _text(payload.get("event_id")) != event_id
    ):
        return False
    if (
        payload.get("schema_version") != H_CAPTURE_SCHEMA_VERSION
        or payload.get("mode") != SHADOW_MODE
        or payload.get("authority") != AUTHORITY
        or payload.get("promotion_eligible") is not False
        or _text(payload.get("calendar_name")) != CALENDAR_NAME
    ):
        return False
    lineage = payload.get("lineage")
    if not isinstance(lineage, Mapping):
        return False
    row_cycle_id = _text(row.get("cycle_id"))
    payload_cycle_id = _text(payload.get("cycle_id"))
    if row_cycle_id != payload_cycle_id or payload_cycle_id != _text(lineage.get("cycle_id")):
        return False
    for field in _LINEAGE_FIELDS:
        if field in payload and _text(payload.get(field)) != _text(lineage.get(field)):
            return False
    if _text(payload.get("content_hash")) != _hash_payload(_stable_event_payload(payload)):
        return False
    if expected_event_type == PREDICTION_EVENT_TYPE:
        return event_id == _event_id(PREDICTION_EVENT_TYPE, _prediction_stable_key(payload))
    if expected_event_type == OUTCOME_EVENT_TYPE:
        semantic_id = _event_id("h_capture_outcome_identity", _outcome_semantic_key(payload))
        return (
            _text(payload.get("outcome_identity_id")) == semantic_id
            and event_id == _event_id(OUTCOME_EVENT_TYPE, _outcome_observation_key(payload))
        )
    return False


def build_prediction_capture(
    *,
    lineage: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None = None,
    capture_observed_at: Any = None,
    producer_stage: str,
    calendar_name: str = CALENDAR_NAME,
) -> dict[str, Any]:
    """Build one deterministic prediction capture without writing storage."""

    normalised_lineage = _normalise_lineage(lineage)
    lineage_status, missing_lineage = _lineage_status(normalised_lineage)
    raw = prediction if isinstance(prediction, Mapping) else None
    prediction_at, prediction_at_status = _utc_text(raw.get("prediction_at") if raw is not None else None)
    predicted_probability, probability_status = _probability(
        raw.get("predicted_probability") if raw is not None else None
    )
    event_definition = _text(raw.get("event_definition") if raw is not None else None)
    event_definition_status = "available" if event_definition else "unavailable"
    horizon_sessions, horizon_status = _positive_int(raw.get("horizon_sessions") if raw is not None else None)
    event_parameters, event_parameters_status = _mapping_copy(
        raw.get("event_parameters") if raw is not None else None
    )
    observed_at, observed_at_status = _utc_text(capture_observed_at)
    field_status = {
        "prediction_at": prediction_at_status,
        "predicted_probability": probability_status,
        "event_definition": event_definition_status,
        "horizon_sessions": horizon_status,
        "event_parameters": event_parameters_status,
        "capture_observed_at": observed_at_status,
        **{
            field: ("available" if value else "unavailable")
            for field, value in normalised_lineage.items()
        },
    }
    core_available = all(
        status == "available"
        for status in (
            prediction_at_status,
            probability_status,
            event_definition_status,
            horizon_status,
        )
    )
    prediction_status = "captured" if raw is not None and core_available else "unavailable"
    reason = None
    if prediction_status != "captured":
        if raw is None:
            reason = "prediction_not_generated"
        else:
            for field, status in (
                ("prediction_at", prediction_at_status),
                ("predicted_probability", probability_status),
                ("event_definition", event_definition_status),
                ("horizon_sessions", horizon_status),
            ):
                if status != "available":
                    reason = f"{field}_{status}"
                    break
    event_parameters_eligible = (
        event_definition != "close_above_reference_price"
        or event_parameters_status == "available"
    )
    denominator_eligible = (
        prediction_status == "captured"
        and lineage_status == "complete"
        and event_parameters_eligible
    )
    eligibility_reasons = [f"missing_lineage:{field}" for field in missing_lineage]
    if prediction_status != "captured":
        eligibility_reasons.append(f"prediction:{reason or 'unavailable'}")
    if not event_parameters_eligible:
        eligibility_reasons.append("event_parameters_unavailable")
    stable_key = _prediction_stable_key(
        {
            "schema_version": H_CAPTURE_SCHEMA_VERSION,
            "producer_stage": _text(producer_stage) or "unavailable",
            "calendar_name": _text(calendar_name) or CALENDAR_NAME,
            "lineage": normalised_lineage,
            "prediction_at": prediction_at,
            "event_definition": event_definition,
            "horizon_sessions": horizon_sessions,
            "event_parameters": event_parameters,
        }
    )
    event_id = _event_id(PREDICTION_EVENT_TYPE, stable_key)
    payload = {
        "schema_version": H_CAPTURE_SCHEMA_VERSION,
        "event_type": PREDICTION_EVENT_TYPE,
        "event_id": event_id,
        "producer_stage": _text(producer_stage) or "unavailable",
        "mode": SHADOW_MODE,
        "authority": AUTHORITY,
        "promotion_eligible": False,
        "calendar_name": _text(calendar_name) or CALENDAR_NAME,
        "lineage": normalised_lineage,
        **normalised_lineage,
        "capture_observed_at": observed_at,
        "prediction_at": prediction_at,
        "predicted_probability": predicted_probability,
        "event_definition": event_definition,
        "horizon_sessions": horizon_sessions,
        "event_parameters": event_parameters,
        "field_status": field_status,
        "prediction_status": prediction_status,
        "lineage_status": lineage_status,
        "denominator_eligible": denominator_eligible,
        "eligibility_status": "eligible" if denominator_eligible else "ineligible",
        "eligibility_reasons": sorted(set(eligibility_reasons)),
        "status": "captured" if prediction_status == "captured" else "unavailable",
        "unavailable_reason": reason,
    }
    return _finish_payload(payload)


def _as_utc(value: Any) -> datetime | None:
    text, status = _utc_text(value)
    if status != "available" or text is None:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _session_date(value: Any) -> str | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except (AttributeError, ValueError):
            pass
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _schedule_rows(market_calendar: Any, start: date, end: date) -> list[dict[str, Any]] | None:
    if market_calendar is None or str(getattr(market_calendar, "calendar_name", "")) != CALENDAR_NAME:
        return None
    try:
        schedule = market_calendar.session_schedule(start.isoformat(), end.isoformat())
    except Exception:  # noqa: BLE001 - observation must fail open.
        return None
    if schedule is None or getattr(schedule, "empty", False):
        return None
    rows: list[dict[str, Any]] = []
    for key, row in schedule.iterrows():
        opened = _as_utc(row.get("market_open"))
        closed = _as_utc(row.get("market_close"))
        session = _session_date(key)
        if session and opened and closed:
            rows.append({"session_date": session, "market_open": opened, "market_close": closed})
    return rows or None


def resolve_xnys_reference_session(
    prediction_at: Any,
    *,
    market_calendar: Any,
) -> dict[str, Any]:
    """Resolve session used as reference for a prediction timestamp."""

    parsed = _as_utc(prediction_at)
    if parsed is None:
        return {"status": "unavailable", "reason": "prediction_at_unavailable"}
    rows = _schedule_rows(
        market_calendar,
        parsed.date() - timedelta(days=7),
        parsed.date() + timedelta(days=21),
    )
    if not rows:
        return {"status": "unavailable", "reason": "xnys_schedule_unavailable"}
    for row in rows:
        if parsed < row["market_open"]:
            return {
                "status": "available",
                "reference_session_date": row["session_date"],
                "reference_market_open": row["market_open"].isoformat().replace("+00:00", "Z"),
                "reference_market_close": row["market_close"].isoformat().replace("+00:00", "Z"),
                "prediction_phase": "pre_open",
            }
        if parsed <= row["market_close"]:
            return {
                "status": "available",
                "reference_session_date": row["session_date"],
                "reference_market_open": row["market_open"].isoformat().replace("+00:00", "Z"),
                "reference_market_close": row["market_close"].isoformat().replace("+00:00", "Z"),
                "prediction_phase": "regular_session",
            }
    return {"status": "unavailable", "reason": "xnys_reference_session_not_found"}


def resolve_xnys_maturity(
    prediction_at: Any,
    horizon_sessions: Any,
    *,
    market_calendar: Any,
) -> dict[str, Any]:
    """Return exact UTC close of N sessions strictly after reference session."""

    horizon, horizon_status = _positive_int(horizon_sessions)
    if horizon is None:
        return {"status": "unavailable", "reason": f"horizon_sessions_{horizon_status}"}
    reference = resolve_xnys_reference_session(prediction_at, market_calendar=market_calendar)
    if reference.get("status") != "available":
        return reference
    reference_date = date.fromisoformat(str(reference["reference_session_date"]))
    rows = _schedule_rows(
        market_calendar,
        reference_date,
        reference_date + timedelta(days=max(30, horizon * 4 + 14)),
    )
    if not rows:
        return {"status": "unavailable", "reason": "xnys_schedule_unavailable"}
    posterior = [row for row in rows if row["session_date"] > reference["reference_session_date"]]
    if len(posterior) < horizon:
        return {"status": "unavailable", "reason": "xnys_horizon_session_not_found"}
    target = posterior[horizon - 1]
    return {
        **reference,
        "status": "available",
        "horizon_sessions": horizon,
        "outcome_maturity_session_date": target["session_date"],
        "outcome_matured_at": target["market_close"].isoformat().replace("+00:00", "Z"),
    }


def _close_by_session(price_frame: Any) -> dict[str, float]:
    if price_frame is None:
        return {}
    prices: dict[str, float] = {}
    if isinstance(price_frame, Mapping):
        for key, value in price_frame.items():
            session = _session_date(key)
            parsed, status = _finite_number(value)
            if session and status == "available" and parsed is not None:
                prices[session] = parsed
        return prices
    if not hasattr(price_frame, "iterrows"):
        return prices
    try:
        for key, row in price_frame.iterrows():
            session = _session_date(key)
            value = row.get("Close") if hasattr(row, "get") else None
            parsed, status = _finite_number(value)
            if session and status == "available" and parsed is not None:
                prices[session] = parsed
    except Exception:  # noqa: BLE001 - missing observation is explicit.
        return {}
    return prices


def _outcome_value(
    event_definition: str | None,
    event_parameters: Mapping[str, Any] | None,
    close: float,
) -> tuple[float | None, str | None]:
    if event_definition not in {"close_above_reference_price", "positive_forward_return"}:
        return None, "event_definition_unsupported"
    reference_price, status = _finite_number((event_parameters or {}).get("reference_price"))
    if status != "available" or reference_price is None or reference_price <= 0:
        return None, "reference_price_unavailable"
    return (1.0 if close > reference_price else 0.0), None


def build_outcome_capture(
    prediction_event: Mapping[str, Any],
    *,
    price_frame: Any,
    observed_at: Any,
    market_calendar: Any,
    outcome_source_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one append-only outcome observation for one prediction event."""

    prediction_id = _text(prediction_event.get("event_id"))
    prediction_status = str(prediction_event.get("prediction_status") or "unavailable")
    denominator_eligible = prediction_event.get("denominator_eligible") is True
    observation, observation_status = _utc_text(observed_at)
    maturity = (
        resolve_xnys_maturity(
            prediction_event.get("prediction_at"),
            prediction_event.get("horizon_sessions"),
            market_calendar=market_calendar,
        )
        if prediction_status == "captured" and denominator_eligible
        else {"status": "unavailable", "reason": "prediction_unavailable"}
    )
    outcome_matured_at = maturity.get("outcome_matured_at")
    maturity_session = maturity.get("outcome_maturity_session_date")
    status = "unavailable"
    reason = maturity.get("reason")
    outcome_value = None
    observed_data_hash = None
    if observation_status != "available":
        reason = "observed_at_unavailable"
    elif maturity.get("status") != "available":
        reason = reason or "maturity_unavailable"
    else:
        observation_dt = datetime.fromisoformat(str(observation).replace("Z", "+00:00"))
        maturity_dt = datetime.fromisoformat(str(outcome_matured_at).replace("Z", "+00:00"))
        if observation_dt < maturity_dt:
            status = "collecting"
            reason = "horizon_not_reached"
        else:
            prices = _close_by_session(price_frame)
            target_close = prices.get(str(maturity_session))
            if target_close is None:
                reason = "outcome_data_unavailable"
            else:
                outcome_value, reason = _outcome_value(
                    _text(prediction_event.get("event_definition")),
                    prediction_event.get("event_parameters")
                    if isinstance(prediction_event.get("event_parameters"), Mapping)
                    else None,
                    target_close,
                )
                if outcome_value is not None:
                    status = "matured"
                    observed_data_hash = _hash_payload(
                        {"session_date": maturity_session, "close": target_close}
                    )
                else:
                    reason = reason or "outcome_value_unavailable"
    source_ref = dict(outcome_source_ref) if isinstance(outcome_source_ref, Mapping) else None
    semantic_key = _outcome_semantic_key(
        {
            "schema_version": H_CAPTURE_SCHEMA_VERSION,
            "prediction_event_id": prediction_id,
            "prediction_content_hash": _text(prediction_event.get("content_hash")),
            "outcome_matured_at": outcome_matured_at,
            "outcome_maturity_session_date": maturity_session,
        }
    )
    outcome_identity_id = _event_id("h_capture_outcome_identity", semantic_key)
    observation_key = _outcome_observation_key(
        {
            **semantic_key,
            "outcome_status": status,
            "outcome_value": outcome_value,
            "observed_data_hash": observed_data_hash,
            "unavailable_reason": reason,
        }
    )
    event_id = _event_id(OUTCOME_EVENT_TYPE, observation_key)
    payload = {
        "schema_version": H_CAPTURE_SCHEMA_VERSION,
        "event_type": OUTCOME_EVENT_TYPE,
        "event_id": event_id,
        "prediction_event_id": prediction_id,
        "prediction_content_hash": _text(prediction_event.get("content_hash")),
        "outcome_identity_id": outcome_identity_id,
        "observation_id": event_id,
        "mode": SHADOW_MODE,
        "authority": AUTHORITY,
        "promotion_eligible": False,
        "calendar_name": _text(prediction_event.get("calendar_name")) or CALENDAR_NAME,
        "lineage": prediction_event.get("lineage")
        if isinstance(prediction_event.get("lineage"), Mapping)
        else {},
        "cycle_id": prediction_event.get("cycle_id"),
        "agent_run_id": prediction_event.get("agent_run_id"),
        "signal_id": prediction_event.get("signal_id"),
        "signal_capture_id": prediction_event.get("signal_capture_id"),
        "candidate_id": prediction_event.get("candidate_id"),
        "source_event_id": prediction_event.get("source_event_id"),
        "event_definition": prediction_event.get("event_definition"),
        "horizon_sessions": prediction_event.get("horizon_sessions"),
        "reference_session_date": maturity.get("reference_session_date"),
        "prediction_at": prediction_event.get("prediction_at"),
        "outcome_maturity_session_date": maturity_session,
        "outcome_matured_at": outcome_matured_at,
        "observed_at": observation,
        "outcome_status": status,
        "outcome_value": outcome_value,
        "outcome_source_ref": source_ref,
        "observed_data_hash": observed_data_hash,
        "field_status": {
            "prediction_at": "available" if prediction_event.get("prediction_at") else "unavailable",
            "outcome_matured_at": "available" if outcome_matured_at else "unavailable",
            "observed_at": observation_status,
            "outcome_value": "available" if outcome_value is not None else "unavailable",
        },
        "status": status,
        "unavailable_reason": reason if status == "unavailable" else None,
        "maturity_status": maturity.get("status"),
        "prediction_status": prediction_status,
        "denominator_eligible": denominator_eligible and status == "matured",
    }
    return _finish_payload(payload)


def persist_h_capture_event(store: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist through existing append-only Store semantics."""

    event = dict(payload)
    event_id = _text(event.get("event_id"))
    event_type = _text(event.get("event_type"))
    if not event_id or not event_type:
        raise ValueError("h_capture_event_identity_required")
    if event_type in {PREDICTION_EVENT_TYPE, OUTCOME_EVENT_TYPE} and not validate_h_capture_event(
        {
            "event_id": event_id,
            "event_type": event_type,
            "cycle_id": _text(event.get("cycle_id")),
            "payload": event,
        },
        expected_event_type=event_type,
    ):
        raise ValueError("invalid_h_capture_event")
    return store.record_append_only_event(
        event_id=event_id,
        event_type=event_type,
        cycle_id=_text(event.get("cycle_id")),
        payload=event,
        lock_timeout_seconds=0.0,
        idempotent_on_content_hash=True,
    )
