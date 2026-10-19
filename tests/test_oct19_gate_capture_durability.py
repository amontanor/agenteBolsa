"""Two decisions sharing a signal survive in the existing durable event."""
from types import SimpleNamespace

from agente_bolsa.cycle_runner import _persist_gate_capture_observation
from agente_bolsa.models import AgentEvent, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.gate_evaluation import collect_gate_path


def test_buy_exit_paths_survive_legacy_attachment_conflict(tmp_path):
    store = Store(tmp_path/'state.sqlite3', tmp_path/'logs')
    store.ensure_schema()
    store.save_signal_outcome(signal_id='shared', source_run_id='cycle', source='local',
                              symbol='AAA', signal_date='2026-10-19', decision='candidate',
                              features={}, gate={}, outcome={})
    candidates = [TradeRecommendation(
        symbol='AAA', action=action, confidence=.8, reason='local',
        decision_lineage={'cycle_id':'cycle','signal_id':'shared',
                          'candidate_id':f'candidate-{action}', 'signal_capture_id':f'capture-{action}'},
    ) for action in ['buy', 'exit']]
    rows = collect_gate_path(cycle_id='cycle', candidates=candidates, stage_rows={},
                             captured_at='2026-10-19T16:00:00+00:00')
    def emit(agent, event_type, cycle_id, message, payload):
        store.record_agent_event(AgentEvent(agent=agent, event_type=event_type,
                                            cycle_id=cycle_id, payload=payload))
    reporter = SimpleNamespace(emit=emit)
    _persist_gate_capture_observation(store, reporter, 'cycle', rows)
    original = store.signal_outcome_by_id('shared')
    event = store.agent_events(event_type_prefix='gate_evaluation_snapshots_captured', limit=10)[0]
    payload = event['payload']
    assert payload['attachment_counts']['attached'] == 1
    assert payload['attachment_counts']['conflict'] == 1
    assert {row['action'] for row in payload['decision_paths']} == {'buy', 'exit'}
    assert {row['signal_capture_id'] for row in payload['decision_paths']} == {'capture-buy', 'capture-exit'}
    assert payload['multi_decision_learning_status'] == 'unavailable'
    assert payload['learning_authority'] == 'legacy_single_snapshot_only'
    _persist_gate_capture_observation(store, reporter, 'cycle', rows)
    assert store.signal_outcome_by_id('shared')['features'] == original['features']
    assert len(store.agent_events(event_type_prefix='gate_evaluation_snapshots_captured', limit=10)) == 2
