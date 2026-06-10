"""Tests del scorecard de figuras y pesos dinamicos (T3.3)."""

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.pattern_scorecard import build_pattern_scorecard, pattern_weight


def _setup(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, **overrides)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed(store, labels, winner, idx):
    store.save_signal_outcome(
        signal_id=f"s{idx}",
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date="2026-06-10",
        decision="buy",
        features={"chart_patterns": {"labels": labels}},
        gate={},
        outcome={"verdict": "winner_fast" if winner else "loser", "return_pct": 0.02 if winner else -0.01},
    )


def test_lift_computation(tmp_path):
    settings, store = _setup(tmp_path)
    for i in range(10):
        _seed(store, ["HCH"], i < 8, i)        # 80% win
    for i in range(10):
        _seed(store, ["flag"], i < 4, 100 + i)  # 40% win

    scorecard = build_pattern_scorecard(store, min_occurrences=5)
    by_pattern = {row["pattern"]: row for row in scorecard["patterns"]}
    # HCH 0.8 / flag-baseline 0.4 = 2.0 ; flag 0.4 / HCH-baseline 0.8 = 0.5
    assert by_pattern["HCH"]["lift"] == 2.0
    assert by_pattern["flag"]["lift"] == 0.5


def test_underperforming_pattern_retired(tmp_path):
    settings, store = _setup(tmp_path)
    for i in range(60):
        _seed(store, ["flag"], i < 20, i)        # 33% win, >=50 occ
    for i in range(60):
        _seed(store, ["winner_pat"], i < 50, 1000 + i)  # 83% win

    scorecard = build_pattern_scorecard(store, min_occurrences=30)
    flag = {row["pattern"]: row for row in scorecard["patterns"]}["flag"]
    assert flag["status"] == "RETIRED"


def test_pattern_weight_dynamic_and_clamped(tmp_path):
    settings, store = _setup(tmp_path, PATTERN_DYNAMIC_WEIGHTS_ENABLED=True, PATTERN_MIN_OCCURRENCES=5)
    for i in range(10):
        _seed(store, ["HCH"], i < 8, i)
    for i in range(10):
        _seed(store, ["flag"], i < 4, 100 + i)
    build_pattern_scorecard(store, min_occurrences=5)

    # lift 2.0 -> base*2 clamped al maximo 2x base.
    assert pattern_weight(store, settings, "HCH", 1.0) == 2.0
    # flag lift 0.5 -> base*0.5.
    assert pattern_weight(store, settings, "flag", 1.0) == 0.5


def test_pattern_weight_falls_back_when_disabled(tmp_path):
    settings, store = _setup(tmp_path, PATTERN_DYNAMIC_WEIGHTS_ENABLED=False)
    assert pattern_weight(store, settings, "HCH", 1.0) == 1.0
