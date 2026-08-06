"""Sanitized, atomic carrier for the independent Kindle page.

The producer is called from the already scheduled portfolio watch after its
canonical PortfolioSnapshot has been acquired.  The HTTP reader only consumes
the published JSON and never imports broker, storage, Streamlit or LLM code.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .equity_metrics import daily_equity_change

SCHEMA_VERSION = "p-l86.kindle-snapshot.v1"
DEFAULT_RELATIVE_PATH = Path("data") / "state" / "kindle_snapshot.json"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def snapshot_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "state" / "kindle_snapshot.json"


def _position_payload(position: Any) -> dict[str, Any]:
    return {
        "symbol": str(getattr(position, "symbol", "") or "").strip().upper() or None,
        "qty": _finite(getattr(position, "qty", None)),
        "avg_entry_price": _finite(getattr(position, "avg_entry_price", None)),
        "current_price": _finite(getattr(position, "current_price", None)),
        "total_pl_pct": _finite(getattr(position, "unrealized_plpc", None)),
        "today_pl_pct": _finite(getattr(position, "unrealized_intraday_plpc", None)),
    }


def _benchmark_payload(
    benchmark: Mapping[str, Any] | None,
    *,
    captured_at: datetime,
) -> dict[str, Any]:
    value = dict(benchmark or {})
    status = str(value.get("status") or "unavailable").strip().lower()
    as_of = value.get("as_of")
    if status != "comparable" or not as_of:
        return {
            "symbol": "SPY",
            "pct": None,
            "status": "unavailable",
            "reason": str(value.get("reason") or "spy_not_comparable"),
            "as_of": as_of,
            "source": value.get("source"),
        }
    return {
        "symbol": str(value.get("symbol") or "SPY").upper(),
        "pct": _finite(value.get("pct")),
        "status": "comparable" if _finite(value.get("pct")) is not None else "unavailable",
        "reason": None if _finite(value.get("pct")) is not None else "spy_return_unavailable",
        "as_of": str(as_of),
        "source": value.get("source"),
        "window_start": value.get("window_start"),
        "window_end": value.get("window_end") or captured_at.isoformat(),
    }


def benchmark_from_performance(performance: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project the already-built canonical EOD benchmark for Kindle.

    A performance row is accepted only when its own EOD authority and
    comparability contract are valid.  Intraday or legacy scalar fields are
    deliberately not promoted to the LAN page.
    """

    row = dict(performance or {})
    contract = row.get("performance_benchmark")
    if not isinstance(contract, Mapping):
        contract = (row.get("payload") or {}).get("performance_benchmark")
    if not isinstance(contract, Mapping):
        return {"status": "unavailable", "reason": "spy_performance_contract_unavailable"}
    benchmark = contract.get("benchmark")
    if not isinstance(benchmark, Mapping):
        return {"status": "unavailable", "reason": "spy_benchmark_unavailable"}
    quality = benchmark.get("data_quality")
    if isinstance(quality, Mapping):
        quality = quality.get("status") or quality.get("quality")
    authorities = {"confirmed", "eod_final", "next_session_confirmed", "post_session_cache"}
    valid = (
        str(benchmark.get("comparison_status") or "").lower() == "comparable"
        and str(benchmark.get("eod_authority") or "").lower() in authorities
        and str(quality or "").lower() == "available"
        and str(benchmark.get("price_basis") or "") in {"adjusted_ohlc", "close_unadjusted"}
        and bool(str(benchmark.get("source") or "").strip())
        and bool(str(benchmark.get("as_of") or "").strip())
        and _finite(benchmark.get("daily_return")) is not None
    )
    if not valid:
        return {"status": "unavailable", "reason": "spy_eod_not_comparable"}
    return {
        "status": "comparable",
        "symbol": str(benchmark.get("symbol") or "SPY").upper(),
        "pct": _finite(benchmark.get("daily_return")),
        "as_of": benchmark.get("as_of"),
        "source": benchmark.get("source"),
        "window_start": benchmark.get("previous_close_as_of"),
        "window_end": benchmark.get("as_of"),
    }


def build_kindle_snapshot(
    portfolio: Any,
    *,
    captured_at: datetime | None = None,
    benchmark: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build only the fields permitted on the LAN Kindle page.

    ``benchmark`` is intentionally supplied by the producer.  The builder
    never reaches a broker, market-data provider, SQLite database or LLM.
    """

    captured = _utc(captured_at)
    equity = _finite(getattr(portfolio, "portfolio_value", None)) if portfolio is not None else None
    previous = _finite(getattr(portfolio, "previous_close_equity", None)) if portfolio is not None else None
    daily = daily_equity_change(equity, previous, source="Alpaca account.last_equity")
    positions = []
    if portfolio is not None:
        positions = [_position_payload(item) for item in (getattr(portfolio, "positions", None) or [])]
    positions = sorted(positions, key=lambda item: str(item.get("symbol") or ""))
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured.isoformat(),
        "as_of": captured.isoformat(),
        "portfolio": {
            "amount": _finite(daily.get("daily_equity_pl")),
            "pct": _finite(daily.get("daily_equity_return")),
            "current_equity": equity,
            "previous_close_equity": previous,
            "source": daily.get("source"),
            "status": "available" if daily.get("status") == "available" else "unavailable",
            "reason": daily.get("reason"),
        },
        "benchmark": _benchmark_payload(benchmark, captured_at=captured),
        "positions": positions,
    }
    stable = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["content_hash"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return payload


def publish_kindle_snapshot(
    data_dir: str | Path,
    portfolio: Any,
    *,
    captured_at: datetime | None = None,
    benchmark: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish a sanitized snapshot atomically; return a fail-open status."""

    target = snapshot_path(data_dir)
    payload = build_kindle_snapshot(portfolio, captured_at=captured_at, benchmark=benchmark)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception as exc:  # noqa: BLE001 - Kindle is observational/fail-open.
        try:
            if "temporary" in locals():
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "failed_open", "reason": f"publish_failed:{type(exc).__name__}"}
    return {"status": "published", "path": str(target), "content_hash": payload["content_hash"]}


def read_kindle_snapshot(path: str | Path) -> dict[str, Any] | None:
    """Read and validate a snapshot without creating or changing anything."""

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    content_hash = payload.get("content_hash")
    stable = dict(payload)
    stable.pop("content_hash", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if not isinstance(content_hash, str) or hashlib.sha256(encoded.encode("utf-8")).hexdigest() != content_hash:
        return None
    return payload
