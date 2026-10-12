from datetime import datetime, timezone

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.capital_allocation_policy import load_capital_allocation_policy
from agente_bolsa.tools.capital_allocation_shadow import shadow_content_hash
from agente_bolsa.tools.capital_allocation_status import allocation_status


def test_absent_database_is_not_created(tmp_path):
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path))
    result = allocation_status(settings)
    assert not settings.database_path.exists()
    assert not result['active']
    assert result['five_complete_sessions'] == 'unavailable'
    assert 'observation_database_absent' in result['reasons']


@pytest.mark.parametrize('limit', [0, -1, True, 5001, 1.5])
def test_status_requires_bounded_limit(tmp_path, limit):
    with pytest.raises(ValueError, match='bounded_limit_required'):
        allocation_status(Settings(_env_file=None, DATA_DIR=str(tmp_path)), limit=limit)


def test_malformed_denominators_do_not_claim_coverage(tmp_path):
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path))
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    policy = load_capital_allocation_policy(tmp_path, settings)
    payload = {'policy_hash': policy['policy_hash'], 'captured_at': '2026-10-12T12:00:00Z',
               'denominators': {'verified_buy_identities': 10, 'buy_recommendations': 1}}
    payload['content_hash'] = shadow_content_hash(payload)
    store.record_append_only_event(event_id='test', event_type='capital_allocation_shadow',
                                  cycle_id='cycle', payload=payload)
    result = allocation_status(settings, now=datetime(2026, 10, 12, 13, tzinfo=timezone.utc))
    assert result['invalid_events'] == 1
    assert result['canonical_events'] == 0
    assert result['identity_coverage'] is None
    assert result['five_complete_sessions'] == 'unavailable'
