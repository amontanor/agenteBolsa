"""Tests del presupuesto economico del laboratorio (T5.9)."""

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.llm_router import LLMBudgetExhausted, chat_for_role
from agente_bolsa.llm_usage import estimate_cost, price_per_mtoken, today_llm_spend
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, LLM_PRIMARY_PREFLIGHT_ENABLED=False, **overrides)
    Store(settings.database_path, settings.agent_logs_dir).ensure_schema()
    return settings


def _record(store, model, total_tokens, role):
    from agente_bolsa.models import new_id

    store.record_llm_usage(
        usage_id=new_id("u"),
        source="test",
        model=model,
        request_count=1,
        prompt_tokens=total_tokens // 2,
        completion_tokens=total_tokens // 2,
        total_tokens=total_tokens,
        payload={},
        role=role,
    )


def test_price_and_cost():
    settings = Settings()
    assert price_per_mtoken(settings, "gemini-3.5-flash") == 0.30
    assert price_per_mtoken(settings, "qwen3.6-27b") == 0.0
    assert estimate_cost(settings, "gemini-3.5-flash", 1_000_000) == 0.30


def test_today_spend_sums_costs(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    _record(store, "gemini-3.5-flash", 2_000_000, "deep")  # 0.60
    _record(store, "mimo-deep", 2_000_000, "deep")  # 1.00
    spend = today_llm_spend(settings)
    assert spend == pytest.approx(1.60, abs=1e-6)
    assert today_llm_spend(settings, role="deep") == pytest.approx(1.60, abs=1e-6)


def test_total_budget_exhausted_raises(tmp_path):
    settings = _settings(tmp_path, LLM_DAILY_BUDGET_USD=1.0)
    store = Store(settings.database_path, settings.agent_logs_dir)
    _record(store, "gemini-3.5-flash", 5_000_000, "fast")  # 1.50 > 1.0
    with pytest.raises(LLMBudgetExhausted):
        chat_for_role("fast", settings=settings, messages=[{"role": "user", "content": "x"}])


def test_no_budget_means_no_limit(tmp_path):
    settings = _settings(tmp_path, LLM_DAILY_BUDGET_USD=0.0, LLM_ROLE_DEEP_DAILY_BUDGET_USD=0.0)
    store = Store(settings.database_path, settings.agent_logs_dir)
    _record(store, "gemini-3.5-flash", 50_000_000, "deep")
    # Sin presupuesto no se lanza LLMBudgetExhausted (fallara luego por red, no por budget).
    try:
        chat_for_role("deep", settings=settings, messages=[{"role": "user", "content": "x"}])
    except LLMBudgetExhausted as exc:
        raise AssertionError("no deberia agotar presupuesto con limite 0") from exc
    except Exception:
        pass  # fallo de red/endpoint es aceptable en el test
