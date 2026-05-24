from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.counterfactual_analysis import (
    build_decision_compare_report,
    build_missed_opportunities_report,
    build_session_retrospective_report,
)
from agente_bolsa.main import build_parser


def _save_buy_order(store: Store, *, plan_id: str, cycle_id: str, symbol: str, created_at: str) -> None:
    store.save_broker_order(
        broker_order_id=f"bo_{plan_id}",
        plan_id=plan_id,
        cycle_id=cycle_id,
        symbol=symbol,
        side="buy",
        status="filled",
        payload={
            "plan": {
                "plan_id": plan_id,
                "notional": 1000.0,
                "payload": {
                    "entry_price": 100.0,
                    "qty": 10.0,
                    "recommendation": {"symbol": symbol, "action": "buy", "confidence": 0.9},
                },
            }
        },
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE broker_orders SET created_at = ? WHERE broker_order_id = ?",
            (created_at, f"bo_{plan_id}"),
        )


def test_new_cli_commands_are_parseable():
    parser = build_parser()

    args = parser.parse_args(["learning-daily-run"])
    assert args.command == "learning-daily-run"

    args = parser.parse_args(["learning-health"])
    assert args.command == "learning-health"

    args = parser.parse_args(["learning-digest"])
    assert args.command == "learning-digest"

    args = parser.parse_args(["policy-candidates"])
    assert args.command == "policy-candidates"

    args = parser.parse_args(["learning-promotions"])
    assert args.command == "learning-promotions"

    args = parser.parse_args(["learning-postmortem"])
    assert args.command == "learning-postmortem"

    args = parser.parse_args(["missed-opportunities"])
    assert args.command == "missed-opportunities"

    args = parser.parse_args(["decision-compare", "--policy", "proposed"])
    assert args.command == "decision-compare"

    args = parser.parse_args(["walk-forward-validate"])
    assert args.command == "walk-forward-validate"

    args = parser.parse_args(["session-retrospective"])
    assert args.command == "session-retrospective"


def test_missed_opportunities_report_only_lists_non_executed_winners(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:AAPL",
        source_run_id="scan1",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-28",
        decision="candidate",
        features={"score": 15},
        outcome={"available": True, "matured": True, "return_5d": 0.08, "verdict": "winner_open"},
    )
    store.save_signal_outcome(
        signal_id="scan1:MSFT",
        source_run_id="scan1",
        source="test",
        symbol="MSFT",
        signal_date="2026-04-28",
        decision="approved_buy",
        features={"score": 13},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c1", symbol="MSFT", created_at="2026-04-28T15:30:00+00:00")

    report = build_missed_opportunities_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "missed_test",
        since_date="2026-04-28",
        top=10,
    )

    assert report["summary"]["missed_opportunities"] == 1
    assert report["top_missed_opportunities"][0]["symbol"] == "AAPL"
    assert report["top_missed_opportunities"][0]["flags"]["ranking_failure"] is True


def test_decision_compare_blocks_duplicate_current_executions(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for suffix, ret in [("1", -0.04), ("2", -0.01)]:
        store.save_signal_outcome(
            signal_id=f"scan2:NVDA:{suffix}",
            source_run_id="scan2",
            source="test",
            symbol="NVDA",
            signal_date="2026-04-29",
            decision="approved_buy",
            features={"score": 16},
            outcome={"available": True, "matured": True, "return_5d": ret, "verdict": "loser_open"},
        )
    _save_buy_order(store, plan_id="p1", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:31:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 2
    assert summary["proposed"]["executed"] == 1
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.01


def test_decision_compare_blocks_same_day_duplicate_across_different_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_a:NVDA",
        source_run_id="scan_a",
        source="test",
        symbol="NVDA",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 16, "rsi_14": 68, "volume_zscore_20": 1.0},
        outcome={"available": True, "matured": True, "return_5d": -0.04, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_b:NVDA",
        source_run_id="scan_b",
        source="test",
        symbol="NVDA",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 15, "rsi_14": 67, "volume_zscore_20": 0.8},
        outcome={"available": True, "matured": True, "return_5d": -0.01, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c3", symbol="NVDA", created_at="2026-04-29T17:31:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_same_day_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 2
    assert summary["proposed"]["executed"] == 1
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.01


def test_decision_compare_blocks_weak_rsi_weak_volume_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_weak:FDX",
        source_run_id="scan_weak",
        source="test",
        symbol="FDX",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 16, "rsi_14": 60.0, "volume_zscore_20": -0.5},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p_weak", cycle_id="c_weak", symbol="FDX", created_at="2026-04-29T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_weak_profile_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 1
    assert summary["proposed"]["executed"] == 0
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.03


def test_decision_compare_reports_rank_shadow_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_rank:LOW",
        source_run_id="scan_rank",
        source="test",
        symbol="LOW",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={"score": 10, "return_20d": -0.01, "distance_sma20": -0.02, "volume_zscore_20": -0.5},
        outcome={"available": True, "matured": True, "return_5d": -0.04, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_rank:HIGH",
        source_run_id="scan_rank",
        source="test",
        symbol="HIGH",
        signal_date="2026-05-01",
        decision="candidate",
        features={"score": 18, "return_20d": 0.08, "distance_sma20": 0.03, "volume_zscore_20": 1.2},
        outcome={"available": True, "matured": True, "return_5d": 0.06, "verdict": "winner_open"},
    )
    _save_buy_order(store, plan_id="p_rank", cycle_id="c_rank", symbol="LOW", created_at="2026-05-01T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "rank_shadow_test",
        since_date="2026-05-01",
        policy="proposed",
    )

    rank_shadow = report["summary"]["rank_shadow"]
    assert rank_shadow["candidate_replacements"] == 1
    assert rank_shadow["positive_replacements"] == 1
    assert rank_shadow["delta_net_opportunity"] == 0.1
    assert report["summary"]["regime_summary"]


def test_decision_compare_rank_shadow_uses_priority_not_only_raw_score(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_rank2:EXEC",
        source_run_id="scan_rank2",
        source="test",
        symbol="EXEC",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={
            "score": 16,
            "return_20d": 0.02,
            "distance_sma20": 0.13,
            "volume_zscore_20": -0.6,
            "rsi_14": 60.0,
            "chart_patterns": {"bullish_confirmed_count": 0},
        },
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_rank2:ALT",
        source_run_id="scan_rank2",
        source="test",
        symbol="ALT",
        signal_date="2026-05-01",
        decision="candidate",
        features={
            "score": 15,
            "return_20d": 0.08,
            "distance_sma20": 0.03,
            "volume_zscore_20": 1.2,
            "rsi_14": 70.0,
            "chart_patterns": {"bullish_confirmed_count": 1},
        },
        outcome={"available": True, "matured": True, "return_5d": 0.04, "verdict": "winner_open"},
    )
    _save_buy_order(store, plan_id="p_rank2", cycle_id="c_rank2", symbol="EXEC", created_at="2026-05-01T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "rank_shadow_priority_test",
        since_date="2026-05-01",
        policy="proposed",
    )

    rank_shadow = report["summary"]["rank_shadow"]
    assert rank_shadow["candidate_replacements"] == 1
    assert rank_shadow["positive_replacements"] == 1
    assert rank_shadow["delta_net_opportunity"] == 0.07
    example = rank_shadow["examples"][0]
    assert example["replace_symbol"] == "EXEC"
    assert example["with_symbol"] == "ALT"
    assert example["with_score"] < example["replace_score"]
    assert example["with_priority"] > example["replace_priority"]


def test_decision_compare_uses_trade_memory_for_executed_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_tm:AAPL",
        source_run_id="scan_tm",
        source="test",
        symbol="AAPL",
        signal_date="2026-05-02",
        decision="approved_buy",
        features={"score": 16},
        outcome={"available": False, "matured": False, "reason": "sin barras posteriores"},
    )
    _save_buy_order(store, plan_id="p_tm", cycle_id="c_tm", symbol="AAPL", created_at="2026-05-02T15:30:00+00:00")
    store.save_trade_memory(
        {
            "memory_id": "tm_aapl",
            "trade_time": "2026-05-02T15:30:00Z",
            "trade_date": "2026-05-02",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 10,
            "price": 100,
            "notional": 1000,
            "realized_pl": None,
            "realized_plpc": None,
            "open_pl": -25,
            "open_plpc": -0.025,
            "verdict": "loser_open",
            "features": {},
            "thesis": {},
            "outcome": {"pl": -25, "plpc": -0.025, "verdict": "loser_open"},
        }
    )

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "trade_memory_test",
        since_date="2026-05-02",
        policy="proposed",
    )

    assert report["summary"]["current"]["matured"] == 1
    assert report["summary"]["current"]["losers"] == 1
    assert report["summary"]["current"]["avg_return_5d"] == -0.025


def test_session_retrospective_aggregates_daily_results(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan3:AMZN:1",
        source_run_id="scan3",
        source="test",
        symbol="AMZN",
        signal_date="2026-04-30",
        decision="approved_buy",
        features={"score": 15},
        outcome={"available": True, "matured": True, "return_5d": -0.02, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan3:AMZN:2",
        source_run_id="scan3",
        source="test",
        symbol="AMZN",
        signal_date="2026-04-30",
        decision="approved_buy",
        features={"score": 14},
        outcome={"available": True, "matured": True, "return_5d": 0.01, "verdict": "flat"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c3", symbol="AMZN", created_at="2026-04-30T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c3", symbol="AMZN", created_at="2026-04-30T15:31:00+00:00")

    report = build_session_retrospective_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "retro_test",
        since_date="2026-04-30",
        end_date="2026-04-30",
        sessions=8,
        policy="proposed",
    )

    assert report["summary"]["sessions"] == 1
    session = report["sessions"][0]
    assert session["blocked_by_new_policy"] == 1
    assert session["delta_fragmentation"] == 1
    assert "rank_shadow_replacements" in session
    assert "aggregate_rank_shadow_delta" in report["summary"]
