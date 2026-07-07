from __future__ import annotations

import json
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.storage import Store


def _store(tmp_path) -> Store:
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _write_overlay_log(tmp_path, payload: dict) -> None:
    log_dir = tmp_path / "research" / "overlay_shadow"
    log_dir.mkdir(parents=True)
    (log_dir / "overlay_shadow_log.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_lab_digest_includes_latest_overlay_shadow_signal(tmp_path):
    store = _store(tmp_path)
    _write_overlay_log(
        tmp_path,
        {
            "data_date": "2026-07-01",
            "price": 745.76,
            "realized_vol_annualized": 0.182797,
            "target_exposures": {
                "vol_target_10pct": 0.547054,
                "vol_target_12pct": 0.656465,
                "regime_sma200": 1.0,
            },
        },
    )

    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["overlay_shadow"]["available"] is True
    assert digest["overlay_shadow"]["stale"] is False
    assert "Overlay shadow" in text
    assert "VT12=0.656465" in text


def test_lab_digest_warns_when_overlay_shadow_is_stale(tmp_path):
    store = _store(tmp_path)
    _write_overlay_log(
        tmp_path,
        {
            "data_date": "2026-06-24",
            "realized_vol_annualized": 0.20,
            "target_exposures": {
                "vol_target_10pct": 0.50,
                "vol_target_12pct": 0.60,
                "regime_sma200": 1.0,
            },
        },
    )

    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["overlay_shadow"]["market_days_old"] > 3
    assert digest["overlay_shadow"]["stale"] is True
    assert "ADVERTENCIA: senal overlay" in text


def test_lab_digest_overlay_shadow_null_fields(tmp_path):
    store = _store(tmp_path)
    _write_overlay_log(
        tmp_path,
        {
            "data_date": "2026-07-01",
            "price": None,
            "realized_vol_annualized": None,
            "target_exposures": None,
        },
    )
    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["overlay_shadow"]["available"] is True
    # Should not crash
    assert "Overlay shadow" in text


def test_lab_digest_overlay_shadow_missing_file(tmp_path):
    store = _store(tmp_path)
    # No overlay log file written
    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["overlay_shadow"]["available"] is False
    # Ensure no crash and appropriate fallback in text
    assert "Overlay shadow" in text
    assert "no disponible" in text.lower()


def test_lab_digest_overlay_shadow_missing_target_exposures(tmp_path):
    store = _store(tmp_path)
    _write_overlay_log(
        tmp_path,
        {
            "data_date": "2026-07-01",
            "price": 750.0,
            "realized_vol_annualized": 0.15,
            # target_exposures omitted intentionally
        },
    )
    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["overlay_shadow"]["available"] is True
    assert "Overlay shadow" in text
    # When target_exposures missing, code computes from realized_vol, so VT10 and VT12 appear
    assert "VT10=" in text
    assert "VT12=" in text
