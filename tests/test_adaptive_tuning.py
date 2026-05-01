from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.adaptive_tuning import (
    active_adaptive_overrides,
    adaptive_config_path,
    adaptive_status,
    promote_post_market_improvements,
    update_adaptive_config,
)


def _store_with_signal(tmp_path, *, tag_case: str = "rsi_extreme"):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for index in range(12):
        if tag_case == "rsi_extreme":
            features = {
                "score": 15,
                "rsi_14": 90,
                "distance_sma20": 0.05,
                "macd_diff": 1.0,
                "volume_zscore_20": 1.2,
                "chart_patterns": {"bullish_confirmed_count": 1},
            }
        else:
            features = {
                "score": 13,
                "rsi_14": 70,
                "distance_sma20": 0.15,
                "macd_diff": 1.0,
                "volume_zscore_20": 1.2,
                "chart_patterns": {"bullish_confirmed_count": 1},
            }
        store.save_signal_outcome(
            signal_id=f"scan:{index}",
            source_run_id="scan",
            source="test",
            symbol=f"T{index}",
            signal_date="2026-04-27",
            decision="approved_buy",
            features=features,
            outcome={"verdict": "loser_open", "return_5d": -0.02},
        )
    return store


def test_adaptive_tune_proposes_shadow_rsi_limit(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ENTRY_QUALITY_MAX_RSI=85)
    settings.ensure_runtime_dirs()
    store = _store_with_signal(tmp_path)

    result = update_adaptive_config(settings, store, min_resolved=10)

    params = result["config"]["parameters"]
    assert "ENTRY_QUALITY_MAX_RSI" in params
    assert params["ENTRY_QUALITY_MAX_RSI"]["status"] == "shadow"
    assert params["ENTRY_QUALITY_MAX_RSI"]["proposed"] == 82.0


def test_adaptive_status_reports_configured_parameters(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data")
    settings.ensure_runtime_dirs()

    status = adaptive_status(settings)

    assert status["exists"] is False
    assert any(item["name"] == "ENTRY_QUALITY_MAX_RSI" for item in status["parameters"])


def test_active_adaptive_overrides_reads_only_active(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data")
    settings.ensure_runtime_dirs()
    path = adaptive_config_path(settings)
    path.write_text(
        """
{
  "version": 1,
  "parameters": {
    "ENTRY_QUALITY_MAX_RSI": {
      "status": "active",
      "proposed": 81
    },
    "ENTRY_QUALITY_MAX_SMA20_DISTANCE": {
      "status": "shadow",
      "proposed": 0.08
    }
  }
}
""",
        encoding="utf-8",
    )

    overrides = active_adaptive_overrides(settings)

    assert overrides == {"entry_quality_max_rsi": 81.0}


def test_promote_post_market_improvements_activates_conservative_overrides(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data")
    settings.ensure_runtime_dirs()
    report = {
        "session_date": "2026-04-28",
        "summary": {
            "day_realized_pl": -100.0,
            "open_unrealized_pl": -25.0,
            "open_positions": 7,
        },
        "proposed_improvements": [
            {
                "id": "prefer_stop_take_exits",
                "priority": "high",
                "reason": "ventas no asociadas a stop/take",
            },
            {
                "id": "limit_daily_entries",
                "priority": "high",
                "suggested_config": {"MAX_ORDERS_PER_CYCLE": 2},
            },
            {
                "id": "add_entry_quality_filters",
                "priority": "medium",
                "reason": "entradas extendidas debiles",
            },
        ],
    }

    result = promote_post_market_improvements(settings, report)
    overrides = active_adaptive_overrides(settings)

    assert set(result["promoted"]) == {
        "LLM_EXIT_EXCEPTION_MIN_CONFIDENCE",
        "LLM_EXIT_EXCEPTION_MIN_DRAWDOWN",
        "MAX_ORDERS_PER_CYCLE",
        "ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE",
        "ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN",
        "ENTRY_QUALITY_EXTENDED_MIN_VOLUME_Z",
    }
    assert overrides["llm_exit_exception_min_confidence"] == 0.95
    assert overrides["llm_exit_exception_min_drawdown"] == 0.08
    assert overrides["max_orders_per_cycle"] == 2
    assert overrides["entry_quality_extended_sma20_distance"] == 0.08
    assert overrides["entry_quality_extended_min_relative_return"] == 0.02
    assert overrides["entry_quality_extended_min_volume_z"] == 0.0
