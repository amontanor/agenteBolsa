"""Tests de prompts versionados y replay (T2.1)."""

from agente_bolsa import prompt_store
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.prompt_replay import evaluate_prompt_promotion, replay_decisions


def _settings(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    prompt_store._CACHE.clear()
    return settings


def test_get_prompt_falls_back_to_default(tmp_path):
    settings = _settings(tmp_path)
    assert prompt_store.get_prompt(settings, "trade_decision_system", "DEFAULT") == "DEFAULT"


def test_propose_and_promote_prompt(tmp_path):
    settings = _settings(tmp_path)
    prompt_store.import_prompts(settings, {"k": "v1 active"})
    assert prompt_store.get_prompt(settings, "k", "fallback") == "v1 active"

    version = prompt_store.propose(settings, "k", "v2 candidate", created_by="lab")
    assert version == 2
    # Sigue sirviendo la ACTIVE (v1) hasta promover.
    assert prompt_store.get_prompt(settings, "k", "fallback") == "v1 active"

    prompt_store.promote(settings, "k", 2)
    assert prompt_store.get_prompt(settings, "k", "fallback") == "v2 candidate"


def test_import_prompts_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    first = prompt_store.import_prompts(settings, {"k": "original"})
    assert first["imported"] == ["k"]
    second = prompt_store.import_prompts(settings, {"k": "changed"})
    assert second["skipped"] == ["k"]
    assert prompt_store.get_prompt(settings, "k", "x") == "original"


def _store(settings):
    return Store(settings.database_path, settings.agent_logs_dir)


def _seed_signal(store, date, decision, ret, winner, idx):
    store.save_signal_outcome(
        signal_id=f"s{idx}",
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date=date,
        decision=decision,
        features={"x": 1},
        gate={},
        outcome={"verdict": "winner_fast" if winner else "loser", "return_pct": ret},
    )


def test_replay_decisions_with_injected_decider(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    prompt_store.propose(settings, "trade_decision_system", "candidate template")
    for i in range(1, 11):
        _seed_signal(store, f"2026-05-{i:02d}", "hold", 0.03 if i % 2 else -0.02, i % 2 == 1, i)

    def decider(template, signal):
        winner = str(signal["outcome"]["verdict"]).startswith("winner")
        return {"action": "buy" if winner else "hold", "valid": True}

    result = replay_decisions(store, settings, "trade_decision_system", 1, sessions=10, decider=decider)
    assert result["ok"] is True
    assert result["expectancy_sim"] == 0.03
    assert result["format_violations"] == 0


def test_evaluate_prompt_promotion_criterion():
    assert evaluate_prompt_promotion({"expectancy_sim": 0.03, "format_violations": 0, "decisions_evaluated": 35}, 0.01)["promote"]
    assert not evaluate_prompt_promotion({"expectancy_sim": 0.03, "format_violations": 1, "decisions_evaluated": 35}, 0.01)["promote"]
    assert not evaluate_prompt_promotion({"expectancy_sim": 0.005, "format_violations": 0, "decisions_evaluated": 35}, 0.01)["promote"]
    assert not evaluate_prompt_promotion({"expectancy_sim": 0.03, "format_violations": 0, "decisions_evaluated": 5}, 0.01)["promote"]
