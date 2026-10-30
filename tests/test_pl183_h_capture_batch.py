"""P-L183: capturas h_capture en una sola transaccion por ciclo.

Solo persistencia: misma semantica append-only (idempotente/conflicto), mismo
fail-open y mismos payloads. Reduce transacciones y fsync por ciclo.
"""

from __future__ import annotations


def _store(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _item(index: int, *, payload: dict | None = None) -> dict:
    body = {"schema_version": "test.v1", "content_hash": f"h{index}", "n": index}
    if payload is not None:
        body = payload
    return {
        "event_id": f"evt-{index}",
        "event_type": "h_capture_prediction",
        "cycle_id": "cyc-1",
        "payload": body,
        "idempotent_on_content_hash": True,
    }


def _count(store, event_type: str = "h_capture_prediction") -> int:
    with store.connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM agent_events WHERE event_type = ?", (event_type,)
        ).fetchone()[0]


def test_batch_uses_one_connection_and_writes_every_event(tmp_path):
    from agente_bolsa.storage import Store

    store = _store(tmp_path)
    calls = {"n": 0}
    original = Store.connect

    def counting(self, **kwargs):
        calls["n"] += 1
        return original(self, **kwargs)

    Store.connect = counting
    try:
        results = store.record_append_only_events(
            [_item(index) for index in range(5)], lock_timeout_seconds=0.0
        )
    finally:
        Store.connect = original

    assert [result["status"] for result in results] == ["inserted"] * 5
    assert calls["n"] == 1
    assert _count(store) == 5


def test_batch_is_idempotent_on_rerun(tmp_path):
    store = _store(tmp_path)
    items = [_item(index) for index in range(3)]
    store.record_append_only_events(items, lock_timeout_seconds=0.0)
    second = store.record_append_only_events(items, lock_timeout_seconds=0.0)
    assert [result["status"] for result in second] == ["idempotent"] * 3
    assert _count(store) == 3


def test_batch_conflict_preserves_original_and_records_conflict(tmp_path):
    store = _store(tmp_path)
    store.record_append_only_events([_item(1)], lock_timeout_seconds=0.0)
    changed = _item(1, payload={"schema_version": "test.v1", "content_hash": "otro", "n": 99})
    results = store.record_append_only_events([changed], lock_timeout_seconds=0.0)
    assert results[0]["status"] == "conflict"
    assert _count(store) == 1
    assert _count(store, "h_capture_prediction_conflict") == 1
    with store.connect() as conn:
        original = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_id = 'evt-1'"
        ).fetchone()[0]
    assert '"h1"' in original


def test_one_bad_item_does_not_abort_the_batch(tmp_path):
    store = _store(tmp_path)
    bad = {"event_id": "evt-2", "event_type": "h_capture_prediction", "cycle_id": None,
           "payload": {"n": 2}, "argumento_invalido": True}
    items = [_item(1), bad, _item(3)]
    results = store.record_append_only_events(items, lock_timeout_seconds=0.0)
    assert results[0]["status"] == "inserted"
    assert results[1]["status"] == "failed"
    assert results[2]["status"] == "inserted"
    assert _count(store) == 2


def test_producer_persists_all_captures_in_one_call(tmp_path, monkeypatch):
    from agente_bolsa.tools import signal_learning

    calls = []

    class FakeStore:
        def record_append_only_events(self, items, *, lock_timeout_seconds=None):
            calls.append((list(items), lock_timeout_seconds))
            return [{"status": "inserted"} for _ in items]

    monkeypatch.setattr(
        signal_learning,
        "build_prediction_capture",
        lambda **kwargs: {"event_id": f"e-{kwargs['lineage']['signal_id']}", "event_type": "h_capture_prediction"},
    )
    monkeypatch.setattr(
        signal_learning,
        "h_capture_batch_item",
        lambda payload: {
            "event_id": payload["event_id"],
            "event_type": payload["event_type"],
            "cycle_id": None,
            "payload": payload,
            "idempotent_on_content_hash": True,
        },
    )
    report = {"as_of": "2026-10-30T12:00:00+00:00"}
    requests = [
        (
            {"signal_id": f"sig-{index}", "features": {}},
            {"candidate_id": f"cand-{index}"},
            {"cycle_id": "cyc-1", "agent_run_id": "run-1", "canonical_agent_id": "agent"},
        )
        for index in range(4)
    ]

    signal_learning._persist_signal_prediction_captures(FakeStore(), report, requests)

    assert len(calls) == 1
    assert len(calls[0][0]) == 4
    assert calls[0][1] == 0.0


def test_out_of_scope_marker():
    """El lote no toca trading: no hay imports de riesgo/ejecucion nuevos."""

    import agente_bolsa.tools.signal_learning as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "record_append_only_events" in source
    assert "broker" not in source.split("def _persist_signal_prediction_captures")[0].lower()
