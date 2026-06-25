"""Tests del embudo del ciclo (B2)."""
from __future__ import annotations

import json

from agente_bolsa.config import Settings
from agente_bolsa.tools.cycle_funnel import (
    build_cycle_funnel,
    build_shadow_scoreboard_from_reports,
    format_cycle_funnel,
    format_shadow_scoreboard,
)


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


class _FakeStoreHistory:
    def __init__(self, events):
        self._events = events

    def latest_events(self, limit):
        return self._events[:limit]


def _completed_event(reason: str, submitted: int = 0) -> dict:
    return {
        "event_type": "paper_auto_trade_completed",
        "cycle_id": "c",
        "created_at": "t",
        "payload_json": json.dumps(
            {
                "recommendations": [{"symbol": "A", "action": "buy"}],
                "entry_quality_gate": [{"symbol": "A", "approved": False, "reason": reason}],
                "submitted": [{"symbol": "A"}] if submitted else [],
            }
        ),
    }


def test_cycle_funnel_history_aggregates_rejection_reasons(tmp_path):
    from agente_bolsa.tools.cycle_funnel import (
        build_cycle_funnel_history,
        format_cycle_funnel_history,
    )

    settings = Settings(DATA_DIR=str(tmp_path))
    events = [
        _completed_event("reward_risk_bajo"),
        _completed_event("reward_risk_bajo"),
        _completed_event("extension_alta"),
        {"event_type": "portfolio_watch", "payload_json": "{}"},  # ruido: se ignora
    ]
    agg = build_cycle_funnel_history(_FakeStoreHistory(events), settings, limit=10)
    assert agg["cycles_analizados"] == 3  # el portfolio_watch queda fuera
    assert agg["ciclos_con_ordenes"] == 0
    assert agg["total_recomendaciones"] == 3
    assert agg["motivos_rechazo_top"]["entry_quality: reward_risk_bajo"] == 2
    assert "EMBUDO AGREGADO" in format_cycle_funnel_history(agg)


def test_shadow_scoreboard_groups_strategy_and_quartiles():
    reports = [
        {
            "run_id": "mkt_1",
            "as_of": "2026-06-25T17:00:00Z",
            "shadow_candidates": [
                {
                    "symbol": "AAA",
                    "strategy_name": "builtin_pullback",
                    "technical_state": {"close": 101, "sma_20": 100, "rsi_14": 45},
                },
                {
                    "symbol": "BBB",
                    "strategy_name": "builtin_pullback",
                    "technical_state": {"close": 104, "sma_20": 100, "rsi_14": 55},
                },
                {
                    "symbol": "CCC",
                    "strategy_name": "experimental_shadow",
                    "technical_state": {"distance_sma20": -0.02, "rsi_14": 40},
                },
            ],
        }
    ]

    scoreboard = build_shadow_scoreboard_from_reports(reports)
    rows = {row["strategy_name"]: row for row in scoreboard["rows"]}

    assert scoreboard["cycles"] == 1
    assert rows["builtin_pullback"]["shadow_candidates"] == 2
    assert rows["builtin_pullback"]["distance_sma20"] == {
        "min": 0.01,
        "q1": 0.01,
        "median": 0.025,
        "q3": 0.04,
        "max": 0.04,
    }
    assert rows["builtin_pullback"]["rsi_14"]["median"] == 50
    assert rows["experimental_shadow"]["shadow_candidates"] == 1
    assert rows["experimental_shadow"]["distance_sma20"]["median"] == -0.02
    assert "SHADOW SCOREBOARD" in format_shadow_scoreboard(scoreboard)
