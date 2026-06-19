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
        llm_model_selector="opencode-go",
        opencode_model="kimi-k2.6",
        mimo_model="mimo-v2.5-pro",
        openai_model="mimo-v2.5-pro",
        llm_local_fallback_model="qwen3.6-27b",
        improvement_llm_provider="opencode-go",
        improvement_llm_model="kimi-k2.6",
        improvement_llm_orchestrator_provider="opencode-go",
        improvement_llm_orchestrator_model="kimi-k2.6",
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
        "status": "failed",
        "model": "mimo-v2.5-pro",
        "fallback_used": False,
        "created_at": "2026-06-02T15:47:12+00:00",
    }

    pills = _dashboard_llm_pills(settings, store, ci_result)

    assert len(pills) == 3
    assert "Trading config kimi-k2.6" in pills[0]["text"]
    assert "ultimo uso mimo-v2.5-pro" in pills[0]["text"]
    assert pills[0]["tone"] == "neutral"
    assert "Agentes config kimi-k2.6" in pills[1]["text"]
    assert pills[1]["tone"] == "good"
    assert "Orquestador config kimi-k2.6" in pills[2]["text"]
    assert "ultimo fallo historico mimo-v2.5-pro" in pills[2]["text"]
    assert pills[2]["tone"] == "neutral"
