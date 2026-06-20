from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.c2_shadow_reporting import build_c2_shadow_report


def test_c2_shadow_report_keeps_behavior_flags_off_and_measures_confirmed_pattern(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        EXIT_POLICY_V2_STALE_GUARD_ENABLED=False,
        SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="s1",
        source_run_id="r1",
        source="test",
        symbol="AAPL",
        signal_date="2026-06-01",
        decision="candidate",
        features={"setup_name": "confirmed_pattern", "chart_patterns": {"bullish_confirmed_count": 1}},
        outcome={
            "return_5d": -0.02,
            "return_10d": -0.03,
            "exit_policy_v2": {"return_pct": -0.04, "peak_return": 0.01},
            "first_hit": {},
        },
    )
    store.save_signal_outcome(
        signal_id="s1-repeat",
        source_run_id="r2",
        source="test",
        symbol="AAPL",
        signal_date="2026-06-01",
        decision="candidate",
        features={"setup_name": "confirmed_pattern", "chart_patterns": {"bullish_confirmed_count": 1}},
        outcome={"return_5d": -0.01, "return_10d": -0.02},
    )

    report = build_c2_shadow_report(settings, store, since_date="2026-06-01")

    assert report["flags"]["stale_guard_behavior_enabled"] is False
    assert report["flags"]["confirmed_pattern_penalty_behavior_enabled"] is False
    assert report["confirmed_pattern"]["signals"] == 1
    assert report["confirmed_pattern"]["applied"] is False
    assert report["stale_guard"]["triggered"] == 1
