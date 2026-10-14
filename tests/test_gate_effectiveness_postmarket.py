from datetime import datetime, timezone

from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.gate_effectiveness_reporting import (
    build_gate_effectiveness_postmarket_report,
    publish_gate_effectiveness_postmarket,
)
from agente_bolsa.tools.gate_evaluation import collect_gate_path


def _store(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _snapshot():
    candidate = TradeRecommendation(symbol="AAA", action="buy", confidence=.8, reason="test", entry_price=100,
        decision_lineage={"signal_id": "sig-1", "candidate_id": "cand-1", "cycle_id": "cycle-1"},
        decision_context_snapshot={"snapshot_id": "ctx", "captured_at": "2026-07-10T10:00:00+00:00", "market_state_ref": {"content_hash": "h"}})
    rows = {"deterministic_review": [{"candidate_id": "cand-1", "signal_id": "sig-1", "cycle_id": "cycle-1", "action": "buy", "approved": True}]}
    return collect_gate_path(cycle_id="cycle-1", candidates=[candidate], stage_rows=rows, captured_at="2026-07-10T10:01:00+00:00")["cand-1"]


def test_postmarket_gate_report_collects_only_prospective_snapshots(tmp_path):
    store = _store(tmp_path)
    store.save_signal_outcome(signal_id="sig-1", source_run_id="run", source="test", symbol="AAA", signal_date="2026-07-10", decision="candidate", features={}, gate={"legacy": True}, outcome={})
    store.attach_gate_evaluation_snapshot("sig-1", _snapshot())
    report = build_gate_effectiveness_postmarket_report(store, session_date="2026-07-10", now=datetime(2026, 7, 10, 21, tzinfo=timezone.utc))
    assert report["status"] == "immature"
    assert report["window"]["snapshots_processed"] == 1
    assert report["window"]["legacy_gate_json_excluded"] is True
    assert report["freshness"]["market_session"] == "2026-07-10"


def test_postmarket_gate_report_is_stable_and_persists_runtime(tmp_path):
    store = _store(tmp_path)
    first = publish_gate_effectiveness_postmarket(store, tmp_path / "reports", run_id="a", session_date="2026-07-10")
    second = publish_gate_effectiveness_postmarket(store, tmp_path / "reports", run_id="b", session_date="2026-07-10")
    assert first["content_hash"] == second["content_hash"]
    assert (tmp_path / "reports" / "latest_gate_effectiveness_quality.json").exists()
    assert store.get_runtime_value("gate_effectiveness_quality_runtime")["status"] == "collecting"


def test_postmarket_gate_report_excludes_conflicted_snapshots_from_quality(tmp_path):
    store = _store(tmp_path)
    store.save_signal_outcome(signal_id="sig-1", source_run_id="run", source="test", symbol="AAA", signal_date="2026-07-10", decision="candidate", features={}, gate={}, outcome={})
    snapshot = _snapshot()
    snapshot["authority_conflict"] = True
    store.attach_gate_evaluation_snapshot("sig-1", snapshot)
    report = build_gate_effectiveness_postmarket_report(store, session_date="2026-07-10")
    assert report["coverage"]["snapshots"] == 1
    assert report["coverage"]["snapshots_eligible"] == 0
    assert report["coverage"]["conflicts"] == 1
    assert report["window"]["conflicts_excluded"] == 1
    assert report["gates"]["candidates_reaching_gate"] == 0
