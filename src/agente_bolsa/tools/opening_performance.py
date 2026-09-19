"""Canonical opening-to-opening account and SPY performance.

The contract is observational.  It never drives trading and never substitutes
an approximate close or a civil UTC date for an exact XNYS opening timestamp.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pandas as pd

from .performance_benchmark import xnys_sessions_between

if TYPE_CHECKING:
    from ..config import Settings
    from ..storage import Store


SCHEMA_VERSION = "p-l72.session-open-snapshot.v1"
EVENT_TYPE = "session_open_snapshot"
EVENT_ID_PREFIX = "session_open_snapshot:"
MARKET_TIMEZONE = ZoneInfo("America/New_York")
# A benchmark quote captured a few minutes before the account read still
# describes the same opening-to-now interval; a stale quote must remain
# unavailable.  This is presentation/measurement metadata only.
CURRENT_BENCHMARK_ALIGNMENT_TOLERANCE_SECONDS = 5 * 60


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stable_hash(payload: Mapping[str, Any]) -> str:
    stable = deepcopy(dict(payload))
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _timestamp(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return parsed.astimezone(timezone.utc)


def _explicit_provider_observed_at(meta: Mapping[str, Any]) -> datetime | None:
    """Return only a provider/market observation timestamp from metadata.

    Cache creation time describes when this process wrote an artifact; it is
    not evidence of when the provider observed the market value.
    """

    for key in ("provider_observed_at", "market_observed_at"):
        observed_at = _timestamp(meta.get(key))
        if observed_at is not None:
            return observed_at
    return None


def _session_open_at(session_date: str) -> datetime:
    local = datetime.combine(date.fromisoformat(session_date), time(9, 30), tzinfo=MARKET_TIMEZONE)
    return local.astimezone(timezone.utc)


def _session_settled_at(session_date: str) -> datetime:
    """End of the regular session plus a capture grace window (P-L153).

    Daily bars downloaded before this instant were still forming and their
    OHLC gets revised after the close. Such partial-bar candidates are
    quarantined whenever a settled candidate exists for the session.
    """

    return _session_open_at(session_date) + timedelta(hours=6, minutes=45)


def _candidate_settled(session_date: str, candidate: Mapping[str, Any]) -> bool:
    """True when the candidate cannot be a partial intraday bar."""

    provenance = candidate.get("provenance") or {}
    if provenance.get("authority") == "explicit_benchmark_open":
        return True
    created = provenance.get("cache_created_at") or candidate.get("cache_created_at")
    if not isinstance(created, str) or not created.strip():
        return True
    try:
        created_at = datetime.fromisoformat(created.strip().replace("Z", "+00:00"))
    except ValueError:
        return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc) >= _session_settled_at(session_date)


def _expected_open_session(now: datetime) -> str | None:
    current = now.astimezone(timezone.utc)
    market_date = current.astimezone(MARKET_TIMEZONE).date()
    start = (market_date - timedelta(days=14)).isoformat()
    sessions = xnys_sessions_between(start, market_date.isoformat())
    opened = [session for session in sessions if _session_open_at(session) <= current]
    return opened[-1] if opened else None


def _is_next_xnys_session(start: str, end: str) -> bool:
    sessions = xnys_sessions_between(start, end)
    return len(sessions) == 2 and sessions == [start, end]


def extract_exact_open_snapshots(history: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract only exact 09:30 America/New_York equity observations."""

    by_session: dict[str, dict[str, Any]] = {}
    for raw_timestamp, raw_equity in zip(
        history.get("timestamp") or [],
        history.get("equity") or [],
        strict=False,
    ):
        observed_at = _timestamp(raw_timestamp)
        equity = _finite(raw_equity)
        if observed_at is None or equity is None or equity <= 0:
            continue
        market_time = observed_at.astimezone(MARKET_TIMEZONE)
        if (market_time.hour, market_time.minute, market_time.second) != (9, 30, 0):
            continue
        session_date = market_time.date().isoformat()
        candidate = {
            "session_date": session_date,
            "equity": equity,
            "observed_at": observed_at.isoformat(),
            "source": "alpaca_portfolio_history_15Min",
        }
        previous = by_session.get(session_date)
        if previous is None or str(candidate["observed_at"]) < str(previous["observed_at"]):
            by_session[session_date] = candidate
    return [by_session[key] for key in sorted(by_session)]


def build_session_open_snapshot(observation: Mapping[str, Any], *, captured_at: datetime | None = None) -> dict[str, Any]:
    del captured_at  # agent_events.created_at is the capture time; content remains idempotent.
    session_date = str(observation.get("session_date") or "")
    observed_at = _timestamp(observation.get("observed_at"))
    equity = _finite(observation.get("equity"))
    if not session_date or observed_at is None or equity is None or equity <= 0:
        raise ValueError("exact session opening observation required")
    market_time = observed_at.astimezone(MARKET_TIMEZONE)
    if market_time.date().isoformat() != session_date or (market_time.hour, market_time.minute, market_time.second) != (9, 30, 0):
        raise ValueError("observation is not the exact XNYS opening")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"{EVENT_ID_PREFIX}{session_date}",
        "session_date": session_date,
        "equity": equity,
        "observed_at": observed_at.isoformat(),
        "source": str(observation.get("source") or "alpaca_portfolio_history_15Min"),
    }
    payload["content_hash"] = _stable_hash(payload)
    return payload


def persist_session_open_snapshot(store: Store, payload: Mapping[str, Any]) -> dict[str, Any]:
    return store.record_append_only_event(
        event_id=str(payload["event_id"]),
        event_type=EVENT_TYPE,
        cycle_id=str(payload["session_date"]),
        payload=dict(payload),
    )


def read_session_open_snapshots(store: Store) -> list[dict[str, Any]]:
    canonical: dict[str, dict[str, Any]] = {}
    for event in store.agent_events(event_type_prefix=EVENT_TYPE, limit=5000):
        if event.get("event_type") != EVENT_TYPE:
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
            continue
        session_date = str(payload.get("session_date") or "")
        if str(event.get("event_id") or "") != f"{EVENT_ID_PREFIX}{session_date}":
            continue
        if _stable_hash(payload) != payload.get("content_hash"):
            continue
        try:
            canonical[session_date] = build_session_open_snapshot(payload)
        except ValueError:
            continue
    return [canonical[key] for key in sorted(canonical)]


def merge_account_open_snapshots(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge exact observations; persisted evidence wins over ephemeral history."""

    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for item in source:
            session_date = str(item.get("session_date") or "")
            equity = _finite(item.get("equity"))
            observed_at = _timestamp(item.get("observed_at"))
            if not session_date or equity is None or observed_at is None:
                continue
            merged[session_date] = {
                "session_date": session_date,
                "equity": equity,
                "observed_at": observed_at.isoformat(),
                "source": str(item.get("source") or "unavailable"),
            }
    return [merged[key] for key in sorted(merged)]


def capture_authoritative_spy_open_cache(
    settings: Settings,
    session_date: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Capture one dedicated SPY-open artifact outside presentation.

    The caller is responsible for a once-per-session guard.  The producer
    uses the existing market-data downloader in an isolated subdirectory and
    promotes only a valid ``SPY`` daily Open into a root cache artifact with
    explicit authority metadata.  It never edits an existing generic cache.
    """

    session = date.fromisoformat(str(session_date))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current < _session_open_at(session.isoformat()):
        return {"status": "unavailable", "reason": "session_open_not_reached"}
    cache_root = Path(settings.data_dir) / "cache" / "market_data"

    def _readable_authoritative_payload(meta_path: Path, meta: Mapping[str, Any]) -> bool:
        data_path = meta_path.with_suffix(".pkl")
        if not data_path.exists():
            return False
        try:
            frame = pd.read_pickle(data_path)
        except Exception:
            return False
        expected = _finite(meta.get("open_price"))
        series = _field_series(frame, "SPY", "Open")
        for raw_index, raw_value in series.items():
            try:
                index = pd.Timestamp(raw_index)
            except Exception:
                continue
            candidate_date = index.tz_convert(MARKET_TIMEZONE).date().isoformat() if index.tzinfo is not None else index.date().isoformat()
            value = _finite(raw_value)
            if candidate_date == str(meta.get("session_date")) and value is not None and value > 0 and (expected is None or abs(value - expected) <= 1e-10):
                return True
        return False

    for meta_path in cache_root.glob("market_data_*.json") if cache_root.exists() else []:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        requested = sorted(str(item).upper() for item in meta.get("requested_symbols", []))
        purpose = str(meta.get("purpose") or meta.get("observation_kind") or "").strip().lower()
        if requested == ["SPY"] and purpose in {"benchmark_open", "spy_open", "session_open", "opening_benchmark"} and str(meta.get("session_date")) == str(session_date) and _readable_authoritative_payload(meta_path, meta):
            return {
                "status": "available",
                "event": "existing_authoritative_cache",
                "cache_id": meta_path.stem.removeprefix("market_data_"),
            }

    # Import lazily so UI/read-only consumers never acquire a network-capable
    # market-data dependency merely by rendering the panel.
    from . import market_data

    staging = cache_root / "_benchmark_open_capture" / str(session_date)
    try:
        frame, source_meta = market_data.download_daily_prices_with_metadata(
            ["SPY"],
            str(session_date),
            (session + timedelta(days=1)).isoformat(),
            cache_dir=staging,
            provider=getattr(settings, "market_data_provider", None),
            fmp_api_key=getattr(settings, "fmp_api_key", None),
        )
    except Exception as exc:  # noqa: BLE001 - producer is observational/fail-open.
        return {"status": "unavailable", "reason": "benchmark_capture_failed", "error_type": type(exc).__name__}
    open_series = _field_series(frame, "SPY", "Open")
    exact_value: float | None = None
    for raw_index, raw_value in open_series.items():
        try:
            index = pd.Timestamp(raw_index)
        except Exception:
            continue
        candidate_date = index.tz_convert(MARKET_TIMEZONE).date().isoformat() if index.tzinfo is not None else index.date().isoformat()
        value = _finite(raw_value)
        if candidate_date == str(session_date) and value is not None and value > 0:
            exact_value = value
            break
    basis = str(source_meta.get("price_basis") or "").lower()
    if exact_value is None or basis != "adjusted_ohlc":
        return {"status": "unavailable", "reason": "benchmark_open_missing_or_basis_unknown"}
    source = str(source_meta.get("source") or source_meta.get("provider") or "")
    created_at = current.isoformat()
    semantic = {
        "symbol": "SPY",
        "session_date": str(session_date),
        "open_price": exact_value,
        "source": source,
        "price_basis": basis,
        "open_time_basis": "XNYS_session_open_field",
        "open_observed_at": _session_open_at(str(session_date)).isoformat(),
    }
    content_hash = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifact_basis = {
        "schema_version": "p-l74.spy-open-authority.v1",
        **semantic,
        "content_hash": content_hash,
        "created_at": created_at,
        "captured_at": created_at,
        "source": source,
        "purpose": "benchmark_open",
        "observation_kind": "spy_open",
        "requested_symbols": ["SPY"],
        "interval": "1d",
        "price_basis": basis,
        "source_created_at": source_meta.get("created_at"),
    }
    identity_hash = hashlib.sha256(
        json.dumps(
            {"symbol": "SPY", "session_date": str(session_date), "price_basis": basis},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    cache_id = "spy_open_{}_{}".format(
        str(session_date).replace("-", ""),
        identity_hash,
    )
    cache_root.mkdir(parents=True, exist_ok=True)
    data_path = cache_root / f"market_data_{cache_id}.pkl"
    meta_path = cache_root / f"market_data_{cache_id}.json"
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if existing.get("content_hash") == content_hash:
            if not _readable_authoritative_payload(meta_path, existing):
                frame.to_pickle(data_path)
                return {"status": "recovered", "cache_id": cache_id, "open_price": exact_value}
            return {"status": "idempotent", "cache_id": cache_id, "open_price": exact_value}
        conflict_id = f"spy_open_conflict_{str(session_date).replace('-', '')}_{content_hash[:12]}"
        (cache_root / f"{conflict_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": "p-l74.spy-open-authority.v1",
                    "status": "conflict",
                    "canonical_cache_id": cache_id,
                    "candidate": artifact_basis,
                    "content_hash": content_hash,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {"status": "conflict", "cache_id": cache_id, "conflict_id": conflict_id}
    # Write data first.  A crash leaves an orphan .pkl which the reader
    # ignores; a metadata file is only published after the payload is ready.
    frame.to_pickle(data_path)
    meta_path.write_text(
        json.dumps(artifact_basis, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    return {"status": "inserted", "cache_id": cache_id, "open_price": exact_value}


def _meta_time(value: Any) -> datetime | None:
    parsed = _timestamp(value)
    return parsed


def _field_series(frame: pd.DataFrame, symbol: str, field: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    wanted_symbol = symbol.upper()
    wanted_field = field.lower()
    matches: list[int] = []
    for index, column in enumerate(frame.columns):
        parts = column if isinstance(column, tuple) else (column,)
        normalized = {str(part).strip().lower() for part in parts}
        if wanted_field not in normalized:
            continue
        if isinstance(frame.columns, pd.MultiIndex) and wanted_symbol.lower() not in normalized:
            continue
        matches.append(index)
    if len(matches) != 1:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame.iloc[:, matches[0]], errors="coerce")


def load_cached_spy_open_observations(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read authoritative local SPY opening observations without network.

    A cache timestamp is provenance, not an authority rule.  When two valid
    artifacts disagree for the same session, the session is explicitly
    unavailable instead of allowing a late or narrow cache to overwrite a
    broad one.  The current price is resolved from the same artifact that
    supplied its session opening; open/current values are never mixed across
    artifacts.
    """

    cache_root = Path(settings.data_dir) / "cache" / "market_data"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    symbol = str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper()
    open_candidates: dict[str, list[dict[str, Any]]] = {}
    current_candidates: dict[str, list[dict[str, Any]]] = {}

    def _cache_provenance(
        meta_path: Path,
        meta: Mapping[str, Any],
        created_at: datetime,
        source: str,
        basis: str,
        interval: str,
    ) -> dict[str, Any]:
        return {
            "cache_id": meta_path.stem,
            "cache_created_at": created_at.isoformat(),
            "source": source,
            "price_basis": basis,
            "interval": interval or "inferred_daily",
            "requested_symbols": sorted(str(item).upper() for item in meta.get("requested_symbols", [])),
            "range_start": meta.get("start"),
            "range_end": meta.get("end"),
            "authority": (
                "explicit_benchmark_open"
                if str(meta.get("purpose") or meta.get("observation_kind") or meta.get("cache_purpose") or "")
                .strip()
                .lower()
                in {"benchmark_open", "spy_open", "session_open", "opening_benchmark"}
                and sorted(str(item).upper() for item in meta.get("requested_symbols", [])) == [symbol]
                else None
            ),
        }

    def _append_candidate(
        target: dict[str, list[dict[str, Any]]],
        session_date: str,
        price: float,
        *,
        observed_at: str | None,
        observation_timestamp_verified: bool,
        provenance: Mapping[str, Any],
        paired_open_price: float | None = None,
    ) -> None:
        target.setdefault(session_date, []).append(
            {
                "session_date": session_date,
                "price": price,
                "observed_at": observed_at,
                "observation_timestamp_verified": observation_timestamp_verified,
                "source": provenance.get("source"),
                "price_basis": provenance.get("price_basis"),
                "cache_created_at": provenance.get("cache_created_at"),
                "provenance": dict(provenance),
                "paired_open_price": paired_open_price,
            }
        )

    for meta_path in cache_root.glob("market_data_*.json") if cache_root.exists() else []:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        symbols = {str(item).upper() for item in meta.get("requested_symbols", [])}
        explicit_symbol = str(meta.get("symbol") or "").upper()
        if symbol not in symbols and explicit_symbol != symbol:
            continue
        created_at = _meta_time(meta.get("created_at"))
        if created_at is None or created_at > current:
            continue
        data_path = meta_path.with_suffix(".pkl")
        try:
            frame = pd.read_pickle(data_path)
        except Exception:
            continue
        interval = str(meta.get("interval") or meta.get("timeframe") or "").lower()
        if interval and interval not in {"1d", "daily", "day"}:
            continue
        if not interval:
            try:
                index = pd.DatetimeIndex(frame.index)
                inferred_daily = len(index) > 1 and all(
                    timestamp.hour == timestamp.minute == timestamp.second == 0
                    for timestamp in index[-min(len(index), 20) :]
                )
            except Exception:
                inferred_daily = False
            if not inferred_daily:
                continue
        basis = str(meta.get("price_basis") or "").lower()
        if not basis and str(meta.get("source") or "").lower() == "yfinance":
            # Historical cache metadata predates P-L71, but the producer has
            # used yfinance(auto_adjust=True) continuously since May 2026.
            basis = "adjusted_ohlc"
        if basis != "adjusted_ohlc":
            continue
        source = str(meta.get("source") or "")
        provenance = _cache_provenance(meta_path, meta, created_at, source, basis, interval)
        provider_observed_at = _explicit_provider_observed_at(meta)
        open_series = _field_series(frame, symbol, "Open")
        close_series = _field_series(frame, symbol, "Close")
        artifact_open_sessions: set[str] = set()
        artifact_open_prices: dict[str, float] = {}
        for raw_index, raw_value in open_series.items():
            value = _finite(raw_value)
            try:
                index = pd.Timestamp(raw_index)
            except Exception:
                continue
            if value is None or value <= 0 or pd.isna(index):
                continue
            session_date = (
                index.tz_convert(MARKET_TIMEZONE).date().isoformat()
                if index.tzinfo is not None
                else index.date().isoformat()
            )
            _append_candidate(
                open_candidates,
                session_date,
                value,
                observed_at=_session_open_at(session_date).isoformat(),
                observation_timestamp_verified=True,
                provenance=provenance,
            )
            artifact_open_sessions.add(session_date)
            artifact_open_prices.setdefault(session_date, value)
        for raw_index, raw_value in close_series.items():
            value = _finite(raw_value)
            try:
                index = pd.Timestamp(raw_index)
            except Exception:
                continue
            if value is None or value <= 0 or pd.isna(index):
                continue
            # A daily cache row is indexed at the civil session date.  Its
            # provider observation time is unavailable unless the metadata
            # carries an explicit provider/market timestamp.  created_at is
            # deliberately not a substitute for that authority.
            observed_at = provider_observed_at.isoformat() if provider_observed_at else None
            session_date = (
                index.tz_convert(MARKET_TIMEZONE).date().isoformat()
                if index.tzinfo is not None
                else index.date().isoformat()
            )
            if session_date not in artifact_open_sessions:
                continue
            _append_candidate(
                current_candidates,
                session_date,
                value,
                observed_at=observed_at,
                observation_timestamp_verified=provider_observed_at is not None,
                provenance=provenance,
                paired_open_price=artifact_open_prices.get(session_date),
            )

    def _comparison_price(price: Any) -> Any:
        # P-L143: group by cent-rounded price for comparability only.
        # Persisted evidence keeps the exact float; only the grouping
        # signature tolerates sub-cent provider revisions (auto_adjust).
        if isinstance(price, bool):
            return price
        if isinstance(price, (int, float)) and price == price:
            return round(float(price), 2)
        return price

    def _resolve_open(
        candidates_by_session: Mapping[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        def _is_authoritative(candidate: Mapping[str, Any]) -> bool:
            return (candidate.get("provenance") or {}).get("authority") == "explicit_benchmark_open"

        def _authority_candidate(group: list[dict[str, Any]]) -> dict[str, Any]:
            return min(
                (candidate for candidate in group if _is_authoritative(candidate)),
                key=lambda item: (
                    str(item.get("cache_created_at") or ""),
                    str((item.get("provenance") or {}).get("cache_id") or ""),
                ),
            )

        resolved: dict[str, dict[str, Any]] = {}
        conflicts: dict[str, list[dict[str, Any]]] = {}
        for session_date, candidates in candidates_by_session.items():
            # P-L153: quarantine partial intraday bars when settled
            # candidates exist. A daily bar downloaded while its session
            # was still forming gets revised after the close; treating it
            # as equal evidence manufactures conflicts (e.g. 759.5 vs
            # 763.15 for 2026-09-17).
            settled = [item for item in candidates if _candidate_settled(session_date, item)]
            if settled and len(settled) < len(candidates):
                candidates = settled
            unique: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for candidate in candidates:
                signature = (
                    _comparison_price(candidate.get("price")),
                    candidate.get("price_basis"),
                )
                unique.setdefault(signature, []).append(candidate)
            authority_groups = [group for group in unique.values() if any(_is_authoritative(candidate) for candidate in group)]
            if len(authority_groups) == 1:
                # Authority belongs to the canonical value group, not to the
                # first artifact that happened to be read from that group.
                # A generic duplicate may precede the dedicated artifact.
                resolved[session_date] = _authority_candidate(authority_groups[0])
                continue
            if len(unique) > 1:
                if len(authority_groups) != 1:
                    conflicts[session_date] = sorted(
                        [candidate for group in unique.values() for candidate in group],
                        key=lambda item: (
                            str(item.get("cache_created_at") or ""),
                            str((item.get("provenance") or {}).get("cache_id") or ""),
                        ),
                    )
                    continue
            group = next(iter(unique.values()))
            # Equivalent opening observations are idempotent.  Pick an
            # explicitly authoritative artifact first, otherwise the oldest
            # artifact, so a late duplicate cannot change the value.
            resolved[session_date] = min(
                group,
                key=lambda item: (
                    0 if (item.get("provenance") or {}).get("authority") else 1,
                    str(item.get("cache_created_at") or ""),
                    str((item.get("provenance") or {}).get("cache_id") or ""),
                ),
            )
        return resolved, conflicts

    def _resolve_current(
        candidates_by_session: Mapping[str, list[dict[str, Any]]],
        opens_by_session: Mapping[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        resolved: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        for session_date, candidates in candidates_by_session.items():
            opening = opens_by_session.get(session_date)
            if opening is None:
                continue
            opening_provenance = opening.get("provenance") or {}
            opening_is_authoritative = opening_provenance.get("authority") == "explicit_benchmark_open"
            eligible = [
                candidate
                for candidate in candidates
                if candidate.get("price_basis") == opening.get("price_basis")
                and (
                    opening_is_authoritative
                    or candidate.get("paired_open_price") == opening.get("price")
                )
            ]
            if not eligible:
                warnings.append("current_open_provenance_mismatch")
                continue
            # Current prices are mutable observations: the freshest valid
            # artifact wins.  This is intentionally different from opening
            # authority, which is immutable for a session.
            resolved[session_date] = max(
                eligible,
                key=lambda item: (
                    str(item.get("cache_created_at") or ""),
                    str((item.get("provenance") or {}).get("cache_id") or ""),
                ),
            )
        return resolved, warnings

    opens, open_conflicts = _resolve_open(open_candidates)
    currents, current_warnings = _resolve_current(current_candidates, opens)
    conflicts = open_conflicts
    warnings: list[str] = []
    if open_conflicts:
        warnings.append("conflicting_session_open_observations")
    if quarantined_open_sessions(open_candidates):
        warnings.append("partial_session_bars_quarantined")
    warnings.extend(current_warnings)
    expected_session = _expected_open_session(current)
    current_price = currents.get(expected_session or "")
    current_session_conflict = expected_session in open_conflicts
    if open_conflicts and not current_session_conflict:
        warnings.append("historical_open_conflict_outside_current_session")
    status = "conflict" if current_session_conflict else "available" if opens or current_price else "unavailable"
    return {
        "opens": [opens[key] for key in sorted(opens)],
        "current": current_price,
        "instrument": "SPY (ETF S&P 500)",
        "status": status,
        "warnings": warnings,
        "conflicts": conflicts,
    }


def quarantined_open_sessions(
    candidates_by_session: Mapping[str, list[dict[str, Any]]],
) -> list[str]:
    """Sessions where partial intraday bars were dropped (P-L153)."""

    quarantined: list[str] = []
    for session_date, candidates in candidates_by_session.items():
        settled = [item for item in candidates if _candidate_settled(session_date, item)]
        if settled and len(settled) < len(candidates):
            quarantined.append(session_date)
    return sorted(quarantined)


def build_open_to_open_rows(
    account_opens: list[dict[str, Any]],
    spy_market: Mapping[str, Any],
    *,
    current_equity: Any = None,
    current_equity_at: datetime | None = None,
    include_current: bool = True,
) -> list[dict[str, Any]]:
    account = {str(item.get("session_date")): item for item in account_opens}
    spy = {str(item.get("session_date")): item for item in spy_market.get("opens") or []}
    sessions = sorted(set(account).intersection(spy))
    rows: list[dict[str, Any]] = []
    for start, end in zip(sessions, sessions[1:], strict=False):
        if not _is_next_xnys_session(start, end):
            continue
        account_start = _finite(account[start].get("equity"))
        account_end = _finite(account[end].get("equity"))
        spy_start = _finite(spy[start].get("price"))
        spy_end = _finite(spy[end].get("price"))
        if None in {account_start, account_end, spy_start, spy_end} or not account_start or not spy_start:
            continue
        if spy[start].get("price_basis") != spy[end].get("price_basis"):
            continue
        rows.append(
            {
                "session_date": start,
                "end_session_date": end,
                "status": "final",
                "system_pct": account_end / account_start - 1.0,
                "system_delta": account_end - account_start,
                "spy_pct": spy_end / spy_start - 1.0,
                "system_start_at": account[start].get("observed_at"),
                "system_end_at": account[end].get("observed_at"),
                "spy_start_at": spy[start].get("observed_at"),
                "spy_end_at": spy[end].get("observed_at"),
                "spy_start_provenance": spy[start].get("provenance"),
                "spy_end_provenance": spy[end].get("provenance"),
                "system_source": account[start].get("source"),
                "spy_source": spy[start].get("source"),
                "price_basis": spy[start].get("price_basis"),
                "benchmark_symbol": "SPY",
                "instrument_label": spy_market.get("instrument") or "SPY (ETF S&P 500)",
                "comparison_status": "comparable",
                "comparison_reason": None,
            }
        )
    current_at = (current_equity_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expected_session = _expected_open_session(current_at)
    latest_session = sessions[-1] if sessions and sessions[-1] == expected_session else None
    current_spy = spy_market.get("current") or {}
    current_equity_value = _finite(current_equity)
    current_spy_value = _finite(current_spy.get("price"))
    current_spy_at = _timestamp(current_spy.get("observed_at"))
    if include_current and latest_session and current_equity_value is not None:
        account_start = _finite(account[latest_session].get("equity"))
        spy_start = _finite(spy[latest_session].get("price"))
        comparison_status = "unavailable"
        comparison_reason = "current_observation_unavailable"
        timestamp_verified = current_spy.get("observation_timestamp_verified")
        spy_pct = (
            current_spy_value / spy_start - 1.0
            if (
                timestamp_verified is not False
                and spy_start is not None
                and spy_start > 0
                and current_spy_value is not None
                and current_spy.get("price_basis") == spy[latest_session].get("price_basis")
            )
            else None
        )
        if account_start is None or account_start <= 0:
            comparison_reason = "account_open_unavailable"
        elif spy_start is None or spy_start <= 0 or current_spy_value is None:
            comparison_reason = "current_spy_unavailable"
        elif current_spy.get("price_basis") != spy[latest_session].get("price_basis"):
            comparison_reason = "current_price_basis_mismatch"
        elif timestamp_verified is False:
            comparison_reason = "current_observation_timestamp_unverified"
        elif current_spy_at is None:
            comparison_reason = "current_observation_unavailable"
        elif current_spy_at > current_at:
            comparison_reason = "current_observation_future"
        elif current_spy_at < _session_open_at(latest_session):
            comparison_reason = "current_observation_before_session_open"
        elif (current_at - current_spy_at).total_seconds() > CURRENT_BENCHMARK_ALIGNMENT_TOLERANCE_SECONDS:
            comparison_reason = "current_observation_not_aligned"
        else:
            comparison_status = "comparable"
            comparison_reason = None
        rows.append(
            {
                "session_date": latest_session,
                "end_session_date": None,
                "status": "in_progress",
                "system_pct": current_equity_value / account_start - 1.0 if account_start else None,
                "system_delta": current_equity_value - account_start if account_start else None,
                "spy_pct": spy_pct,
                "spy_current_price": current_spy_value,
                "system_start_at": account[latest_session].get("observed_at"),
                "system_end_at": current_at.isoformat(),
                "spy_start_at": spy[latest_session].get("observed_at"),
                "spy_end_at": current_spy.get("observed_at"),
                "spy_start_provenance": spy[latest_session].get("provenance"),
                "spy_current_provenance": current_spy.get("provenance"),
                "system_source": account[latest_session].get("source"),
                "spy_source": current_spy.get("source"),
                "price_basis": current_spy.get("price_basis"),
                "benchmark_symbol": "SPY",
                "instrument_label": spy_market.get("instrument") or "SPY (ETF S&P 500)",
                "comparison_status": comparison_status,
                "comparison_reason": comparison_reason,
                "comparison_lag_seconds": (
                    (current_at - current_spy_at).total_seconds() if current_spy_at is not None else None
                ),
                "comparison_alignment_tolerance_seconds": CURRENT_BENCHMARK_ALIGNMENT_TOLERANCE_SECONDS,
                "comparison_coverage": {
                    "system_end_at": current_at.isoformat(),
                    "spy_end_at": current_spy_at.isoformat() if current_spy_at is not None else None,
                    "aligned": comparison_status == "comparable",
                },
            }
        )
    return rows


def build_opening_omissions(
    account_opens: list[dict[str, Any]],
    spy_market: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Explain exact XNYS intervals that were not comparable.

    This is presentation metadata only.  It never fabricates a row or changes
    the conservative intersection used by ``build_open_to_open_rows``.
    """

    if len(account_opens) < 2:
        return []
    account = {str(item.get("session_date")): item for item in account_opens}
    spy = {str(item.get("session_date")): item for item in spy_market.get("opens") or []}
    conflicts = spy_market.get("conflicts") or {}
    sessions = xnys_sessions_between(
        str(account_opens[0].get("session_date")),
        str(account_opens[-1].get("session_date")),
    )
    completed_starts = {str(row.get("session_date")) for row in rows if row.get("status") == "final"}
    omissions: list[dict[str, Any]] = []
    for start, end in zip(sessions, sessions[1:], strict=False):
        if start in completed_starts:
            continue
        account_start = start in account
        account_end = end in account
        spy_start = start in spy
        spy_end = end in spy
        if not account_start or not account_end:
            reason = "account_open_unavailable"
        elif start in conflicts or end in conflicts:
            reason = "spy_open_conflict"
        elif not spy_start or not spy_end:
            reason = "spy_open_unavailable"
        elif spy[start].get("price_basis") != spy[end].get("price_basis"):
            reason = "price_basis_mismatch"
        else:
            reason = "not_comparable"
        omissions.append(
            {
                "session_date": start,
                "end_session_date": end,
                "status": "omitted",
                "reason": reason,
                "coverage": {
                    "account_start": account_start,
                    "account_end": account_end,
                    "spy_start": spy_start,
                    "spy_end": spy_end,
                },
            }
        )
    return omissions


def build_current_account_interval(
    account_opens: list[dict[str, Any]],
    *,
    current_equity: Any,
    current_equity_at: datetime,
) -> dict[str, Any] | None:
    current_value = _finite(current_equity)
    expected_session = _expected_open_session(current_equity_at)
    account = {str(item.get("session_date")): item for item in account_opens}
    opening = account.get(expected_session or "")
    opening_value = _finite((opening or {}).get("equity"))
    if opening is None or opening_value is None or opening_value <= 0 or current_value is None:
        return None
    return {
        "session_date": expected_session,
        "status": "in_progress",
        "opening_equity": opening_value,
        "current_equity": current_value,
        "system_pct": current_value / opening_value - 1.0,
        "system_delta": current_value - opening_value,
        "system_start_at": opening.get("observed_at"),
        "system_end_at": current_equity_at.astimezone(timezone.utc).isoformat(),
        "system_source": opening.get("source"),
    }


def opening_performance_context(
    settings: Settings,
    store: Store,
    *,
    intraday_history: Mapping[str, Any] | None = None,
    current_equity: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    persisted = read_session_open_snapshots(store)
    ephemeral = extract_exact_open_snapshots(intraday_history or {})
    account_opens = merge_account_open_snapshots(ephemeral, persisted)
    spy_market = load_cached_spy_open_observations(settings, now=now)
    rows = build_open_to_open_rows(
        account_opens,
        spy_market,
        current_equity=current_equity,
        current_equity_at=current,
    )
    omitted_sessions = build_opening_omissions(account_opens, spy_market, rows)
    account_current = build_current_account_interval(
        account_opens,
        current_equity=current_equity,
        current_equity_at=current,
    )
    final_count = sum(row.get("status") == "final" for row in rows)
    expected_final_count = max(
        len(xnys_sessions_between(account_opens[0]["session_date"], account_opens[-1]["session_date"])) - 1,
        0,
    ) if account_opens else 0
    return {
        "schema_version": "p-l72.opening-performance.v1",
        "rows": rows,
        "account_open_count": len(account_opens),
        "spy_open_count": len(spy_market.get("opens") or []),
        "spy_status": spy_market.get("status"),
        "spy_warnings": list(spy_market.get("warnings") or []),
        "spy_conflicts": dict(spy_market.get("conflicts") or {}),
        "exact_comparison_count": len(rows),
        "final_comparison_count": final_count,
        "omitted_session_count": max(expected_final_count - final_count, 0),
        "omitted_sessions": omitted_sessions,
        "account_current": account_current,
        "current": rows[-1] if rows and rows[-1]["status"] == "in_progress" else None,
    }
