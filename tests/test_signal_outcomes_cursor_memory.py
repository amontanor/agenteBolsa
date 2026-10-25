"""Wide signal reads preserve the contract without retaining raw SQLite rows."""

import json

import pytest

from agente_bolsa.storage import Store


@pytest.mark.parametrize("invalid", [False, True])
def test_wide_cursor_is_streamed_and_closed(tmp_path, monkeypatch, invalid):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    features = {"unknown": {"nested": [1, None]}, "padding": "x" * 8192}
    raw = dict(signal_id="id", source_run_id="run", source="daily_scan", symbol="TEST",
               signal_date="2026-10-23", decision="candidate", features_json=json.dumps(features),
               gate_json="{}", outcome_json="{}", created_at="stamp", updated_at="stamp")
    if invalid:
        raw["features_json"] = "{broken"

    class Cursor:
        closed = False
        def __iter__(self):
            yield raw
        def fetchall(self):
            pytest.fail("Wide raw rows must not be materialized")
        def close(self):
            self.closed = True

    cursor = Cursor()
    class Connection:
        def execute(self, query, params):
            assert "ORDER BY signal_date DESC, created_at DESC LIMIT ?" in query
            assert params[-1] == 7
            return cursor

    monkeypatch.setattr(store, "read_connection", lambda: Connection())
    if invalid:
        with pytest.raises(json.JSONDecodeError):
            store.signal_outcomes(limit=7)
    else:
        result = store.signal_outcomes(limit=7)
        assert result[0]["features"] == features
        assert result[0]["signal_id"] == "id"
        assert raw["features_json"] == json.dumps(features)
    assert cursor.closed


@pytest.mark.parametrize("options", [
    {}, {"limit": 2}, {"since_date": "2026-10-22"},
    {"include_lab_book": True, "include_learning_experiment": True},
    {"sources": ["daily_scan"]},
])
def test_real_store_full_payload_parity_with_iterator(tmp_path, options):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcomes_bulk([
        {"signal_id": f"s{i}", "source_run_id": f"run{i}",
         "source": source, "symbol": "TEST", "signal_date": f"2026-10-{20+i:02d}",
         "decision": "candidate", "features": {"unknown": [None, {"x": i}], "padding": "x" * 8192},
         "gate": {"custom": i}, "outcome": {"unknown": i}}
        for i, source in enumerate(["daily_scan", "lab_book", "learning_experiment", "daily_scan"])
    ])
    before = list(store.iter_signal_outcomes(**options))
    actual = store.signal_outcomes(**options)
    assert actual == before
    assert list(store.iter_signal_outcomes(**options)) == before
    for row in actual:
        assert len(row["features"]["padding"]) == 8192
        assert "unknown" in row["features"]
