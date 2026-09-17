from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE
from agente_bolsa.tools.learning_scoreboard import build_learning_scoreboard


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _observation(signal_date, symbol, *, return_5d, slippage_bps=None):
    execution = {}
    if slippage_bps is not None:
        execution = {"execution_snapshot": {"metrics": {"signal_to_fill_bps": slippage_bps}}}
    return {
        "observation_id": f"{signal_date}:{symbol}:exec",
        "signal_date": signal_date,
        "symbol": symbol,
        "source_family": LEARNING_EXPERIMENT_SOURCE,
        "source_run_ids": ["cycle-a"],
        "best_signal_id": f"sig-{symbol}",
        "best_score": 15.0,
        "decision": "executed_buy",
        "approved_buy": True,
        "executed_buy": True,
        "duplicate_count": 0,
        "features": {},
        "gate": {},
        "outcome": {"return_5d": return_5d, "matured_horizons": {"5d": True}},
        "execution": execution,
    }


def _build(tmp_path, monkeypatch, rows):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    for row in rows:
        store.upsert_learning_observation(row)
    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {},
    )
    return build_learning_scoreboard(
        settings, store, tmp_path / "reports", "score",
        since_date="2026-07-07", end_date="2026-07-20",
    )


def test_no_snapshots_keeps_assumption_and_calibrated_unavailable(tmp_path, monkeypatch):
    rows = [_observation("2026-07-07", f"S{i}", return_5d=0.02) for i in range(3)]
    report = _build(tmp_path, monkeypatch, rows)

    assert report["schema_version"] == 3
    assert report["cost_calibration"]["cost_basis"] == "assumption_10bps"
    assert report["cost_calibration"]["calibration_samples"] == 0
    assert report["weekly_rows"][0]["expectancy_net_calibrated"] is None
    # Bandas legacy intactas.
    assert report["weekly_rows"][0]["expectancy_net_10bps"] is not None
    assert report["weekly_rows"][0]["expectancy_net_20bps"] is not None


def test_calibrated_median_drives_net_expectancy(tmp_path, monkeypatch):
    # 10 snapshots a 30bps adversos: coste calibrado 0.003.
    rows = [_observation("2026-07-07", f"S{i}", return_5d=0.02, slippage_bps=30.0) for i in range(10)]
    report = _build(tmp_path, monkeypatch, rows)

    calibration = report["cost_calibration"]
    assert calibration["cost_basis"] == "calibrated"
    assert calibration["calibration_samples"] == 10
    assert calibration["cost_bps"] == 30.0
    # 0.02 - 0.003 = 0.017
    assert report["weekly_rows"][0]["expectancy_net_calibrated"] == 0.017
    # Bandas legacy sin cambios.
    assert report["weekly_rows"][0]["expectancy_net_10bps"] == 0.019


def test_below_threshold_stays_unavailable(tmp_path, monkeypatch):
    rows = [_observation("2026-07-07", f"S{i}", return_5d=0.02, slippage_bps=30.0) for i in range(9)]
    report = _build(tmp_path, monkeypatch, rows)

    assert report["cost_calibration"]["cost_basis"] == "assumption_10bps"
    assert report["cost_calibration"]["calibration_samples"] == 9
    assert report["weekly_rows"][0]["expectancy_net_calibrated"] is None


def test_outlier_beyond_200bps_excluded(tmp_path, monkeypatch):
    rows = [_observation("2026-07-07", f"S{i}", return_5d=0.02, slippage_bps=20.0) for i in range(10)]
    rows.append(_observation("2026-07-07", "OUT", return_5d=0.02, slippage_bps=5000.0))
    report = _build(tmp_path, monkeypatch, rows)

    assert report["cost_calibration"]["calibration_samples"] == 10
    assert report["cost_calibration"]["cost_bps"] == 20.0
