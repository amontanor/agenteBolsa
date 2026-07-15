import json
from datetime import datetime, timezone
from types import SimpleNamespace

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement import digest as digest_module
from agente_bolsa.continuous_improvement.digest import build_lab_digest
from agente_bolsa.storage import Store
from agente_bolsa.tools import adaptive_tuning as adaptive_tuning_module
from agente_bolsa.tools import operational_health as operational_health_module
from agente_bolsa.tools.adaptive_tuning import (
    adaptive_config_path,
    adaptive_governance_status,
    promote_post_market_improvements,
    save_adaptive_config,
    update_adaptive_config,
)
from agente_bolsa.tools.operational_health import build_operational_health_report
from agente_bolsa.tools.post_market_review import _normalize_llm_review


def _report(items):
    return {
        "session_date": "2026-07-13",
        "summary": {},
        "proposed_improvements": items,
    }


def _freeze_health_clock(monkeypatch, fixed_now):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = fixed_now
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(operational_health_module, "datetime", FrozenDateTime)


def test_false_blocks_creation_at_the_write_boundary(tmp_path):
    path = tmp_path / "state" / "adaptive_config.json"
    result = save_adaptive_config(
        path,
        {"version": 1, "parameters": {"MAX_ORDERS_PER_CYCLE": {"proposed": 2}}},
        settings=SimpleNamespace(allow_auto_apply_improvements=False),
    )

    assert result["status"] == "blocked_by_policy"
    assert result["write_performed"] is False
    assert not path.exists()


def test_blocked_write_preserves_existing_bytes_and_mtime(tmp_path):
    path = tmp_path / "state" / "adaptive_config.json"
    path.parent.mkdir()
    original = b'{"version": 1, "parameters": {"MAX_ORDERS_PER_CYCLE": {"status": "active", "proposed": 2}}}\n'
    path.write_bytes(original)
    before = path.stat()

    result = save_adaptive_config(
        path,
        {"version": 1, "parameters": {"NEW": {"status": "active", "proposed": 1}}},
        settings=SimpleNamespace(allow_auto_apply_improvements=False),
    )

    after = path.stat()
    assert result["status"] == "blocked_by_policy"
    assert path.read_bytes() == original
    assert after.st_mtime_ns == before.st_mtime_ns


def test_only_literal_true_authorizes_write(tmp_path):
    candidates = [SimpleNamespace(), SimpleNamespace(allow_auto_apply_improvements=None)]
    candidates.extend(SimpleNamespace(allow_auto_apply_improvements=value) for value in ("true", 1, 0, False))
    for index, settings in enumerate(candidates):
        path = tmp_path / f"blocked-{index}" / "adaptive_config.json"
        result = save_adaptive_config(
            path,
            {"version": 1, "parameters": {}},
            settings=settings,
        )
        assert result["status"] == "blocked_by_policy"
        assert not path.exists()

    path = tmp_path / "authorized" / "adaptive_config.json"
    result = save_adaptive_config(
        path,
        {"version": 1, "parameters": {}},
        settings=SimpleNamespace(allow_auto_apply_improvements=True),
    )
    assert result["write_performed"] is True
    assert path.exists()


def test_alternate_promoters_are_blocked_without_consuming_or_writing(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    items = [{"id": "limit_daily_entries", "priority": "high"} for _ in range(5)]
    path = adaptive_config_path(settings)
    before = path.read_bytes() if path.exists() else None

    promoted = promote_post_market_improvements(settings, _report(items))
    tuned = update_adaptive_config(settings, Store(tmp_path / "state.sqlite3", tmp_path / "logs"))

    assert promoted["status"] == "blocked_by_policy"
    assert promoted["promoted"] == []
    assert promoted["requested_promotions"] == 5
    assert tuned["status"] == "blocked_by_policy"
    assert (path.read_bytes() if path.exists() else None) == before


def test_llm_auto_apply_is_only_a_request():
    normalized = _normalize_llm_review(
        {"minimal_improvements": [{"id": "x", "auto_apply": True, "priority": "high"}]}
    )
    item = normalized["minimal_improvements"][0]
    assert "auto_apply" not in item
    assert item["requested_auto_apply"] is True
    assert item["authorized_auto_apply"] is False


def test_llm_request_cannot_authorize_promotion(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    report = _report([{"id": "limit_daily_entries", "priority": "high"}])
    report["llm_review"] = {"minimal_improvements": [{"auto_apply": True}]}
    result = promote_post_market_improvements(settings, report)
    assert result["status"] == "blocked_by_policy"
    assert result["promoted"] == []


def test_existing_override_is_reported_without_rewrite(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    path = adaptive_config_path(settings)
    payload = {
        "version": 1,
        "parameters": {
            "MAX_ORDERS_PER_CYCLE": {
                "status": "active",
                "proposed": 2,
                "created_at": "2026-07-10T20:52:47+00:00",
            }
        },
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    before = path.read_bytes()
    status = adaptive_governance_status(settings)

    row = status["overrides"][0]
    assert status["active_override_count"] == 1
    assert status["unauthorized_or_legacy_active_override_count"] == 1
    assert row["classification"] == "stricter"
    assert row["governance"] == "preexisting_unauthorized"
    assert path.read_bytes() == before


def test_blocked_promotion_is_structured_and_postmarket_safe(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    result = promote_post_market_improvements(
        settings,
        _report([{"id": "add_entry_quality_filters", "priority": "high"}]),
    )
    assert result["status"] == "blocked_by_policy"
    assert result["reason_code"] == "adaptive_auto_apply_not_authorized"
    assert result["blocked_promotion_attempts"] == 1
    assert result["write_performed"] is False


def test_health_and_digest_publish_governance_signal(tmp_path, monkeypatch):
    fixed_now = datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)
    _freeze_health_clock(monkeypatch, fixed_now)
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
        TRADING_MODE="paper",
        ALLOW_LIVE_TRADING=False,
    )
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = settings.data_dir / "reports"

    def isolated_digest_settings(**kwargs):
        return Settings(
            _env_file=None,
            DATA_DIR=kwargs.get("DATA_DIR", settings.data_dir),
            ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
            TRADING_MODE="paper",
            ALLOW_LIVE_TRADING=False,
        )

    monkeypatch.setattr(digest_module, "Settings", isolated_digest_settings)
    monkeypatch.setattr(adaptive_tuning_module, "Settings", lambda **_kwargs: settings)

    for external in ({}, {
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": "true",
        "TRADING_MODE": "live",
        "ALLOW_LIVE_TRADING": "true",
    }):
        for key in ("ALLOW_AUTO_APPLY_IMPROVEMENTS", "TRADING_MODE", "ALLOW_LIVE_TRADING"):
            monkeypatch.delenv(key, raising=False)
        for key, value in external.items():
            monkeypatch.setenv(key, value)
        health = build_operational_health_report(settings, store, reports_dir, "governance-health", now=fixed_now)
        digest = build_lab_digest(store, data_dir=settings.data_dir, now=fixed_now)

        assert health["report_health"]["adaptive_config_governance"]["status"] == "collecting"
        assert health["report_health"]["adaptive_config_governance"]["adaptive_auto_apply_authorized"] is False
        assert digest["adaptive_config_governance"]["adaptive_auto_apply_authorized"] is False
        assert digest["adaptive_config_governance"]["blocked_promotion_attempts"] is None
        assert digest["adaptive_config_governance"]["active_override_count"] == 0

    path = adaptive_config_path(settings)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "parameters": {
                    "MAX_ORDERS_PER_CYCLE": {
                        "status": "active",
                        "proposed": 2,
                        "created_at": "2026-07-10T20:52:47+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    health = build_operational_health_report(settings, store, reports_dir, "governance-override", now=fixed_now)
    digest = build_lab_digest(store, data_dir=settings.data_dir, now=fixed_now)
    row = digest["adaptive_config_governance"]["overrides"][0]

    assert health["report_health"]["adaptive_config_governance"]["status"] == "degraded_governance"
    assert digest["adaptive_config_governance"]["active_override_count"] == 1
    assert digest["adaptive_config_governance"]["unauthorized_or_legacy_active_override_count"] == 1
    assert row["classification"] == "stricter"
    assert row["governance"] == "preexisting_unauthorized"
