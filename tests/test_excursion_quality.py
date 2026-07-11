from copy import deepcopy

from agente_bolsa.tools.excursion_quality import build_excursion_quality_report


class FakeStore:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.calls = 0

    def signal_outcomes(self, *, limit=500_000, since_date=None, until_date=None):
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


def test_complete_geometry_is_deterministic_and_observational():
    store = FakeStore([row()])
    report = build_excursion_quality_report(store, start="2026-07-01", end="2026-07-01", min_sample=1)
    metrics = report["horizons"]["10d"]
    assert report["status"] == "available"
    assert report["observational_only"] is True
    assert metrics["sample_size"] == 1
    assert metrics["status"] == "evaluable"
    assert metrics["mean_mfe"] == 0.2
    assert metrics["mean_mae"] == -0.05
    assert metrics["mean_reward_risk_ratio"] == 3.0
    assert metrics["mean_mfe_r"] == 0.02
    assert metrics["mean_mae_r"] == 0.005
    assert report["groups"]["target_attainment"]["[0.00,0.25)"]["sample_size"] == 4
    assert report["data_quality"]["imputation_count"] == 0
    assert report["data_quality"]["alpha"] == "unavailable"
    assert store.calls == 1


def test_invalid_geometry_and_immature_rows_are_excluded_with_reasons():
    bad_stop = row(features={**row()["features"], "stop_loss": 100.0})
    bad_take = row(features={**row()["features"], "take_profit": 100.0})
    missing_mfe = row(outcome={key: value for key, value in row()["outcome"].items() if key != "mfe_10d"})
    immature = row(outcome={"return_1d": 0.1})
    report = build_excursion_quality_report(FakeStore([bad_stop, bad_take, missing_mfe, immature]), min_sample=1)
    reasons = report["data_quality"]["exclusions_by_reason"]
    assert reasons["stop_ge_entry"] == 4
    assert reasons["take_le_entry"] == 4
    assert reasons["mfe_non_numeric_or_missing"] == 5
    assert report["data_quality"]["maturity_by_horizon"]["immature_10d"] == 1
    assert report["horizons"]["10d"]["sample_size"] == 0
    assert report["horizons"]["10d"]["status"] == "insufficient_sample"


def test_filters_horizon_dates_and_historical_window():
    rows = [row(signal_date="2026-06-01"), row(signal_date="2026-07-01")]
    store = FakeStore(rows)
    report = build_excursion_quality_report(store, horizon="1d", start="2026-07-01", end="2026-07-01", min_sample=1)
    assert report["parameters"]["horizon"] == "1d"
    assert report["horizons"]["1d"]["sample_size"] == 1
    historical = build_excursion_quality_report(store, horizon="1d", historical=True, min_sample=1)
    assert historical["parameters"]["from"] == "2026-06-01"
    assert historical["horizons"]["1d"]["sample_size"] == 2


def test_invalid_arguments_return_unavailable_without_traceback():
    store = FakeStore([row()])
    assert build_excursion_quality_report(store, horizon="2d")["reason"] == "horizon_invalid"
    assert build_excursion_quality_report(store, min_sample=0)["reason"] == "min_sample_invalid"
    assert build_excursion_quality_report(store, start="bad")["reason"] == "Fecha invalida: bad"
