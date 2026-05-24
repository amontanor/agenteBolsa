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
