import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agente_bolsa import main
from agente_bolsa.storage import Store
from agente_bolsa.tools.excursion_quality import _in_bucket, build_excursion_quality_report


class FakeStore:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.calls = 0

    def signal_outcomes(self, *, limit=500_000):
        self.calls += 1
        return deepcopy(self.rows)


def row(**overrides):
    value = {
        "signal_date": "2026-07-01",
        "symbol": "AAA",
        "features": {
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 130.0,
            "setup_quality": "strong",
        },
        "outcome": {
            "return_1d": 0.10,
            "return_3d": 0.20,
            "return_5d": 0.15,
            "return_10d": 0.25,
            "mfe_10d": 0.20,
            "mae_10d": -0.05,
            "first_hit": {"type": "take_profit"},
            "verdict": "winner_take_profit",
        },
    }
    value.update(overrides)
    return value


def report(rows, **kwargs):
    return build_excursion_quality_report(FakeStore(rows), start="2026-07-01", end="2026-07-01", **kwargs)


def test_example_has_dimensionally_correct_r_values_and_buckets():
    payload = report([row()], min_sample=1)
    metrics = payload["horizons"]["10d"]
    groups = payload["groups_by_return_horizon"]["10d"]
    assert payload["schema_version"] == "p-l27b.excursion-quality.v2"
    assert metrics["mean_mfe_r"] == 2.0
    assert metrics["mean_mae_r"] == 0.5
    assert metrics["mean_stop_consumption"] == 0.5
    assert metrics["mean_target_attainment"] == pytest.approx(2 / 3)
    assert metrics["mean_reward_risk_ratio"] == 3.0
    assert groups["stop_consumption"]["[0.50,0.75)"]["sample_size"] == 1
    assert groups["target_attainment"]["[0.50,0.75)"]["sample_size"] == 1
    assert groups["reward_risk_ratio"][">=3"]["sample_size"] == 1
    assert metrics["return_horizon"] == "10d"
    assert metrics["excursion_horizon"] == "10d"


def test_price_scale_invariance_and_target_invariant():
    small = row(features={**row()["features"], "entry_price": 10.0, "stop_loss": 9.0, "take_profit": 13.0})
    normal = row()
    payload = report([small, normal], horizon="10d", min_sample=1)
    metrics = payload["horizons"]["10d"]
    assert metrics["mean_mfe_r"] == 2.0
    assert metrics["mean_mae_r"] == 0.5
    assert metrics["mean_target_attainment"] == pytest.approx(2 / 3)


def test_mfe_mae_signs_and_near_geometry_are_safe():
    adverse = row(outcome={**row()["outcome"], "mfe_10d": -0.1, "mae_10d": 0.1})
    near_stop = row(features={**row()["features"], "stop_loss": 99.999})
    near_take = row(features={**row()["features"], "take_profit": 100.001})
    payload = report([adverse, near_stop, near_take], horizon="10d", min_sample=1)
    assert payload["horizons"]["10d"]["sample_size"] == 3
    assert payload["horizons"]["10d"]["mean_mfe_r"] >= 0
    assert payload["horizons"]["10d"]["mean_mae_r"] >= 0


def test_bucket_boundaries_are_disjoint_and_cover_non_negative_values():
    buckets = ((0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1), (1, 1.5), (1.5, float("inf")))
    for value in (0, 0.25, 0.5, 0.75, 1, 1.5, 10):
        assert sum(_in_bucket(value, low, high) for low, high in buckets) == 1


def test_direction_and_geometry_exclusions_are_separated_by_source_and_horizon():
    short = row(features={**row()["features"], "direction": "short"})
    missing = row(features={key: value for key, value in row()["features"].items() if key != "direction"})
    invalid = row(features={**row()["features"], "direction": "sideways"})
    bad_entry = row(features={**row()["features"], "entry_price": 0.0})
    corrupt = row(outcome="bad")
    payload = report([row(), short, missing, invalid, bad_entry, corrupt], min_sample=1)
    quality = payload["data_quality"]
    assert quality["selected_source_rows"] == 6
    assert quality["direction_source_rows"] == {"invalid": 1, "long": 2, "short": 1, "unknown_or_missing": 2}
    assert quality["exclusions_by_reason_source_rows"]["direction_short"] == 1
    assert quality["exclusions_by_reason_source_rows"]["direction_unknown_or_missing"] == 1
    assert quality["exclusions_by_reason_source_rows"]["direction_invalid"] == 1
    assert quality["exclusions_by_reason_source_rows"]["entry_zero_or_negative"] == 1
    assert quality["exclusions_by_reason_source_rows"]["outcome_corrupt"] == 1
    assert quality["selected_horizon_observations"] == 24
    assert quality["valid_matured_horizon_observations"] == 4
    assert quality["excluded_matured_horizon_observations"] == 16
    assert quality["immature_horizon_observations"] == 4
    assert quality["geometry_coverage"] == 0.5
    assert quality["matured_valid_coverage"] == 0.2


@pytest.mark.parametrize(
    "feature_patch,outcome_patch,reason",
    [
        ({"entry_price": None}, {}, "entry_non_numeric_or_missing"),
        ({"entry_price": 0}, {}, "entry_zero_or_negative"),
        ({"stop_loss": None}, {}, "stop_non_numeric_or_missing"),
        ({"stop_loss": 100}, {}, "stop_ge_entry"),
        ({"take_profit": None}, {}, "take_non_numeric_or_missing"),
        ({"take_profit": 100}, {}, "take_le_entry"),
        ({}, {"mfe_10d": None}, "mfe_non_numeric_or_missing"),
        ({}, {"mae_10d": None}, "mae_non_numeric_or_missing"),
    ],
)
def test_every_geometry_field_has_auditable_reason(feature_patch, outcome_patch, reason):
    item = row(features={**row()["features"], **feature_patch}, outcome={**row()["outcome"], **outcome_patch})
    payload = report([item], horizon="10d", min_sample=1)
    assert payload["data_quality"]["exclusions_by_reason_source_rows"][reason] == 1


def test_maturity_counts_filters_and_horizon_unit_do_not_multiply_signals_silently():
    immature = row(outcome={**row()["outcome"], "return_10d": None})
    payload = report([row(), immature], min_sample=1)
    quality = payload["data_quality"]
    assert quality["selected_horizon_observations"] == 8
    assert quality["matured_horizon_observations"] == 7
    assert quality["immature_horizon_observations"] == 1
    assert payload["horizons"]["10d"]["sample_size"] == 1
    assert payload["groups_by_return_horizon"]["1d"]["sample_unit"] == "source_row_x_return_horizon"


def test_statuses_lineage_and_temporal_semantics():
    assert report([], horizon="10d")["status"] == "unavailable"
    small = report([row()], horizon="10d", min_sample=2)["horizons"]["10d"]
    enough = report([row(), row()], horizon="10d", min_sample=2)["horizons"]["10d"]
    verified = report([row(features={**row()["features"], "decision_lineage": "real"})], horizon="10d", min_sample=1)
    mismatched = report([row()], horizon="1d", min_sample=1)["horizons"]["1d"]
    assert small["status"] == "insufficient_sample"
    assert enough["status"] == "evaluable"
    assert enough["lineage_status"] == "legacy_unverified"
    assert verified["horizons"]["10d"]["lineage_status"] == "verified"
    assert "observational_mismatched_horizon" in mismatched["data_quality_warnings"]
    assert report([row()], horizon="10d", min_sample=1)["horizons"]["10d"]["data_quality_warnings"] == ["legacy_unverified_observations"]


def test_hash_is_stable_json_serializes_and_read_is_pure():
    store = FakeStore([row()])
    first = build_excursion_quality_report(store, start="2026-07-01", end="2026-07-01")
    second = build_excursion_quality_report(store, start="2026-07-01", end="2026-07-01")
    assert first["content_hash"] == second["content_hash"]
    assert first["parameters"]["to"] == "2026-07-01"
    assert store.rows == [row()]
    json.dumps(first)


def test_invalid_arguments_and_empty_date_window_are_unavailable():
    store = FakeStore([row()])
    assert build_excursion_quality_report(store, horizon="2d")["reason"] == "horizon_invalid"
    assert build_excursion_quality_report(store, min_sample=0)["reason"] == "min_sample_invalid"
    assert build_excursion_quality_report(store, start="bad")["reason"] == "Fecha invalida: bad"
    empty = build_excursion_quality_report(store, start="2020-01-01", end="2020-01-01")
    assert empty["status"] == "unavailable"


def test_cli_uses_real_temporary_store_and_json(monkeypatch, capsys, tmp_path):
    database = tmp_path / "state.sqlite3"
    store = Store(database, tmp_path / "logs")
    store.ensure_schema()
    sample = row()
    store.save_signal_outcome(
        signal_id="signal-1", source_run_id="run-1", source="test", symbol="AAA", signal_date="2026-07-01",
        decision="buy", features=sample["features"], outcome=sample["outcome"],
    )
    settings = SimpleNamespace(database_path=database, agent_logs_dir=tmp_path / "logs", logs_dir=tmp_path / "logs", log_level="INFO")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main.command_excursion_quality_report(SimpleNamespace(start="2026-07-01", end="2026-07-01", horizon="10d", min_sample=1, historical=False, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["schema_version"] == "p-l27b.excursion-quality.v2"
    assert store.signal_outcomes(limit=10)[0]["outcome"] == sample["outcome"]
