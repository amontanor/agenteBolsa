"""Tests de promocion champion/challenger (T1.3)."""

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.promotion import (
    PromotionManager,
    compute_strategy_metrics,
)
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, **overrides)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _seed_outcome(store, strategy, date, ret, winner, shadow, idx):
    store.save_signal_outcome(
        signal_id=f"{strategy}_{idx}",
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date=date,
        decision="buy",
        features={"strategy_name": strategy, "shadow": shadow},
        gate={},
        outcome={"verdict": "winner_fast" if winner else "loser", "return_pct": ret, "shadow": shadow},
    )


def _open_window(store, manager, strategy):
    window = manager.start_shadow(strategy, "1")
    window["started_at"] = "2026-05-01T00:00:00+00:00"
    store.upsert_promotion_window(window)
    return window


def test_compute_strategy_metrics():
    outcomes = [
        {"signal_date": "2026-05-01", "outcome": {"verdict": "winner_fast", "return_pct": 0.05}},
        {"signal_date": "2026-05-02", "outcome": {"verdict": "loser", "return_pct": -0.02}},
        {"signal_date": "2026-05-03", "outcome": {"verdict": "pending"}},
    ]
    metrics = compute_strategy_metrics(outcomes)
    assert metrics["signals"] == 2
    assert metrics["hit_rate"] == 0.5
    assert metrics["sessions"] == 2


def test_challenger_clearly_better_is_promoted(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.upsert_strategy_version({"name": "builtin_breakout", "version": "1", "status": "ACTIVE"})
    for i in range(22):
        date = f"2026-05-{(i % 20) + 1:02d}"
        _seed_outcome(store, "chal", date, 0.03 if i % 4 else -0.005, i % 4 != 0, True, i)
        _seed_outcome(store, "builtin_breakout", date, 0.01 if i % 2 else -0.01, i % 2 == 0, False, i)
    manager = PromotionManager(store, settings)
    _open_window(store, manager, "chal")

    decisions = manager.evaluate_windows()

    assert decisions[0]["verdict"] == "PROMOTED"
    status = {row["name"]: row["status"] for row in store.strategy_versions()}
    assert status["chal"] == "ACTIVE"
    assert status["builtin_breakout"] == "SHADOW"


def test_challenger_worse_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.upsert_strategy_version({"name": "builtin_breakout", "version": "1", "status": "ACTIVE"})
    for i in range(22):
        date = f"2026-05-{(i % 20) + 1:02d}"
        _seed_outcome(store, "chal", date, -0.02 if i % 2 else 0.005, i % 2 != 0, True, i)
        _seed_outcome(store, "builtin_breakout", date, 0.02 if i % 2 else -0.005, i % 2 == 0, False, i)
    manager = PromotionManager(store, settings)
    _open_window(store, manager, "chal")

    decisions = manager.evaluate_windows()

    assert decisions[0]["verdict"] == "REJECTED_SHADOW"
    status = {row["name"]: row["status"] for row in store.strategy_versions()}
    assert status["chal"] == "RETIRED"


def test_insufficient_evidence_extends_window(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    for i in range(5):
        _seed_outcome(store, "chal", f"2026-05-0{i + 1}", 0.03, True, True, i)
    manager = PromotionManager(store, settings)
    _open_window(store, manager, "chal")

    decisions = manager.evaluate_windows()
    assert decisions[0]["verdict"] == "EXTEND"
    assert store.promotion_windows(status="OPEN")  # sigue abierta


def test_start_shadow_creates_window_and_marks_shadow(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    store.upsert_strategy_version({"name": "chal", "version": "1", "status": "ACTIVE"})
    PromotionManager(store, settings).start_shadow("chal", "1")
    assert store.promotion_windows(status="OPEN")
    status = {row["name"]: row["status"] for row in store.strategy_versions()}
    assert status["chal"] == "SHADOW"
