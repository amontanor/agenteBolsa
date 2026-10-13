import json
from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.llm_client import ImprovementLLMClient


@pytest.mark.parametrize('kind', ['urllib', 'sdk', 'status', 'response'])
def test_402_stops_primary_retry_and_uses_configured_fallback(tmp_path, monkeypatch, kind):
    settings = Settings(
        _env_file=None, DATA_DIR=tmp_path, IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_PROVIDER='mimo', IMPROVEMENT_LLM_API_KEY='tp-test',
        IMPROVEMENT_LLM_BASE_URL='https://token-plan-ams.xiaomimimo.com/v1',
        IMPROVEMENT_LLM_MODEL='mimo-v2.5', IMPROVEMENT_LLM_RETRIES=3,
        IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED=True,
        LLM_LOCAL_FALLBACK_API_BASE='http://127.0.0.1:8080/v1',
        LLM_LOCAL_FALLBACK_API_KEY='local-test', LLM_LOCAL_FALLBACK_MODEL='test',
    )
    client = ImprovementLLMClient(settings)
    calls = []
    failure = OSError('opaque provider failure')
    if kind == 'urllib':
        failure = OSError('HTTP 402: Insufficient account funds')
    elif kind == 'sdk':
        failure = OSError('Error code: 402 - Insufficient account funds')
    elif kind == 'status':
        failure.status_code = 402
    else:
        failure.response = SimpleNamespace(status_code=402)

    def fail_primary(*args):
        calls.append('primary')
        raise failure

    def succeed_fallback(*args):
        calls.append('fallback')
        return json.dumps({
            'diagnosis': {'summary': 'ok', 'confidence': 'LOW', 'data_quality': 'PARTIAL'},
            'detected_issues': [], 'proposals': [], 'recommended_next_actions': [],
        })

    def forbid_sleep(*args):
        pytest.fail('402 must not sleep before fallback')

    monkeypatch.setattr(client, '_post_json', fail_primary)
    monkeypatch.setattr(client, '_sdk_chat_completion_content', succeed_fallback)
    monkeypatch.setattr('agente_bolsa.continuous_improvement.llm_client.time.sleep', forbid_sleep)
    result = client.generate_json([{'role': 'user', 'content': 'test'}], {})
    assert result.ok
    assert calls == ['primary', 'fallback']
    assert result.request_preview['primary_error_status'] == 402
    assert result.request_preview['primary_error_class'] == 'account_funds_exhausted'


@pytest.mark.parametrize('fallback_enabled', [False, True])
def test_402_terminal_classification_without_recovery(tmp_path, monkeypatch, fallback_enabled):
    settings = Settings(
        _env_file=None, DATA_DIR=tmp_path, IMPROVEMENT_LLM_ENABLED=True,
        IMPROVEMENT_LLM_PROVIDER='mimo', IMPROVEMENT_LLM_API_KEY='tp-test',
        IMPROVEMENT_LLM_BASE_URL='https://token-plan-ams.xiaomimimo.com/v1',
        IMPROVEMENT_LLM_MODEL='mimo-v2.5', IMPROVEMENT_LLM_RETRIES=3,
        IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED=fallback_enabled,
        LLM_LOCAL_FALLBACK_API_BASE='http://127.0.0.1:8080/v1',
        LLM_LOCAL_FALLBACK_API_KEY='local-test', LLM_LOCAL_FALLBACK_MODEL='test',
    )
    client = ImprovementLLMClient(settings)
    calls = []
    events = []

    def fail(*args):
        calls.append('call')
        raise OSError('HTTP 402: Insufficient account funds')

    def forbid_sleep(*args):
        pytest.fail('402 must not sleep')

    monkeypatch.setattr(client, '_post_json', fail)
    monkeypatch.setattr(client, '_sdk_chat_completion_content', fail)
    monkeypatch.setattr('agente_bolsa.continuous_improvement.llm_client.time.sleep', forbid_sleep)
    monkeypatch.setattr(
        'agente_bolsa.continuous_improvement.llm_client.log_system_event',
        lambda directory, name, payload: events.append((name, payload)),
    )
    result = client.generate_json([{'role': 'user', 'content': 'test'}], {})
    assert not result.ok
    assert len(calls) == (2 if fallback_enabled else 1)
    assert events[-1][1]['error_status'] == 402
    assert events[-1][1]['error_class'] == 'account_funds_exhausted'
