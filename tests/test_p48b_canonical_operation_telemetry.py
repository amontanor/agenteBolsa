"""Pruebas productivas aisladas del contrato canónico P-L48B."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_p48b_canonical_operation_telemetry_characterization import _raw_fixture

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_operation_telemetry import (
    SCHEMA_VERSION,
    _stable_hash,
    build_canonical_operation_telemetry,
    persist_canonical_operation_telemetry,
    read_canonical_operation_telemetry,
)
from agente_bolsa.tools.performance_baseline import build_daily_performance

CAPTURED_AT = datetime(2026, 7, 18, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def test_real_fixture_has_expected_canonical_denominators() -> None:
    fixture = _raw_fixture()
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["denominators"] == {
        "broker_order_count": 8,
        "buy_order_count": 7,
        "sell_order_count": 1,
        "fill_fragment_count": 16,
        "signal_count": 7,
        "candidate_count": 7,
        "recommendation_count": 7,
        "plan_count": 8,
    }
    assert result["exits"] == {
        "automatic_exit_count": 1,
        "manual_exit_count": 0,
        "unknown_exit_origin_count": 0,
        "by_normalized_origin": {"automatic_stop_loss": 1},
    }


def test_anet_keeps_two_fragments_and_normalized_stop_loss() -> None:
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    anet = next(item for item in result["operations"] if item["symbol"] == "ANET")
    assert anet["broker_order_id"] == "bo-anet-17"
    assert anet["fill_fragment_count"] == 2
    assert anet["raw_exit_trigger"] == "stop_loss"
    assert anet["normalized_exit_origin"] == "automatic_stop_loss"


def test_hash_excludes_capture_time_but_not_content() -> None:
    fixture = _raw_fixture()
    one = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    two = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT.replace(hour=12))
    assert one["content_hash"] == two["content_hash"]
    changed = copy.deepcopy(one)
    changed["denominators"]["broker_order_count"] = 9
    assert _stable_hash(changed) != one["content_hash"]


def test_append_only_persistence_is_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = build_canonical_operation_telemetry(None, "2026-07-17", source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    assert persist_canonical_operation_telemetry(store, snapshot)["status"] == "inserted"
    assert persist_canonical_operation_telemetry(store, copy.deepcopy(snapshot))["status"] == "idempotent"
    changed = copy.deepcopy(snapshot)
    changed["data_quality_warnings"] = ["changed"]
    changed["content_hash"] = _stable_hash(changed)
    conflict = persist_canonical_operation_telemetry(store, changed)
    assert conflict["status"] == "conflict"
    assert read_canonical_operation_telemetry(store, "2026-07-17")["content_hash"] == snapshot["content_hash"]
    events = store.agent_events(event_type_prefix="canonical_operation_telemetry", limit=20)
    assert len(events) == 2
    store.close_read_connection()


def test_capture_timestamp_is_outside_idempotency_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = build_canonical_operation_telemetry(None, "2026-07-17", source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    second = build_canonical_operation_telemetry(None, "2026-07-17", source_data=_raw_fixture(), captured_at=CAPTURED_AT.replace(hour=12))
    assert first["content_hash"] == second["content_hash"]
    assert persist_canonical_operation_telemetry(store, first)["status"] == "inserted"
    assert persist_canonical_operation_telemetry(store, second)["status"] == "idempotent"


def test_missing_event_is_collecting_with_null_denominators(tmp_path: Path) -> None:
    store = _store(tmp_path)
    report = read_canonical_operation_telemetry(store, "2026-07-18")
    assert report["status"] == "collecting"
    assert report["denominators"] is None


def test_pending_position_without_exact_link_does_not_confirm_fill() -> None:
    fixture = {
        "broker_orders": [{
            "broker_order_id": "pending-1", "client_order_id": "client-pending-1", "symbol": "BBY",
            "side": "buy", "status": "PENDING_NEW", "cycle_id": "cycle", "submitted_qty": 2,
            "position_observed": True,
        }],
        "fill_fragments": [],
    }
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    operation = result["operations"][0]
    assert operation["reconciliation_status"] == "position_observed_without_exact_order_link"
    assert result["execution"]["filled_count"] == 0


def test_invalid_timestamps_and_nonfinite_prices_are_unavailable() -> None:
    fixture = _raw_fixture()
    fixture["broker_orders"][0]["signal_at"] = "2026-07-17T16:00:00"
    fixture["broker_orders"][0]["signal_price"] = float("nan")
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    freshness = next(item for item in result["operations"] if item["symbol"] == "CRWD")["freshness"]
    assert freshness["signal_price"] is None
    assert freshness["freshness_status"] == "unavailable"
    assert any("naive_timestamp" in warning or "invalid" in warning for warning in freshness["warnings"])


def test_equal_prices_do_not_claim_refresh() -> None:
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=_raw_fixture(), captured_at=CAPTURED_AT)
    assert all(item["freshness"]["price_refresh_status"] == "unverified" for item in result["operations"])


def test_source_data_is_not_mutated_and_forbidden_fields_do_not_leak() -> None:
    fixture = _raw_fixture()
    fixture["broker_orders"][0]["pnl"] = 10
    before = copy.deepcopy(fixture)
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    assert fixture == before
    encoded = str(result).lower()
    assert "mfe" not in encoded and "mae" not in encoded and "llm_response" not in encoded


class _PerformanceStore:
    def performance_daily(self, *, limit: int) -> list[dict[str, object]]:
        return []

    def signal_outcomes(self, **_: object) -> list[dict[str, object]]:
        return [{"signal_date": "2026-07-17", "decision": "candidate"}]

    def continuous_improvement_applied_changes(self, **_: object) -> list[dict[str, object]]:
        return []


def test_performance_consumes_canonical_counts_without_recounting_signals() -> None:
    telemetry = build_canonical_operation_telemetry(None, "2026-07-17", source_data={"broker_orders": _raw_fixture()["broker_orders"], "fill_fragments": _raw_fixture()["fill_fragments"], "signal_count": 7, "candidate_count": 7, "recommendation_count": 7, "plan_count": 8}, captured_at=CAPTURED_AT)
    payload = build_daily_performance(_PerformanceStore(), object(), "2026-07-17", canonical_telemetry=telemetry)
    assert payload["canonical_buy_order_count"] == 7
    assert payload["canonical_sell_order_count"] == 1
    assert payload["process_metrics"]["legacy_actionable_signal_count"] == 0


def test_duplicate_ids_are_reported_without_creating_extra_operations() -> None:
    fixture = _raw_fixture()
    fixture["broker_orders"].append(copy.deepcopy(fixture["broker_orders"][0]))
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    assert result["denominators"]["broker_order_count"] == 8
    assert any("duplicate_broker_order_id" in warning for warning in result["data_quality_warnings"])


@pytest.mark.parametrize("raw, expected", [("stop_loss", "automatic_stop_loss"), ("take_profit", "automatic_take_profit"), ("trailing_stop", "automatic_trailing_stop"), ("time_stop_v2", "automatic_time_stop"), ("manual", "manual"), ("invalid", "unknown_exit_origin")])
def test_exit_matrix(raw: str, expected: str) -> None:
    fixture = {"broker_orders": [{"broker_order_id": raw, "symbol": "X", "side": "sell", "status": "filled", "exit_trigger": raw}], "fill_fragments": []}
    result = build_canonical_operation_telemetry(None, "2026-07-17", source_data=fixture, captured_at=CAPTURED_AT)
    assert result["operations"][0]["normalized_exit_origin"] == expected
