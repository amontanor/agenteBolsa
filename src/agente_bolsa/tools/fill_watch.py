"""Bounded, fail-open intraday watcher for broker-confirmed fills."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .fill_provider import TERMINAL_STATUSES, OrderStatusProvider, build_order_status_provider
from .telegram_trade_notifications import publish_trade_fill_notifications

WATCH_STATE_PREFIX = "trade_fill_watch:order:"
WATCH_LAST_RUN_KEY = "trade_fill_watch:last_run"


def _utc_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _backoff_state(settings: Any, previous: dict[str, Any] | None, now: datetime, reason: str) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    attempt = int(previous.get("attempt") or 0) + 1
    base = max(1, int(getattr(settings, "trade_fill_watch_backoff_seconds", 30)))
    maximum = max(base, int(getattr(settings, "trade_fill_watch_max_backoff_seconds", 300)))
    delay = min(maximum, base * (2 ** max(0, attempt - 1)))
    return {
        "status": "provider_unavailable",
        "attempt": attempt,
        "reason": reason[:240],
        "last_attempt_at": now.isoformat(),
        "next_attempt_at": (now + timedelta(seconds=delay)).isoformat(),
        "backoff_seconds": delay,
    }


def _terminal_state(status: str, now: datetime) -> dict[str, Any]:
    return {
        "status": status,
        "attempt": 0,
        "last_attempt_at": now.isoformat(),
        "next_attempt_at": None,
    }


def run_trade_fill_watch(
    settings: Any,
    store: Any,
    *,
    provider: OrderStatusProvider | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Poll local non-terminal orders and publish only committed fills.

    The provider call happens outside the local write transaction.  A fill is
    first committed to ``broker_orders`` and only then reaches the Telegram
    fail-open publisher.
    """

    started = _utc_now(now)
    result: dict[str, Any] = {
        "status": "disabled" if not bool(getattr(settings, "trade_fill_watch_enabled", False)) else "completed",
        "pending_checked": 0,
        "filled_transitions": 0,
        "sent": 0,
        "failed": 0,
        "skipped_backoff": 0,
        "provider_unavailable": 0,
        "errors": [],
    }
    if result["status"] == "disabled":
        result["duration_seconds"] = 0.0
        return result

    started_clock = datetime.now(timezone.utc)
    limit = max(1, int(getattr(settings, "trade_fill_watch_max_pending_per_run", 25)))
    pending = store.pending_broker_orders(limit=limit)
    result["pending_checked"] = len(pending)
    retry_changes = store.retryable_trade_fill_changes(limit=limit)
    states = store.runtime_values_by_prefix(WATCH_STATE_PREFIX)
    updates: dict[str, Any] = {}
    if retry_changes:
        retry_result = publish_trade_fill_notifications(settings, store, retry_changes)
        result["sent"] += int(retry_result.get("sent") or 0)
        retry_errors = retry_result.get("errors") or []
        result["failed"] += len(retry_errors)
        result["errors"].extend(retry_errors)
    if not pending:
        result["duration_seconds"] = round((datetime.now(timezone.utc) - started_clock).total_seconds(), 3)
        updates[WATCH_LAST_RUN_KEY] = result | {"at": started.isoformat()}
        store.set_runtime_values(updates)
        return result
    try:
        status_provider = provider or build_order_status_provider(settings)
    except Exception as exc:  # noqa: BLE001 - watcher is fail-open.
        result["status"] = "provider_unavailable"
        result["provider_unavailable"] = len(pending)
        result["errors"].append({"stage": "provider_build", "reason": type(exc).__name__})
        result["duration_seconds"] = round((datetime.now(timezone.utc) - started_clock).total_seconds(), 3)
        for row in pending:
            key = f"{WATCH_STATE_PREFIX}{row['broker_order_id']}"
            updates[key] = _backoff_state(settings, states.get(key), started, str(exc))
        updates[WATCH_LAST_RUN_KEY] = result | {"at": started.isoformat()}
        store.set_runtime_values(updates)
        return result

    for row in pending:
        order_id = str(row["broker_order_id"])
        state_key = f"{WATCH_STATE_PREFIX}{order_id}"
        previous = states.get(state_key) if isinstance(states.get(state_key), dict) else {}
        next_attempt = _parse_time(previous.get("next_attempt_at"))
        if next_attempt is not None and next_attempt > started:
            result["skipped_backoff"] += 1
            continue
        client_order_id = str(((row.get("payload") or {}).get("broker_order") or {}).get("client_order_id") or "").strip() or None
        try:
            snapshot = status_provider.snapshot_order(
                order_id,
                client_order_id=client_order_id,
                timeout_seconds=int(getattr(settings, "trade_fill_watch_request_timeout_seconds", 5)),
            )
            snapshot_dict = snapshot.as_dict() if hasattr(snapshot, "as_dict") else dict(snapshot)
            remote_status = str(snapshot_dict.get("status") or "").strip().lower()
            if not remote_status:
                raise ValueError("provider_status_missing")
            transition = store.apply_broker_order_snapshot(order_id, snapshot_dict, observed_at=started.isoformat())
        except Exception as exc:  # noqa: BLE001 - one provider failure cannot block others.
            result["provider_unavailable"] += 1
            result["errors"].append({"broker_order_id": order_id, "reason": type(exc).__name__})
            updates[state_key] = _backoff_state(settings, previous, started, str(exc))
            continue

        if transition.get("status") == "transitioned" and transition.get("new") == "filled":
            result["filled_transitions"] += 1
            notification = publish_trade_fill_notifications(settings, store, [transition])
            result["sent"] += int(notification.get("sent") or 0)
            errors = notification.get("errors") or []
            result["failed"] += len(errors)
            if errors:
                result["errors"].extend(errors)
        if remote_status in TERMINAL_STATUSES:
            updates[state_key] = _terminal_state(remote_status, started)
        else:
            updates[state_key] = {
                "status": remote_status,
                "attempt": 0,
                "last_attempt_at": started.isoformat(),
                "next_attempt_at": None,
            }

    result["duration_seconds"] = round((datetime.now(timezone.utc) - started_clock).total_seconds(), 3)
    updates[WATCH_LAST_RUN_KEY] = result | {"at": started.isoformat()}
    store.set_runtime_values(updates)
    return result
