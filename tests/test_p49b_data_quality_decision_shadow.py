"""Productive P-L49B shadow contract tests using only temporary SQLite."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa.storage import Store
from agente_bolsa.tools.data_quality_decision_shadow import (
    SCHEMA_VERSION,
    canonical_content_hash,
    capture_data_quality_phase_a,
    data_quality_decision_shadow_digest,
    finalize_data_quality_phase_b,
    market_data_observation_id,
    persist_data_quality_decision_shadow,
    quality_report_freshness,
    read_data_quality_decision_shadow,
)

DECISION = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def observation(symbol: str, *, quality: str = "valid", as_of: str = "2026-07-20T13:59:00+00:00") -> dict:
    row = {
        "provider": "fixture",
        "symbol": symbol,
        "interval": "1d",
        "bar_timestamp": "2026-07-20T13:55:00+00:00",
        "bar_date": "2026-07-20",
        "price_basis": "unadjusted",
        "as_of": as_of,
        "quality_status": quality,
        "invalid_fields": ["high"] if quality == "blocking" else [],
        "invalidity_class": "ohlc_invalid" if quality == "blocking" else None,
        "blocking_reason": "invalid_ohlc" if quality == "blocking" else None,
        "ohlcv": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
    }
    row["market_data_observation_id"] = market_data_observation_id(row)
    return row


def candidate(symbol: str, row: dict, *, side: str = "buy", **extra: object) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "signal_capture_id": f"capture_{symbol}",
        "signal_id": f"signal_{symbol}",
        "candidate_id": extra.pop("candidate_id", f"candidate_{symbol}"),
        "cycle_id": "cycle_1",
        "market_data_observation_id": row.get("market_data_observation_id"),
        **extra,
    }


def test_phase_a_exact_identity_and_blocking_are_shadow_only():
    bad = observation("EIX", quality="blocking")
    good = observation("WELL")
    active = candidate("EIX", bad, legacy_selected=True)
    phase = capture_data_quality_phase_a(
        cycle_id="cycle_1",
        market_snapshot={"provider": "fixture", "symbols": {"EIX": {}, "WELL": {}}, "observations": [bad, good]},
        candidates=[active, candidate("WELL", good)],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    assert phase["schema_version"] == SCHEMA_VERSION
    assert [item["shadow_reason"] for item in phase["details"]] == ["blocked_exact_quality", "eligible"]
    assert phase["denominators"]["shadow_blocked_count"] == 1
    assert active["legacy_selected"] is True


def test_identity_is_not_reconstructed_by_symbol_and_late_observation_is_unavailable():
    row = observation("EIX")
    candidate_row = candidate("EIX", row)
    candidate_row["market_data_observation_id"] = "different-observation"
    phase = capture_data_quality_phase_a(
        cycle_id="cycle_1",
        market_snapshot={"observations": [row]},
        candidates=[candidate_row],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    assert phase["details"][0]["shadow_reason"] == "unavailable_identity"
    late = observation("EIX", quality="blocking", as_of="2026-07-20T14:01:00+00:00")
    phase = capture_data_quality_phase_a(
        cycle_id="cycle_1", market_snapshot={"observations": [late]}, candidates=[candidate("EIX", late)], decision_at=DECISION, captured_at=DECISION
    )
    assert phase["details"][0]["shadow_reason"] == "unavailable_temporal"


def test_sell_time_stop_exits_are_exempt_from_entry_shadow():
    rows = [observation(symbol, quality="blocking") for symbol in ("DDOG", "BNY", "JPM", "BAC")]
    phase = capture_data_quality_phase_a(
        cycle_id="cycle_1",
        market_snapshot={"observations": rows},
        candidates=[candidate(row["symbol"], row, side="sell") for row in rows],
        decision_at=DECISION,
        captured_at=DECISION,
    )
    assert [item["shadow_reason"] for item in phase["details"]] == ["not_applicable_exit"] * 4
    assert phase["denominators"]["protective_exits_exempt"] == 4


def test_phase_b_matches_only_exact_lineage_and_never_symbol():
    row = observation("EIX", quality="blocking")
    phase = capture_data_quality_phase_a(cycle_id="cycle_1", market_snapshot={"observations": [row]}, candidates=[candidate("EIX", row)], decision_at=DECISION, captured_at=DECISION)
    unrelated = {"symbol": "EIX", "action": "buy", "cycle_id": "cycle_1"}
    final = finalize_data_quality_phase_b(phase, recommendations=[unrelated], cycle_id="cycle_1")
    assert final["denominators"]["recommended_affected"] == 0
    exact = {"signal_id": "signal_EIX", "cycle_id": "cycle_1", "action": "buy"}
    final = finalize_data_quality_phase_b(phase, recommendations=[exact], plans=[{"signal_id": "signal_EIX", "cycle_id": "cycle_1", "plan_id": "plan_eix"}], cycle_id="cycle_1")
    assert final["denominators"]["recommended_affected"] == 1
    assert final["denominators"]["planned_affected"] == 1


def test_detail_limit_keeps_blocking_and_selected_rows():
    rows = [observation(f"SYM{i}", quality="blocking" if i == 0 else "valid") for i in range(4)]
    candidates = [candidate(row["symbol"], row, legacy_selected=i == 0) for i, row in enumerate(rows)]
    phase = capture_data_quality_phase_a(cycle_id="cycle_1", market_snapshot={"observations": rows}, candidates=candidates, decision_at=DECISION, captured_at=DECISION, detail_limit=1)
    assert phase["details_included"] == 1
    assert phase["details_omitted"] == 3
    assert phase["blocking_details_included"] == 1


def test_append_only_idempotency_and_conflict(tmp_path: Path):
    store = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    store.ensure_schema()
    row = observation("EIX", quality="blocking")
    snapshot = capture_data_quality_phase_a(cycle_id="cycle_1", market_snapshot={"observations": [row]}, candidates=[candidate("EIX", row)], decision_at=DECISION, captured_at=DECISION)
    final = finalize_data_quality_phase_b(snapshot, cycle_id="cycle_1")
    assert persist_data_quality_decision_shadow(store, final)["status"] == "inserted"
    assert persist_data_quality_decision_shadow(store, copy.deepcopy(final))["status"] == "idempotent"
    conflict = copy.deepcopy(final)
    conflict["warnings"] = ["different"]
    conflict["content_hash"] = canonical_content_hash(conflict)
    result = persist_data_quality_decision_shadow(store, conflict)
    assert result["status"] == "conflict"
    assert read_data_quality_decision_shadow(store, "cycle_1")["content_hash"] == final["content_hash"]
    digest = data_quality_decision_shadow_digest(store, "cycle_1")
    assert digest["conflict_events"] == 1


def test_no_event_is_collecting_with_null_denominators(tmp_path: Path):
    store = Store(tmp_path / "state.sqlite", tmp_path / "logs")
    store.ensure_schema()
    report = read_data_quality_decision_shadow(store, "missing")
    assert report["status"] == "collecting"
    assert report["denominators"] is None


def test_health_freshness_does_not_accept_future_or_wrong_session():
    read_at = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
    latest = {"report_id": "quality", "generated_at": "2026-07-20T13:59:00+00:00", "as_of": "2026-07-20T13:58:00+00:00", "session_date": "2026-07-20"}
    assert quality_report_freshness(latest, consumer_read_at=read_at, expected_session="2026-07-20", source_path="latest.json")["freshness_status"] == "fresh"
    assert quality_report_freshness({**latest, "session_date": "2026-07-19"}, consumer_read_at=read_at, expected_session="2026-07-20", source_path="latest.json")["freshness_status"] == "stale"


def test_nan_and_infinity_never_create_market_identity():
    row = observation("EIX")
    row["ohlcv"]["high"] = float("nan")
    assert market_data_observation_id(row) is None
