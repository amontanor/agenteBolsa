import pytest

from agente_bolsa.tools.counterfactual_analysis import _iter_signal_rows_spooled, _signal_rows
from agente_bolsa.tools.learning_spool import LearningSpool


def test_spool_preserves_order_and_unknown_nested_fields(tmp_path):
    records = [
        {"signal_id": "b", "features": {"unknown": {"items": [None, 0, False, "á"]}}},
        {"signal_id": "a", "features": {"payload": "x" * 8192}},
    ]
    with LearningSpool(directory=tmp_path) as spool:
        spool_path = spool.path
        for record in records:
            spool.append(record)
        assert list(spool) == records
        assert list(spool) == records
    assert not spool_path.exists()


def test_spool_cleans_up_when_consumer_raises(tmp_path):
    with pytest.raises(ValueError, match="failure"):
        with LearningSpool(directory=tmp_path) as spool:
            spool_path = spool.path
            spool.append({"features": {"unexpected": 1}})
            raise ValueError("failure")
    assert not spool_path.exists()
    with pytest.raises(RuntimeError, match="closed"):
        spool.append({})


def test_sources_and_rows_keep_first_seen_order(tmp_path):
    records = [
        {"signal_id": "1", "source_run_id": "b"},
        {"signal_id": "2", "source_run_id": "a"},
        {"signal_id": "3", "source_run_id": "b"},
        {"signal_id": "4", "source_run_id": None},
    ]
    with LearningSpool(directory=tmp_path) as spool:
        for record in records:
            spool.append(record)
        assert list(spool.source_runs()) == ["b", "a", ""]
        assert list(spool.rows_for_source("b")) == [records[0], records[2]]


def test_replace_preserves_ordinal_and_unknown_fields(tmp_path):
    with LearningSpool(directory=tmp_path) as spool:
        ordinal = spool.append({"source_run_id": "x", "features": {"unknown": [1, 2]}})
        spool.append({"source_run_id": "x", "features": {"unknown": [3]}})
        spool.replace(ordinal, {"source_run_id": "x", "features": {"unknown": [1, 2], "score_rank": 1}})
        assert list(spool.indexed_rows_for_source("x")) == [
            (ordinal, {"source_run_id": "x", "features": {"unknown": [1, 2], "score_rank": 1}}),
            (ordinal + 1, {"source_run_id": "x", "features": {"unknown": [3]}}),
        ]
        with pytest.raises(KeyError):
            spool.replace(999, {})


def test_spooled_signal_order_matches_legacy_and_closes_on_interrupt():
    records = [
        {"signal_id": "z", "signal_date": "2026-10-15", "created_at": "2", "features": {"unknown": "wide"}},
        {"signal_id": "b", "signal_date": "2026-10-10", "created_at": "1", "features": {"unknown": [1, 2]}},
        {"signal_id": "a", "signal_date": "2026-10-10", "created_at": "1", "features": {"unknown": {"x": 2}}},
        {"signal_id": "older", "signal_date": "2026-10-01", "created_at": "0", "features": {}},
    ]
    state = {"closed": False}

    class Store:
        def signal_outcomes(self, **kwargs):
            return records[:kwargs["limit"]]

        def iter_signal_outcomes(self, **kwargs):
            try:
                yield from records[:kwargs["limit"]]
            finally:
                state["closed"] = True

    kwargs = {"since_date": "2026-10-01", "end_date": "2026-10-12", "limit": 3}
    assert list(_iter_signal_rows_spooled(Store(), **kwargs)) == _signal_rows(Store(), **kwargs)
    assert state["closed"]
    stream = _iter_signal_rows_spooled(Store(), **kwargs)
    next(stream)
    stream.close()
    assert state["closed"]
