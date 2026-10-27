from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agente_bolsa import main
from agente_bolsa.tools.learning_spool import LearningSpool
from agente_bolsa.tools.rr_cohort import (
    COHORT_FEATURE_KEY,
    COHORT_START,
    CONTRACT,
    HYPOTHESIS_ID,
    _collection_sessions_completed,
    _post_signal_sessions_completed,
    _session_close_at,
    _temporal_card,
    build_rr_cohort_report,
    nth_xnys_session_after,
    rr_cohort_digest_summary,
    sync_rr_cohort_observations,
    sync_rr_cohort_observations_spooled,
)


class FakeStore:
    def __init__(self, rows: list[dict[str, object]]):
        self.rows = deepcopy(rows)
        self.writes = 0

    def learning_observations(self, *, since_date=None, end_date=None, limit=500_000):
        rows = [
            row
            for row in self.rows
            if (not since_date or row["signal_date"] >= since_date)
            and (not end_date or row["signal_date"] <= end_date)
        ]
        return deepcopy(rows[:limit])

    def upsert_learning_observation(self, item):
        self.writes += 1
        for index, row in enumerate(self.rows):
            if row["observation_id"] == item["observation_id"]:
                self.rows[index] = deepcopy(item)
                return
        self.rows.append(deepcopy(item))

    def signal_outcomes(self, *, limit=500_000):
        return []


class StreamingBatchStore(FakeStore):
    def iter_learning_observations(self, **kwargs):
        yield from self.learning_observations(**kwargs)

    def upsert_learning_observations_batch(self, items):
        count = 0
        for item in items:
            self.upsert_learning_observation(item)
            count += 1
        return {"status": "available", "received": count, "written": count, "chunks_completed": 1}


def observation(
    index: int = 1,
    *,
    signal_date: str = "2026-07-13",
    rr: float = 1.2,
    mature: bool = False,
    value: float = 0.02,
    direction: str = "long",
    lineage: bool = True,
    cycle_id: str = "cycle-1",
    decision: str = "candidate",
    executed: bool = False,
    capacity_control: bool = False,
) -> dict[str, object]:
    entry, stop = 100.0, 90.0
    take = entry + (entry - stop) * rr
    features = {
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": take,
        "setup_quality": "verified_setup",
        "decision_lineage": {
            "lineage_id": f"lineage-{index}" if lineage else None,
            "lineage_status": "verified" if lineage else "legacy_unverified",
            "cycle_id": cycle_id if lineage else None,
            "strategy_name": "observed_strategy",
            "strategy_version": "v1",
            "decision_source": "candidate",
            "candidate_rank": index,
        },
    }
    return {
        "observation_id": f"observation-{index}",
        "signal_date": signal_date,
        "symbol": f"SYM{index}",
        "source_family": "signals",
        "source_run_ids": [cycle_id],
        "first_seen_at": f"{signal_date}T20:00:00+00:00",
        "last_seen_at": f"{signal_date}T20:00:00+00:00",
        "best_signal_id": f"signal-{index}",
        "best_score": 10.0,
        "decision": decision,
        "approved_buy": decision == "approved_buy",
        "executed_buy": executed,
        "duplicate_count": 0,
        "features": features,
        "gate": {"gate_status": "passed", "execution": {"status": "approved_not_planned" if capacity_control else ""}},
        "outcome": {"return_10d": value, "matured_horizons": {"10d": mature}, "source": "signal_outcomes"},
        "execution": {"reason": "max_orders_per_cycle_reached" if capacity_control else ""},
    }


def cards(store: FakeStore):
    return [row["features"][COHORT_FEATURE_KEY] for row in store.rows if COHORT_FEATURE_KEY in row["features"]]


def test_spooled_rr_sync_matches_legacy_and_preserves_unknown_features(tmp_path):
    rows = [
        observation(i, decision="approved_buy", capacity_control=True) if i < 5
        else observation(i, executed=i % 2 == 0, lineage=i != 8)
        for i in range(1, 11)
    ]
    for i, row in enumerate(rows):
        row["features"]["unknown"] = {"payload": f"{i}-" + "x" * 8192}
    ordered = sorted(rows, key=lambda row: (row["signal_date"], row["symbol"], row["source_family"]))
    legacy = StreamingBatchStore(ordered)
    streamed = StreamingBatchStore(ordered)
    expected = sync_rr_cohort_observations(legacy, deepcopy(ordered))
    with LearningSpool(directory=tmp_path) as spool:
        for row in ordered:
            spool.append(row)
        actual = sync_rr_cohort_observations_spooled(streamed, spool)
    assert actual == expected
    assert streamed.rows == legacy.rows


def test_temporal_card_reuses_calendar_values_only_within_explicit_cache(monkeypatch):
    from datetime import datetime, timezone

    from agente_bolsa.tools import rr_cohort

    calls = {"sessions": 0, "maturity": 0}

    def sessions(_date, _as_of):
        calls["sessions"] += 1
        return 12

    def maturity(_date, _count):
        calls["maturity"] += 1
        return "2026-10-27"

    monkeypatch.setattr(rr_cohort, "_post_signal_sessions_completed", sessions)
    monkeypatch.setattr(rr_cohort, "nth_xnys_session_after", maturity)
    card = {"signal_date": "2026-10-10", "schema_version": rr_cohort.SCHEMA_VERSION,
            "maturity_status_10d": "immature"}
    as_of = datetime(2026, 10, 27, tzinfo=timezone.utc)
    expected = rr_cohort._temporal_card(card, as_of)
    calls.update(sessions=0, maturity=0)
    cache = {}
    assert rr_cohort._temporal_card(card, as_of, calendar_cache=cache) == expected
    assert rr_cohort._temporal_card(card, as_of, calendar_cache=cache) == expected
    assert calls == {"sessions": 1, "maturity": 1}


def test_rr_digest_summary_matches_full_report_without_per_observation_maps(monkeypatch):
    from agente_bolsa.tools import rr_cohort

    monkeypatch.setattr(rr_cohort, "_post_signal_sessions_completed", lambda *_args: 12)
    monkeypatch.setattr(rr_cohort, "_collection_sessions_completed", lambda *_args: 12)
    monkeypatch.setattr(rr_cohort, "nth_xnys_session_after", lambda *_args: "2026-10-27")
    rows = [observation(i, mature=i % 2 == 0, rr=1.2 if i % 2 else 1.7) for i in range(1, 12)]
    store = StreamingBatchStore(rows)
    sync_rr_cohort_observations(store, store.learning_observations())
    full = build_rr_cohort_report(store)
    selected = full["views"]["selected"]
    expected = {
        "status": full["overall_status"], "collection_sessions_completed": full["collection_sessions_completed"],
        "mature_by_arm": {arm: selected["arms"][arm]["matured_count"] for arm in ("A", "B")},
        "lineage_coverage": selected["lineage_coverage"], "control_coverage": selected["control_coverage"],
        "criteria_pending": [key for key, value in full["criteria"].items() if value is not True],
        "next_possible_maturity_date": full["next_possible_maturity_date"],
    }
    assert rr_cohort_digest_summary(store) == expected
    card = store.rows[0]["features"][COHORT_FEATURE_KEY]
    card["data_quality_warnings"] = [{}]
    with pytest.raises(TypeError):
        build_rr_cohort_report(store)
    with pytest.raises(TypeError):
        rr_cohort_digest_summary(store)


def test_contract_and_boundaries_are_pre_registered_without_trading_fields():
    assert CONTRACT["hypothesis_id"] == HYPOTHESIS_ID
    assert CONTRACT["change_class"] == "observability"
    assert CONTRACT["arms"] == {"A": {"rr_gte": 1.0, "rr_lt": 1.5}, "B": {"rr_gte": 1.5, "rr_lt": 2.0}}
    store = FakeStore([observation(1, rr=1.0), observation(2, rr=1.5), observation(3, rr=2.0)])
    sync_rr_cohort_observations(store, store.learning_observations())
    assert [card["rr_arm"] for card in cards(store)] == ["A", "B", None]
    assert cards(store)[2]["exclusion_reason"] == "rr_outside_contract"
    assert all("pnl" not in json.dumps(card).lower() for card in cards(store))


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"direction": "short"}, "direction_not_long"),
        ({"direction": None}, "direction_not_long"),
        ({"entry_price": 0.0}, "geometry_invalid"),
        ({"best_signal_id": None}, "signal_id_missing"),
        ({"lineage": False}, "lineage_not_verified"),
        ({"cycle_id": ""}, "cycle_id_missing"),
    ],
)
def test_eligibility_exclusions_are_auditable(patch, reason):
    item = observation()
    if "best_signal_id" in patch:
        item["best_signal_id"] = patch["best_signal_id"]
    if "lineage" in patch or "cycle_id" in patch:
        item = observation(lineage=patch.get("lineage", True), cycle_id=patch.get("cycle_id", "cycle-1"))
    for key in ("direction", "entry_price"):
        if key in patch:
            item["features"][key] = patch[key]
    store = FakeStore([item])
    sync_rr_cohort_observations(store, store.learning_observations())
    assert cards(store)[0]["eligibility_status"] == "excluded"
    assert cards(store)[0]["exclusion_reason"] == reason


def test_sync_is_prospective_idempotent_and_control_is_same_cycle_and_geometry():
    legacy = observation(1, signal_date="2026-07-10")
    primary = observation(2, rr=1.2, mature=True)
    control = observation(3, rr=1.2, decision="approved_buy", capacity_control=True)
    foreign_cycle = observation(4, rr=1.2, cycle_id="other", decision="approved_buy", capacity_control=True)
    store = FakeStore([legacy, primary, control, foreign_cycle])
    sync_rr_cohort_observations(store, store.learning_observations())
    first = deepcopy(store.rows)
    sync_rr_cohort_observations(store, store.learning_observations())
    primary_card = next(card for card in cards(store) if card["signal_id"] == "signal-2")
    assert COHORT_FEATURE_KEY not in store.rows[0]["features"]
    assert primary_card["comparable_control_available"] is True
    assert primary_card["comparable_control_ids"] == ["observation-3"]
    assert first == store.rows


def test_controls_are_capped_and_gate_blocked_or_fills_are_not_controls():
    primary = observation(1)
    controls = [observation(index, decision="approved_buy", capacity_control=True) for index in range(2, 7)]
    blocked = observation(7, decision="approved_buy", capacity_control=False)
    filled = observation(8, decision="approved_buy", capacity_control=True, executed=True)
    store = FakeStore([primary, *controls, blocked, filled])
    sync_rr_cohort_observations(store, store.learning_observations())
    card = next(card for card in cards(store) if card["signal_id"] == "signal-1")
    assert len(card["comparable_control_ids"]) == 3
    assert "observation-7" not in card["comparable_control_ids"]
    assert "observation-8" not in card["comparable_control_ids"]


def test_report_separates_immature_and_mature_outcomes_without_legacy_reinterpretation():
    store = FakeStore([observation(1, rr=1.2, mature=False), observation(2, rr=1.6, mature=True, value=-0.02)])
    sync_rr_cohort_observations(store, store.learning_observations())
    report = build_rr_cohort_report(store)
    assert report["overall_status"] == "immature"
    assert report["views"]["selected"]["arms"]["A"]["matured_count"] == 0
    assert report["views"]["selected"]["arms"]["B"]["matured_count"] == 1
    assert report["legacy_context"] is None
    assert build_rr_cohort_report(store, include_legacy_context=True)["legacy_context"]["primary_excluded"] is True


def test_chronological_windows_keep_dates_atomic_and_hash_ignores_generated_at():
    rows = []
    for index in range(1, 5):
        rows.append(observation(index, signal_date="2026-07-13" if index < 3 else "2026-07-14", rr=1.2 if index % 2 else 1.6, mature=True))
    store = FakeStore(rows)
    sync_rr_cohort_observations(store, store.learning_observations())
    first = build_rr_cohort_report(store)
    second = build_rr_cohort_report(store)
    assert first["content_hash"] == second["content_hash"]
    assert first["views"]["first"]["raw_count"] == 2
    assert first["views"]["second"]["raw_count"] == 2


def test_xnys_session_calendar_excludes_weekends_and_independence_day_observance():
    assert nth_xnys_session_after("2026-07-13", 1) == "2026-07-14"
    assert nth_xnys_session_after("2026-07-13", 10) == "2026-07-27"
    assert nth_xnys_session_after("2026-07-02", 1) == "2026-07-06"
    assert nth_xnys_session_after("2026-07-04", 1) == "2026-07-06"
    with pytest.raises(ValueError):
        nth_xnys_session_after("2026-07-13", 0)


def test_collection_and_post_signal_sessions_respect_xnys_close_time():
    close = _session_close_at("2026-07-13")
    assert close is not None
    assert _collection_sessions_completed(COHORT_START, close - timedelta(minutes=1)) == 0
    assert _collection_sessions_completed(COHORT_START, close + timedelta(minutes=1)) == 1
    assert _post_signal_sessions_completed("2026-07-13", close + timedelta(minutes=1)) == 0
    assert _post_signal_sessions_completed("2026-07-13", _session_close_at("2026-07-24")) == 9
    assert _post_signal_sessions_completed("2026-07-13", _session_close_at("2026-07-27")) == 10


def test_report_uses_outcome_maturity_as_authority_and_separates_temporal_fields():
    store = FakeStore([observation(1, mature=False)])
    sync_rr_cohort_observations(store, store.learning_observations())
    report = build_rr_cohort_report(store, end="2026-07-27")
    selected = report["views"]["selected"]
    card = _temporal_card(cards(store)[0], _session_close_at("2026-07-27"))
    assert report["schema_version"] == "p-l27d.rr-cohort.v2"
    assert report["collection_sessions_completed"] == 11
    assert report["earliest_possible_first_maturity_date"] == "2026-07-27"
    assert report["cohort_evaluation_date"] == "unavailable"
    assert selected["post_signal_sessions_completed_by_observation"]["rrcohort:observation-1"] == 10
    assert card["maturity_status_10d"] == "immature"
    assert "calendar_maturity_due_outcome_immature" in card["data_quality_warnings"]


def test_v1_cards_are_read_only_compatible_and_marked_legacy_temporal_semantics():
    store = FakeStore([observation(1)])
    sync_rr_cohort_observations(store, store.learning_observations())
    store.rows[0]["features"][COHORT_FEATURE_KEY].pop("schema_version")
    store.rows[0]["features"][COHORT_FEATURE_KEY].pop("temporal_semantics")
    report = build_rr_cohort_report(store, end="2026-07-13")
    assert report["views"]["selected"]["temporal_semantics_by_observation"]["rrcohort:observation-1"] == "legacy_semantics"


def test_cli_json_uses_read_only_report(monkeypatch, capsys):
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(logs_dir=".", log_level="INFO", database_path="unused", agent_logs_dir="unused"))
    monkeypatch.setattr(main, "configure_logging", lambda *_args: None)
    monkeypatch.setattr(main, "Store", lambda *_args: object())
    monkeypatch.setattr(main, "build_rr_cohort_report", lambda *_args, **_kwargs: {"overall_status": "collecting", "schema_version": "p-l27d.rr-cohort.v1"})
    main.command_rr_cohort_report(SimpleNamespace(start=None, end=None, window="all", include_legacy_context=False, json=True))
    assert json.loads(capsys.readouterr().out)["ok"] is True
