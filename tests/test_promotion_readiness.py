from datetime import datetime, timedelta, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement import promotion_readiness
from agente_bolsa.storage import Store


def _row(idx: int, ret5: float, ret10: float, *, regime: str = "neutral"):
    return {
        "signal_date": f"2026-05-{(idx % 20) + 1:02d}",
        "regime": regime,
        "outcome": {
            "return_1d": ret5,
            "return_3d": ret5,
            "return_5d": ret5,
            "return_10d": ret10,
        },
    }


def test_candidate_decision_holds_small_positive_sample():
    rows = [_row(idx, 0.02, 0.04) for idx in range(5)]

    decision = promotion_readiness._candidate_decision(kind="setup", key="orderly_breakout", rows=rows, benchmark={})

    assert decision["verdict"] == "HOLD"
    assert decision["promotion_checks"]["matured_sample"] is False


def test_candidate_decision_retires_negative_confirmed_pattern():
    rows = [_row(idx, -0.05, -0.02) for idx in range(8)]
    benchmark = {(row["signal_date"], horizon): 0.0 for row in rows for horizon in (1, 3, 5, 10)}

    decision = promotion_readiness._candidate_decision(kind="setup", key="confirmed_pattern", rows=rows, benchmark=benchmark)

    assert decision["verdict"] == "RETIRE_CANDIDATE"
    assert decision["retire_checks"]["negative_alpha"] is True


def test_validation_backlog_marks_stale_pending(tmp_path):
    settings = Settings(DATA_DIR=tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store.save_continuous_improvement_validation(
        {
            "validation_id": "v-old",
            "proposal_id": "p",
            "cycle_id": "c",
            "status": "PENDING",
            "validation_type": "deterministic",
            "payload": {},
            "created_at": old,
        }
    )

    backlog = promotion_readiness._validation_backlog(store)

    assert backlog["pending"] == 1
    assert backlog["recommended_closures"] == 1
    assert backlog["stale_pending"][0]["recommended_status"] == "EXPIRED_PENDING"
