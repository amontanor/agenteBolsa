"""Dashboard loading: persistent snapshot first, independent publication.

Design
------
- Hydration reads the last valid snapshot from SQLite before any remote request.
- ``account``/``positions``/``orders`` share one remote read (the broker returns
  them together) but keep independent state, timestamps and storage rows.
- ``fills`` and ``curve`` are independent: a failure in one keeps the previous
  value and never blocks publishing the account.
- Remote work is deduplicated per ``(identity, resource)`` in a process-wide
  registry with a bounded global worker pool, so a new browser tab reuses an
  in-flight read instead of issuing an identical download.
- Every resource has its own download cadence, which depends on whether the
  market is open (``MarketCalendar``, local and network-free). The UI poll
  interval is separate and never decides when a download happens.
- One refresh has a logical budget. Exceeding it marks the resource degraded,
  abandons that generation (a late result is discarded, never published) and
  schedules a retry with growing, jittered waits. Capacity stays bounded, so no
  thread is accumulated while the old request is still running.
- Every completed resource is published immediately, including refreshes.

Presentation-only: nothing here creates, blocks, delays or changes orders.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any

from .dashboard_broker import DashboardBroker
from .dashboard_fills import (
    FILLS_SYNC_MAX_PAGES,
    FillRepository,
    fetch_for_client,
    merge_fill_lists,
    sync_recent,
)
from .dashboard_snapshot import (
    RESOURCE_ACCOUNT,
    RESOURCE_CURVE,
    RESOURCE_FILLS,
    RESOURCE_INTRADAY,
    RESOURCE_ORDERS,
    RESOURCE_POSITIONS,
    RESOURCES,
    ResourceSnapshot,
    SnapshotRepository,
    environment_fingerprint,
    utc_now_iso,
)
from .dashboard_snapshot import (
    identity_key as build_identity_key,
)
from .market_calendar import MarketCalendar
from .models import OrderSnapshot, PortfolioSnapshot, PositionSnapshot, new_id
from .tools.broker import BrokerClientFactory
from .tools.trade_history import build_trade_history

LOGGER = logging.getLogger("agente_bolsa.dashboard")

REMOTE_PORTFOLIO = "portfolio"
REMOTE_FILLS = "fills"
REMOTE_CURVE = "curve"
REMOTE_INTRADAY = "intraday"
REMOTE_RESOURCES = (REMOTE_PORTFOLIO, REMOTE_FILLS, REMOTE_CURVE, REMOTE_INTRADAY)

REMOTE_TO_RESOURCES: dict[str, tuple[str, ...]] = {
    REMOTE_PORTFOLIO: (RESOURCE_ACCOUNT, RESOURCE_POSITIONS, RESOURCE_ORDERS),
    REMOTE_FILLS: (RESOURCE_FILLS,),
    REMOTE_CURVE: (RESOURCE_CURVE,),
    REMOTE_INTRADAY: (RESOURCE_INTRADAY,),
}

# A resource older than this is shown as stale. This is a presentation
# threshold, not a trading, risk or execution parameter.
RESOURCE_FRESH_SECONDS = 60.0

# Download cadence per remote resource, in seconds, as
# ``(market open, market closed)``. This is the minimum time between two
# downloads of the same resource; the UI poll interval does not change it.
# - account/positions/orders: 30 s open, 5 min closed.
# - fills: 2 min open (2-5 min band), 5 min closed.
# - curve: 15 min both, during the session and after the close.
REMOTE_CADENCE_SECONDS: dict[str, tuple[float, float]] = {
    REMOTE_PORTFOLIO: (30.0, 300.0),
    REMOTE_FILLS: (120.0, 300.0),
    REMOTE_CURVE: (900.0, 900.0),
    REMOTE_INTRADAY: (900.0, 900.0),
}

# Logical budget for one remote refresh. The transport sets its own timeouts
# where the installed SDK allows it; this budget is what the loader promises to
# the UI. Exceeding it publishes a degraded state and abandons the generation.
UPDATE_BUDGET_SECONDS = 10.0

# Retry wait after a failure or an exhausted budget: exponential with a cap and
# a deterministic, injectable jitter (default: up to 50 % of the base wait).
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 120.0
RETRY_JITTER_RATIO = 0.5

# How long the market-open answer is reused. It is never cached for the whole
# session: the calendar object is reused, the open/closed boolean is not.
MARKET_STATUS_TTL_SECONDS = 5.0

# Explicit row ceiling for the legacy fills read. ``alpaca_trade_activities``
# clamps the page size to 100, so this is the requested ceiling of the fallback
# read, not a guarantee of full historical coverage. The synchronized path uses
# a bounded number of pages and records explicit coverage instead.
FILLS_ROW_LIMIT = 1000

# Global ceiling of concurrent remote reads for the whole process.
MAX_REMOTE_WORKERS = 3

_INFLIGHT_LOCK = Lock()
_INFLIGHT: dict[tuple[str, str], Future] = {}
_GENERATION: dict[tuple[str, str], int] = {}
_EXECUTOR_LOCK = Lock()
_EXECUTOR: ThreadPoolExecutor | None = None

_CALENDAR_LOCK = Lock()
_CALENDARS: dict[str, MarketCalendar] = {}
_MARKET_STATUS: dict[str, tuple[float, bool]] = {}


def _default_jitter(base_seconds: float) -> float:
    return random.uniform(0.0, max(0.0, base_seconds) * RETRY_JITTER_RATIO)


def market_is_open(settings: Any, clock: Callable[[], float] | None = None) -> bool:
    """Market open/closed from the local exchange calendar. Never uses network."""
    name = str(getattr(settings, "market_calendar", None) or "XNYS")
    reference = clock or perf_counter
    now = reference()
    with _CALENDAR_LOCK:
        cached = _MARKET_STATUS.get(name)
        if cached is not None and 0.0 <= now - cached[0] <= MARKET_STATUS_TTL_SECONDS:
            return cached[1]
        calendar = _CALENDARS.get(name)
        if calendar is None:
            calendar = MarketCalendar(calendar_name=name)
            _CALENDARS[name] = calendar
    try:
        is_open = bool(calendar.status().is_open)
    except Exception as exc:  # noqa: BLE001 - unknown market state must not break the UI.
        LOGGER.debug("dashboard_market_state_failed error=%s", type(exc).__name__)
        return False
    with _CALENDAR_LOCK:
        _MARKET_STATUS[name] = (now, is_open)
    return is_open


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=MAX_REMOTE_WORKERS,
                thread_name_prefix="dashboard-remote",
            )
        return _EXECUTOR


def active_remote_workers() -> int:
    with _INFLIGHT_LOCK:
        return sum(1 for future in _INFLIGHT.values() if not future.done())


def inflight_keys() -> list[tuple[str, str]]:
    with _INFLIGHT_LOCK:
        return [key for key, future in _INFLIGHT.items() if not future.done()]


def reset_remote_state() -> None:
    """Drop the in-flight registry. Used by tests; never cancels running work."""
    with _INFLIGHT_LOCK:
        _INFLIGHT.clear()
        _GENERATION.clear()


def inflight_generation(identity_key: str, resource: str) -> int | None:
    """Generation of the read currently registered for ``(identity, resource)``."""
    with _INFLIGHT_LOCK:
        return _GENERATION.get((str(identity_key), str(resource)))


def submit_remote(
    identity_key: str,
    resource: str,
    callback: Callable[[], Any],
) -> tuple[Future | None, bool]:
    """Submit one remote read, reusing an identical in-flight one.

    Returns ``(future, created)`` where ``created`` is False when an existing
    read for the same account/resource was reused. Each newly created read gets
    the next generation of its ``(identity, resource)`` key, so a result from an
    older generation can be recognised and discarded when it arrives late.
    """
    key = (str(identity_key), str(resource))
    with _INFLIGHT_LOCK:
        existing = _INFLIGHT.get(key)
        if existing is not None and not existing.done():
            return existing, False
        # Bound both running calls and queued work across all sessions/accounts.
        completed = [item for item, work in _INFLIGHT.items() if work.done()]
        for item in completed:
            _INFLIGHT.pop(item, None)
        if len(_INFLIGHT) >= len(REMOTE_RESOURCES):
            return None, False
        generation = _GENERATION.get(key, 0) + 1
        _GENERATION[key] = generation
        future: Future = Future()
        _INFLIGHT[key] = future
    try:
        _executor().submit(_execute_remote, key, future, callback, generation)
    except BaseException:
        with _INFLIGHT_LOCK:
            if _INFLIGHT.get(key) is future:
                _INFLIGHT.pop(key, None)
        raise
    return future, True


def _execute_remote(
    key: tuple[str, str],
    future: Future,
    callback: Callable[[], Any],
    generation: int,
) -> None:
    if not future.set_running_or_notify_cancel():
        with _INFLIGHT_LOCK:
            if _INFLIGHT.get(key) is future:
                _INFLIGHT.pop(key, None)
        return
    started = perf_counter()
    try:
        value = callback()
    except BaseException as exc:  # noqa: BLE001 - reported as data, never raised here.
        error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
        future.set_exception(error)
    else:
        future.set_result(
            {
                "value": value,
                "observed_at": utc_now_iso(),
                "seconds": perf_counter() - started,
                "generation": int(generation),
            }
        )
    return


def _utc_age_seconds(observed_at: str, now: datetime | None = None) -> float | None:
    text = str(observed_at or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (reference - parsed.astimezone(timezone.utc)).total_seconds())


def _portfolio_from_payloads(
    account: Mapping[str, Any] | None,
    positions: list[Mapping[str, Any]] | None,
    orders: list[Mapping[str, Any]] | None,
) -> PortfolioSnapshot | None:
    """Assemble a ``PortfolioSnapshot`` from the stored ``account``/``positions``/``orders`` shape.

    Returns ``None`` when the payloads cannot be interpreted; callers must treat
    that as unavailable, never as an empty portfolio.
    """
    if not account:
        return None
    try:
        snapshot_positions = [
            PositionSnapshot(
                symbol=str(item.get("symbol") or ""),
                qty=float(item.get("qty") or 0.0),
                market_value=float(item.get("market_value") or 0.0),
                avg_entry_price=float(item.get("avg_entry_price") or 0.0),
                current_price=float(item.get("current_price") or 0.0),
                unrealized_pl=float(item.get("unrealized_pl") or 0.0),
                unrealized_plpc=float(item.get("unrealized_plpc") or 0.0),
                side=str(item.get("side") or "long"),
                unrealized_intraday_pl=item.get("unrealized_intraday_pl"),
                unrealized_intraday_plpc=item.get("unrealized_intraday_plpc"),
            )
            for item in (positions or [])
        ]
        snapshot_orders = [
            OrderSnapshot(
                order_id=str(item.get("order_id") or ""),
                symbol=str(item.get("symbol") or ""),
                side=str(item.get("side") or ""),
                qty=None if item.get("qty") is None else float(item["qty"]),
                notional=None if item.get("notional") is None else float(item["notional"]),
                order_type=str(item.get("order_type") or ""),
                status=str(item.get("status") or ""),
                submitted_at=(
                    None if item.get("submitted_at") is None else str(item["submitted_at"])
                ),
            )
            for item in (orders or [])
        ]
        return PortfolioSnapshot(
            account_id=str(account.get("account_id") or ""),
            status=str(account.get("status") or ""),
            currency=str(account.get("currency") or ""),
            cash=float(account.get("cash") or 0.0),
            portfolio_value=float(account.get("portfolio_value") or 0.0),
            buying_power=float(account.get("buying_power") or 0.0),
            positions=snapshot_positions,
            open_orders=snapshot_orders,
            previous_close_equity=account.get("previous_close_equity"),
        )
    except (TypeError, ValueError):
        return None


def portfolio_from_snapshots(
    snapshots: Mapping[str, ResourceSnapshot],
) -> PortfolioSnapshot | None:
    """Portfolio assembled from persisted ``account``/``positions``/``orders`` snapshots."""
    account = snapshots.get(RESOURCE_ACCOUNT)
    if account is None:
        return None
    positions = snapshots.get(RESOURCE_POSITIONS)
    orders = snapshots.get(RESOURCE_ORDERS)
    return _portfolio_from_payloads(
        dict(account.payload),
        [item for item in (positions.payload.get("positions", []) if positions else []) if isinstance(item, dict)],
        [item for item in (orders.payload.get("orders", []) if orders else []) if isinstance(item, dict)],
    )


def fills_from_snapshots(
    snapshots: Mapping[str, ResourceSnapshot],
) -> list[dict[str, Any]] | None:
    """Last persisted fills, or ``None`` when there is no valid fills snapshot."""
    snapshot = snapshots.get(RESOURCE_FILLS)
    if snapshot is None:
        return None
    fills = snapshot.payload.get("fills")
    if not isinstance(fills, list):
        return None
    return [item for item in fills if isinstance(item, dict)]


def load_persisted_snapshots(settings: Any) -> dict[str, ResourceSnapshot]:
    """Valid persisted snapshots for the configured account and environment.

    Local SQLite only, fail-open: a missing table, missing account hint or any
    read error yields an empty mapping, never an invented payload.
    """
    database_path = getattr(settings, "database_path", None)
    if database_path is None:
        return {}
    try:
        repository = SnapshotRepository(database_path)
        fingerprint = environment_fingerprint(settings)
        account_id = repository.account_hint(fingerprint)
        if not account_id:
            return {}
        return repository.load_all(build_identity_key(fingerprint, account_id))
    except Exception as exc:  # noqa: BLE001 - the page keeps working without cache.
        LOGGER.warning("dashboard_persisted_snapshot_failed error=%s", type(exc).__name__)
        return {}


class _CachedFills:
    """Local history input; never calls a provider."""
    def __init__(self, fills: list[dict[str, Any]]) -> None:
        self.fills = fills

    def alpaca_trade_activities(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.fills)


class DashboardLoadState:
    """Per-session view over shared, deduplicated remote reads.

    ``update`` never waits for remote I/O; it only collects finished work and
    starts a new cycle when one is due.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        market_open: Callable[[Any], bool] | None = None,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        self.data: dict[str, Any] | None = None
        self.errors: list[str] = []
        self.futures: dict[str, Future] = {}
        self.failed: dict[str, str] = {}
        self.started_at = 0.0
        self.completed_at: float | None = None
        self.refresh_requested = False
        self.load_id: str | None = None
        self.fingerprint: str | None = None
        self.account_id: str | None = None
        self.identity_key: str | None = None
        self.repository: SnapshotRepository | None = None
        self.fills_repository: FillRepository | None = None
        self.fills_coverage: dict[str, Any] | None = None
        self.fills_sync: dict[str, Any] | None = None
        self.hydrated = False
        self.settings: Any = None
        self.observed_at: dict[str, str] = {}
        self.source: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self.remote_calls = 0
        self.progress_future: Future | None = None
        # Bumped on every published change of ``data``. Local, expensive readings
        # keyed by it are only rebuilt when the load actually changed.
        self.revision = 0
        # Market state and scheduling. Injected in tests; deterministic, no sleeps.
        self.market_open: bool | None = None
        self.degraded: dict[str, dict[str, Any]] = {}
        # Number of late results discarded because their generation was abandoned.
        self.stale_results = 0
        self._clock = clock or perf_counter
        self._market_open_probe = market_open
        self._jitter = jitter or _default_jitter
        self._generation: dict[str, int] = {}
        self._attempt_started: dict[str, float] = {}
        self._abandoned: dict[str, int] = {}
        self._orphans: dict[str, Future] = {}
        self._attempts: dict[str, int] = {}
        self._next_attempt_at: dict[str, float] = {}
        self._last_success_at: dict[str, float] = {}
        self._force: set[str] = set()
        self._known_order_ids: set[str] | None = None
        self._known_fill_ids: set[str] | None = None
        self._account: dict[str, Any] | None = None
        self._positions: list[dict[str, Any]] | None = None
        self._orders: list[dict[str, Any]] | None = None
        self._fills: list[dict[str, Any]] | None = None
        self._curve: dict[str, Any] | None = None
        self._intraday: dict[str, Any] | None = None
        self._finished_at: str | None = None

    # -- introspection --------------------------------------------------
    @property
    def loading(self) -> bool:
        return any(not future.done() for future in self.futures.values())

    @property
    def resource_status(self) -> dict[str, str]:
        status: dict[str, str] = {}
        now = datetime.now(timezone.utc)
        for resource in RESOURCES:
            observed = self.observed_at.get(resource)
            if not observed:
                status[resource] = "pending" if self.loading else "none"
                continue
            age = _utc_age_seconds(observed, now)
            status[resource] = (
                "fresh" if age is not None and age <= RESOURCE_FRESH_SECONDS else "stale"
            )
        return status

    @property
    def pending_resources(self) -> list[str]:
        status = self.resource_status
        return [resource for resource in RESOURCES if status[resource] in {"pending", "none"}]

    @property
    def cache_state(self) -> str:
        statuses = self.resource_status
        if not self.observed_at:
            return "none"
        values = set(statuses.values())
        if values & {"none", "pending"}:
            return "partial"
        if values == {"fresh"}:
            return "fresh"
        return "stale"

    def resource_ages(self) -> dict[str, float | None]:
        now = datetime.now(timezone.utc)
        return {
            resource: _utc_age_seconds(self.observed_at[resource], now)
            if resource in self.observed_at
            else None
            for resource in RESOURCES
        }

    # -- wiring ---------------------------------------------------------
    def _wire(self, settings: Any) -> None:
        if settings is None:
            return
        self.settings = settings
        fingerprint = environment_fingerprint(settings)
        if self.fingerprint is not None and self.fingerprint != fingerprint:
            self.reset()
            self.repository = None
            self.fills_repository = None
        self.fingerprint = fingerprint
        if self.repository is None:
            database_path = getattr(settings, "database_path", None)
            if database_path is not None:
                self.repository = SnapshotRepository(database_path)
        if self.fills_repository is None:
            database_path = getattr(settings, "database_path", None)
            if database_path is not None:
                self.fills_repository = FillRepository(database_path)

    def reset(self) -> None:
        """Forget every cached resource. Only used when the environment changes."""
        self.data = None
        # Old workers may finish, but their results no longer belong to this
        # view. Their callbacks capture the original storage identity below.
        self.futures = {}
        self.load_id = None
        self.completed_at = None
        self.errors = []
        self.failed = {}
        self.observed_at = {}
        self.source = {}
        self.timings = {}
        self._account = None
        self._positions = None
        self._orders = None
        self._fills = None
        self._curve = None
        self._intraday = None
        self._finished_at = None
        self.fills_coverage = None
        self.fills_sync = None
        self.account_id = None
        self.identity_key = None
        self.hydrated = False
        self.degraded = {}
        self.revision = 0
        self._generation = {}
        self._attempt_started = {}
        self._abandoned = {}
        self._orphans = {}
        self._attempts = {}
        self._next_attempt_at = {}
        self._last_success_at = {}
        self._force = set()
        self._known_order_ids = None
        self._known_fill_ids = None

    def hydrate(self) -> bool:
        """Load the last valid snapshot before any remote request."""
        if self.hydrated:
            return False
        self.hydrated = True
        repository = self.repository
        if repository is None or self.fingerprint is None:
            return False
        try:
            account_id = repository.account_hint(self.fingerprint)
        except Exception as exc:  # noqa: BLE001 - cache miss must never break the UI.
            LOGGER.warning("dashboard_snapshot_hint_failed error=%s", type(exc).__name__)
            return False
        if not account_id:
            return False
        self.account_id = account_id
        self.identity_key = build_identity_key(self.fingerprint, account_id)
        try:
            snapshots = repository.load_all(self.identity_key)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("dashboard_snapshot_load_failed error=%s", type(exc).__name__)
            return False
        if not snapshots:
            return False
        for snapshot in snapshots.values():
            self._apply_snapshot(snapshot.resource, snapshot.payload, snapshot.observed_at)
        now = self._clock()
        for remote, resources in REMOTE_TO_RESOURCES.items():
            ages = [_utc_age_seconds(self.observed_at[item]) for item in resources if item in self.observed_at]
            if len(ages) == len(resources) and all(age is not None for age in ages):
                self._last_success_at[remote] = now - max(ages)
        self._rebuild()
        self._log("hydrated")
        return True

    def _apply_snapshot(self, resource: str, payload: Mapping[str, Any], observed_at: str) -> None:
        if resource == RESOURCE_ACCOUNT:
            self._account = dict(payload)
        elif resource == RESOURCE_POSITIONS:
            self._positions = [item for item in payload.get("positions", []) if isinstance(item, dict)]
        elif resource == RESOURCE_ORDERS:
            self._orders = [item for item in payload.get("orders", []) if isinstance(item, dict)]
        elif resource == RESOURCE_FILLS:
            self._fills = [item for item in payload.get("fills", []) if isinstance(item, dict)]
            coverage = payload.get("coverage")
            self.fills_coverage = dict(coverage) if isinstance(coverage, Mapping) else None
        elif resource == RESOURCE_INTRADAY:
            self._intraday = dict(payload.get("curve") or {})
        elif resource == RESOURCE_CURVE:
            curve = payload.get("curve")
            self._curve = dict(curve) if isinstance(curve, Mapping) else {}
        else:
            return
        self.observed_at[resource] = observed_at
        self.source[resource] = "snapshot"

    # -- cycle ----------------------------------------------------------
    def update(self, settings: Any, refresh_after: float) -> bool:
        """Return whether the caller must rerun. Never waits for remote I/O.

        ``refresh_after`` is the UI poll interval. It is deliberately not used
        as a download cadence: each resource decides with its own cadence and
        the market state, so a 1 s poll cannot multiply broker reads.
        """
        del refresh_after  # UI-only parameter; kept for callers.
        self._wire(settings)
        if not self.hydrated:
            self.hydrate()
        changed = self._collect()
        now = self._clock()
        if self._expire_budgets(now):
            changed = True
        started = self._request_due(settings, now)
        if self.refresh_requested:
            self.refresh_requested = False
        return bool(changed or started)

    def begin(self, settings: Any, *, repository: SnapshotRepository | None = None) -> None:
        """Hydrate and start one cycle; used by the synchronous loader."""
        if repository is not None:
            self.repository = repository
        self._wire(settings)
        self.hydrate()
        self._start_cycle(settings)

    def _start_cycle(self, settings: Any) -> None:
        if settings is None:
            return
        self.settings = settings
        self.load_id = new_id("dash")
        self.errors = []
        self.failed = {}
        self.degraded = {}
        self.timings = {}
        self.remote_calls = 0
        self.started_at = self._clock()
        self._finished_at = None
        if self.identity_key is None:
            self.identity_key = build_identity_key(self.fingerprint or "", self.account_id)
        self._refresh_market_state(settings)
        callbacks = self._callbacks(settings)
        now = self._clock()
        # Priority order: account/positions/orders first, then fills, then curve.
        for resource in REMOTE_RESOURCES:
            self._start_resource(resource, callbacks, now)
        self._log("start")

    # -- per-resource scheduling ---------------------------------------
    def _refresh_market_state(self, settings: Any) -> None:
        probe = self._market_open_probe
        try:
            if probe is not None:
                self.market_open = bool(probe(settings))
            elif settings is not None:
                self.market_open = market_is_open(settings, self._clock)
            else:
                self.market_open = None
        except Exception as exc:  # noqa: BLE001 - unknown state, never a failure.
            LOGGER.debug("dashboard_market_probe_failed error=%s", type(exc).__name__)
            self.market_open = None

    def _cadence_seconds(self, resource: str) -> float:
        open_seconds, closed_seconds = REMOTE_CADENCE_SECONDS[resource]
        # Unknown market state: use the shorter cadence, so freshness is never
        # worse than the open-market target.
        if self.market_open is False:
            return closed_seconds
        return open_seconds

    def _is_due(self, resource: str, now: float) -> bool:
        if resource in self._force:
            return True
        if self.refresh_requested:
            # Manual refresh requests work now, but it never bypasses the
            # in-flight deduplication, the abandoned generation or capacity.
            return True
        retry_at = self._next_attempt_at.get(resource)
        if retry_at is not None and now < retry_at:
            return False
        last_success = self._last_success_at.get(resource)
        if last_success is None:
            return True
        return now - last_success >= self._cadence_seconds(resource)

    def _request_due(self, settings: Any, now: float) -> bool:
        if settings is None:
            return False
        self._refresh_market_state(settings)
        callbacks = self._callbacks(settings)
        first_load = self.load_id is None and not self.futures
        started = False
        for resource in REMOTE_RESOURCES:
            if resource in self.futures or resource in self._abandoned:
                continue
            if not self._is_due(resource, now):
                continue
            if self._start_resource(resource, callbacks, now):
                started = True
        if started:
            self._log("start" if first_load else "refresh")
        return started

    def _start_resource(
        self,
        resource: str,
        callbacks: Mapping[str, Callable[[], Any]],
        now: float,
    ) -> bool:
        if self.identity_key is None:
            self.identity_key = build_identity_key(self.fingerprint or "", self.account_id)
        future, created = submit_remote(
            self.identity_key, resource, callbacks[resource]
        )
        if future is None:
            return False
        generation = inflight_generation(self.identity_key, resource) or 0
        if not created and self._abandoned.get(resource) == generation:
            return False
        had_work = bool(self.futures)
        self._generation[resource] = generation
        self.futures[resource] = future
        self._attempt_started[resource] = now
        self._force.discard(resource)
        self.timings.pop(resource, None)
        self.failed.pop(resource, None)
        self.errors = [
            item for item in self.errors if not item.startswith(f"{resource}: ")
        ]
        if created:
            self.remote_calls += 1
        if not had_work:
            self.started_at = now
            self._finished_at = None
            if self.load_id is None:
                self.load_id = new_id("dash")
        return True

    def _expire_budgets(self, now: float) -> bool:
        changed = False
        for resource, started in list(self._attempt_started.items()):
            future = self.futures.get(resource)
            if future is None or future.done():
                continue
            if now - started < UPDATE_BUDGET_SECONDS:
                continue
            generation = self._generation.get(resource, 0)
            self._abandoned[resource] = generation
            self._orphans[resource] = future
            self.futures.pop(resource, None)
            self._attempt_started.pop(resource, None)
            self._schedule_retry(resource, "budget_exceeded", now)
            self._record_failure(
                resource,
                TimeoutError(
                    f"presupuesto de actualizacion agotado ({UPDATE_BUDGET_SECONDS:.0f} s)"
                ),
            )
            changed = True
        return changed

    def _schedule_retry(self, resource: str, reason: str, now: float | None = None) -> None:
        attempts = self._attempts.get(resource, 0) + 1
        self._attempts[resource] = attempts
        base = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
        delay = max(0.0, base + float(self._jitter(base)))
        reference = self._clock() if now is None else now
        self._next_attempt_at[resource] = reference + delay
        self.degraded[resource] = {
            "reason": reason,
            "attempts": attempts,
            "retry_in_seconds": round(delay, 3),
            "generation": self._generation.get(resource, 0),
        }

    def _callbacks(self, settings: Any) -> dict[str, Callable[[], Any]]:
        fills_repository = self.fills_repository
        fills_identity = self.identity_key if self.account_id else None
        snapshot_repository = self.repository
        def portfolio() -> Any:
            if snapshot_repository is not None:
                snapshot_repository.ensure_schema()
            return BrokerClientFactory(settings).alpaca_portfolio_snapshot()

        def fills() -> Any:
            # With a real bound account identity the read is incremental: it
            # resumes from the persisted cursor and stores the fills locally.
            # Without one (first cycle, before the account is observed) or with
            # a repository-less state the legacy bounded list read is kept; the
            # full history is never walked here.
            if fills_repository is not None and fills_identity:
                return self._sync_fills(settings, fills_repository, fills_identity)
            return DashboardBroker(settings).alpaca_trade_activities(
                limit=FILLS_ROW_LIMIT
            )

        def curve() -> Any:
            return BrokerClientFactory(settings).alpaca_portfolio_history(
                period="all", timeframe="1D"
            )

        def intraday() -> Any:
            return BrokerClientFactory(settings).alpaca_portfolio_history(period="2W", timeframe="15Min")

        return {REMOTE_PORTFOLIO: portfolio, REMOTE_FILLS: fills,
                REMOTE_CURVE: curve, REMOTE_INTRADAY: intraday}

    def _sync_fills(
        self, settings: Any, repository: FillRepository, identity: str
    ) -> dict[str, Any]:
        """Bounded incremental fill sync; a failure keeps the previous fills."""
        try:
            result = sync_recent(
                settings,
                repository=repository,
                identity_key=identity,
                fetch=fetch_for_client(DashboardBroker(settings)),
                max_pages=FILLS_SYNC_MAX_PAGES,
            )
        except Exception as exc:  # noqa: BLE001 - local cache is fail-open.
            LOGGER.warning("dashboard_fills_sync_failed error=%s", type(exc).__name__)
            raise
        if result.status == "degraded":
            # Published as a failure so the previous fills stay untouched and
            # the resource keeps its own retry/degradation state.
            raise RuntimeError(result.error or "sincronizacion de fills degradada")
        if result.truncated:
            LOGGER.info(
                "dashboard_fills_truncated pages=%s stop_reason=%s",
                result.pages,
                result.stop_reason,
            )
        return {
            "fills": repository.load_fills(identity),
            "coverage": result.coverage,
            "sync": result.as_dict(),
        }

    def _collect(self) -> bool:
        changed = False
        now = self._clock()
        # A late result from an abandoned generation is discarded, never
        # published: a newer attempt already owns the resource.
        for resource, future in list(self._orphans.items()):
            if not future.done():
                continue
            self._orphans.pop(resource, None)
            self.stale_results += 1
            LOGGER.info(
                "dashboard_stale_result_discarded resource=%s generation=%s",
                resource,
                self._abandoned.pop(resource, None),
            )
            changed = True
        for resource, future in list(self.futures.items()):
            if self.futures.get(resource) is not future:
                continue  # An earlier result changed the observed account.
            if not future.done():
                continue
            self.futures.pop(resource, None)
            self._attempt_started.pop(resource, None)
            try:
                pack = future.result()
            except Exception as exc:  # noqa: BLE001 - published, never raised.
                self._record_failure(resource, exc)
                self._schedule_retry(resource, "error", now)
                changed = True
                continue
            generation = int(pack.get("generation") or 0)
            expected = self._generation.get(resource)
            if expected is not None and generation != expected:
                self.stale_results += 1
                LOGGER.info(
                    "dashboard_stale_result_discarded resource=%s generation=%s expected=%s",
                    resource,
                    generation,
                    expected,
                )
                changed = True
                continue
            self.timings[resource] = float(pack.get("seconds") or 0.0)
            self._publish(resource, pack)
            self._last_success_at[resource] = now
            self._attempts[resource] = 0
            self._next_attempt_at.pop(resource, None)
            self.degraded.pop(resource, None)
            changed = True
        if changed and not self.futures and not self._orphans:
            self._finish_cycle()
        return changed

    def _publish(self, remote_resource: str, pack: Mapping[str, Any]) -> None:
        value = pack.get("value")
        observed_at = str(pack.get("observed_at") or utc_now_iso())
        self.failed.pop(remote_resource, None)
        if remote_resource == REMOTE_PORTFOLIO:
            if not isinstance(value, PortfolioSnapshot):
                self._record_failure(
                    remote_resource, RuntimeError("respuesta de cartera no valida")
                )
                return
            self._bind_account(value.account_id)
            self._account = {
                "account_id": value.account_id,
                "status": value.status,
                "currency": value.currency,
                "cash": value.cash,
                "portfolio_value": value.portfolio_value,
                "buying_power": value.buying_power,
                "previous_close_equity": value.previous_close_equity,
            }
            self._positions = [asdict(item) for item in value.positions]
            self._orders = [
                {
                    "order_id": item.order_id,
                    "symbol": item.symbol,
                    "side": item.side,
                    "qty": item.qty,
                    "notional": item.notional,
                    "order_type": item.order_type,
                    "status": item.status,
                    "submitted_at": item.submitted_at,
                }
                for item in value.open_orders
            ]
            for resource in REMOTE_TO_RESOURCES[REMOTE_PORTFOLIO]:
                self.observed_at[resource] = observed_at
                self.source[resource] = "remote"
        elif remote_resource == REMOTE_FILLS:
            if isinstance(value, Mapping) and isinstance(value.get("fills"), list):
                self._fills = [dict(item) for item in value["fills"] if isinstance(item, Mapping)]
                coverage = value.get("coverage")
                self.fills_coverage = dict(coverage) if isinstance(coverage, Mapping) else None
                sync = value.get("sync")
                self.fills_sync = dict(sync) if isinstance(sync, Mapping) else None
            else:
                self._fills = [item for item in (value or []) if isinstance(item, dict)]
                self.fills_coverage = None
                self.fills_sync = None
            self.observed_at[RESOURCE_FILLS] = observed_at
            self.source[RESOURCE_FILLS] = "remote"
        elif remote_resource == REMOTE_INTRADAY:
            self._intraday = dict(value) if isinstance(value, Mapping) else {}
            self.observed_at[RESOURCE_INTRADAY] = observed_at
            self.source[RESOURCE_INTRADAY] = "remote"
        elif remote_resource == REMOTE_CURVE:
            self._curve = dict(value) if isinstance(value, Mapping) else {}
            self.observed_at[RESOURCE_CURVE] = observed_at
            self.source[RESOURCE_CURVE] = "remote"
        else:
            return
        self._note_new_operation(remote_resource, value)
        self._persist(remote_resource)
        if remote_resource == REMOTE_PORTFOLIO:
            # Reads can finish before the first account response; persist those
            # observations once the identity is known, retaining their own times.
            for pending_resource in (REMOTE_FILLS, REMOTE_CURVE, REMOTE_INTRADAY):
                if pending_resource in self.observed_at:
                    self._persist(pending_resource)
        self._rebuild(rebuild_history=remote_resource in {REMOTE_PORTFOLIO, REMOTE_FILLS})
        if (
            remote_resource == REMOTE_PORTFOLIO
            and self.progress_future is not None
            and not self.progress_future.done()
        ):
            self.progress_future.set_result(dict(self.data or {}))

    def _note_new_operation(self, remote_resource: str, value: Any) -> None:
        """A new order or fill makes the paired resource due immediately.

        Detection is by identity (``order_id``), never by symbol or date. It
        only requests work: the in-flight deduplication and the worker ceiling
        still decide whether a download happens.
        """
        if remote_resource == REMOTE_PORTFOLIO and isinstance(value, PortfolioSnapshot):
            observed = {str(order.order_id) for order in value.open_orders if order.order_id}
            previous = self._known_order_ids
            self._known_order_ids = observed
            if previous is not None and observed - previous:
                self._force.add(REMOTE_FILLS)
        elif remote_resource == REMOTE_FILLS:
            observed = {
                str(item.get("order_id") or item.get("id") or "")
                for item in (self._fills or [])
                if isinstance(item, Mapping)
            }
            observed.discard("")
            previous = self._known_fill_ids
            self._known_fill_ids = observed
            if previous is not None and observed - previous:
                self._force.add(REMOTE_PORTFOLIO)

    def _bind_account(self, account_id: str) -> None:
        observed = str(account_id or "").strip()
        if not observed or observed == self.account_id:
            return
        if self.account_id is not None and self.identity_key is not None:
            # Never display one account's snapshot under another account's identity.
            LOGGER.warning(
                "dashboard_account_mismatch expected=%s observed=%s",
                self.account_id[-6:],
                observed[-6:],
            )
            self.reset()
        self.account_id = observed
        self.identity_key = build_identity_key(self.fingerprint or "", observed)
        if self.repository is not None and self.fingerprint is not None:
            try:
                self.repository.record_account_hint(self.fingerprint, observed)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("dashboard_snapshot_hint_write_failed error=%s", type(exc).__name__)

    def _persist(self, remote_resource: str) -> None:
        if self.repository is None or self.identity_key is None or self.account_id is None:
            return
        entries: list[tuple[str, Mapping[str, Any], str]] = []
        if remote_resource == REMOTE_PORTFOLIO and self._account is not None:
            observed = self.observed_at.get(RESOURCE_ACCOUNT) or utc_now_iso()
            entries = [
                (RESOURCE_ACCOUNT, self._account, observed),
                (RESOURCE_POSITIONS, {"positions": self._positions or []}, observed),
                (RESOURCE_ORDERS, {"orders": self._orders or []}, observed),
            ]
        elif remote_resource == REMOTE_FILLS:
            observed = self.observed_at.get(RESOURCE_FILLS) or utc_now_iso()
            fills = self._fills or []
            payload: dict[str, Any] = {"fills": fills, "count": len(fills)}
            if self.fills_coverage is not None:
                payload["coverage"] = dict(self.fills_coverage)
            entries = [(RESOURCE_FILLS, payload, observed)]
        elif remote_resource == REMOTE_INTRADAY:
            observed = self.observed_at.get(RESOURCE_INTRADAY) or utc_now_iso()
            entries = [(RESOURCE_INTRADAY, {"curve": self._intraday or {}}, observed)]
        elif remote_resource == REMOTE_CURVE:
            observed = self.observed_at.get(RESOURCE_CURVE) or utc_now_iso()
            entries = [(RESOURCE_CURVE, {"curve": self._curve or {}}, observed)]
        if not entries:
            return
        try:
            self.repository.save_many(self.identity_key, entries)
        except Exception as exc:  # noqa: BLE001 - the snapshot is fail-open.
            self._append_error(f"snapshot: {exc}")

    def _record_failure(self, remote_resource: str, exc: BaseException) -> None:
        message = f"{remote_resource}: {exc}"
        self.errors = [
            item for item in self.errors if not item.startswith(f"{remote_resource}: ")
        ]
        self.errors.append(message)
        self.failed[remote_resource] = str(exc)
        if self.repository is not None and self.identity_key is not None:
            for resource in REMOTE_TO_RESOURCES.get(remote_resource, ()):
                try:
                    self.repository.record_attempt(
                        self.identity_key,
                        resource,
                        "error",
                        error_code=type(exc).__name__,
                    )
                except Exception:  # noqa: BLE001 - observability only.
                    LOGGER.warning("dashboard_snapshot_attempt_failed")
        self._rebuild()

    def _append_error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def _finish_cycle(self) -> None:
        self.completed_at = perf_counter()
        self.timings["total"] = self.completed_at - self.started_at
        self._finished_at = utc_now_iso()
        self._rebuild()
        self._log("complete")

    # -- assembly -------------------------------------------------------
    def _portfolio(self) -> PortfolioSnapshot | None:
        if not self._account:
            return None
        portfolio = _portfolio_from_payloads(
            self._account, self._positions, self._orders
        )
        if portfolio is None:
            self._append_error("snapshot: payload de cartera no interpretable")
        return portfolio

    @property
    def cached_fills(self) -> list[dict[str, Any]] | None:
        """Fills available in this session, local sync included, or ``None``."""
        fills = self._merged_fills()
        return None if fills is None else list(fills)

    def _merged_fills(self) -> list[dict[str, Any]] | None:
        """Session/snapshot fills merged with the local synchronized repository."""
        local: list[dict[str, Any]] = []
        if self.fills_repository is not None and self.identity_key:
            try:
                local = self.fills_repository.load_fills(self.identity_key)
            except Exception:  # noqa: BLE001 - local cache is fail-open.
                local = []
        if self._fills is None and not local:
            return None
        return merge_fill_lists(self._fills, local)

    def _current_fills_coverage(self) -> dict[str, Any] | None:
        if self.fills_coverage is not None:
            return dict(self.fills_coverage)
        if self.fills_repository is not None and self.identity_key:
            try:
                return dict(self.fills_repository.coverage(self.identity_key))
            except Exception:  # noqa: BLE001
                return None
        return None

    def _rebuild(self, *, rebuild_history: bool = True) -> None:
        self.revision += 1
        previous = dict(self.data or {})
        portfolio = self._portfolio()
        fills = self._merged_fills() if rebuild_history else None
        coverage = self._current_fills_coverage() if rebuild_history else previous.get("fills_coverage")
        history: dict[str, Any] = {}
        if rebuild_history and portfolio is not None and self.settings is not None:
            try:
                history = build_trade_history(
                    self.settings,
                    limit=1000,
                    start_date="2026-04-01",
                    portfolio_snapshot=portfolio,
                    broker_client=_CachedFills(list(fills or [])),
                )
            except Exception as exc:  # noqa: BLE001 - keeps the previous history.
                self._append_error(f"history: {exc}")
                history = dict(previous.get("history") or {})
        else:
            history = dict(previous.get("history") or {})
        if history:
            history["fills_coverage"] = coverage
        curve = self._curve if self._curve is not None else previous.get("portfolio_history")
        self.data = {
            "load_id": self.load_id,
            "portfolio": portfolio,
            "history": history,
            "portfolio_history": dict(curve or {}),
            "intraday_portfolio_history": dict(self._intraday or {}),
            "fills_count": (None if fills is None else len(fills)) if rebuild_history else previous.get("fills_count"),
            "fills_coverage": coverage,
            "fills_sync": dict(self.fills_sync or {}) or None,
            "observed_at": dict(self.observed_at),
            "status": self.resource_status,
            "ages_seconds": self.resource_ages(),
            "source": dict(self.source),
            "pending": self.pending_resources,
            "cache_state": self.cache_state,
            "remote_calls": self.remote_calls,
            "timings": dict(self.timings),
            "fetched_at": self._finished_at or previous.get("fetched_at"),
            "errors": list(self.errors),
            "degraded": {
                resource: dict(detail) for resource, detail in self.degraded.items()
            },
            "market_open": self.market_open,
            "stale_results": self.stale_results,
        }

    # -- observability --------------------------------------------------
    def _log(self, phase: str) -> None:
        if self.fingerprint is None:
            return
        statuses = self.resource_status
        ages = self.resource_ages()
        record = {
            "event": "dashboard_load",
            "phase": phase,
            "load_id": self.load_id,
            "identity": (self.identity_key or "")[:12] or "unavailable",
            "account_tail": (self.account_id or "")[-6:] or "unavailable",
            "cache_state": self.cache_state,
            "resources": {
                resource: {
                    "status": statuses[resource],
                    "source": self.source.get(resource) or "unavailable",
                    "age_seconds": (
                        None if ages.get(resource) is None else round(float(ages[resource]), 1)
                    ),
                }
                for resource in RESOURCES
            },
            "remote_calls": self.remote_calls,
            "active_workers": active_remote_workers(),
            "pending": self.pending_resources,
            "market_open": self.market_open,
            "degraded": {
                resource: dict(detail) for resource, detail in self.degraded.items()
            },
            "stale_results": self.stale_results,
            "errors": [str(item)[:200] for item in self.errors],
            "timings_seconds": {
                key: round(float(value), 3) for key, value in self.timings.items()
            },
            "budget_seconds": UPDATE_BUDGET_SECONDS,
            "cadence_seconds": {
                resource: self._cadence_seconds(resource) for resource in REMOTE_RESOURCES
            },
            "transport": self._transport_report(),
        }
        LOGGER.info(json.dumps(record, sort_keys=True, default=str))

    def _transport_report(self) -> Any:
        return {"portfolio_sdk_timeout": "unavailable", "fills_socket_timeout_seconds": 5.0}

    # -- synchronous helpers --------------------------------------------
    def wait(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else perf_counter() + timeout
        while self.futures:
            pending = list(self.futures.values())
            remaining = None if deadline is None else max(0.0, deadline - perf_counter())
            done, _ = wait_futures(
                pending, timeout=remaining, return_when=FIRST_COMPLETED
            )
            if not done:
                return
            self._collect()


def load_dashboard_data(
    settings: Any,
    progress: Future | None = None,
    *,
    repository: SnapshotRepository | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Read every resource once and return the assembled dashboard payload.

    Kept for direct callers and tests; the Streamlit path uses
    ``DashboardLoadState`` so nothing blocks the UI.
    """
    state = DashboardLoadState()
    state.progress_future = progress
    state.begin(settings, repository=repository)
    state.wait(timeout=timeout)
    if progress is not None and not progress.done():
        progress.set_result(dict(state.data or {}))
    data = state.data or {}
    return {
        "load_id": data.get("load_id"),
        "portfolio": data.get("portfolio"),
        "history": data.get("history") or {},
        "portfolio_history": data.get("portfolio_history") or {},
        "fills_count": data.get("fills_count"),
        "observed_at": data.get("observed_at") or {},
        "status": data.get("status") or {},
        "ages_seconds": data.get("ages_seconds") or {},
        "source": data.get("source") or {},
        "pending": data.get("pending") or [],
        "cache_state": data.get("cache_state") or "none",
        "remote_calls": data.get("remote_calls") or 0,
        "errors": list(state.errors),
        "timings": data.get("timings") or {},
        "fetched_at": data.get("fetched_at") or utc_now_iso(),
    }
