"""P-L122: la sincronizacion nunca activa y preserva lo humano (guardas)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _store(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store

    settings = Settings(_env_file=None, DATA_DIR=tmp_path, ALLOW_LIVE_TRADING=False, TRADING_MODE="paper")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _old(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_sync_never_activates_and_preserves_human_held(tmp_path):
    from agente_bolsa.continuous_improvement.promotion_loop import sync_promotion_policies

    store = _store(tmp_path)
    store.upsert_learning_policy_candidate({
        "policy_id": "auto_setup_confirmed_pattern",
        "name": "Auto shadow setup:confirmed_pattern",
        "policy_type": "setup_shadow",
        "status": "guarded_active",
        "scope": "global",
        "auto_activatable": False,
        "evidence": {"verdict": "PROMOTE_CANDIDATE"},
        "metrics": {},
        "notes": "promovida por humano",
        "promoted_at": _old(5),
        "last_evaluated_at": _old(5),
        "created_at": _old(40),
        "updated_at": _old(5),
    })
    evaluations = [
        {"kind": "setup", "key": "confirmed_pattern", "verdict": "PROMOTE_CANDIDATE",
         "metrics": {"matured_10d": 30}, "sessions": 15},
    ]
    result = sync_promotion_policies(store, evaluations=evaluations)
    assert result["shadowed"] == []
    assert result["kept"] == ["auto_setup_confirmed_pattern"]
    assert result["human_review"] == ["auto_setup_confirmed_pattern"]
    policies = {p["policy_id"]: p for p in store.learning_policy_candidates()}
    assert policies["auto_setup_confirmed_pattern"]["status"] == "guarded_active"
    assert policies["auto_setup_confirmed_pattern"]["auto_activatable"] is False
