from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.findings_to_proposals import persist_findings_to_proposals
from agente_bolsa.storage import Store
from agente_bolsa.tools.daily_learning import build_learning_digest_report
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def test_learning_digest_exposes_learning_experiment_shadow_without_fills(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    store.save_signal_outcome(
        signal_id="learn-1",
        source_run_id="run-learn",
        source=LEARNING_EXPERIMENT_SOURCE,
        symbol="LYV",
        signal_date="2026-07-07",
        decision="approved_buy",
        features={
            "score": 15,
            "entry_price": 184.83,
            "stop_loss": 174.6679,
            "take_profit": 200.0732,
            "cohort": LEARNING_EXPERIMENT_SOURCE,
            "learning_mode": True,
        },
    )
    (reports_dir / "latest_learning_mode_shadow.json").write_text(
        json.dumps(
            {
                "session_date": "2026-07-07",
                "would_buy": [{"symbol": "LYV", "notional": 924.15}],
                "operational_kill_switch": {"kill_switch_active": True},
            }
        ),
        encoding="utf-8",
    )

    report = build_learning_digest_report(
        store,
        reports_dir,
        "digest",
        since_date="2026-07-07",
        end_date="2026-07-07",
    )

    section = report["digest"]["learning_experiment_yesterday"]
    assert section["available"] is True
    assert section["signals"] == 1
    assert section["observations"] == 1
    assert section["trades"] == 0
    assert section["shadow"]["available"] is True
    assert section["shadow"]["would_buy"][0]["symbol"] == "LYV"
    assert section["pipeline"]["signal_outcomes"]["status"] == "ok"
    assert section["pipeline"]["broker_reconciliation"]["status"] == "pending_first_fill"


def test_findings_to_proposals_persists_learning_experiment_bridge_candidates(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_daily_learning_digest.json").write_text(
        json.dumps(
            {
                "learning_experiment_yesterday": {
                    "available": True,
                    "session_date": "2026-07-07",
                    "lessons": ["near-miss pierde consistentemente"],
                    "shadow": {"available": True},
                    "pipeline": {"findings_to_proposals": {"status": "ok"}},
                    "adjustments": {
                        "proposal_candidates": [
                            {
                                "proposal_type": "RISK_RULE_CHANGE",
                                "target_component": "learning_mode",
                                "target_identifier": "backtest_near_miss_threshold",
                                "current_value": "near_miss activo",
                                "proposed_value": "Endurecer near_miss del learning mode.",
                                "rationale": "El cohorte learning_experiment rinde mal en near-miss.",
                                "expected_impact": "Reducir overrides con expectativa negativa.",
                                "risk_level": "MEDIUM",
                                "required_validations": ["tests", "paper_trading_evidence"],
                                "rollback_plan": "Restaurar umbrales previos.",
                                "promotion_state": "shadow",
                                "evidence": ["avg_return_3d=-0.021"],
                                "target_files": ["data/config/learning_mode.json"],
                                "test_requirement": "tests/test_learning_mode.py",
                                "test_commands": ["python -m pytest tests/test_learning_mode.py -q"],
                                "source": "learning_experiment_digest",
                            }
                        ]
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = persist_findings_to_proposals(settings=settings, store=store, limit=0, dry_run=False)

    assert result["learning_experiment_bridge"]["available"] is True
    assert len(result["created"]) == 1
    proposal = store.continuous_improvement_proposals(limit=10)[0]
    assert proposal["proposal_type"] == "RISK_RULE_CHANGE"
    assert proposal["target_identifier"] == "backtest_near_miss_threshold"
