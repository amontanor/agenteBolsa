from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE
from agente_bolsa.tools.learning_scoreboard import build_learning_scoreboard


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _executed(signal_date, symbol, *, return_5d=0.02, source="cycle-a"):
    return {
        "observation_id": f"{signal_date}:{symbol}:exec",
        "signal_date": signal_date,
        "symbol": symbol,
        "source_family": LEARNING_EXPERIMENT_SOURCE,
        "source_run_ids": [source],
        "best_signal_id": f"sig-{symbol}",
        "best_score": 15.0,
        "decision": "executed_buy",
        "approved_buy": True,
        "executed_buy": True,
        "duplicate_count": 0,
        "features": {"direction": "long", "decision_lineage": {"cycle_id": source}},
        "gate": {},
        "outcome": {"return_5d": return_5d, "matured_horizons": {"5d": True}},
        "execution": {},
    }


def _control(signal_date, symbol, *, return_5d=0.01):
    row = _executed(signal_date, symbol, return_5d=return_5d)
    row["observation_id"] = f"{signal_date}:{symbol}:ctrl"
    row["decision"] = "approved_buy"
    row["executed_buy"] = False
    row["approved_buy"] = False
    row["gate"] = {"execution": {"status": "plan_rejected", "reason": "max_orders_per_cycle_reached"}}
    return row


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


def _verified_pair(executed, control):
    executed["features"]["comparable_control_set"] = {
        "status": "verified",
        "cycle_id": "cycle-a",
        "treatment": {"signal_id": executed["best_signal_id"]},
        "controls": [{"signal_id": control["best_signal_id"], "gate_eligibility": "verified"}],
    }
    return [executed, control]


def test_matched_week_reports_coverage_and_control_cost_basis(tmp_path, monkeypatch):
    report = _build(
        tmp_path, monkeypatch,
        _verified_pair(_executed("2026-07-07", "EXEC"), _control("2026-07-07", "CTRL")),
    )
    row = report["weekly_rows"][0]

    assert row["matched_executed"] == 1
    assert row["unmatched_executed"] == 0
    assert row["control_n"] == 1
    assert row["control_cost_basis"] == "assumption_10bps"
    # Controles no ejecutados: sin fills, el calibrado no aplica.
    assert row["expectancy_net_calibrated"] is None
    assert report["cost_calibration"]["cost_basis"] == "assumption_10bps"


def test_unmatched_executed_counted_without_hiding(tmp_path, monkeypatch):
    report = _build(tmp_path, monkeypatch, [_executed("2026-07-07", "ALONE")])
    row = report["weekly_rows"][0]

    assert row["matched_executed"] == 0
    assert row["unmatched_executed"] == 1
    assert row["control_n"] == 0
    assert row["control_expectancy_net_10bps"] is None


def test_mixed_week_separates_matched_from_unmatched(tmp_path, monkeypatch):
    report = _build(
        tmp_path, monkeypatch,
        _verified_pair(_executed("2026-07-07", "EXEC"), _control("2026-07-07", "CTRL"))
        + [_executed("2026-07-07", "ALONE", source="cycle-b")],
    )
    row = report["weekly_rows"][0]

    assert row["matched_executed"] == 1
    assert row["unmatched_executed"] == 1
    assert row["n"] == 2


def test_same_cycle_without_verified_contract_remains_unmatched(tmp_path, monkeypatch):
    report = _build(tmp_path, monkeypatch,
                    [_executed("2026-07-07", "EXEC"), _control("2026-07-07", "CTRL")])
    assert report["weekly_rows"][0]["matched_executed"] == 0
    assert report["weekly_rows"][0]["control_n"] == 0
    assert report["control_coverage"]["comparability_status"] != "verified"
