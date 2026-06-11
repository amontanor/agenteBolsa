import json
import os

from agente_bolsa.agent_config import validate_agent_task_config
from agente_bolsa.config import Settings
from agente_bolsa.tools.market_state import build_market_state
from agente_bolsa.tools.market_state import load_latest_market_state


def _settings(tmp_path):
    return Settings(DATA_DIR=tmp_path, DEFAULT_UNIVERSE="AAPL,MSFT,NVDA", BENCHMARK_SYMBOL="SPY")


def test_validate_agent_task_config_accepts_repo_defaults():
    payload = validate_agent_task_config()

    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["summary"]["agents"] >= 10
    assert payload["summary"]["enabled_tasks"] >= 1


def test_market_state_degrades_when_macro_and_earnings_are_missing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.tools.market_state._sector_leadership",
        lambda settings: (
            {"available": True, "leaders": [{"symbol": "XLK", "return_20d": 0.06}], "laggards": [], "coverage_ratio": 0.1},
            [],
        ),
    )
    snapshot = {
        "benchmark": "SPY",
        "provider": "auto",
        "warnings": [],
        "symbols": {
            "SPY": {
                "close": 500.0,
                "return_20d": 0.04,
                "sma_20": 490.0,
                "sma_50": 480.0,
                "sma_200": 450.0,
                "atr_14": 8.0,
                "trend_positive": True,
                "above_long_trend": True,
            },
            "AAPL": {
                "close": 200.0,
                "return_20d": 0.08,
                "sma_20": 190.0,
                "sma_50": 185.0,
                "sma_200": 170.0,
                "atr_14": 4.0,
                "trend_positive": True,
                "above_long_trend": True,
            },
            "MSFT": {
                "close": 420.0,
                "return_20d": 0.02,
                "sma_20": 415.0,
                "sma_50": 410.0,
                "sma_200": 390.0,
                "atr_14": 6.0,
                "trend_positive": True,
                "above_long_trend": True,
            },
        },
    }

    state = build_market_state(settings, settings.data_dir / "reports", "run_1", market_snapshot=snapshot)

    assert state["market_regime"] == "bullish"
    assert state["risk_posture"] in {"balanced", "defensive"}
    assert state["market_regime_policy"]["profile"] in {"neutral", "bullish"}
    assert state["data_quality"]["data_vendor_quality"]["provider_used"] == "auto"
    assert state["breadth"]["trend_positive_ratio"] == 1.0
    assert state["data_quality"]["status"] in {"PARTIAL", "INSUFFICIENT"}
    assert "macro_summary_missing" in state["data_quality"]["notes"]
    assert state["path"]
    assert json.loads((settings.data_dir / "reports" / "market_state_run_1.json").read_text(encoding="utf-8"))["run_id"] == "run_1"


def test_market_state_policy_halts_new_buys_when_data_insufficient(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "agente_bolsa.tools.market_state._sector_leadership",
        lambda settings: ({"available": False, "leaders": [], "laggards": [], "coverage_ratio": 0.0}, []),
    )
    state = build_market_state(settings, settings.data_dir / "reports", "insufficient", market_snapshot={"symbols": {}, "benchmark": "SPY"})

    assert state["data_quality"]["status"] == "INSUFFICIENT"
    assert state["risk_posture"] == "halt_new_buys"
    assert state["market_regime_policy"]["allow_new_buys"] is False


def test_load_latest_market_state_returns_most_recent_report(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    old_path = reports_dir / "market_state_old.json"
    old_path.write_text(json.dumps({"run_id": "old"}), encoding="utf-8")
    latest_path = reports_dir / "market_state_new.json"
    latest_path.write_text(json.dumps({"run_id": "new"}), encoding="utf-8")
    os.utime(old_path, (1, 1))
    os.utime(latest_path, None)

    payload = load_latest_market_state(reports_dir)

    assert payload is not None
    assert payload["run_id"] == "new"
    assert payload["path"] == str(latest_path)
