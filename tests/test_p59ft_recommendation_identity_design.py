"""P-L59F-T-R2: caracterizacion final de la colision recommendation_id en P-L53.

Correcciones R2:
- _auto_paper_trade: sin rec_id preasignado, mismo decision_lineage,
  build_order_plans usa los gated recibidos, orden ejecucion registrado
- Expansion: misma identidad duplicada, _denominators + match_same_cycle_controls
- test_stage_order local eliminado (integration test es la evidencia)

Base: P-L59D-D HEAD 520559c6, tree e3c80ba, v0.4.196.
"""

from __future__ import annotations

import copy
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _auto_paper_trade
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    _denominators,
    build_canonical_selection_ledger,
    match_same_cycle_controls,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
    stable_content_hash,
)
from agente_bolsa.tools.capital_deployment_funnel_shadow import (
    build_capital_deployment_funnel_shadow,
)

CAPTURED_AT = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _candidate_row(
    *,
    cycle_id: str = "cycle-collision",
    session_date: str = "2026-07-27",
    signal_capture_id: str = "capture:tsla:buy",
    signal_id: str = "signal:tsla:buy",
    candidate_id: str = "candidate:tsla:buy",
    symbol: str = "TSLA",
    action: str = "buy",
) -> dict[str, Any]:
    signal_at = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
    return {
        "cycle_id": cycle_id,
        "session_date": session_date,
        "signal_capture_id": signal_capture_id,
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": "builtin_breakout",
        "setup": "continuation",
        "score_universe": "domain-A",
        "score": 15.0,
        "selection_score": 0.8,
        "score_rank": 1,
        "selection_rank": 1,
        "data_quality": "good",
        "freshness": "fresh",
        "price_basis": "close_unadjusted",
        "signal_at": signal_at.isoformat(),
        "decision_at": signal_at.isoformat(),
        "eligible_at_selection": True,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": True,
    }


def _phase_a(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"all_candidates": list(rows), "selected_candidates": list(rows)}


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "signal_id": row["signal_id"],
        "candidate_id": row["candidate_id"],
    }


def _recommendation(
    row: dict[str, Any],
    *,
    recommendation_id: str = "rec:A",
    source: str = "llm",
    llm_selected: bool | None = True,
    confidence: float = 0.85,
) -> dict[str, Any]:
    """Recommendacion con decision_context_snapshot."""
    snapshot: dict[str, Any] = {
        "llm_considered": source in {"llm", "deterministic_capacity_fill"},
        "gate_frontier": row.get("gate_frontier"),
        "llm_selected": llm_selected,
    }
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "recommendation_id": recommendation_id,
        "source": source,
        "decision_origin": source,
        "confidence": confidence,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": snapshot,
    }


# ===================================================================
# 1. REPRODUCCION DE LA COLISION
# ===================================================================


def test_two_recommendations_same_identity_last_wins() -> None:
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:first", llm_selected=True, confidence=0.90)
    rec_b = _recommendation(row, recommendation_id="rec:second", llm_selected=False, confidence=0.60)
    result = build_canonical_selection_ledger(
        "cycle-collision", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    assert len(result["candidate_rows"]) == 1
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:second"
    assert r["llm_selected"] is False
    assert r["recommended"] is True
    assert result["denominators"]["recommended_count"] == 1
    assert result["content_hash"] == stable_content_hash(result)


def test_two_recommendations_same_identity_reverse_order_last_wins() -> None:
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:first", llm_selected=False)
    rec_b = _recommendation(row, recommendation_id="rec:second", llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-collision", _phase_a(row),
        recommendations=[rec_b, rec_a], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:first"
    assert r["llm_selected"] is False


def test_first_recommendation_evidence_lost() -> None:
    row = _candidate_row()
    rec_first = _recommendation(row, recommendation_id="rec:first", llm_selected=True, confidence=0.90)
    rec_second = _recommendation(row, recommendation_id="rec:second", llm_selected=False, confidence=0.40)
    result = build_canonical_selection_ledger(
        "cycle-collision", _phase_a(row),
        recommendations=[rec_first, rec_second], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] != "rec:first"
    assert r["llm_selected"] is not True
    assert "recommendation_without_phase_a_candidate" not in result.get("warnings", [])
    collision_warnings = [w for w in result.get("warnings", []) if "collision" in w.lower() or "overwrite" in w.lower()]
    assert len(collision_warnings) == 0


# ===================================================================
# 2. MISMO recommendation_id
# ===================================================================


def test_same_rec_id_same_content_within_one_build_last_wins_silently() -> None:
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:dual", source="llm", llm_selected=True, confidence=0.80)
    rec_b = _recommendation(row, recommendation_id="rec:dual", source="llm", llm_selected=True, confidence=0.80)
    result = build_canonical_selection_ledger(
        "cycle-same-content", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:dual"
    assert r["recommended"] is True
    assert "candidate_idempotent_duplicate" not in result.get("warnings", [])


def test_same_rec_id_different_content_within_one_build_last_wins() -> None:
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:dual", source="llm", llm_selected=True, confidence=0.90)
    rec_b = _recommendation(row, recommendation_id="rec:dual", source="capacity_fill", llm_selected=False, confidence=0.40)
    result = build_canonical_selection_ledger(
        "cycle-diff-content", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:dual"
    assert r["llm_selected"] is False
    assert r["decision_source"] == "deterministic_capacity_fill"
    assert "conflict" not in str(result.get("warnings", [])).lower()


def test_same_rec_id_different_content_across_builds_store_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:store", llm_selected=True, confidence=0.90)
    p1 = build_canonical_selection_ledger("cycle-store", _phase_a(row),
                                            recommendations=[rec_a], captured_at=CAPTURED_AT)
    rec_b = _recommendation(row, recommendation_id="rec:store", llm_selected=False, confidence=0.40)
    p2 = build_canonical_selection_ledger("cycle-store", _phase_a(row),
                                            recommendations=[rec_b], captured_at=CAPTURED_AT)
    assert p1["content_hash"] != p2["content_hash"]
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"
    rb = read_canonical_selection_ledger(store, "cycle-store")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:store"
    assert rb["candidate_rows"][0]["llm_selected"] is True


def test_same_rec_id_same_content_across_builds_store_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:idem", llm_selected=True)
    p1 = build_canonical_selection_ledger("cycle-idem", _phase_a(row),
                                            recommendations=[rec], captured_at=CAPTURED_AT)
    p2 = build_canonical_selection_ledger("cycle-idem", _phase_a(row),
                                            recommendations=[rec], captured_at=CAPTURED_AT)
    assert p1["content_hash"] == p2["content_hash"]
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "idempotent"
    rb = read_canonical_selection_ledger(store, "cycle-idem")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:idem"


# ===================================================================
# 3. BUY vs EXIT
# ===================================================================


def test_buy_and_exit_same_signal_preserved_separately() -> None:
    row = _candidate_row(action="buy", signal_id="signal:tsla")
    row_exit = _candidate_row(action="exit", signal_id="signal:tsla",
                              signal_capture_id="capture:tsla:exit",
                              candidate_id="candidate:tsla:exit")
    rec_buy = _recommendation(row, recommendation_id="rec:buy")
    rec_exit = _recommendation(row_exit, recommendation_id="rec:exit")
    rec_exit["action"] = "exit"
    rec_exit["decision_lineage"]["action"] = "exit"
    result = build_canonical_selection_ledger(
        "cycle-buy-exit", _phase_a(row, row_exit),
        recommendations=[rec_buy, rec_exit], captured_at=CAPTURED_AT,
    )
    by_action = {r["action"]: r for r in result["candidate_rows"]}
    assert "buy" in by_action and "exit" in by_action
    assert by_action["buy"]["recommendation_id"] == "rec:buy"
    assert by_action["exit"]["recommendation_id"] == "rec:exit"
    assert result["denominators"]["recommended_count"] == 2


def test_two_buys_one_exit_same_signal() -> None:
    row_buy = _candidate_row(action="buy", signal_id="signal:aapl")
    row_exit = _candidate_row(action="exit", signal_id="signal:aapl",
                              signal_capture_id="capture:aapl:exit",
                              candidate_id="candidate:aapl:exit")
    rec_buy_a = _recommendation(row_buy, recommendation_id="rec:buy:a", llm_selected=True)
    rec_buy_b = _recommendation(row_buy, recommendation_id="rec:buy:b", llm_selected=False)
    rec_exit_x = _recommendation(row_exit, recommendation_id="rec:exit:x")
    rec_exit_x["action"] = "exit"
    rec_exit_x["decision_lineage"]["action"] = "exit"
    result = build_canonical_selection_ledger(
        "cycle-buy-buy-exit", _phase_a(row_buy, row_exit),
        recommendations=[rec_buy_a, rec_buy_b, rec_exit_x], captured_at=CAPTURED_AT,
    )
    assert len(result["candidate_rows"]) == 2
    by_action = {r["action"]: r for r in result["candidate_rows"]}
    assert by_action["buy"]["recommendation_id"] == "rec:buy:b"
    assert by_action["exit"]["recommendation_id"] == "rec:exit:x"
    assert result["denominators"]["recommended_count"] == 2


# ===================================================================
# 4. MISSING recommendation_id LEGACY
# ===================================================================


def test_missing_recommendation_id_stays_none() -> None:
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="")
    rec["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-no-rec-id", _phase_a(row),
        recommendations=[rec], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] is None
    assert r["recommended"] is True


def test_mixed_legacy_and_new_recommendation_ids() -> None:
    row = _candidate_row()
    rec_legacy = _recommendation(row, recommendation_id="")
    rec_legacy["recommendation_id"] = None
    rec_new = _recommendation(row, recommendation_id="rec:new", llm_selected=False)
    result = build_canonical_selection_ledger(
        "cycle-mixed", _phase_a(row),
        recommendations=[rec_legacy, rec_new], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:new"
    assert r["llm_selected"] is False


def test_multiple_recommendations_all_missing_ids() -> None:
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="", llm_selected=True)
    rec_a["recommendation_id"] = None
    rec_b = _recommendation(row, recommendation_id="", llm_selected=False)
    rec_b["recommendation_id"] = None
    result = build_canonical_selection_ledger(
        "cycle-no-ids", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] is None
    assert r["llm_selected"] is False
    assert result["denominators"]["recommended_count"] == 1


# ===================================================================
# 5. WIRING REAL: _auto_paper_trade con DOS recomendaciones
#    R2: SIN recommendation_id preasignado; MISMO decision_lineage;
#    build_order_plans recibe gated_recommendations y los usa.
# ===================================================================


class _NullReporter:
    def emit(self, *_args, **_kwargs) -> None:
        pass


def test_wiring_two_recs_same_lineage_ids_assigned_ordered(monkeypatch, tmp_path):
    """Ejecuta _auto_paper_trade con DOS TradeRecommendation que entran
    SIN recommendation_id preasignado y con el MISMO decision_lineage
    (mismo cycle_id, action, signal_capture_id, signal_id, candidate_id).
    _auto_paper_trade asigna IDs en L1805. Espia P-L53 y P-L54.
    build_order_plans usa los objetos gated recibidos (con IDs asignados).
    Registra orden ejecucion: request -> review -> gates -> plans -> submit
    -> P-L53 final -> P-L54 final."""
    import agente_bolsa.cycle_runner as runner

    # --- recomendaciones sin recommendation_id, MISMO decision_lineage literal ---
    rec1 = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9,
                                reason="test1", entry_price=100,
                                stop_loss=95, take_profit=110)
    rec2 = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8,
                                reason="test2", entry_price=101,
                                stop_loss=96, take_profit=112)
    assert rec1.recommendation_id is None
    assert rec2.recommendation_id is None
    # Asignar MISMO decision_lineage literal (como haria _annotate con cycle_id real)
    common_lineage = {
        "cycle_id": "cycle-two-recs",
        "action": "buy",
        "signal_capture_id": "capture:aapl:buy",
        "signal_id": "signal:aapl:buy",
        "candidate_id": "candidate:aapl:buy",
    }
    rec1 = dc_replace(rec1, decision_lineage=common_lineage)
    rec2 = dc_replace(rec2, decision_lineage=common_lineage)
    assert rec1.decision_lineage == rec2.decision_lineage
    assert rec1.decision_lineage["cycle_id"] == "cycle-two-recs"

    # --- spies ---
    calls_order: list[str] = []
    p53_calls: list[dict] = []
    p54_calls: list[dict] = []
    gated_recs_captured: list[list] = []

    def _spy_p53(**kwargs):
        calls_order.append("P-L53")
        p53_calls.append(dict(kwargs))
        return {"status": "verified", "persist_status": "inserted"}

    def _spy_p54(**kwargs):
        calls_order.append("P-L54")
        p54_calls.append(dict(kwargs))
        return {"status": "verified", "persist_status": "inserted"}

    # build_order_plans: construye planes desde los gated RECIBIDOS
    def _build_plans_from_gated(settings, portfolio, gated, **_kw):
        calls_order.append("build_order_plans")
        gated_recs_captured.append(list(gated))
        plans = []
        for g in gated:
            rec = g.recommendation if hasattr(g, 'recommendation') else g
            entry = getattr(rec, 'entry_price', 100.0)
            plan = OrderPlan(getattr(rec, 'symbol', 'AAPL'), "buy",
                             entry, 1.0, entry, entry * 0.95, entry * 1.10,
                             rec, RiskDecision(True, "ok", {}))
            plans.append(plan)
        return plans

    monkeypatch.setattr(runner, "_persist_selection_ledger_shadow", _spy_p53)
    monkeypatch.setattr(runner, "_persist_capital_deployment_funnel_shadow", _spy_p54)
    monkeypatch.setattr(runner, "active_learning_mode", lambda _s: None)
    monkeypatch.setattr(runner, "load_daily_learning_context", lambda _p: {})
    monkeypatch.setattr(runner, "load_operational_response_context", lambda _p: {})
    monkeypatch.setattr(runner, "load_operational_block_context", lambda _p: {})
    monkeypatch.setattr(runner, "record_setup_edge_cycle_shadow", lambda *_a: {})
    monkeypatch.setattr(runner, "MarketCalendar", lambda *_a: SimpleNamespace(
        status=lambda: SimpleNamespace(is_open=True)))
    monkeypatch.setattr(runner, "BrokerClientFactory", lambda _s: SimpleNamespace(
        alpaca_portfolio_snapshot=lambda: {"equity": 100000, "cash": 50000, "gross_exposure": 0.5}))
    monkeypatch.setattr(runner, "build_portfolio_rebalance_context", lambda *_a: {})
    monkeypatch.setattr(runner, "load_latest_sentiment", lambda _p: {})
    monkeypatch.setattr(runner, "augment_recommendations_with_deterministic_fallback",
                        lambda _s, _p, _ctx, items, **_kw: (items, {"added": []}))

    # request -> recommendations SIN ID
    monkeypatch.setattr(runner, "request_trade_recommendations",
                        lambda *_a: (calls_order.append("request_trade_recommendations"),
                                     {"recommendations": [rec1, rec2]})[-1])
    # review -> devuelve las mismas (con lineage asignado por _annotate)
    monkeypatch.setattr(runner, "review_recommendations",
                        lambda *_a: (calls_order.append("review_recommendations"),
                                     [rec1, rec2],
                                     [{"symbol": "AAPL", "action": "buy", "approved": True},
                                      {"symbol": "AAPL", "action": "buy", "approved": True}])[-2:])
    monkeypatch.setattr(runner, "review_recommendations_adversarial",
                        lambda *_a, **_kw: [{"symbol": "AAPL", "action": "buy", "approved": True}])
    monkeypatch.setattr(runner, "_annotate_recommendations_with_strategy", lambda items, *_a: items)
    monkeypatch.setattr(runner, "_annotate_recommendations_with_lineage", lambda items, *_a, **_kw: items)
    monkeypatch.setattr(runner, "recommendation_input_fingerprint", lambda *_a, **_kw: "fp")
    monkeypatch.setattr(runner, "_decision_context_snapshot_for_recommendation",
                        lambda _store, rec, **kw: {
                            "llm_considered": True,
                            "gate_frontier": "entry_eligibility_v1",
                            "llm_selected": None,
                            "cycle_id": kw.get("cycle_id"),
                            "source_run_id": kw.get("source_run_id"),
                        })

    # gates -> ambos pasan (devolver quality_recommendations/gated)
    # _apply_entry_quality_gate(s, rep, run_id, reviewed, ...) -> _a[3]
    monkeypatch.setattr(runner, "_apply_entry_quality_gate",
                        lambda *_a, **_kw: (calls_order.append("_apply_entry_quality_gate"),
                                            _a[3], [])[-2:])
    # _apply_backtest_gate(s, store, rep, run_id, quality, ...) -> _a[4]
    monkeypatch.setattr(runner, "_apply_backtest_gate",
                        lambda *_a, **_kw: (calls_order.append("_apply_backtest_gate"),
                                            _a[4], [])[-2:])

    monkeypatch.setattr(runner, "update_signal_decisions", lambda *_a, **_kw: 0)
    monkeypatch.setattr(runner, "build_order_plans", _build_plans_from_gated)
    monkeypatch.setattr(runner, "_apply_daily_buy_limit",
                        lambda *_a, **_kw: _a[4])
    monkeypatch.setattr(runner, "_apply_low_sample_daily_quota",
                        lambda *_a, **_kw: _a[4])
    monkeypatch.setattr(runner, "_separate_strategy_paused_plans",
                        lambda _m, plans: (plans, []))
    monkeypatch.setattr(runner, "_effective_buy_plan_limit", lambda *_a: 2)
    monkeypatch.setattr(runner, "_effective_daily_buy_limit", lambda *_a: 2)
    monkeypatch.setattr(runner, "_low_sample_usage_payload", lambda *_a: {})

    # submit -> un plan por recomendacion
    submit_count = [0]
    def _submit_tracking(*_a, **_kw):
        calls_order.append(f"submit_paper_order_plan_{submit_count[0]}")
        submit_count[0] += 1
        return {"id": f"broker-{submit_count[0]}", "status": "accepted"}
    monkeypatch.setattr(runner, "submit_paper_order_plan", _submit_tracking)

    monkeypatch.setattr(runner, "update_signal_execution_status", lambda *_a, **_kw: 1)
    monkeypatch.setattr(runner, "_write_learning_mode_shadow_report", lambda *_a, **_kw: "s.json")
    monkeypatch.setattr(runner, "collect_gate_path", lambda **_kw: {})
    monkeypatch.setattr(runner, "attach_gate_evaluation_snapshots", lambda _store, snapshots=None: None)
    monkeypatch.setattr(runner, "build_comparable_control_sets", lambda **_kw: {})
    monkeypatch.setattr(runner, "_persist_learning_penalty_cycle_shadow_final",
                        lambda **kw: {"status": "available"})

    store = SimpleNamespace(
        calls=[],
        save_trade_recommendation=lambda **kw: store.calls.append("save_trade_recommendation"),
        save_order_plan=lambda **kw: store.calls.append("save_order_plan") or store.__setattr__("plans", store.__dict__.get("plans", []) + [{**kw, "status": "PENDING"}]),
        pending_order_plans=lambda **_kw: store.__dict__.get("plans", []),
        save_broker_order=lambda **kw: store.calls.append("save_broker_order"),
        count_broker_orders=lambda **_kw: 0,
    )
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True,
                        REQUIRE_HUMAN_APPROVAL=False)
    _auto_paper_trade(
        settings, store, _NullReporter(), "cycle-two-recs",
        {"run_id": "source"}, {}, {},
    )

    # --- Order ejecutado: request -> review -> gates -> plans -> submit -> shadows ---
    expected_order_prefix = [
        "request_trade_recommendations",
        "review_recommendations",
        "_apply_entry_quality_gate",
        "_apply_backtest_gate",
        "build_order_plans",
    ]
    for prefix in expected_order_prefix:
        assert prefix in calls_order, (
            f"Falta {prefix} en orden ejecucion: {calls_order}"
        )
    req_idx = calls_order.index("request_trade_recommendations")
    rev_idx = calls_order.index("review_recommendations")
    eq_idx = calls_order.index("_apply_entry_quality_gate")
    bt_idx = calls_order.index("_apply_backtest_gate")
    pl_idx = calls_order.index("build_order_plans")
    assert req_idx < rev_idx < eq_idx < bt_idx < pl_idx, (
        f"Orden incorrecto: {calls_order}"
    )
    # submit ocurre despues de plans
    submit_indices = [i for i, c in enumerate(calls_order) if c.startswith("submit_paper_order_plan")]
    assert len(submit_indices) == 2, f"Esperados 2 submits, hubo {len(submit_indices)}"
    assert all(si > pl_idx for si in submit_indices)
    # P-L53 y P-L54 finales despues de submits
    assert "P-L53" in calls_order
    assert "P-L54" in calls_order
    p53_idx = calls_order.index("P-L53")
    p54_idx = calls_order.index("P-L54")
    assert p53_idx > max(submit_indices)
    assert p54_idx > max(submit_indices)

    # --- Stage: P-L53 explícitamente antes que P-L54 ---
    assert p53_idx < p54_idx, (
        f"P-L53 debe ejecutarse antes que P-L54: P-L53@{p53_idx}, P-L54@{p54_idx}"
    )

    # --- P-L53 recibio 2 recomendaciones con IDs NO nulos y distintos ---
    assert len(p53_calls) >= 1
    p53_kw = p53_calls[-1]
    p53_recs = p53_kw.get("recommendations")
    assert p53_recs is not None and len(p53_recs) == 2, (
        f"P-L53 esperaba 2 recomendaciones, recibio {p53_recs}"
    )
    id_a = getattr(p53_recs[0], "recommendation_id", None)
    id_b = getattr(p53_recs[1], "recommendation_id", None)
    assert id_a is not None and id_b is not None
    assert id_a != id_b, f"IDs deben ser distintos: {id_a} == {id_b}"
    # Verificar que ambas conservan el mismo decision_lineage
    for rec in p53_recs:
        lineage = getattr(rec, "decision_lineage", None)
        assert lineage is not None, "P-L53 debe recibir recommendations con decision_lineage"
        assert lineage.get("cycle_id") == "cycle-two-recs"
        assert lineage.get("action") == "buy"
        assert lineage.get("signal_capture_id") == common_lineage["signal_capture_id"]

    # --- Coherencia adjuntos P-L53: plans y plan_records ---
    p53_plans = p53_kw.get("plans")
    p53_plan_records = p53_kw.get("plan_records")
    if p53_plans is not None:
        assert len(p53_plans) == 2, f"P-L53 esperaba 2 plans, recibio {len(p53_plans)}"
        for plan in p53_plans:
            plan_rec = plan.recommendation if hasattr(plan, "recommendation") else plan.get("recommendation", {})
            plan_rec_id = getattr(plan_rec, "recommendation_id", None)
            assert plan_rec_id in {id_a, id_b}, (
                f"Cada plan debe apuntar a un recommendation_id de P-L53: {plan_rec_id}"
            )
    if p53_plan_records is not None:
        for pr in p53_plan_records:
            rec_in_record = pr.get("recommendation") if isinstance(pr, dict) else getattr(pr, "recommendation", None)
            if rec_in_record is not None:
                pr_rec_id = getattr(rec_in_record, "recommendation_id", None)
                assert pr_rec_id in {id_a, id_b, None}, (
                    f"plan_record debe transportar recommendation_id coherente: {pr_rec_id}"
                )

    # --- P-L54: recomendaciones + planes ---
    assert len(p54_calls) >= 1
    p54_kw = p54_calls[-1]
    p54_recs = p54_kw.get("recommendations")
    assert p54_recs is not None and len(p54_recs) == 2
    p54_ids = [getattr(r, "recommendation_id", None) for r in p54_recs]
    assert set(p54_ids) == {id_a, id_b}, (
        f"P-L54 debe recibir los mismos recommendation_id que P-L53: {p54_ids} != {{{id_a}, {id_b}}}"
    )
    # P-L54 recibe tambien plans (o plan_records)
    p54_plans = p54_kw.get("plans")
    p54_plan_records = p54_kw.get("plan_records")
    p54_effective = p54_plan_records or p54_plans
    if p54_effective is not None:
        assert len(p54_effective) == 2, f"P-L54 esperaba 2 planes/plan_records, recibio {len(p54_effective)}"

    # --- Coherencia: IDs en gated coinciden con P-L53 y P-L54 ---
    assert len(gated_recs_captured) >= 1
    gated = gated_recs_captured[-1]
    assert len(gated) == 2
    gated_ids = [getattr(g, "recommendation_id", None) for g in gated]
    assert gated_ids[0] is not None and gated_ids[1] is not None
    assert gated_ids[0] != gated_ids[1]
    assert set(gated_ids) == {id_a, id_b}


# ===================================================================
# 6. P-L54 API REAL
# ===================================================================


def _p54_candidate_row(index: int, rec_id: str, *,
                       signal_capture: str = "capture-0",
                       cycle_id: str = "cycle-p54") -> dict:
    return {
        "cycle_id": cycle_id,
        "action": "buy",
        "signal_capture_id": signal_capture,
        "candidate_id": f"candidate-{index}",
        "recommendation_id": rec_id,
        "strategy": "setup-a",
        "setup": "breakout",
        "stage_statuses": {
            "selection": "passed", "gates": "passed", "capacity": "passed",
            "sizing": "passed", "risk": "passed", "plans": "passed",
            "orders": "passed", "fills": "passed",
        },
        "requested_notional": 1500.0,
        "planned_notional": 1000.0,
        "submitted_notional": 1000.0,
        "filled_notional": 1000.0,
        "currency": "USD",
        "as_of": "2026-07-27T19:00:00+00:00",
        "plan_id": f"plan-{index}",
        "broker_order_id": f"order-{index}",
        "order_status": "filled",
    }


def test_p54_two_decisions_same_signal_distinct_rec_ids_produce_two_rows() -> None:
    row_a = _p54_candidate_row(0, "rec:a", signal_capture="capture-0", cycle_id="cycle-p54")
    row_b = _p54_candidate_row(1, "rec:b", signal_capture="capture-0", cycle_id="cycle-p54")
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54", [row_a, row_b],
        account={"equity": 100000.0, "cash": 80000.0, "gross_exposure": 0.20},
        captured_at=CAPTURED_AT,
    )
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    assert len(buy_rows) == 2
    by_rec_id = {r["recommendation_id"]: r for r in buy_rows}
    assert "rec:a" in by_rec_id and "rec:b" in by_rec_id
    assert result["denominators"]["recommendations_generated"] == 2


def test_p54_same_rec_id_true_identical_content_idempotent() -> None:
    row = _p54_candidate_row(0, "rec:same", cycle_id="cycle-p54-idem")
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54-idem", [row, row],
        captured_at=CAPTURED_AT,
    )
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    assert len(buy_rows) == 1
    assert buy_rows[0]["recommendation_id"] == "rec:same"


def test_p54_same_rec_id_different_content_becomes_ambiguous() -> None:
    row_a = _p54_candidate_row(0, "rec:same", cycle_id="cycle-p54-merge")
    row_a["planned_notional"] = 500.0
    row_b = _p54_candidate_row(1, "rec:same", cycle_id="cycle-p54-merge")
    row_b["planned_notional"] = 2000.0
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54-merge", [row_a, row_b],
        captured_at=CAPTURED_AT,
    )
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    assert len(buy_rows) == 2
    assert all(r["identity_status"] == "identity_ambiguous" for r in buy_rows)
    assert all(r["recommendation_id"] == "rec:same" for r in buy_rows)


# ===================================================================
# 7. EXPANSION: misma identidad duplicada, _denominators + match_same_cycle_controls
# ===================================================================


def test_expansion_same_identity_duplicated_inflates_counters() -> None:
    """Caracteriza que ocurriria si candidate_rows se expandiera 1:1
    duplicando la misma identidad: canonical_count y recommended_count
    se inflan, match_same_cycle_controls excluye la copia como same_treatment.

    Paso 1: build normal -> 1 fila, recommended_count=1.
    Paso 2: duplicar manualmente la fila con distinto recommendation_id
    para simular que pasaria si `_attach_phase_b` no colapsara.
    Paso 3: ejecutar match_same_cycle_controls sobre la lista duplicada."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:a")
    rec_b = _recommendation(row, recommendation_id="rec:b")

    # --- Paso 1: comportamiento actual (colapsa) ---
    result = build_canonical_selection_ledger(
        "cycle-expand", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    assert result["denominators"]["recommended_count"] == 1
    assert result["denominators"]["canonical_count"] == 1

    # --- Paso 2: fabricar manualmente la situacion "expandida" ---
    # Tomamos la unica candidate_row del resultado y la duplicamos
    # con distinto recommendation_id para simular que pasaria si
    # la colision NO existiera (identity_key es la misma).
    original = copy.deepcopy(result["candidate_rows"][0])
    duplicada = copy.deepcopy(original)
    duplicada["recommendation_id"] = "rec:b"
    duplicada["llm_selected"] = False
    duplicada["decision_source"] = "fallback"

    expanded_rows = [original, duplicada]
    assert len(expanded_rows) == 2

    # --- Paso 2: _denominators REAL sobre la lista expandida ---
    # raw_count=1 porque solo hay 1 identidad de candidato unica real,
    # pero la lista artificial tiene 2 filas con misma identity_key
    deno = _denominators(expanded_rows, raw_count=1, conflicts=0, truncated_count=0)
    assert deno["recommended_count"] == 2, (
        f"Con expansion, recommended_count inflado a {deno['recommended_count']}"
    )
    assert deno["canonical_count"] == 2, (
        f"Con expansion, canonical_count inflado a {deno['canonical_count']}"
    )
    # Contraste: con raw_count=1 pero 2 filas, recommended_count > raw_count
    assert deno["recommended_count"] > (deno["raw_count"] or 0), (
        "recommended_count no deberia exceder raw_count (candidatos unicos)"
    )

    # --- Paso 3: match_same_cycle_controls sobre lista expandida ---
    # La fila original como treatment, la duplicada como candidata
    controls = match_same_cycle_controls(
        expanded_rows[0],  # treatment
        expanded_rows,       # candidates (incluye la duplicada)
    )
    # La duplicada tiene la misma identity_key -> excluida como same_treatment
    excluded_reasons = [e.get("reason", "") for e in controls.get("excluded", [])]
    assert any("same_treatment" in r for r in excluded_reasons), (
        f"Duplicada debe ser excluida como same_treatment: {excluded_reasons}"
    )
    assert controls["status"] == "unavailable"  # sin controles elegibles
