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
