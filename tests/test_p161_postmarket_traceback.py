"""P-L161: the post-market failure event must carry the traceback.

The production failures of 26/27-oct-2026 reached the durable event as
``TypeError("<' not supported between instances of 'NoneType' and 'int'")``
without a frame, so the failing producer could not be attributed. These tests
freeze that contract: the frame travels in the same event, bounded, and the
helper never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        DATABASE_PATH=tmp_path / "data" / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "data" / "logs" / "agents",
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _failed_payloads(store: Store) -> list[dict]:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_type = 'post_market_review_failed'"
            " ORDER BY created_at"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def test_failed_postmarket_event_carries_the_frame(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    def _boom(*_args, **_kwargs):
        raise TypeError("'<' not supported between instances of 'NoneType' and 'int'")

    monkeypatch.setattr(scheduler, "build_post_market_review", _boom)

    assert (
        scheduler.post_market_review_job(
            settings, store, use_llm=False, verbose=False, force=True, trigger="scheduled"
        )
        is None
    )

    payloads = _failed_payloads(store)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["error"] == "TypeError(\"'<' not supported between instances of 'NoneType' and 'int'\")"
    frame = payload["traceback"]
    assert "_boom" in frame
    assert "TypeError" in frame
    assert frame.index("_boom") < frame.index("TypeError")


def test_failure_traceback_is_bounded_and_never_raises() -> None:
    assert scheduler._failure_traceback() == ""

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        short = scheduler._failure_traceback()

    assert "RuntimeError: boom" in short

    try:
        raise RuntimeError("x" * 20000)
    except RuntimeError:
        bounded = scheduler._failure_traceback(max_chars=500)

    assert len(bounded) == 500
    assert bounded.strip() == "x" * 499
