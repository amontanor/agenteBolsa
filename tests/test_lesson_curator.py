import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.lesson_curator import curate_lessons
from agente_bolsa.storage import Store


def _setup(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _seed(store, setup, ret, winner, idx):
    store.save_signal_outcome(
        signal_id=f"{setup}_{idx}",
        source_run_id="run",
        source="test",
        symbol="AAA",
        signal_date="2026-06-10",
        decision="buy",
        features={"setup": setup},
        gate={},
        outcome={"verdict": "winner_fast" if winner else "loser", "return_pct": ret},
    )


def test_curate_lessons_runs_full_cycle(tmp_path, monkeypatch):
    settings, store = _setup(tmp_path)
    for i in range(8):
        _seed(store, "breakout", 0.03, True, i)
    for i in range(2):
        _seed(store, "breakout", -0.01, False, 100 + i)
    monkeypatch.setattr(
        "agente_bolsa.continuous_improvement.lesson_distiller._default_llm",
        lambda settings, messages: json.dumps(
            {"lessons": [{"scope": "setup", "statement": "breakout funciona", "setup": "breakout"}]}
        ),
    )

    result = curate_lessons(store, settings, since_date="2026-06-01")

    assert "summary" in result
    assert result["distilled"]["distilled"] == 1
    assert isinstance(store.distilled_lessons(limit=20), list)
