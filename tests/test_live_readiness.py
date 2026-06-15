from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.live_readiness import build_live_readiness_report


def test_live_readiness_blocks_without_official_data_and_traceability(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        MARKET_DATA_PROVIDER="yfinance",
        REQUIRE_HUMAN_APPROVAL=True,
        OPERATIONAL_KILL_SWITCH_ENABLED=True,
    )
    settings.ensure_runtime_dirs()
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_trade_memory(
        {
            "memory_id": "tm_missing",
            "trade_time": "2026-05-13T15:30:00Z",
            "trade_date": "2026-05-13",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "price": 100.0,
            "notional": 100.0,
            "verdict": "pending",
            "features": {},
            "thesis": {},
            "outcome": {},
        }
    )

    report = build_live_readiness_report(
        settings,
        store,
        settings.data_dir / "reports",
        "live_test",
        since_date="2026-05-01",
    )

    checks = {item["key"]: item for item in report["checks"]}
    assert report["summary"]["ready_for_live"] is False
    assert checks["market_data_provider"]["status"] == "block"
    assert checks["fill_signal_traceability"]["status"] == "block"
    assert checks["human_approval"]["status"] == "pass"
    assert checks["shadow_daily_learning_window"]["status"] == "block"
    assert checks["shadow_rule_evidence_window"]["status"] == "block"


def test_live_readiness_passes_shadow_window_when_learning_and_rule_evidence_exist(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        MARKET_DATA_PROVIDER="fmp",
        FMP_API_KEY="key",
        REQUIRE_HUMAN_APPROVAL=True,
        OPERATIONAL_KILL_SWITCH_ENABLED=True,
    )
    settings.ensure_runtime_dirs()
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for idx in range(20):
        store.upsert_learning_daily_summary(
            summary_id=f"daily:{idx}",
            session_date=f"2026-05-{idx + 1:02d}",
            kind="daily_learning",
            payload={"digest": {"summary": {}}},
        )
    store.upsert_strategy_rule(
        {
            "rule_id": "rule_shadow_window",
            "name": "shadow window",
            "description": "test",
            "condition": {"all": [{"field": "side", "op": "==", "value": "buy"}]},
            "effect": "block_buy",
            "status": "shadow",
            "source": "test",
            "evidence": {},
            "metrics": {},
        }
    )
    for idx in range(20):
        store.save_rule_evaluation(
            {
                "evaluation_id": f"eval_{idx}",
                "rule_id": "rule_shadow_window",
                "memory_id": f"memory_{idx}",
                "symbol": "AAPL",
                "would_block": True,
                "actual_outcome": "loser_open",
            }
        )

    report = build_live_readiness_report(
        settings,
        store,
        settings.data_dir / "reports",
        "live_shadow_test",
        since_date="2026-05-01",
    )

    checks = {item["key"]: item for item in report["checks"]}
    assert checks["shadow_daily_learning_window"]["status"] == "pass"
    assert checks["shadow_rule_evidence_window"]["status"] == "pass"


def test_trading_safety_blocks_live_with_informal_market_data(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        TRADING_MODE="live",
        ALLOW_LIVE_TRADING=True,
        ALPACA_PAPER=False,
        MARKET_DATA_PROVIDER="yfinance",
    )

    try:
        settings.assert_trading_safety()
    except RuntimeError as exc:
        assert "FMP_API_KEY" in str(exc)
    else:
        raise AssertionError("live trading should require formal market data")
