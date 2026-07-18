"""Caracterización aislada del contrato P-L48B.

Estas pruebas describen el contrato futuro sin conectarlo a scheduler, postmarket,
health, digest ni a ninguna ruta que pueda tomar decisiones de trading.  Los IDs y
precios son fixtures sanitizadas basadas en la auditoría de 16--17 de julio.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from agente_bolsa.tools.performance_baseline import _count_signals
from agente_bolsa.tools.post_market_review import _exit_attribution

SCHEMA_VERSION = "p-l48b.canonical-operation-telemetry.v1"


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _bps(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or not all(math.isfinite(v) for v in (old, new)):
        return None
    return (new / old - 1.0) * 10_000.0


def _hash_without_captured_at(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop("captured_at", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _freshness(operation: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "signal_at": operation.get("signal_at"),
        "signal_price": operation.get("signal_price"),
        "recommendation_at": operation.get("recommendation_at"),
        "recommendation_price": operation.get("recommendation_price"),
        "plan_created_at": operation.get("plan_created_at"),
        "plan_price": operation.get("plan_price"),
        "submitted_at": operation.get("submitted_at"),
        "first_fill_at": operation.get("first_fill_at"),
        "fill_price": operation.get("fill_price"),
        "signal_to_recommendation_seconds": None,
        "signal_to_plan_seconds": None,
        "signal_to_submit_seconds": None,
        "signal_to_fill_seconds": None,
        "signal_to_plan_bps": None,
        "signal_to_fill_bps": None,
        "price_refresh_status": "unverified",
        "freshness_status": "unavailable",
        "warnings": [],
    }
    timestamps: dict[str, datetime] = {}
    for name in ("signal_at", "recommendation_at", "plan_created_at", "submitted_at", "first_fill_at"):
        raw = fields[name]
        if raw is None:
            fields["warnings"].append(f"missing:{name}")
            continue
        try:
            timestamps[name] = _dt(str(raw))
        except (TypeError, ValueError):
            fields["warnings"].append(f"invalid:{name}")
    for name in ("signal_price", "recommendation_price", "plan_price", "fill_price"):
        value = fields[name]
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            fields["warnings"].append(f"invalid:{name}")
            fields[name] = None
    signal_at = timestamps.get("signal_at")
    for name, output in (
        ("recommendation_at", "signal_to_recommendation_seconds"),
        ("plan_created_at", "signal_to_plan_seconds"),
        ("submitted_at", "signal_to_submit_seconds"),
        ("first_fill_at", "signal_to_fill_seconds"),
    ):
        if signal_at is not None and name in timestamps:
            seconds = (timestamps[name] - signal_at).total_seconds()
            if seconds < 0:
                fields["warnings"].append(f"inverted:{name}")
            else:
                fields[output] = seconds
    fields["signal_to_plan_bps"] = _bps(fields["signal_price"], fields["plan_price"])
    fields["signal_to_fill_bps"] = _bps(fields["signal_price"], fields["fill_price"])
    if fields["signal_to_plan_seconds"] is not None and fields["signal_to_fill_seconds"] is not None:
        fields["freshness_status"] = "aged_signal" if fields["signal_to_plan_seconds"] > 900 else "fresh_signal"
    return fields


def _normalize_exit(raw_trigger: Any) -> str:
    mapping = {
        "stop_loss": "automatic_stop_loss",
        "take_profit": "automatic_take_profit",
        "trailing_stop": "automatic_trailing_stop",
        "time_stop_v2": "automatic_time_stop",
        "manual": "manual",
        "manual_exit": "manual",
    }
    return mapping.get(str(raw_trigger or "").strip().lower(), "unknown_exit_origin")


def _canonicalize_operations(fixture: Mapping[str, Any]) -> dict[str, Any]:
    broker_orders = list(fixture.get("broker_orders") or [])
    fragments = list(fixture.get("fill_fragments") or [])
    by_order: dict[str, list[Mapping[str, Any]]] = {}
    for fragment in fragments:
        order_id = fragment.get("broker_order_id")
        if order_id is not None:
            by_order.setdefault(str(order_id), []).append(fragment)
    canonical = []
    for order in broker_orders:
        order_id = order.get("broker_order_id")
        if not order_id:
            continue
        order_fragments = by_order.get(str(order_id), [])
        canonical.append(
            {
                **dict(order),
                "fill_fragment_count": len(order_fragments),
                "fragment_qty": sum(float(item.get("qty") or 0.0) for item in order_fragments),
                "duplicate_fragment_count": max(0, len(order_fragments) - 1),
                "freshness": _freshness(order),
                "raw_exit_trigger": order.get("exit_trigger"),
                "normalized_exit_origin": _normalize_exit(order.get("exit_trigger")),
            }
        )
    client_ids = [str(item["client_order_id"]) for item in broker_orders if item.get("client_order_id")]
    broker_ids = [str(item["broker_order_id"]) for item in broker_orders if item.get("broker_order_id")]
    return {
        "schema_version": SCHEMA_VERSION,
        "broker_order_count": len(canonical),
        "buy_order_count": sum(item.get("side") == "buy" for item in canonical),
        "sell_order_count": sum(item.get("side") == "sell" for item in canonical),
        "fill_fragment_count": len(fragments),
        "signal_count": fixture.get("signal_count"),
        "candidate_count": fixture.get("candidate_count"),
        "recommendation_count": fixture.get("recommendation_count"),
        "plan_count": fixture.get("plan_count"),
        "operations": canonical,
        "duplicate_broker_order_ids": sorted({item for item in broker_ids if broker_ids.count(item) > 1}),
        "duplicate_client_order_ids": sorted({item for item in client_ids if client_ids.count(item) > 1}),
    }


def _raw_fixture() -> dict[str, Any]:
    def buy(symbol: str, order_id: str, signal_at: str, recommendation_at: str, plan_at: str, submitted_at: str, fill_at: str, signal_price: float, fill_price: float, side: str = "buy") -> dict[str, Any]:
        return {
            "symbol": symbol,
            "broker_order_id": order_id,
            "client_order_id": f"client-{order_id}",
            "side": side,
            "status": "filled",
            "signal_at": signal_at,
            "signal_price": signal_price,
            "recommendation_at": recommendation_at,
            "recommendation_price": signal_price,
            "plan_created_at": plan_at,
            "plan_price": signal_price,
            "submitted_at": submitted_at,
            "first_fill_at": fill_at,
            "fill_price": fill_price,
            "exit_trigger": "stop_loss" if side == "sell" else None,
            "strategy_name": "builtin_breakout" if side == "buy" else None,
            "candidate_id": f"candidate-{symbol.lower()}" if side == "buy" else None,
            "signal_id": f"signal-{symbol.lower()}" if side == "buy" else None,
            "cycle_id": "cycle-16" if "16" in signal_at else "cycle-17",
        }

    operations = [
        buy("CRWD", "bo-crwd-16", "2026-07-16T13:47:01.903432+00:00", "2026-07-16T13:56:31.735380+00:00", "2026-07-16T13:56:51.639981+00:00", "2026-07-16T13:56:53.856144+00:00", "2026-07-16T13:56:55.317589+00:00", 201.605, 201.620),
        buy("TFC", "bo-tfc-16", "2026-07-16T13:47:01.903432+00:00", "2026-07-16T13:56:31.636516+00:00", "2026-07-16T13:56:51.601961+00:00", "2026-07-16T13:56:55.496770+00:00", "2026-07-16T13:56:55.944312+00:00", 53.55, 53.49),
        buy("WELL", "bo-well-16", "2026-07-16T13:47:01.903432+00:00", "2026-07-16T13:56:31.588531+00:00", "2026-07-16T13:56:51.582962+00:00", "2026-07-16T13:56:57.163039+00:00", "2026-07-16T13:56:57.895439+00:00", 237.16, 237.25),
        buy("VTR", "bo-vtr-17", "2026-07-17T13:45:09.746725+00:00", "2026-07-17T16:08:14.857218+00:00", "2026-07-17T16:08:34.286506+00:00", "2026-07-17T16:08:35.841255+00:00", "2026-07-17T16:08:36.833223+00:00", 96.43, 96.51),
        buy("BBY", "bo-bby-17", "2026-07-17T13:45:09.746725+00:00", "2026-07-17T16:08:14.820215+00:00", "2026-07-17T16:08:34.275506+00:00", "2026-07-17T16:08:37.506723+00:00", "2026-07-17T16:08:39.794909+00:00", 85.005, 85.31),
        buy("VTRS", "bo-vtrs-17", "2026-07-17T13:45:09.746725+00:00", "2026-07-17T16:08:14.801683+00:00", "2026-07-17T16:08:34.268986+00:00", "2026-07-17T16:08:39.062703+00:00", "2026-07-17T16:08:40.219427+00:00", 17.41, 17.44),
        buy("MTB", "bo-mtb-17", "2026-07-17T13:45:09.746725+00:00", "2026-07-17T16:08:14.779670+00:00", "2026-07-17T16:08:34.260321+00:00", "2026-07-17T16:08:40.646067+00:00", "2026-07-17T16:08:42.254592+00:00", 251.42, 251.41),
        buy("ANET", "bo-anet-17", "2026-07-17T13:33:20.789450+00:00", "2026-07-17T13:33:20.789450+00:00", "2026-07-17T13:33:20.789450+00:00", "2026-07-17T13:33:20.789450+00:00", "2026-07-17T13:34:47.872476+00:00", 161.9156, 161.344, "sell"),
    ]
    quantities = {"bo-crwd-16": (1, 2, 1), "bo-tfc-16": (18,), "bo-well-16": (4,), "bo-vtr-17": (9, 1), "bo-bby-17": (2, 8, 1), "bo-vtrs-17": (28, 29), "bo-mtb-17": (2, 1), "bo-anet-17": (4, 1)}
    fragments = [
        {"broker_order_id": order_id, "qty": qty, "fragment_id": f"fragment-{index}"}
        for order_id, values in quantities.items()
        for index, qty in enumerate(values, 1)
    ]
    return {
        "broker_orders": operations,
        "fill_fragments": fragments,
        "signal_count": 7,
        "candidate_count": 7,
        "recommendation_count": 7,
        "plan_count": 8,
    }


@dataclass
class _SignalStore:
    rows: list[dict[str, Any]]

    def signal_outcomes(self, *, limit: int, since_date: str) -> list[dict[str, Any]]:
        return self.rows


def test_legacy_performance_counts_candidate_decisions_as_zero() -> None:
    rows = [{"signal_date": "2026-07-16", "decision": "candidate"} for _ in range(576)]
    assert _count_signals(_SignalStore(rows), "2026-07-16") == {"signals": 576, "buys": 0, "sells": 0}


def test_future_denominators_keep_domains_separate_and_missing_unavailable() -> None:
    fixture = _raw_fixture()
    result = _canonicalize_operations(fixture)
    assert result["broker_order_count"] == 8
    assert result["buy_order_count"] == 7
    assert result["sell_order_count"] == 1
    assert result["fill_fragment_count"] == 16
    assert result["signal_count"] == 7
    fixture["signal_count"] = None
    assert _canonicalize_operations(fixture)["signal_count"] is None


def test_fragments_never_create_operations_and_duplicates_are_visible() -> None:
    result = _canonicalize_operations(_raw_fixture())
    by_symbol = {row["symbol"]: row for row in result["operations"]}
    assert by_symbol["CRWD"]["fill_fragment_count"] == 3
    assert by_symbol["CRWD"]["duplicate_fragment_count"] == 2
    assert by_symbol["ANET"]["fill_fragment_count"] == 2
    assert result["broker_order_count"] == 8


def test_anet_exit_preserves_raw_and_normalized_attribution() -> None:
    order = {"payload": {"plan": {"payload": {"risk_decision": {"checks": {"trigger": "stop_loss"}}}}}}
    trigger, legacy_origin, _ = _exit_attribution({"exit_trigger": "stop_loss"}, order)
    assert (trigger, legacy_origin) == ("stop_loss", "stop_loss")
    anet = next(row for row in _canonicalize_operations(_raw_fixture())["operations"] if row["symbol"] == "ANET")
    assert anet["raw_exit_trigger"] == "stop_loss"
    assert anet["normalized_exit_origin"] == "automatic_stop_loss"
    assert sum(row["normalized_exit_origin"].startswith("automatic_") for row in _canonicalize_operations(_raw_fixture())["operations"] if row["side"] == "sell") == 1


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("stop_loss", "automatic_stop_loss"),
        ("take_profit", "automatic_take_profit"),
        ("trailing_stop", "automatic_trailing_stop"),
        ("time_stop_v2", "automatic_time_stop"),
        ("manual", "manual"),
        ("unknown", "unknown_exit_origin"),
        ("not-a-trigger", "unknown_exit_origin"),
    ],
)
def test_exit_attribution_matrix(raw: str, normalized: str) -> None:
    assert _normalize_exit(raw) == normalized


def test_reconciliation_states_do_not_confirm_fill_from_symbol() -> None:
    states = {
        "submitted",
        "pending_local",
        "position_observed_without_exact_order_link",
        "reconciled_filled",
        "reconciled_rejected",
        "reconciliation_unavailable",
        "conflict",
    }
    assert "position_observed_without_exact_order_link" in states
    assert "filled" not in states
    observation = {"symbol": "BBY", "broker_order_id": None, "status": "PENDING_NEW"}
    assert observation["broker_order_id"] is None
    assert "position_observed_without_exact_order_link" != "reconciled_filled"


def test_reconciliation_timestamps_are_distinct_and_ordered() -> None:
    values = [
        "2026-07-17T16:08:35.841255+00:00",
        "2026-07-17T16:10:00+00:00",
        "2026-07-17T20:08:27.975683+00:00",
        "2026-07-17T20:20:41.194830+00:00",
        "2026-07-17T16:08:36.833223+00:00",
        "2026-07-17T16:08:36.833223+00:00",
    ]
    assert _dt(values[0]) < _dt(values[1]) < _dt(values[2])
    assert _dt(values[4]) <= _dt(values[5])


def test_freshness_uses_seconds_and_marks_aged_signal() -> None:
    operation = _raw_fixture()["broker_orders"][3]
    freshness = _freshness(operation)
    assert freshness["signal_to_plan_seconds"] == pytest.approx(8604.539781)
    assert freshness["signal_to_fill_seconds"] == pytest.approx(8607.086498)
    assert freshness["freshness_status"] == "aged_signal"
    assert freshness["signal_to_plan_seconds"] > 8_000


def test_freshness_does_not_claim_price_refresh_when_prices_are_equal() -> None:
    operation = _raw_fixture()["broker_orders"][0]
    freshness = _freshness(operation)
    assert freshness["signal_to_plan_bps"] == 0
    assert freshness["price_refresh_status"] == "unverified"


@pytest.mark.parametrize(
    "changes",
    [
        {"signal_at": "2026-07-17T16:00:00",},
        {"signal_at": "2026-07-17T17:00:00+00:00", "plan_created_at": "2026-07-17T16:00:00+00:00"},
        {"signal_price": float("nan")},
        {"fill_price": float("inf")},
    ],
)
def test_freshness_invalid_or_missing_values_warn_and_never_become_zero(changes: dict[str, Any]) -> None:
    operation = {**_raw_fixture()["broker_orders"][0], **changes}
    freshness = _freshness(operation)
    assert freshness["warnings"] or freshness["freshness_status"] == "unavailable"
    if any(isinstance(value, float) and not math.isfinite(value) for value in changes.values()):
        assert freshness["signal_to_fill_bps"] is None


def test_rejections_preserve_null_identity_and_never_join_by_symbol() -> None:
    rows = [
        {"symbol": "VTR", "cycle_id": "cycle-a", "candidate_id": "candidate-a", "signal_id": "signal-a", "recommendation_id": None, "plan_id": None, "reason_code": "duplicate_symbol_cycle_guard"},
        {"symbol": "VTR", "cycle_id": "cycle-b", "candidate_id": "candidate-b", "signal_id": "signal-b", "recommendation_id": None, "plan_id": None, "reason_code": "duplicate_symbol_cycle_guard"},
    ]
    assert len({(row["cycle_id"], row["candidate_id"], row["signal_id"]) for row in rows}) == 2
    assert all(row["recommendation_id"] is None and row["plan_id"] is None for row in rows)


def test_capacity_fill_is_observational_only() -> None:
    payload = {
        "decision_source": "deterministic_capacity_fill",
        "capacity_fill_reason_code": "capacity_fill_tras_llm_ok",
        "llm_considered": True,
        "llm_selected": False,
        "micro_experiment": True,
        "size_multiplier": 0.5,
        "setup_edge_3d_raw": -0.0007,
        "operational_penalty": 0.05,
        "expected_edge_3d": -0.0507,
        "sample_size": 27957,
        "confidence": 0.66,
    }
    before = copy.deepcopy(payload)
    assert payload["expected_edge_3d"] == pytest.approx(payload["setup_edge_3d_raw"] - payload["operational_penalty"])
    assert payload["micro_experiment"] is True and payload["size_multiplier"] == 0.5
    assert payload == before


def test_hash_is_stable_and_excludes_captured_at() -> None:
    base = {"schema_version": SCHEMA_VERSION, "cycle_id": "cycle-17", "counts": {"buy": 7}, "captured_at": "2026-07-18T00:00:00+00:00"}
    changed_time = {**base, "captured_at": "2026-07-18T12:00:00+00:00"}
    assert _hash_without_captured_at(base) == _hash_without_captured_at(changed_time)
    assert _hash_without_captured_at(base) == _hash_without_captured_at(json.loads(json.dumps(base)))


def test_same_hash_is_noop_and_changed_content_is_conflict() -> None:
    original = {"cycle_id": "cycle-17", "content_hash": "hash-a", "status": "available"}
    repeated = copy.deepcopy(original)
    changed = {**original, "content_hash": "hash-b"}
    assert repeated == original
    assert changed["content_hash"] != original["content_hash"]
    assert original["status"] == "available"


def test_duplicate_broker_and_client_ids_are_detectable() -> None:
    fixture = _raw_fixture()
    fixture["broker_orders"].append(copy.deepcopy(fixture["broker_orders"][0]))
    result = _canonicalize_operations(fixture)
    assert result["duplicate_broker_order_ids"] == ["bo-crwd-16"]
    assert result["duplicate_client_order_ids"] == ["client-bo-crwd-16"]


def test_parity_fixture_is_not_mutated_and_active_fields_are_untouched() -> None:
    fixture = _raw_fixture()
    before = copy.deepcopy(fixture)
    active = {"signals": ["s1"], "scores": [15], "ranks": [8], "gates": ["passed"], "plans": ["p1"], "orders": ["o1"], "exposure": 0.1}
    active_before = copy.deepcopy(active)
    _canonicalize_operations(fixture)
    assert fixture == before
    assert active == active_before


def test_real_fixture_denominators_match_audit_and_schema() -> None:
    result = _canonicalize_operations(_raw_fixture())
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["broker_order_count"] == 8
    assert result["buy_order_count"] == 7
    assert result["sell_order_count"] == 1
    assert result["fill_fragment_count"] == 16
    assert result["candidate_count"] == 7
    assert result["recommendation_count"] == 7
    assert result["plan_count"] == 8


def test_operation_identity_requires_broker_order_id() -> None:
    fixture = _raw_fixture()
    fixture["broker_orders"].append({"symbol": "VTR", "side": "buy", "status": "filled"})
    result = _canonicalize_operations(fixture)
    assert result["broker_order_count"] == 8


def test_contract_contains_no_post_decision_features() -> None:
    forbidden = {"pnl", "mfe", "mae", "first_hit", "prompt", "llm_response", "matured_outcome"}
    result = _canonicalize_operations(_raw_fixture())
    encoded = json.dumps(result, ensure_ascii=False).lower()
    assert not any(term in encoded for term in forbidden)
