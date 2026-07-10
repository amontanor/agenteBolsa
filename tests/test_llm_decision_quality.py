from __future__ import annotations

from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.llm_decision_quality import (
    build_llm_decision_quality,
    classify_fallback_error,
    classify_trade_recommendation,
    write_llm_decision_quality_report,
)


def _store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _save(store, recommendation_id: str, payload: dict):
    store.save_trade_recommendation(
        recommendation_id=recommendation_id,
        cycle_id="cycle_quality",
        symbol="AAPL",
        action="hold",
        confidence=0.5,
        payload=payload,
    )


def test_classify_fallback_error_is_specific_only_when_evidence_exists():
    assert classify_fallback_error("gateway timeout after 30s") == "timeout"
    assert classify_fallback_error("connection reset by provider") == "network_or_provider"
    assert classify_fallback_error("invalid JSON schema") == "invalid_response_or_schema"
    assert classify_fallback_error("daily budget circuit breaker") == "budget_or_circuit_breaker"
    assert classify_fallback_error(None) == "unknown"


def test_trade_recommendation_preserves_unknown_legacy_origin():
    assert classify_trade_recommendation({"source": "deterministic_fallback"}) == {
        "decision_role": "trade_decision",
        "decision_source": "deterministic_fallback",
        "decision_origin": None,
        "model": None,
        "classification": "deterministic_unclassified",
        "fallback_reason": "unknown",
        "is_fallback": True,
        "is_llm_failure": False,
    }


def test_quality_separates_llm_failure_from_capacity_fill_after_llm_ok(tmp_path):
    store = _store(tmp_path)
    _save(store, "real", {"source": "llm", "model_info": {"llm_model": "primary"}})
    _save(
        store,
        "failure",
        {
            "source": "deterministic_fallback",
            "decision_origin": "deterministic_fallback_llm_failed",
            "model_info": {"llm_model": "primary", "decision_fallback_error": "request timeout"},
        },
    )
    _save(
        store,
        "capacity",
        {
            "source": "deterministic_capacity_fill",
            "decision_origin": "deterministic_capacity_fill",
            "capacity_fill_reason_code": "capacity_fill_tras_llm_ok",
        },
    )
    _save(store, "legacy", {"source": "deterministic_fallback"})

    report = build_llm_decision_quality(store, now=datetime.now(timezone.utc))

    assert report["summary"] == {
        "recommendations": 4,
        "known_decisions": 4,
        "unknown_decisions": 0,
        "real_decisions": 1,
        "fallback_decisions": 3,
        "llm_failure_fallback_decisions": 1,
        "deterministic_after_llm_ok_decisions": 1,
        "fallback_ratio": 0.75,
        "real_ratio": 0.25,
        "llm_failure_fallback_ratio": 0.25,
        "status": "available",
    }
    assert report["by_fallback_reason"] == {
        "capacity_fill_after_llm_ok": 1,
        "timeout": 1,
        "unknown": 1,
    }


def test_quality_report_is_persisted_with_latest_alias(tmp_path):
    store = _store(tmp_path)
    _save(store, "real", {"source": "llm"})

    report = write_llm_decision_quality_report(store, tmp_path / "reports", "quality_test")

    assert report["schema_version"] == 1
    assert (tmp_path / "reports" / "latest_llm_decision_quality.json").exists()
