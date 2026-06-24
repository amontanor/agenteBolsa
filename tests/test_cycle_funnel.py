"""Tests del embudo del ciclo (B2)."""
from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.tools.cycle_funnel import build_cycle_funnel, format_cycle_funnel


class _FakeStore:
    def __init__(self, payload: dict, cid: str = "mkt_x", created: str = "2026-06-24T16:00:00Z"):
        self._ev = {"cycle_id": cid, "created_at": created, "payload_json": json.dumps(payload)}

    def latest_event_of_type(self, _types):
        return self._ev


def _write_study(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "latest_closed_market_technical_study.json").write_text(
        json.dumps(
            {
                "symbols_scanned": 343,
                "symbols_with_data": 340,
                "all_candidates": [{"symbol": f"S{i}"} for i in range(343)],
                "top_longs": [{"symbol": f"S{i}"} for i in range(15)],
                "setup_counts": {"chart_pattern": 300},
            }
        ),
        encoding="utf-8",
    )


def test_funnel_identifies_entry_quality_bottleneck(tmp_path):
    settings = Settings(DATA_DIR=str(tmp_path))
    _write_study(tmp_path)
    payload = {
        "recommendations": [{"symbol": "AAA", "action": "buy"}, {"symbol": "BBB", "action": "buy"}],
        "deterministic_review": [{"symbol": "AAA", "approved": True}, {"symbol": "BBB", "approved": True}],
        "adversarial_review": [{"symbol": "AAA", "approved": True}, {"symbol": "BBB", "approved": True}],
        "entry_quality_gate": [
            {"symbol": "AAA", "approved": False, "reason": "reward_risk_bajo"},
            {"symbol": "BBB", "approved": False, "reason": "reward_risk_bajo"},
        ],
        "backtest_gate": [],
        "rejected_order_plans": [],
        "submitted": [],
        "failed": [],
        "effective_max_orders_per_cycle": 3,
        "effective_max_daily_buy_orders": 5,
    }
    funnel = build_cycle_funnel(_FakeStore(payload), settings)
    st = funnel["stages"]
    assert st["universo"] == 343
    assert st["candidatos"] == 343
    assert st["recomendaciones"] == 2
    assert st["gate_entry_quality"]["blocked"] == 2
    assert st["gate_entry_quality"]["approved"] == 0
    assert "gate_entry_quality" in funnel["cuello"]
    assert "reward_risk_bajo" in funnel["cuello"]
    assert "EMBUDO DEL CICLO" in format_cycle_funnel(funnel)


def test_funnel_reports_no_recommendations(tmp_path):
    settings = Settings(DATA_DIR=str(tmp_path))
    _write_study(tmp_path)
    payload = {
        "recommendations": [],
        "deterministic_review": [],
        "adversarial_review": [],
        "entry_quality_gate": [],
        "backtest_gate": [],
        "rejected_order_plans": [],
        "submitted": [],
        "failed": [],
    }
    funnel = build_cycle_funnel(_FakeStore(payload), settings)
    assert funnel["stages"]["recomendaciones"] == 0
    assert "decision" in funnel["cuello"]
