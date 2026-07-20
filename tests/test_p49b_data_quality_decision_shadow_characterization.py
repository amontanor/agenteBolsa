"""Caracterización aislada del contrato P-L49B.

Este módulo contiene únicamente helpers de prueba. No importa el wiring de
decisión productivo ni escribe en Store, SQLite o runtime_state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.config import Settings

SCHEMA_VERSION = "p-l49b.data-quality-decision-shadow.v1"
CONTRACT_VERSION = SCHEMA_VERSION
DECISION_AT = datetime(2026, 7, 20, 13, 55, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FrozenClock:
    """Reloj explícito para impedir dependencia del reloj del host."""

    now_value: datetime

    def now(self) -> datetime:
        return self.now_value


@dataclass
class CandidateFixture:
    symbol: str
    signal_capture_id: str | None
    signal_id: str | None
    candidate_id: str | None
    cycle_id: str
    market_observation_id: str | None
    side: str = "buy"
    legacy_stage_reached: str = "selected"
    legacy_selected: bool = False
    legacy_recommended: bool = False
    legacy_planned: bool = False
    legacy_ordered: bool = False
    score: float | None = 15.0
    rank: int | None = 1


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_content_hash(payload: dict[str, Any]) -> str:
    """Hash estable; captured_at queda fuera del contenido canónico."""

    body = {key: value for key, value in payload.items() if key != "captured_at"}
    encoded = json.dumps(_jsonable(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalise_columns(columns: Any) -> tuple[str, ...]:
    """Representa columnas planas y MultiIndex sin consultar proveedores."""

    result = []
    for column in columns:
        if isinstance(column, tuple):
            result.append("|".join(str(part) for part in column if str(part) != "nan"))
        else:
            result.append(str(column))
    return tuple(result)


def market_observation_id(observation: dict[str, Any]) -> str | None:
    """Identidad de mercado que evita unir solo por símbolo/fecha."""

    required = ("provider", "symbol", "interval", "bar_timestamp", "price_basis")
    if any(not observation.get(field) for field in required):
        return None
    ohlcv = observation.get("ohlcv") or {}
    normalised = {field: _finite_number(ohlcv.get(field)) for field in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in normalised.values()):
        return None
    body = {
        "contract_version": CONTRACT_VERSION,
        "provider": observation["provider"],
        "symbol": str(observation["symbol"]).upper(),
        "interval": observation["interval"],
        "bar_timestamp": observation["bar_timestamp"],
        "price_basis": observation["price_basis"],
        "ohlcv": normalised,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _temporal_quality(observation: dict[str, Any], *, decision_at: datetime) -> tuple[str, str | None]:
    raw_timestamp = observation.get("bar_timestamp")
    raw_as_of = observation.get("as_of")
    if not raw_timestamp or not raw_as_of:
        return "unavailable_temporal", "missing_timestamp_or_as_of"
    try:
        bar_timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        as_of = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
    except ValueError:
        return "unavailable_temporal", "invalid_timestamp"
    if bar_timestamp.tzinfo is None or as_of.tzinfo is None:
        return "unavailable_temporal", "naive_timestamp"
    if bar_timestamp > decision_at or as_of > decision_at:
        return "unavailable_temporal", "observation_after_decision"
    return "eligible", None


def shadow_entry_decision(
    candidate: CandidateFixture,
    observation: dict[str, Any] | None,
    *,
    decision_at: datetime = DECISION_AT,
) -> dict[str, Any]:
    """Comparación shadow preregistrada; nunca muta candidate ni activa gates."""

    if candidate.side.lower() == "sell":
        return {"shadow_entry_eligible": None, "shadow_reason": "not_applicable_exit", "identity_quality": "not_applicable"}
    if observation is None or not candidate.market_observation_id:
        return {"shadow_entry_eligible": None, "shadow_reason": "unavailable_identity", "identity_quality": "unavailable"}
    observation_id = market_observation_id(observation)
    if observation_id is None or observation_id != candidate.market_observation_id:
        return {"shadow_entry_eligible": None, "shadow_reason": "unavailable_identity", "identity_quality": "conflict"}
    if observation.get("cycle_id") not in (None, candidate.cycle_id):
        return {"shadow_entry_eligible": None, "shadow_reason": "unavailable_identity", "identity_quality": "conflict"}
    temporal_status, temporal_warning = _temporal_quality(observation, decision_at=decision_at)
    if temporal_status != "eligible":
        return {
            "shadow_entry_eligible": None,
            "shadow_reason": temporal_status,
            "identity_quality": "verified",
            "temporal_quality": temporal_status,
            "warnings": [temporal_warning],
        }
    quality = str(observation.get("quality_status") or "")
    if quality in {"blocking", "ohlc_invalid", "stale", "incomplete"}:
        return {
            "shadow_entry_eligible": False,
            "shadow_reason": "blocked_exact_quality",
            "identity_quality": "verified",
            "temporal_quality": "eligible",
            "warnings": [],
        }
    return {
        "shadow_entry_eligible": True,
        "shadow_reason": "eligible",
        "identity_quality": "verified",
        "temporal_quality": "eligible",
        "warnings": [],
    }


def build_shadow_detail(candidate: CandidateFixture, observation: dict[str, Any] | None) -> dict[str, Any]:
    decision = shadow_entry_decision(candidate, observation)
    detail = {
        "symbol": candidate.symbol,
        "market_data_observation_id": candidate.market_observation_id,
        "provider": observation.get("provider") if observation else None,
        "bar_timestamp": observation.get("bar_timestamp") if observation else None,
        "bar_date": observation.get("bar_date") if observation else None,
        "price_basis": observation.get("price_basis") if observation else None,
        "data_as_of": observation.get("as_of") if observation else None,
        "quality_status": observation.get("quality_status") if observation else None,
        "invalid_fields": list(observation.get("invalid_fields") or []) if observation else [],
        "invalidity_class": observation.get("invalidity_class") if observation else None,
        "blocking_reason": observation.get("blocking_reason") if observation else None,
        "signal_capture_id": candidate.signal_capture_id,
        "signal_id": candidate.signal_id,
        "candidate_id": candidate.candidate_id,
        "cycle_id": candidate.cycle_id,
        "legacy_stage_reached": candidate.legacy_stage_reached,
        "legacy_selected": candidate.legacy_selected,
        "legacy_recommended": candidate.legacy_recommended,
        "legacy_planned": candidate.legacy_planned,
        "legacy_ordered": candidate.legacy_ordered,
    }
    detail.update(decision)
    detail.setdefault("warnings", [])
    detail.setdefault("temporal_quality", None)
    return detail


def build_contract_snapshot(
    observations: list[dict[str, Any]],
    candidates: list[CandidateFixture],
    *,
    cycle_id: str,
    captured_at: str = "2026-07-20T14:00:00+00:00",
    source: str = "local_fixture",
) -> dict[str, Any]:
    by_id = {
        observation_id: item
        for item in observations
        if (observation_id := market_observation_id(item)) is not None
    }
    details = [build_shadow_detail(candidate, by_id.get(candidate.market_observation_id)) for candidate in candidates]
    blocking = sum(item["shadow_reason"] == "blocked_exact_quality" for item in details)
    unavailable = sum(item["shadow_reason"] in {"unavailable_identity", "unavailable_temporal"} for item in details)
    unchanged = sum(item["shadow_reason"] == "eligible" for item in details)
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "captured_at": captured_at,
        "content_hash": "",
        "market_data_snapshot_id": "snapshot_fixture_20260720",
        "source": source,
        "as_of": "2026-07-20T13:54:00+00:00",
        "session_date": "2026-07-20",
        "universe_total": len(observations),
        "symbols_evaluable": len(observations) - sum(item.get("quality_status") == "blocking" for item in observations),
        "symbols_blocking": sum(item.get("quality_status") == "blocking" for item in observations),
        "symbols_unavailable": 0,
        "market_observations": len(observations),
        "exact_observations": len(by_id),
        "blocking_observations": sum(item.get("quality_status") == "blocking" for item in observations),
        "unavailable_observations": len(observations) - len(by_id),
        "candidates_evaluated": len(candidates),
        "candidates_with_exact_quality": sum(item["identity_quality"] == "verified" for item in details),
        "legacy_selected_count": sum(candidate.legacy_selected for candidate in candidates),
        "shadow_blocked_count": blocking,
        "shadow_unchanged_count": unchanged,
        "candidates_shadow_blocked": blocking,
        "candidates_shadow_unchanged": unchanged,
        "candidates_shadow_unavailable": unavailable,
        "recommended_affected": sum(item["legacy_recommended"] and item["shadow_reason"] == "blocked_exact_quality" for item in details),
        "planned_affected": sum(item["legacy_planned"] and item["shadow_reason"] == "blocked_exact_quality" for item in details),
        "ordered_affected": sum(item["legacy_ordered"] and item["shadow_reason"] == "blocked_exact_quality" for item in details),
        "protective_exits_exempt": sum(item["shadow_reason"] == "not_applicable_exit" for item in details),
        "details": details,
        "warnings": ["characterization_only", "no_productive_wiring"],
    }


def quality_observation(
    symbol: str,
    *,
    quality_status: str = "valid",
    cycle_id: str | None = "mkt_fixture",
    bar_timestamp: str = "2026-07-20T13:45:00+00:00",
    as_of: str = "2026-07-20T13:45:05+00:00",
    invalid_fields: list[str] | None = None,
    provider: str = "local_fixture",
    price_basis: str = "unadjusted",
) -> dict[str, Any]:
    observation = {
        "provider": provider,
        "symbol": symbol,
        "interval": "1d",
        "bar_timestamp": bar_timestamp,
        "bar_date": "2026-07-20",
        "price_basis": price_basis,
        "as_of": as_of,
        "cycle_id": cycle_id,
        "quality_status": quality_status,
        "invalid_fields": invalid_fields or [],
        "invalidity_class": "ohlc_invalid" if invalid_fields else None,
        "blocking_reason": "invalid_ohlc" if invalid_fields else None,
        "ohlcv": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
    }
    observation["market_data_observation_id"] = market_observation_id(observation)
    return observation


def _legacy_flow(*, quality: str, affects_operational_scan: bool) -> dict[str, Any]:
    """Reproducción del flujo observado, no una llamada al cycle_runner real."""

    return {
        "market_data": "received",
        "ohlc_validation": "telemetry_only" if affects_operational_scan else "valid",
        "features": "built",
        "market_state_quality": quality,
        "candidate": "created",
        "ranking": "completed",
        "recommendation": "continued" if quality == "PARTIAL" else "blocked",
        "plan": "continued" if quality == "PARTIAL" else "blocked",
        "order": "continued" if quality == "PARTIAL" else "blocked",
    }


def health_freshness(
    report: dict[str, Any] | None,
    *,
    consumer_read_at: datetime,
    expected_session: str,
    source_path: str | None = "data/reports/latest_market_data_quality.json",
    expected_content_hash: str | None = None,
) -> dict[str, Any]:
    if report is None or not source_path:
        return {"freshness_status": "unavailable", "age_seconds": None, "source_path": source_path}
    if report.get("session_date") not in (None, expected_session):
        return {"freshness_status": "stale", "age_seconds": None, "source_path": source_path}
    if expected_content_hash is not None and report.get("content_hash") != expected_content_hash:
        return {"freshness_status": "unavailable", "age_seconds": None, "source_path": source_path}
    try:
        generated_at = datetime.fromisoformat(str(report["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return {"freshness_status": "unavailable", "age_seconds": None, "source_path": source_path}
    age_seconds = (consumer_read_at - generated_at).total_seconds()
    return {
        "report_id": report.get("report_id"),
        "generated_at": report.get("generated_at"),
        "as_of": report.get("as_of"),
        "age_seconds": age_seconds,
        "current_session": expected_session,
        "consumer_read_at": consumer_read_at.isoformat(),
        "source_path": source_path,
        "freshness_status": "fresh" if age_seconds >= 0 else "stale",
    }


def event_write_result(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> str:
    if existing is None:
        return "inserted"
    if existing.get("content_hash") == incoming.get("content_hash"):
        return "noop"
    return "conflict"


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, FrozenClock]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_AUTO_APPLY_IMPROVEMENTS", "false")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "local_fixture")
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        trading_mode="paper",
        allow_live_trading=False,
        allow_auto_apply_improvements=False,
        market_data_provider="local_fixture",
    )
    return settings, FrozenClock(DECISION_AT)


def test_fixture_uses_temporary_data_dir_and_frozen_clock(isolated_runtime: tuple[Settings, FrozenClock]):
    settings, clock = isolated_runtime
    assert settings.data_dir.name == "data"
    assert settings.trading_mode == "paper"
    assert settings.allow_live_trading is False
    assert settings.allow_auto_apply_improvements is False
    assert clock.now() == DECISION_AT


def test_legacy_invalid_selected_technical_continues_and_affects_flag_is_telemetry_only():
    flow = _legacy_flow(quality="PARTIAL", affects_operational_scan=True)
    assert flow["ohlc_validation"] == "telemetry_only"
    assert flow["features"] == "built"
    assert flow["ranking"] == "completed"
    assert flow["recommendation"] == "continued"
    assert flow["plan"] == "continued"


def test_shadow_blocks_only_exact_entry_and_keeps_legacy_unchanged():
    observation = quality_observation("EIX", quality_status="blocking", invalid_fields=["low"])
    candidate = CandidateFixture(
        "EIX", "capture_eix", "signal_eix", None, "mkt_fixture", observation["market_data_observation_id"],
        legacy_selected=True, legacy_recommended=True, legacy_planned=True,
    )
    before = copy.deepcopy(candidate.__dict__)
    detail = build_shadow_detail(candidate, observation)
    assert detail["shadow_reason"] == "blocked_exact_quality"
    assert detail["shadow_entry_eligible"] is False
    assert candidate.__dict__ == before


@pytest.mark.parametrize(
    ("invalid_fields", "quality_status"),
    [
        (["high_below_open"], "blocking"),
        (["low_above_close"], "blocking"),
        (["high_below_low"], "blocking"),
        (["open_null"], "blocking"),
        (["high_nan"], "blocking"),
        (["low_infinity"], "blocking"),
        (["volume_invalid"], "blocking"),
    ],
)
def test_ohlc_invalid_matrix_is_explicit_and_never_unknown(invalid_fields: list[str], quality_status: str):
    observation = quality_observation("TEST", quality_status=quality_status, invalid_fields=invalid_fields)
    candidate = CandidateFixture("TEST", "capture", "signal", "candidate", "mkt_fixture", observation["market_data_observation_id"])
    detail = build_shadow_detail(candidate, observation)
    assert detail["invalidity_class"] == "ohlc_invalid"
    assert detail["shadow_reason"] == "blocked_exact_quality"
    assert detail["shadow_reason"] != "UNKNOWN"


@pytest.mark.parametrize(
    "observation_kwargs",
    [
        {"bar_timestamp": "2026-07-20T13:45:00", "as_of": "2026-07-20T13:45:05+00:00"},
        {"bar_timestamp": "2026-07-20T14:00:00+00:00"},
        {"as_of": "2026-07-20T14:00:00+00:00"},
        {"bar_timestamp": "2026-07-20T13:45:00+00:00", "as_of": "2026-07-20T13:56:00+00:00"},
    ],
)
def test_future_naive_or_missing_timestamps_are_unavailable(observation_kwargs: dict[str, str]):
    observation = quality_observation("TEST", **observation_kwargs)
    candidate = CandidateFixture("TEST", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"])
    detail = build_shadow_detail(candidate, observation)
    assert detail["shadow_reason"] == "unavailable_temporal"
    assert detail["shadow_entry_eligible"] is None


def test_late_report_is_not_applied_retroactively():
    observation = quality_observation("EIX", quality_status="blocking", invalid_fields=["high"], as_of="2026-07-20T14:00:00+00:00")
    candidate = CandidateFixture("EIX", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"])
    detail = build_shadow_detail(candidate, observation)
    assert detail["shadow_reason"] == "unavailable_temporal"
    assert "observation_after_decision" in detail["warnings"]


def test_missing_market_link_is_unavailable_not_blocked():
    candidate = CandidateFixture("MPC", "capture", "signal", None, "mkt_fixture", None)
    detail = build_shadow_detail(candidate, None)
    assert detail["shadow_reason"] == "unavailable_identity"
    assert detail["shadow_entry_eligible"] is None


def test_cycle_conflict_is_unavailable_identity():
    observation = quality_observation("PSX", cycle_id="other_cycle")
    candidate = CandidateFixture("PSX", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"])
    detail = build_shadow_detail(candidate, observation)
    assert detail["shadow_reason"] == "unavailable_identity"
    assert detail["identity_quality"] == "conflict"


def test_eix_mpc_psx_are_finalists_without_recommendation_or_order():
    observations = [quality_observation(symbol) for symbol in ("EIX", "MPC", "PSX")]
    candidates = [
        CandidateFixture(symbol, f"capture_{symbol}", f"signal_{symbol}", None, "mkt_fixture", observation["market_data_observation_id"], rank=index)
        for index, (symbol, observation) in enumerate(zip(("EIX", "MPC", "PSX"), observations, strict=True), start=12)
    ]
    snapshot = build_contract_snapshot(observations, candidates, cycle_id="mkt_fixture")
    assert snapshot["candidates_evaluated"] == 3
    assert all(item["legacy_stage_reached"] == "selected" for item in snapshot["details"])
    assert all(item["legacy_recommended"] is False for item in snapshot["details"])
    assert all(item["legacy_planned"] is False for item in snapshot["details"])
    assert all(item["legacy_ordered"] is False for item in snapshot["details"])


def test_500_symbols_and_37_blocking_anomalies_have_explicit_denominators():
    symbols = [f"SYM{index:03d}" for index in range(500)]
    observations = [quality_observation(symbol, quality_status="blocking" if index < 37 else "valid", invalid_fields=["high"] if index < 37 else []) for index, symbol in enumerate(symbols)]
    candidates = [
        CandidateFixture(symbol, f"capture_{symbol}", f"signal_{symbol}", None, "mkt_fixture", observation["market_data_observation_id"])
        for symbol, observation in zip(symbols, observations, strict=True)
    ]
    snapshot = build_contract_snapshot(observations, candidates, cycle_id="mkt_fixture")
    assert snapshot["universe_total"] == 500
    assert snapshot["symbols_blocking"] == 37
    assert snapshot["symbols_evaluable"] == 463
    assert snapshot["shadow_blocked_count"] == 37
    assert snapshot["shadow_unchanged_count"] == 463
    assert snapshot["candidates_shadow_unavailable"] == 0
    assert snapshot["shadow_blocked_count"] + snapshot["shadow_unchanged_count"] == snapshot["candidates_evaluated"]


def test_healthy_symbol_coexists_with_invalid_symbol():
    bad = quality_observation("EIX", quality_status="blocking", invalid_fields=["low"])
    good = quality_observation("WELL")
    candidates = [
        CandidateFixture("EIX", "cap_eix", "sig_eix", None, "mkt_fixture", bad["market_data_observation_id"]),
        CandidateFixture("WELL", "cap_well", "sig_well", None, "mkt_fixture", good["market_data_observation_id"]),
    ]
    snapshot = build_contract_snapshot([bad, good], candidates, cycle_id="mkt_fixture")
    assert [item["shadow_reason"] for item in snapshot["details"]] == ["blocked_exact_quality", "eligible"]


def test_risk_sell_and_four_time_stop_exits_are_not_applicable_to_entry_shadow():
    observation = quality_observation("DDOG", quality_status="blocking", invalid_fields=["close"])
    candidates = [
        CandidateFixture(f"EXIT{index}", None, None, None, "mkt_fixture", None, side="sell")
        for index in range(4)
    ]
    details = [build_shadow_detail(candidate, observation) for candidate in candidates]
    assert [item["shadow_reason"] for item in details] == ["not_applicable_exit"] * 4
    assert all(item["shadow_entry_eligible"] is None for item in details)


def test_market_identity_distinguishes_provider_basis_timestamp_revision_and_columns():
    base = quality_observation("EIX")
    assert market_observation_id(base) != market_observation_id({**base, "provider": "other_provider"})
    assert market_observation_id(base) != market_observation_id({**base, "price_basis": "adjusted"})
    assert market_observation_id(base) != market_observation_id({**base, "bar_timestamp": "2026-07-20T13:46:00+00:00"})
    assert _normalise_columns([("price", "close"), ("price", "open")]) == ("price|close", "price|open")
    assert _normalise_columns(["open", "close"]) == ("open", "close")


def test_duplicate_identical_and_conflicting_observations_are_separate_cases():
    observation = quality_observation("EIX")
    duplicate = copy.deepcopy(observation)
    conflicting = {**observation, "price_basis": "adjusted"}
    assert market_observation_id(observation) == market_observation_id(duplicate)
    assert market_observation_id(observation) != market_observation_id(conflicting)


def test_health_freshness_distinguishes_latest_stale_and_missing_paths():
    read_at = datetime(2026, 7, 20, 14, 1, tzinfo=timezone.utc)
    latest = {"report_id": "quality_latest", "generated_at": "2026-07-20T14:00:00+00:00", "as_of": "2026-07-20T13:59:00+00:00", "session_date": "2026-07-20"}
    stale = {"report_id": "quality_old", "generated_at": "2026-07-19T14:00:00+00:00", "as_of": "2026-07-19T13:59:00+00:00", "session_date": "2026-07-19"}
    assert health_freshness(latest, consumer_read_at=read_at, expected_session="2026-07-20")["freshness_status"] == "fresh"
    assert health_freshness(stale, consumer_read_at=read_at, expected_session="2026-07-20")["freshness_status"] == "stale"
    assert health_freshness(None, consumer_read_at=read_at, expected_session="2026-07-20")["freshness_status"] == "unavailable"
    assert health_freshness(latest, consumer_read_at=read_at, expected_session="2026-07-20", source_path=None)["freshness_status"] == "unavailable"
    assert health_freshness({**latest, "content_hash": "wrong"}, consumer_read_at=read_at, expected_session="2026-07-20", expected_content_hash="expected")["freshness_status"] == "unavailable"


def test_health_can_read_old_report_while_latest_is_newer():
    read_at = datetime(2026, 7, 20, 14, 1, tzinfo=timezone.utc)
    old = {"report_id": "old", "generated_at": "2026-07-19T14:00:00+00:00", "as_of": "2026-07-19T13:59:00+00:00", "session_date": "2026-07-19"}
    latest = {"report_id": "latest", "generated_at": "2026-07-20T14:00:00+00:00", "as_of": "2026-07-20T13:59:00+00:00", "session_date": "2026-07-20"}
    assert health_freshness(old, consumer_read_at=read_at, expected_session="2026-07-20")["freshness_status"] == "stale"
    assert health_freshness(latest, consumer_read_at=read_at, expected_session="2026-07-20")["freshness_status"] == "fresh"


def test_idempotency_hash_excludes_captured_at_and_is_key_order_independent():
    payload = {"schema_version": SCHEMA_VERSION, "cycle_id": "mkt_a", "captured_at": "2026-07-20T14:00:00Z", "details": [{"symbol": "EIX", "quality_status": "blocking"}]}
    reordered = {"details": payload["details"], "cycle_id": "mkt_a", "schema_version": SCHEMA_VERSION, "captured_at": "2026-07-20T15:00:00Z"}
    first = {**payload, "content_hash": canonical_content_hash(payload)}
    second = {**reordered, "content_hash": canonical_content_hash(reordered)}
    assert first["content_hash"] == second["content_hash"]
    assert event_write_result(first, second) == "noop"
    conflict = {**second, "details": [{"symbol": "EIX", "quality_status": "valid"}]}
    conflict["content_hash"] = canonical_content_hash(conflict)
    assert event_write_result(first, conflict) == "conflict"


def test_two_cycles_providers_and_revision_never_collapse_to_one_observation():
    a = quality_observation("EIX", cycle_id="mkt_a")
    b = quality_observation("EIX", cycle_id="mkt_b", provider="other_provider")
    c = quality_observation("EIX", cycle_id="mkt_a", bar_timestamp="2026-07-20T13:46:00+00:00")
    assert len({market_observation_id(item) for item in (a, b, c)}) == 3


@pytest.mark.parametrize("status", ["stale", "incomplete"])
def test_stale_previous_session_and_incomplete_bars_are_exact_shadow_cases(status: str):
    observation = quality_observation("EIX", quality_status=status, invalid_fields=["close"])
    observation["bar_date"] = "2026-07-17"
    observation["session_status"] = "early_close"
    candidate = CandidateFixture("EIX", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"])
    detail = build_shadow_detail(candidate, observation)
    assert detail["shadow_reason"] == "blocked_exact_quality"
    assert detail["temporal_quality"] == "eligible"


def test_early_close_is_not_invalid_when_quality_is_valid_and_session_is_verifiable():
    observation = quality_observation("WELL")
    observation["session_status"] = "early_close"
    candidate = CandidateFixture("WELL", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"])
    assert build_shadow_detail(candidate, observation)["shadow_reason"] == "eligible"


def test_shadow_helpers_do_not_mutate_active_decision_fields():
    candidate = CandidateFixture("EIX", "capture", "signal", "candidate", "mkt_fixture", None, legacy_selected=True, legacy_recommended=True, legacy_planned=True, legacy_ordered=False, score=16, rank=3)
    before = copy.deepcopy(candidate.__dict__)
    result = shadow_entry_decision(candidate, None)
    assert result["shadow_reason"] == "unavailable_identity"
    assert candidate.__dict__ == before
    assert candidate.score == 16
    assert candidate.rank == 3


def test_parity_invariants_cover_trading_and_shadow_lots():
    active = {
        "scores": {"EIX": 16},
        "ranks": {"EIX": 12},
        "recommendations": [],
        "gates": {"entry_quality": "legacy"},
        "sizing": {"EIX": 0.5},
        "plans": [],
        "orders": [],
        "stops": {"EIX": 95.0},
        "takes": {"EIX": 110.0},
        "exposure": 0.10,
        "policies": {"p43": "legacy_calendar_days", "p44": "legacy_double_application", "p45": "batch_250", "p47": "lease_v1", "p48": "canonical_telemetry"},
    }
    before = copy.deepcopy(active)
    observation = quality_observation("EIX", quality_status="blocking", invalid_fields=["high"])
    shadow_entry_decision(CandidateFixture("EIX", "capture", "signal", None, "mkt_fixture", observation["market_data_observation_id"]), observation)
    assert active == before


def test_base_legacy_without_contract_is_unavailable_not_zero():
    snapshot = build_contract_snapshot([], [], cycle_id="legacy_cycle")
    snapshot["universe_total"] = None
    snapshot["symbols_evaluable"] = None
    snapshot["symbols_blocking"] = None
    snapshot["symbols_unavailable"] = None
    snapshot["candidates_evaluated"] = None
    assert snapshot["universe_total"] is None
    assert snapshot["details"] == []


def test_proposed_schema_contains_required_top_level_fields():
    snapshot = build_contract_snapshot([], [], cycle_id="mkt_fixture")
    assert set(snapshot) >= {
        "schema_version", "cycle_id", "captured_at", "content_hash", "market_data_snapshot_id",
        "source", "as_of", "session_date", "universe_total", "symbols_evaluable", "symbols_blocking",
        "symbols_unavailable", "candidates_evaluated", "legacy_selected_count", "shadow_blocked_count",
        "shadow_unchanged_count", "market_observations", "exact_observations", "blocking_observations",
        "unavailable_observations", "candidates_with_exact_quality", "candidates_shadow_unavailable",
        "recommended_affected", "planned_affected", "ordered_affected", "protective_exits_exempt", "details", "warnings",
    }
    assert snapshot["schema_version"] == SCHEMA_VERSION
