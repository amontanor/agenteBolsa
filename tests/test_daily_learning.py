from agente_bolsa.config import Settings
from agente_bolsa.models import AgentEvent
from agente_bolsa.storage import Store
from agente_bolsa.tools.daily_learning import (
    build_learning_daily_run,
    build_learning_digest_report,
    build_learning_health_report,
    build_learning_promotions_report,
    build_policy_candidates_report,
    load_daily_learning_context,
)


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


def test_learning_daily_run_deduplicates_intraday_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for suffix, score in [("1", 10), ("2", 15)]:
        store.save_signal_outcome(
            signal_id=f"scan1:AAPL:{suffix}",
            source_run_id="scan1",
            source="test",
            symbol="AAPL",
            signal_date="2026-05-01",
            decision="candidate" if suffix == "1" else "approved_buy",
            features={"score": score, "score_rank": 1, "score_rank_percentile": 0.1},
            outcome={"available": True, "matured": False, "return_3d": 0.02, "matured_horizons": {"3d": True}},
        )
    _save_buy_order(store, plan_id="p1", cycle_id="c1", symbol="AAPL", created_at="2026-05-01T15:30:00+00:00")
    store.save_signal_outcome(
        signal_id="scan2:MSFT",
        source_run_id="scan2",
        source="test",
        symbol="MSFT",
        signal_date="2026-05-01",
        decision="candidate",
        features={"score": 12},
        outcome={"available": True, "matured": False, "return_1d": -0.01, "matured_horizons": {"1d": True}},
    )

    report = build_learning_daily_run(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "daily_test",
        since_date="2026-05-01",
    )

    observations = store.learning_observations(since_date="2026-05-01", limit=50)
    assert report["observations_summary"]["observations"] == 2
    assert report["observations_summary"]["duplicates_removed"] == 1
    assert report["manifest_path"].endswith("learning_daily_run_daily_test.manifest.json")
    assert len(observations) == 2
    aapl = next(item for item in observations if item["symbol"] == "AAPL")
    assert aapl["executed_buy"] is True
    assert aapl["duplicate_count"] == 1


def test_learning_daily_run_includes_same_session_non_executed_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:GLW",
        source_run_id="scan1",
        source="intraday_scan",
        symbol="GLW",
        signal_date="2026-05-13",
        decision="candidate",
        features={"direction": "long", "score": 16, "entry_price": 197.2},
        outcome={},
    )
    store.save_signal_outcome(
        signal_id="scan2:GLW",
        source_run_id="scan2",
        source="intraday_scan",
        symbol="GLW",
        signal_date="2026-05-13",
        decision="candidate",
        features={"direction": "long", "score": 16, "entry_price": 208.6},
        outcome={},
    )
    store.record_agent_event(
        AgentEvent(
            agent="execution_agent",
            event_type="paper_auto_trade_completed",
            cycle_id="scan2",
            payload={
                "rejected_order_plans": [
                    {
                        "symbol": "GLW",
                        "action": "buy",
                        "stage": "position_sizing",
                        "reason": "below_min_order_notional",
                        "checks": {},
                    }
                ]
            },
        )
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE agent_events SET created_at = ? WHERE event_type = ?",
            ("2026-05-13T17:00:00+00:00", "paper_auto_trade_completed"),
        )

    report = build_learning_daily_run(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "ledger_test",
        since_date="2026-05-13",
        end_date="2026-05-13",
    )

    ledger = report["digest"]["same_session_opportunity_ledger"]
    assert ledger["summary"]["non_executed"] == 1
    assert ledger["top_non_executed"][0]["symbol"] == "GLW"
    assert ledger["top_non_executed"][0]["same_session_return"] == 0.0578
    assert ledger["top_non_executed"][0]["reason_not_executed"] == "position_sizing: below_min_order_notional"


def test_learning_daily_run_adds_intraday_momentum_shadow_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for symbol, first_entry, mid_entry, latest_entry in [("HOOD", 100.0, 103.0, 106.0), ("SMCI", 50.0, 51.5, 53.0)]:
        store.save_signal_outcome(
            signal_id=f"scan1:{symbol}",
            source_run_id="scan1",
            source="intraday_scan",
            symbol=symbol,
            signal_date="2026-05-28",
            decision="candidate",
            features={"direction": "long", "score": 15, "entry_price": first_entry},
            outcome={},
        )
        store.save_signal_outcome(
            signal_id=f"scan2:{symbol}",
            source_run_id="scan2",
            source="intraday_scan",
            symbol=symbol,
            signal_date="2026-05-28",
            decision="candidate",
            features={"direction": "long", "score": 15, "entry_price": mid_entry},
            outcome={},
        )
        store.save_signal_outcome(
            signal_id=f"scan3:{symbol}",
            source_run_id="scan3",
            source="intraday_scan",
            symbol=symbol,
            signal_date="2026-05-28",
            decision="candidate",
            features={
                "direction": "long",
                "score": 15,
                "entry_price": latest_entry,
                "rsi_14": 68.0,
                "volume_zscore_20": 0.8,
                "distance_sma20": 0.09,
                "chart_patterns": {"bullish_confirmed_count": 2},
            },
            outcome={},
        )

    report = build_learning_daily_run(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "shadow_intraday_test",
        since_date="2026-05-28",
        end_date="2026-05-28",
    )

    shadow = report["digest"]["shadow_candidates"]
    intraday = next(item for item in shadow if item["policy_id"] == "shadow_intraday_same_session_momentum_promotion")
    active = next(
        item
        for item in report["digest"]["active_or_guarded_policies"]
        if item["policy_id"] == "intraday_same_session_momentum_promotion"
    )
    assert intraday["tag"] == "intraday_same_session_momentum"
    assert intraday["metrics"]["cases"] == 2
    assert intraday["metrics"]["top3_portfolio_capture_at_5pct"] == 0.006
    assert active["status"] == "guarded_active"
    assert "momentum intradia repetido" in report["digest"]["guidance"][-1]


def test_learning_daily_run_is_incremental_on_repeated_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan3:NVDA",
        source_run_id="scan3",
        source="test",
        symbol="NVDA",
        signal_date="2026-05-02",
        decision="candidate",
        features={"score": 18},
        outcome={"available": True, "return_3d": 0.04, "matured_horizons": {"3d": True}},
    )

    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, tmp_path / "reports", "run1", since_date="2026-05-02")
    first = store.learning_observations(since_date="2026-05-02", limit=20)
    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, tmp_path / "reports", "run2", since_date="2026-05-02")
    second = store.learning_observations(since_date="2026-05-02", limit=20)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["observation_id"] == second[0]["observation_id"]


def test_learning_digest_and_health_reports_reflect_partial_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for idx, ret in enumerate([0.03, 0.025, -0.02], start=1):
            store.save_signal_outcome(
                signal_id=f"scan4:SYM{idx}",
                source_run_id=f"scan4_{idx}",
                source="test",
                symbol=f"SYM{idx}",
                signal_date="2026-05-03",
                decision="candidate",
                features={"score": 14 + idx, "rsi_14": 88, "distance_sma20": 0.14, "volume_zscore_20": -0.2},
                gate={"llm": {"confidence": 0.92}},
                outcome={"available": True, "return_3d": ret, "matured_horizons": {"3d": True}},
            )

    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, tmp_path / "reports", "run_digest", since_date="2026-05-03")
    health = build_learning_health_report(store, tmp_path / "reports", "health", since_date="2026-05-03")
    digest = build_learning_digest_report(store, tmp_path / "reports", "digest", since_date="2026-05-03")

    assert health["health"]["horizon_coverage"]["3d"] == 3
    assert digest["digest"]["summary"]["horizon_coverage"]["3d"] == 3
    assert digest["digest"]["setup_stats_3d"]
    assert digest["digest"]["setup_priors_3d"]
    assert digest["digest"]["confidence_calibration_3d"]
    assert digest["digest"]["prior_accuracy_3d"]
    assert "entry_quality_filter_calibration_3d" in digest["digest"]
    assert "backtest_filter_calibration_3d" in digest["digest"]
    assert load_daily_learning_context(tmp_path)["available"] is True
    assert load_daily_learning_context(tmp_path)["setup_priors_3d"]
    assert load_daily_learning_context(tmp_path)["confidence_calibration_3d"]
    assert load_daily_learning_context(tmp_path)["prior_accuracy_3d"]


def test_learning_digest_exposes_false_positive_and_false_negative_rates(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_fp:AAPL",
        source_run_id="scan_fp",
        source="test",
        symbol="AAPL",
        signal_date="2026-05-04",
        decision="approved_buy",
        features={"score": 18, "selection_score": 0.08, "selection_rank": 1, "orderly_breakout_long": True},
        outcome={"available": True, "return_3d": -0.03, "matured_horizons": {"3d": True}},
    )
    _save_buy_order(store, plan_id="fp_plan", cycle_id="scan_fp", symbol="AAPL", created_at="2026-05-04T15:30:00+00:00")
    store.save_signal_outcome(
        signal_id="scan_fn:MSFT",
        source_run_id="scan_fn",
        source="test",
        symbol="MSFT",
        signal_date="2026-05-04",
        decision="blocked_entry_quality",
        features={"score": 17, "rank_priority_score": 0.06, "selection_rank": 2, "event_momentum_long": True},
        outcome={"available": True, "return_3d": 0.04, "matured_horizons": {"3d": True}},
    )

    report = build_learning_daily_run(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "error_rates",
        since_date="2026-05-04",
        end_date="2026-05-04",
    )

    rates = report["digest"]["summary"]["decision_error_rates_3d"]
    assert rates["false_positive_executed_losers"] == 1
    assert rates["false_positive_rate"] == 1.0
    assert rates["false_negative_blocked_winners"] == 1
    assert rates["false_negative_rate"] == 1.0
    assert rates["false_positive_examples"][0]["symbol"] == "AAPL"
    assert rates["false_positive_examples"][0]["setup"] == "orderly_breakout"
    assert rates["false_positive_examples"][0]["selection_score"] == 0.08
    assert rates["false_negative_examples"][0]["symbol"] == "MSFT"
    assert rates["false_negative_examples"][0]["setup"] == "event_momentum"
    memory = report["digest"]["symbol_setup_memory_3d"]
    assert {"AAPL", "MSFT"} == {item["symbol"] for item in memory}
    assert load_daily_learning_context(tmp_path)["symbol_setup_memory_3d"]


def test_learning_digest_includes_pre_earnings_context_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan7:AAPL",
        source_run_id="scan7",
        source="test",
        symbol="AAPL",
        signal_date="2026-05-06",
        decision="candidate",
        features={"score": 18},
        outcome={"available": True, "return_3d": 0.03, "matured_horizons": {"3d": True}},
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_pre_earnings_learning_digest.json").write_text(
        '{"available": true, "as_of": "2026-05-06T20:00:00+00:00", "summary": {"blocked_big_winners": 2}, "guidance": ["revisar vetos de riesgo"]}',
        encoding="utf-8",
    )

    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, reports_dir, "run_preearn_ctx", since_date="2026-05-06")
    digest = load_daily_learning_context(tmp_path)

    assert digest["pre_earnings"]["available"] is True
    assert digest["pre_earnings"]["summary"]["blocked_big_winners"] == 2
    assert "revisar vetos de riesgo" in digest["guidance"]


def test_policy_candidates_and_promotions_are_conservative(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for suffix in ["1", "2"]:
        store.save_signal_outcome(
            signal_id=f"scan5:AMD:{suffix}",
            source_run_id="scan5",
            source="test",
            symbol="AMD",
            signal_date="2026-05-04",
            decision="approved_buy",
            features={"score": 16, "rsi_14": 90, "distance_sma20": 0.15, "volume_zscore_20": -0.5},
            outcome={"available": True, "return_3d": -0.03, "matured_horizons": {"3d": True}},
        )
    _save_buy_order(store, plan_id="p2", cycle_id="c2", symbol="AMD", created_at="2026-05-04T15:30:00+00:00")
    _save_buy_order(store, plan_id="p3", cycle_id="c2", symbol="AMD", created_at="2026-05-04T15:31:00+00:00")

    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, tmp_path / "reports", "run_policy", since_date="2026-05-04")
    candidates = build_policy_candidates_report(store, tmp_path / "reports", "policies")
    promotions = build_learning_promotions_report(store, tmp_path / "reports", "promotions")

    dedupe = next(item for item in candidates["policies"] if item["policy_id"] == "dedupe_same_symbol_cycle")
    assert dedupe["status"] in {"guarded_active", "active"}
    assert dedupe["auto_activatable"] is True
    assert all(item["status"] != "active" for item in candidates["policies"] if item["policy_id"] != "dedupe_same_symbol_cycle")
    assert promotions["summary"]["guarded_active"] >= 1


def test_learning_daily_run_creates_small_number_of_shadow_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.daily_learning.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for idx in range(120):
        store.save_signal_outcome(
            signal_id=f"scan6:WEAK:{idx}",
            source_run_id=f"scan6_{idx}",
            source="test",
            symbol=f"W{idx}",
            signal_date="2026-05-05",
            decision="candidate",
            features={"score": 13, "rsi_14": 68, "distance_sma20": 0.03, "volume_zscore_20": 0.2},
            outcome={"available": True, "return_3d": -0.02 if idx < 80 else 0.0, "matured_horizons": {"3d": True}},
        )
    for idx in range(120):
        store.save_signal_outcome(
            signal_id=f"scan6:OTHER:{idx}",
            source_run_id=f"scan6x_{idx}",
            source="test",
            symbol=f"O{idx}",
            signal_date="2026-05-05",
            decision="candidate",
            features={"score": 16, "rsi_14": 55, "distance_sma20": 0.12, "volume_zscore_20": 1.1},
            outcome={"available": True, "return_3d": 0.02, "matured_horizons": {"3d": True}},
        )

    build_learning_daily_run(Settings(DATA_DIR=tmp_path), store, tmp_path / "reports", "run_shadow", since_date="2026-05-05")
    candidates = build_policy_candidates_report(store, tmp_path / "reports", "policies_shadow")

    shadows = [item for item in candidates["policies"] if item["status"] == "shadow"]
    assert 1 <= len(shadows) <= 2
    assert all(item["auto_activatable"] is False for item in shadows)
    assert all((item.get("evidence") or {}).get("selection_reason") for item in shadows)
