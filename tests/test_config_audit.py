from __future__ import annotations

import json
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.storage import Store
from agente_bolsa.tools.config_audit import (
    build_config_audit,
    digest_safety_summary,
    format_config_audit_text,
)


def _settings(tmp_path, **overrides):
    params = {
        "DATA_DIR": tmp_path,
        "DATABASE_PATH": tmp_path / "state" / "test.sqlite3",
        "AGENT_LOGS_DIR": tmp_path / "logs" / "agents",
        "ALPACA_API_KEY": "key",
        "ALPACA_SECRET_KEY": "secret",
        "ALLOW_LIVE_TRADING": False,
        "TRADING_MODE": "paper",
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
    }
    params.update(overrides)
    return Settings(**params)


def _write_core_sleeve(tmp_path, *, dry_run: bool = True):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "core_sleeve.json").write_text(
        json.dumps({"enabled": True, "dry_run": dry_run, "sleeve_fraction": 0.3}),
        encoding="utf-8",
    )


def test_safety_ok_with_safe_flags(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=True)
    audit = build_config_audit(_settings(tmp_path))
    assert audit["safety"]["ok"] is True
    assert audit["safety"]["violations"] == []
    text = format_config_audit_text(audit)
    assert "Safety: OK" in text
    assert "learning_mode=sin_datos" in text


def test_safety_learning_mode_enabled_is_not_violation_when_authorized(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "learning_mode.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "human_gated": True,
                "shadow_first": False,
                "authorized_by": "Antonio 2026-07-07",
            }
        ),
        encoding="utf-8",
    )

    audit = build_config_audit(_settings(tmp_path))

    assert audit["safety"]["ok"] is True
    assert audit["safety"]["violations"] == []
    text = format_config_audit_text(audit)
    assert "Safety: OK" in text
    assert "learning_mode=ON, shadow_first=False" in text


def test_safety_learning_mode_enabled_without_authorization_alerts(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "learning_mode.json").write_text(
        json.dumps({"enabled": True, "human_gated": True, "shadow_first": False, "authorized_by": ""}),
        encoding="utf-8",
    )

    audit = build_config_audit(_settings(tmp_path))

    assert audit["safety"]["ok"] is False
    assert "learning_mode.sin_autorizacion" in audit["safety"]["violations"]
    text = format_config_audit_text(audit)
    assert "Safety: ALERTA -> learning_mode.sin_autorizacion" in text
    assert "learning_mode=ON, shadow_first=False" in text


def test_safety_learning_mode_parse_error_alerts(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "learning_mode.json").write_text("{bad json", encoding="utf-8")

    audit = build_config_audit(_settings(tmp_path))

    assert audit["safety"]["ok"] is False
    assert "learning_mode.config_parseable" in audit["safety"]["violations"]


def test_safety_alerts_when_auto_apply_enabled(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=True)
    audit = build_config_audit(_settings(tmp_path, ALLOW_AUTO_APPLY_IMPROVEMENTS=True))
    assert audit["safety"]["ok"] is False
    assert "allow_auto_apply_improvements" in audit["safety"]["violations"]
    text = format_config_audit_text(audit)
    assert "Safety: ALERTA" in text


def test_safety_alerts_when_core_sleeve_not_dry_run(tmp_path):
    _write_core_sleeve(tmp_path, dry_run=False)
    audit = build_config_audit(_settings(tmp_path))
    assert audit["safety"]["ok"] is False
    assert "core_sleeve.dry_run" in audit["safety"]["violations"]


def test_missing_file_configs_do_not_break(tmp_path):
    audit = build_config_audit(_settings(tmp_path))
    assert audit["file_configs"]["lab_book"] is None
    text = format_config_audit_text(audit)
    assert "(ausente)" in text


def test_divergent_field_detected(tmp_path):
    _write_core_sleeve(tmp_path)
    audit = build_config_audit(_settings(tmp_path, AUTO_PAPER_TRADING=True))
    row = next(item for item in audit["fields"] if item["field"] == "auto_paper_trading")
    assert row["effective"] is True
    assert row["divergent"] is True


def test_digest_safety_summary_never_raises(tmp_path):
    summary = digest_safety_summary(_settings(tmp_path))
    assert summary is None or isinstance(summary, dict)


def test_digest_safety_summary_exposes_learning_mode(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "learning_mode.json").write_text(
        json.dumps({"enabled": False, "human_gated": True, "shadow_first": True}),
        encoding="utf-8",
    )

    summary = digest_safety_summary(_settings(tmp_path))
    assert summary is not None
    assert summary["learning_mode"] == {
        "enabled": False,
        "human_gated": True,
        "shadow_first": True,
        "authorized_by": "",
    }


def test_digest_renders_safety_line_and_cast_counters(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    digest = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={"ok": False, "violations": ["allow_auto_apply_improvements"]},
    )
    text = format_lab_digest_text(digest)
    assert "Safety: ALERTA -> allow_auto_apply_improvements" in text
    assert "ultimo market_cycle: sin registros" in text
    assert "kill_switch: inactivo" in text
    assert "cast_cap=0" in text
    assert "not_proposer=0" in text

    digest_ok = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={
            "ok": True,
            "violations": [],
            "learning_mode": {"enabled": False, "shadow_first": True, "authorized_by": ""},
        },
    )
    assert "Safety: ALERTA -> market_cycle.sin_registro | learning_mode=OFF, shadow_first=True" in format_lab_digest_text(digest_ok)

    digest_alert = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={
            "ok": False,
            "violations": ["learning_mode.sin_autorizacion"],
            "learning_mode": {"enabled": True, "shadow_first": False, "authorized_by": ""},
        },
    )
    assert "Safety: ALERTA -> learning_mode.sin_autorizacion, market_cycle.sin_registro | learning_mode=ON, shadow_first=False" in format_lab_digest_text(
        digest_alert
    )

    digest_authorized = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={
            "ok": True,
            "violations": [],
            "learning_mode": {"enabled": True, "shadow_first": False, "authorized_by": "Antonio 2026-07-07"},
        },
    )
    assert "authorized_by=Antonio 2026-07-07" in format_lab_digest_text(digest_authorized)

    digest_none = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
    )
    assert "Safety: ALERTA -> market_cycle.sin_registro" in format_lab_digest_text(digest_none)
