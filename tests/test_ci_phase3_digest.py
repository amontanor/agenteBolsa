from __future__ import annotations

import json
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import (
    EXECUTABLE,
    PROSE,
    build_lab_digest,
    classify_proposal_quality,
    format_lab_digest_text,
    latest_core_sleeve_signal,
    write_lab_digest_file,
)
from agente_bolsa.continuous_improvement.research_agenda import save_research_agenda
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_health import activate_persistent_kill_switch


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _store(tmp_path) -> Store:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _proposal(
    store: Store,
    proposal_id: str,
    *,
    status: str = "READY_TO_APPLY",
    target_component: str = "settings",
    target_identifier: str = "max_orders_per_cycle",
    payload: dict | None = None,
    created_at: str = "2026-06-30T10:00:00+00:00",
) -> None:
    payload = payload or {
        "current_value": "4",
        "proposed_value": "8",
        "rationale": "Currently max_orders_per_cycle is 4; proposed 8.",
        "initiative_key": "software:max_orders_per_cycle",
    }
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": "ci_cycle_phase3",
            "fingerprint": f"fp_{proposal_id}",
            "proposal_type": "PARAMETER_CHANGE",
            "target_component": target_component,
            "target_identifier": target_identifier,
            "status": status,
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": payload,
            "guard": {"status": status, "reasons": []},
            "created_at": created_at,
        }
    )


def test_lab_digest_writes_markdown_file_with_approval_section(tmp_path):
    store = _store(tmp_path)
    _proposal(store, "ci_prop_ready")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_ready",
            "proposal_id": "ci_prop_ready",
            "artifact_type": "code_diff_preview",
            "content_text": "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n",
            "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True, "target_paths": ["docs/x.md"]},
        }
    )

    result = write_lab_digest_file(
        store,
        tmp_path / "reports",
        days=7,
        run_date=datetime(2026, 7, 2, tzinfo=timezone.utc).date(),
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )

    path = tmp_path / "reports" / "ci_digest_2026-07-02.md"
    assert result["ok"] is True
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "KPI funnel - ultimas 4 semanas" in text
    assert "Calidad de propuestas - medicion sin enforcement" in text
    assert "PIDE APROBACIÓN" in text
    assert "ci_prop_ready" in text
    assert "docs/x.md" in text


def test_lab_digest_kpis_from_synthetic_database(tmp_path):
    store = _store(tmp_path)
    _proposal(store, "ci_prop_a", created_at="2026-06-29T10:00:00+00:00")
    _proposal(store, "ci_prop_b", status="PENDING", created_at="2026-06-30T10:00:00+00:00")
    store.save_continuous_improvement_experiment(
        {
            "experiment_id": "ci_exp_a",
            "proposal_id": "ci_prop_a",
            "cycle_id": "ci_cycle_phase3",
            "status": "PASSED",
            "created_at": "2026-06-30T12:00:00+00:00",
        }
    )
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": "ci_applied_a",
            "proposal_id": "ci_prop_b",
            "cycle_id": "ci_cycle_phase3",
            "status": "APPLIED",
            "change_type": "CODE_CHANGE",
            "target_key": "docs/x.md",
            "created_at": "2026-07-01T12:00:00+00:00",
        }
    )
    store.update_continuous_improvement_proposal_status(
        "ci_prop_a",
        status="READY_TO_APPLY",
        actor="DecisionCommitteeAgent",
        reason="synthetic decision",
        payload={},
    )

    digest = build_lab_digest(store, days=7, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc))
    current_week = digest["kpi_funnel"]["weeks"][-1]

    assert current_week["week_start"] == "2026-06-29"
    assert current_week["proposals"] == 2
    assert current_week["experiments"] == 1
    assert current_week["applied_changes"] == 1
    assert current_week["proposal_to_experiment_pct"] == 50.0
    assert current_week["experiment_to_applied_pct"] == 100.0
    assert digest["kpi_funnel"]["wip_current"]["total"] >= 1


def test_lab_digest_includes_research_agenda_and_kpis(tmp_path):
    store = _store(tmp_path)
    save_research_agenda(
        [
            {
                "hypothesis_id": "agenda_test_open",
                "title": "pullback",
                "status": "pendiente",
                "target_date": "2026-07-06",
                "notes": "medir",
            },
            {
                "hypothesis_id": "agenda_test_killed",
                "title": "old edge",
                "status": "matada",
                "target_date": "2026-07-02",
                "notes": "sin edge",
                "closed_at": "2026-07-01T12:00:00+00:00",
            },
        ],
        tmp_path / "research" / "research_agenda.json",
    )
    store.save_continuous_improvement_experiment(
        {
            "experiment_id": "ci_exp_research",
            "proposal_id": "ci_prop_research",
            "cycle_id": "ci_cycle_research",
            "status": "PASSED",
            "created_at": "2026-07-01T12:00:00+00:00",
        }
    )

    digest = build_lab_digest(store, days=7, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["research_agenda"]["kpis"]["estudios_ejecutados_semana"] == 1
    assert digest["research_agenda"]["kpis"]["hipotesis_matadas_semana"] == 1
    assert "KPIs de investigacion" in text
    assert "estudios_ejecutados/semana: 1" in text
    assert "Agenda de investigacion" in text
    assert "| pullback | pendiente | 2026-07-06 | medir |" in text


def test_lab_digest_safety_includes_market_cycle_and_kill_switch_freshness(tmp_path):
    store = _store(tmp_path)
    store.set_runtime_value(
        "scheduler_job_status:market_cycle",
        {
            "job": "market_cycle",
            "status": "completed",
            "run_id": "mkt_live",
            "finished_at": "2026-07-02T11:40:00+00:00",
            "detail": "ciclo de mercado ejecutado",
        },
    )

    digest = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={"ok": True, "violations": []},
    )
    text = format_lab_digest_text(digest)

    assert digest["safety"]["market_cycle"]["status"] == "completed"
    assert digest["safety"]["kill_switch"]["active"] is False
    assert "ultimo market_cycle: hace 20 min (completed)" in text
    assert "kill_switch: inactivo" in text
    assert "low_sample: 0/0 usado hoy" in text


def test_lab_digest_shows_low_sample_quota_usage(tmp_path):
    store = _store(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "learning_mode.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "human_gated": True,
                "shadow_first": False,
                "low_sample_daily_quota": 1,
                "authorized_by": "Antonio 2026-07-08",
            }
        ),
        encoding="utf-8",
    )
    store.set_runtime_value(
        "learning_mode_low_sample_usage:2026-07-02",
        {
            "session_date": "2026-07-02",
            "quota": 1,
            "orders": [{"run_id": "mkt_1", "plan_id": "plan_1", "symbol": "AAPL"}],
        },
    )

    digest = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={"ok": True, "violations": []},
    )
    text = format_lab_digest_text(digest)

    assert digest["low_sample_usage"]["used"] == 1
    assert "low_sample: 1/1 usado hoy" in text


def test_lab_digest_renders_learning_experiment_yesterday_with_paused_shadow(tmp_path):
    store = _store(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "learning_experiment_yesterday": {
                    "available": True,
                    "session_date": "2026-07-09",
                    "trades": 2,
                    "pnl": {"open": 5.6, "realized": 0.0},
                    "execution_snapshot": [
                        {"symbol": "AIZ", "bracket_state": "open", "open_pl": -2.0, "realized_pl": None}
                    ],
                    "shadow": {
                        "would_buy_by_strategy": [
                            {"strategy_name": "builtin_pullback", "would_buy": 1, "paused": True}
                        ]
                    },
                    "lessons": ["La pausa conserva la medicion sin abrir posicion."],
                }
            }
        ),
        encoding="utf-8",
    )

    text = format_lab_digest_text(
        build_lab_digest(store, days=1, now=datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    )

    assert "Aprendizaje de ayer" in text
    assert "AIZ: bracket=open" in text
    assert "builtin_pullback (SOMBRA por pausa): habria comprado 1" in text
    assert "leccion: La pausa conserva la medicion" in text


def test_lab_digest_safety_alerts_on_active_kill_switch_and_missing_cycle(tmp_path):
    store = _store(tmp_path)
    activate_persistent_kill_switch(
        tmp_path,
        reason="kernel_integrity_violation: src/agente_bolsa/kernel.py",
        kind="kernel_integrity_violation",
    )

    digest = build_lab_digest(
        store,
        days=1,
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        data_dir=tmp_path,
        safety={"ok": True, "violations": []},
    )
    text = format_lab_digest_text(digest)

    assert "Safety: ALERTA" in text
    assert "market_cycle.sin_registro" in text
    assert "kill_switch.activo:kernel_integrity_violation: src/agente_bolsa/kernel.py" in text
    assert "ultimo market_cycle: sin registros" in text
    assert "kill_switch: activo" in text


def test_proposal_quality_classifier_executable_and_prose_cases():
    executable_parameter = {
        "target_identifier": "max_orders_per_cycle",
        "payload": {"current_value": "4", "proposed_value": "8"},
    }
    executable_diff = {
        "payload": {"file_edits": [{"path": "docs/x.md", "old": "a", "new": "b"}]},
    }
    executable_shadow = {
        "payload": {
            "promotion_state": "shadow",
            "entry": "rsi_14 < 35",
            "exit": "time stop 5d",
            "stop_loss": "2 ATR",
        }
    }
    executable_metric_target = {
        "target_identifier": "outcome_attribution",
        "payload": {"expected_impact": {"metric": "attributed_outcomes", "current_value": 0, "target_value": 80}},
    }
    prose = {
        "target_identifier": "quality",
        "payload": {"rationale": "Improve the system with better proposals and more focus."},
    }

    assert classify_proposal_quality(executable_parameter)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_diff)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_shadow)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_metric_target)["class"] == EXECUTABLE
    assert classify_proposal_quality(prose)["class"] == PROSE


def test_format_lab_digest_ends_with_pide_aprobacion_section(tmp_path):
    store = _store(tmp_path)
    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc))

    text = format_lab_digest_text(digest)

    assert text.splitlines()[-2] == "PIDE APROBACIÓN"
    assert text.splitlines()[-1] == "- No hay propuestas READY_FOR_HUMAN_REVIEW con tests_ok=true."


def test_core_sleeve_section_in_digest(tmp_path):
    store = _store(tmp_path)
    # Create core_sleeve log directory and file with data samples
    log_dir = tmp_path / "research" / "core_sleeve"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "core_sleeve_log.jsonl"
    line1 = '{"created_at": "2026-07-02T11:11:38.004021+00:00", "status": "disabled", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76001, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": false, "dry_run": true, "sleeve_fraction": 0.3, "rebalance_band_pp": 5.0, "target_vol": 0.12}, "decision": null}'
    line2 = '{"created_at": "2026-07-02T11:12:06.753314+00:00", "status": "would_submit", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76001, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": true, "dry_run": true, "sleeve_fraction": 0.3, "rebalance_band_pp": 5.0, "target_vol": 0.12}, "decision": {"data_date": "2026-07-01", "equity": 70653.37, "price": 745.76001, "exposure": 0.656465, "sleeve_fraction": 0.3, "target_notional": 13914.44, "current_notional": 0.0, "max_sleeve_notional": 21196.01, "rebalance_band_notional": 1059.8, "delta_notional": 13914.44, "order": {"symbol": "SPY", "side": "buy", "notional": 13914.44, "payload": {"qty": 18.658067, "entry_price": 745.76001, "source": "core_sleeve_vt12"}}, "reason": "buy_to_target"}}'
    log_path.write_text(line1 + "\n" + line2 + "\n", encoding="utf-8")

    digest = build_lab_digest(store, days=7, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    core = digest.get("core_sleeve", {})
    assert core.get("available") is True
    assert core.get("status") == "would_submit"
    assert core.get("exposure") == 0.656465
    assert core.get("decision_reason") == "buy_to_target"
    assert core.get("decision_order_side") == "buy"
    assert core.get("decision_order_notional") == 13914.44
    assert core.get("stale") is False  # data_date 2026-07-01, now 2026-07-02, so not stale


def test_latest_core_sleeve_signal_handles_real_no_order_with_null_order(tmp_path):
    log_dir = tmp_path / "research" / "core_sleeve"
    log_dir.mkdir(parents=True, exist_ok=True)
    real_crash_line = '{"created_at": "2026-07-02T13:45:05.206059+00:00", "status": "no_order", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76001, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": true, "dry_run": true, "sleeve_fraction": 0.3, "rebalance_band_pp": 5.0, "target_vol": 0.12}, "decision": {"data_date": "2026-07-01", "equity": 70653.37, "price": 745.76001, "exposure": 0.656465, "sleeve_fraction": 0.3, "target_notional": 13914.44, "current_notional": 0.0, "max_sleeve_notional": 21196.01, "rebalance_band_notional": 1059.8, "delta_notional": 13914.44, "order": null, "reason": "already_rebalanced_today"}}'
    (log_dir / "core_sleeve_log.jsonl").write_text(real_crash_line + "\n", encoding="utf-8")

    core = latest_core_sleeve_signal(tmp_path, now=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc))

    assert core["available"] is True
    assert core["status"] == "no_order"
    assert core["decision_reason"] == "already_rebalanced_today"
    assert core["decision_order_side"] is None
    assert core["decision_order_notional"] is None


def test_latest_core_sleeve_signal_handles_missing_nested_order(tmp_path):
    log_dir = tmp_path / "research" / "core_sleeve"
    log_dir.mkdir(parents=True, exist_ok=True)
    line = '{"created_at": "2026-07-02T13:45:05.206059+00:00", "status": "no_order", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76001, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": true, "dry_run": true}, "decision": {"reason": "within_rebalance_band"}}'
    (log_dir / "core_sleeve_log.jsonl").write_text(line + "\n", encoding="utf-8")

    core = latest_core_sleeve_signal(tmp_path, now=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc))

    assert core["decision_reason"] == "within_rebalance_band"
    assert core["decision_order_side"] is None
    assert core["decision_order_notional"] is None


def test_latest_core_sleeve_signal_covers_all_producer_status_shapes(tmp_path):
    cases = [
        (
            "disabled",
            None,
            None,
            None,
        ),
        (
            "no_order",
            {"reason": "within_rebalance_band", "order": None},
            None,
            None,
        ),
        (
            "would_submit",
            {"reason": "buy_to_target", "order": {"symbol": "SPY", "side": "buy", "notional": 13914.44}},
            "buy",
            13914.44,
        ),
        (
            "market_closed",
            {"reason": "sell_to_target", "order": {"symbol": "SPY", "side": "sell", "notional": 500.0}},
            "sell",
            500.0,
        ),
        (
            "submitted",
            {"reason": "buy_to_target", "order": {"symbol": "SPY", "side": "buy", "notional": 750.0}},
            "buy",
            750.0,
        ),
    ]
    for status, decision, expected_side, expected_notional in cases:
        data_dir = tmp_path / status
        log_dir = data_dir / "research" / "core_sleeve"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": "2026-07-02T13:45:05.206059+00:00",
            "status": status,
            "symbol": "SPY",
            "data_date": "2026-07-01",
            "price": 745.76001,
            "realized_vol_annualized": 0.182797,
            "exposure": 0.656465,
            "config": {"enabled": status != "disabled", "dry_run": status != "submitted"},
            "decision": decision,
        }
        (log_dir / "core_sleeve_log.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")

        core = latest_core_sleeve_signal(data_dir, now=datetime(2026, 7, 2, 14, 0, tzinfo=timezone.utc))

        assert core["available"] is True
        assert core["status"] == status
        assert core["decision_order_side"] == expected_side
        assert core["decision_order_notional"] == expected_notional
