from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa.web_app import _dashboard_llm_pills


class _StoreStub:
    def __init__(self, rows):
        self._rows = rows

    def latest_llm_usage(self, limit=200):
        return self._rows[:limit]


def test_dashboard_llm_pills_show_trading_and_ci_models():
    settings = SimpleNamespace(
        openai_model="mimo-v2.5-pro",
        llm_local_fallback_model="qwen3.6-27b",
        improvement_llm_orchestrator_model="mimo-v2.5-pro",
    )
    store = _StoreStub(
        [
            {
                "source": "trade_decision",
                "model": "mimo-v2.5-pro",
                "request_count": 1,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "payload_json": "{}",
                "created_at": "2026-06-02T15:36:45+00:00",
            }
        ]
    )
    ci_result = {
        "status": "ok",
        "model": "mimo-v2.5-pro",
        "fallback_used": False,
        "created_at": "2026-06-02T15:47:12+00:00",
    }

    pills = _dashboard_llm_pills(settings, store, ci_result)

    assert len(pills) == 2
    assert "Trading LLM mimo-v2.5-pro" in pills[0]["text"]
    assert pills[0]["tone"] == "good"
    assert "mimo" in pills[0]["text"]
    assert "CI LLM mimo-v2.5-pro" in pills[1]["text"]
    assert pills[1]["tone"] == "good"
