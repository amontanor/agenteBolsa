from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.counterfactual_analysis import build_missed_opportunities_report


def test_missed_opportunities_report_includes_filter_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:WIN",
        source_run_id="scan1",
        source="test",
        symbol="WIN",
        signal_date="2026-05-01",
        decision="blocked_entry_quality",
        features={
            "score": 16,
            "return_20d": 0.08,
            "distance_sma20": 0.03,
            "volume_zscore_20": 1.1,
            "rsi_14": 70.0,
        },
        gate={"entry_quality_gate": {"approved": False, "reason": "rsi_extremo_shadow"}},
        outcome={"available": True, "matured": True, "return_5d": 0.05, "verdict": "winner_open"},
    )
    store.save_signal_outcome(
        signal_id="scan1:LOSE",
        source_run_id="scan1",
        source="test",
        symbol="LOSE",
        signal_date="2026-05-01",
        decision="blocked_entry_quality",
        features={
            "score": 14,
            "return_20d": -0.02,
            "distance_sma20": 0.12,
            "volume_zscore_20": -0.4,
            "rsi_14": 59.0,
        },
        gate={"entry_quality_gate": {"approved": False, "reason": "rsi_extremo_shadow"}},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )

    report = build_missed_opportunities_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "missed_calibration",
        since_date="2026-05-01",
        top=10,
    )

    entry_quality = report["filter_calibration"]["entry_quality"]
    assert entry_quality["signals"] == 2
    assert entry_quality["matured"] == 2
    assert entry_quality["missed_winners"] == 1
    assert entry_quality["avoided_losers"] == 1
    assert entry_quality["by_reason"][0]["label"] == "rsi_extremo_shadow"


def test_missed_opportunities_report_includes_approved_not_executed_breakdown(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:WINNER",
        source_run_id="scan1",
        source="test",
        symbol="WINNER",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={"score": 16},
        gate={"execution": {"status": "plan_rejected", "stage": "position_sizing", "reason": "below_min_order_notional"}},
        outcome={"available": True, "matured": True, "return_5d": 0.06, "verdict": "winner_open"},
    )
    store.save_signal_outcome(
        signal_id="scan1:LOSER",
        source_run_id="scan1",
        source="test",
        symbol="LOSER",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={"score": 15},
        gate={"execution": {"status": "submit_failed", "side": "buy"}},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )

    report = build_missed_opportunities_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "missed_exec_breakdown",
        since_date="2026-05-01",
        top=10,
    )

    approved_not_executed = report["approved_not_executed"]
    assert approved_not_executed["signals"] == 2
    assert approved_not_executed["matured"] == 2
    assert approved_not_executed["missed_winners"] == 1
    assert approved_not_executed["avoided_losers"] == 1
    labels = {item["label"] for item in approved_not_executed["by_execution_stage"]}
    assert "plan_rejected:position_sizing:below_min_order_notional" in labels
    assert "submit_failed:buy" in labels
