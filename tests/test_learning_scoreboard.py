from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE
from agente_bolsa.tools.learning_scoreboard import (
    LEARNING_SCOREBOARD_CRITERION,
    build_learning_scoreboard,
)


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _observation(signal_date: str, symbol: str, *, executed: bool, return_5d: float) -> dict[str, object]:
    return {
        "observation_id": f"{signal_date}:{symbol}:{'exec' if executed else 'ctrl'}",
        "signal_date": signal_date,
        "symbol": symbol,
        "source_family": LEARNING_EXPERIMENT_SOURCE,
        "source_run_ids": ["run"],
        "best_signal_id": f"sig-{symbol}",
        "best_score": 15.0,
        "decision": "executed_buy" if executed else "candidate",
        "approved_buy": executed,
        "executed_buy": executed,
        "duplicate_count": 0,
        "features": {},
        "gate": {},
        "outcome": {
            "return_5d": return_5d,
            "matured_horizons": {"5d": True},
        },
        "execution": {},
    }


def test_learning_scoreboard_marks_pending_without_executed_cohort(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {},
    )

    report = build_learning_scoreboard(settings, store, tmp_path / "reports", "score")

    assert report["evaluation"]["status"] == "pending_no_executed_cohort"
    assert report["evaluation"]["criterion_verbatim"] == LEARNING_SCOREBOARD_CRITERION
    assert report["weekly_rows"] == []


def test_learning_scoreboard_evaluates_pre_registered_criterion_with_synthetic_data(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    returns = [0.003, 0.004, 0.005, 0.006, 0.012, 0.014, 0.016, 0.018]
    controls = [0.002, 0.002, 0.003, 0.003, 0.006, 0.006, 0.007, 0.007]
    dates = [
        "2026-07-07",
        "2026-07-14",
        "2026-07-21",
        "2026-07-28",
        "2026-08-04",
        "2026-08-11",
        "2026-08-18",
        "2026-08-25",
    ]
    for index, signal_date in enumerate(dates, start=1):
        store.upsert_learning_observation(_observation(signal_date, f"EXEC{index}", executed=True, return_5d=returns[index - 1]))
        store.upsert_learning_observation(_observation(signal_date, f"CTRL{index}", executed=False, return_5d=controls[index - 1]))

    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {(signal_date, 5): 0.001 for signal_date in dates},
    )

    report = build_learning_scoreboard(
        settings,
        store,
        tmp_path / "reports",
        "score",
        since_date="2026-07-07",
        end_date="2026-08-31",
    )

    evaluation = report["evaluation"]
    assert len(report["weekly_rows"]) == 8
    assert evaluation["criterion_verbatim"] == LEARNING_SCOREBOARD_CRITERION
    assert evaluation["weeks_5_8_expectancy_net_10bps"] > evaluation["weeks_1_4_expectancy_net_10bps"]
    assert evaluation["weekly_slope_expectancy_net_10bps"] > 0
    assert evaluation["beats_counterfactual"] is True
    assert evaluation["learns"] is True
    assert evaluation["status"] == "learning_confirmed"
