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
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _observation(
    signal_date: str,
    symbol: str,
    *,
    executed: bool,
    return_5d: float | None,
    mature_5d: bool = True,
    outcome_source: str | None = None,
) -> dict[str, object]:
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
        "features": {"direction": "long"},
        "gate": {},
        "outcome": {
            "return_5d": return_5d,
            "matured_horizons": {"5d": mature_5d},
            "source": outcome_source,
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
    assert report["schema_version"] == 3
    assert report["period"]["to"] is not None


def _verified_pair(treatment, control, cycle_id):
    for row in (treatment, control):
        row["features"].setdefault("decision_lineage", {})["cycle_id"] = cycle_id
    treatment["features"]["comparable_control_set"] = {
        "status": "verified", "cycle_id": cycle_id,
        "treatment": {"signal_id": treatment["best_signal_id"]},
        "controls": [{"signal_id": control["best_signal_id"], "gate_eligibility": "verified"}],
    }


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
        executed = _observation(signal_date, f"EXEC{index}", executed=True, return_5d=returns[index - 1])
        executed["source_run_ids"] = [f"cycle-{index}"]
        control = _observation(signal_date, f"CTRL{index}", executed=False, return_5d=controls[index - 1])
        control["source_run_ids"] = [f"cycle-{index}"]
        control["decision"] = "approved_buy"
        control["gate"] = {
            "execution": {"status": "plan_rejected", "reason": "max_orders_per_cycle_reached"}
        }
        _verified_pair(executed, control, f"cycle-{index}")
        store.upsert_learning_observation(executed)
        store.upsert_learning_observation(control)

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
    assert report["weekly_rows"][0]["policy_expectancy_net_10bps"] == report["weekly_rows"][0]["expectancy_net_10bps"]


def test_learning_scoreboard_excludes_trade_memory_and_immature_returns(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_learning_observation(
        _observation(
            "2026-07-08",
            "OPEN",
            executed=True,
            return_5d=0.04,
            mature_5d=True,
            outcome_source="trade_memory",
        )
    )
    store.upsert_learning_observation(
        _observation(
            "2026-07-09",
            "EARLY",
            executed=True,
            return_5d=0.02,
            mature_5d=False,
        )
    )
    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {},
    )

    report = build_learning_scoreboard(
        settings,
        store,
        tmp_path / "reports",
        "score",
        since_date="2026-07-07",
        end_date="2026-07-10",
    )

    assert report["weekly_rows"][0]["n"] == 0
    assert report["weekly_rows"][0]["expectancy_net_10bps"] is None
    assert report["evaluation"]["status"] == "pending_maturity"
    assert report["data_quality"]["excluded_trade_memory_as_forward"] == 1
    assert report["maturity_by_horizon"]["5d"]["executed"] == 0


def test_learning_scoreboard_groups_same_day_returns_for_drawdown(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.upsert_learning_observation(_observation("2026-07-07", "WIN", executed=True, return_5d=0.10))
    store.upsert_learning_observation(_observation("2026-07-07", "LOSE", executed=True, return_5d=-0.10))
    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {},
    )

    report = build_learning_scoreboard(
        settings,
        store,
        tmp_path / "reports",
        "score",
        since_date="2026-07-07",
        end_date="2026-07-20",
    )

    # Equal-weighted portfolio return is -10 bps after costs, rather than
    # sequentially compounding two simultaneous positions.
    assert report["weekly_rows"][0]["portfolio_max_drawdown"] == -0.001


def test_learning_scoreboard_uses_only_same_cycle_eligible_capacity_controls(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    executed = _observation("2026-07-07", "EXEC", executed=True, return_5d=0.03)
    executed["source_run_ids"] = ["cycle-a"]
    executed["features"]["decision_lineage"] = {"lineage_status": "verified"}
    eligible = _observation("2026-07-07", "NEXT", executed=False, return_5d=0.01)
    eligible["source_run_ids"] = ["cycle-a"]
    eligible["decision"] = "approved_buy"
    eligible["gate"] = {
        "execution": {"status": "plan_rejected", "reason": "max_orders_per_cycle_reached"}
    }
    blocked = _observation("2026-07-07", "BLOCK", executed=False, return_5d=0.20)
    blocked["source_run_ids"] = ["cycle-a"]
    blocked["decision"] = "blocked_backtest"
    other_cycle = _observation("2026-07-07", "OTHER", executed=False, return_5d=0.30)
    other_cycle["source_run_ids"] = ["cycle-b"]
    other_cycle["decision"] = "approved_buy"
    other_cycle["gate"] = {
        "execution": {"status": "plan_rejected", "reason": "max_orders_per_cycle_reached"}
    }
    _verified_pair(executed, eligible, "cycle-a")
    other_cycle["features"]["decision_lineage"] = {"cycle_id": "cycle-b"}
    for row in (executed, eligible, blocked, other_cycle):
        store.upsert_learning_observation(row)
    monkeypatch.setattr(
        "agente_bolsa.tools.learning_scoreboard._build_spy_forward_returns",
        lambda *_args, **_kwargs: {},
    )

    report = build_learning_scoreboard(
        settings,
        store,
        tmp_path / "reports",
        "score",
        since_date="2026-07-07",
        end_date="2026-07-20",
    )

    coverage = report["control_coverage"]
    assert coverage["status"] == "available"
    assert coverage["matched_executed"] == 1
    assert coverage["matched_control_observations"] == 1
    assert report["weekly_rows"][0]["control_n"] == 1
    assert report["data_quality"]["blocked_candidates"] == {"blocked_backtest": 1}


def test_scoreboard_streams_and_keeps_stable_control_order():
    from agente_bolsa.tools.learning_scoreboard import _cohort_rows

    treatment = _observation("2026-07-07", "EXEC", executed=True, return_5d=0.03)
    controls = [_observation("2026-07-07", f"C{i}", executed=False, return_5d=0.01) for i in range(4)]
    for control in controls:
        control["best_signal_id"] = "shared"
        control["observation_id"] = "same"
        control["decision"] = "approved_buy"
        control["gate"] = {"execution": {"status": "approved_not_planned"}}
        control["features"]["decision_lineage"] = {"cycle_id": "cycle"}
        control["features"]["wide_unknown"] = "x" * 10000
    _verified_pair(treatment, controls[0], "cycle")
    treatment["features"]["comparable_control_set"]["controls"] = [
        {"signal_id": "shared", "gate_eligibility": "verified"}
    ]
    closed = []

    class StreamStore:
        def iter_learning_observations(self, **kwargs):
            assert kwargs["limit"] == 200000
            try:
                yield from [treatment, *controls]
            finally:
                closed.append(True)

        def learning_observations(self, **kwargs):
            raise AssertionError("must use stream")

    executed, matched, matches, all_control = _cohort_rows(
        StreamStore(), since_date="2026-07-01", end_date="2026-07-31", compact=True
    )
    assert closed == [True]
    assert len(executed) == 1 and len(all_control) == 4
    assert matches[treatment["observation_id"]] == ["same", "same", "same"]
    assert len(matched) == 1
    assert "wide_unknown" not in all_control[0]["features"]
