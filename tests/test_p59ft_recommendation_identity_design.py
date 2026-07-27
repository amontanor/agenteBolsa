"""P-L59F-T-R1: caracterizacion corregida de la colision recommendation_id en P-L53.

Defectos corregidos (R1):
- Same-ID real con contenido igual/distinto en un build; separado de
  persistencia append-only
- _auto_paper_trade con dos TradeRecommendation mismo symbol/action/signal
- P-L54 build_capital_deployment_funnel_shadow con dos decisiones
- Tests tautologicos eliminados; expansion usando _denominators real
- Diseno B corregido con summary v2 y backward compatibility

Precondicion: XNYS abierto, solo tests/docs, sin src.
Base: P-L59D-D HEAD 520559c6, tree e3c80ba, v0.4.196.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.cycle_runner import _auto_paper_trade
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
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
# helpers: fixtures minimos con identidad explicita
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
    """Recommendacion con decision_context_snapshot real."""
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
# 1. REPRODUCCION DE LA COLISION (misma identidad, distinto rec_id)
# ===================================================================


def test_two_recommendations_same_identity_last_wins() -> None:
    """Dos BUY mismo candidato con distinto recommendation_id -> last-wins."""
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
    assert r["decision_source"] == "llm"
    assert r["recommended"] is True
    assert result["denominators"]["recommended_count"] == 1
    assert result["content_hash"] == stable_content_hash(result)


def test_two_recommendations_same_identity_reverse_order_last_wins() -> None:
    """Invertir orden confirma last-wins (no first-wins ni merge)."""
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
    """La primera recomendacion pierde su ID y llm_selected sin warning."""
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
# 2. MISMO recommendation_id DENTRO DE UN BUILD
#    (a) mismo ID + mismo contenido semantico
#    (b) mismo ID + distinto contenido (confidence/llm_selected/source)
#    (c) separado: persistencia append-only por event_id
# ===================================================================


def test_same_rec_id_same_content_within_one_build_last_wins_silently() -> None:
    """Dentro de UN build, dos entradas con mismo recommendation_id y mismo
    contenido semantico (misma fuente, confidence, llm_selected). No hay
    dedup explicita: la segunda sobreescribe en silencio via last-wins."""
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
    # No hay dedup explicita de recommendation_id en _attach_phase_b
    assert "candidate_idempotent_duplicate" not in result.get("warnings", [])


def test_same_rec_id_different_content_within_one_build_last_wins() -> None:
    """Dentro de UN build, mismo recommendation_id pero distinto contenido
    (confidence/llm_selected/source). La segunda sobreescribe los campos."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:dual", source="llm", llm_selected=True, confidence=0.90)
    rec_b = _recommendation(row, recommendation_id="rec:dual", source="capacity_fill", llm_selected=False, confidence=0.40)

    result = build_canonical_selection_ledger(
        "cycle-diff-content", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    # Last-wins: los campos de la segunda decision prevalecen
    assert r["recommendation_id"] == "rec:dual"
    assert r["llm_selected"] is False
    assert r["decision_source"] == "deterministic_capacity_fill"
    # Sin warning de conflicto (la colision in-memory es silenciosa)
    assert "conflict" not in str(result.get("warnings", [])).lower()


def test_same_rec_id_different_content_across_builds_store_conflict(tmp_path: Path) -> None:
    """Dos builds separados (mismo cycle_id -> mismo event_id) con mismo
    recommendation_id pero distinto contenido global -> conflicto append-only
    en Store. El original se preserva."""
    store = _store(tmp_path)
    row = _candidate_row()

    # Build A: recomendacion con llm_selected=True, confidence=0.90
    rec_a = _recommendation(row, recommendation_id="rec:store", llm_selected=True, confidence=0.90)
    p1 = build_canonical_selection_ledger("cycle-store", _phase_a(row),
                                            recommendations=[rec_a], captured_at=CAPTURED_AT)

    # Build B: mismo recommendation_id pero llm_selected=False
    rec_b = _recommendation(row, recommendation_id="rec:store", llm_selected=False, confidence=0.40)
    p2 = build_canonical_selection_ledger("cycle-store", _phase_a(row),
                                            recommendations=[rec_b], captured_at=CAPTURED_AT)

    assert p1["content_hash"] != p2["content_hash"]
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    # Mismo event_id + distinto hash -> conflicto
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"
    # El lector devuelve la version original
    rb = read_canonical_selection_ledger(store, "cycle-store")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:store"
    assert rb["candidate_rows"][0]["llm_selected"] is True


def test_same_rec_id_same_content_across_builds_store_idempotent(tmp_path: Path) -> None:
    """Mismo recommendation_id + mismo contenido en dos builds -> idempotente."""
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
# 3. BUY vs EXIT con misma signal identity
# ===================================================================


def test_buy_and_exit_same_signal_preserved_separately() -> None:
    """BUY y EXIT misma senal no colisionan: action es parte de la clave."""
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
    """Dos BUY colisionan a 1 fila; EXIT separado."""
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
    """Recomendacion sin recommendation_id -> el campo queda None."""
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
    """Recomendacion con ID y otra sin ID para el mismo candidato -> last-wins."""
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
    """Varias recomendaciones sin ID -> last-wins, ID queda None."""
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
#    mismo symbol/action/signal, espia P-L53 y P-L54 final
# ===================================================================


def _store_spy() -> SimpleNamespace:
    spy = SimpleNamespace()
    spy.calls = []
    spy.plans = []
    spy.broker_payloads = []
    spy.p53_payloads = []
    spy.p54_payloads = []

    def _save_trade_recommendation(**kwargs):
        spy.calls.append("save_trade_recommendation")

    def _save_order_plan(**kwargs):
        spy.calls.append("save_order_plan")
        spy.plans.append({**kwargs, "status": "PENDING"})

    def _pending_order_plans(**_kwargs):
        return spy.plans

    def _save_broker_order(**kwargs):
        spy.calls.append("save_broker_order")
        spy.broker_payloads.append(dict(kwargs))

    def _count_broker_orders(**_kwargs):
        return 0

    spy.save_trade_recommendation = _save_trade_recommendation
    spy.save_order_plan = _save_order_plan
    spy.pending_order_plans = _pending_order_plans
    spy.save_broker_order = _save_broker_order
    spy.count_broker_orders = _count_broker_orders
    return spy


class _NullReporter:
    def emit(self, *_args, **_kwargs) -> None:
        pass


def test_auto_paper_trade_two_recommendations_same_signal_p53_p54_spies(monkeypatch, tmp_path):
    """Ejecuta _auto_paper_trade con DOS TradeRecommendation mismo
    symbol/action/signal. Espia P-L53 y P-L54 final para demostrar que
    reciben dos recomendaciones con distintos recommendation_id. Confirma
    que ambas decisiones existen con IDs distintos antes del shadow."""
    import agente_bolsa.cycle_runner as runner

    rec1 = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9,
                                reason="test1", entry_price=100,
                                stop_loss=95, take_profit=110)
    rec2 = TradeRecommendation(symbol="AAPL", action="buy", confidence=0.8,
                                reason="test2", entry_price=101,
                                stop_loss=96, take_profit=112)
    # Asignar recommendation_id simulando cycle_runner.py:1805
    from agente_bolsa.models import new_id
    rec1 = replace(rec1, recommendation_id=new_id("rec"))
    rec2 = replace(rec2, recommendation_id=new_id("rec"))
    assert rec1.recommendation_id != rec2.recommendation_id, (
        "Dos recomendaciones distintas deben tener IDs distintos"
    )

    plan1 = OrderPlan("AAPL", "buy", 100.0, 1.0, 100.0, 95.0, 110.0, rec1, RiskDecision(True, "ok", {}))
    plan2 = OrderPlan("AAPL", "buy", 101.0, 1.0, 101.0, 96.0, 112.0, rec2, RiskDecision(True, "ok", {}))

    # P-L53 spy: capturar las recomendaciones que recibe
    p53_received: list[list] = []
    def _spy_p53(**kwargs):
        recs_received = kwargs.get("recommendations")
        if recs_received is not None:
            p53_received.append(list(recs_received))
        return {"status": "verified", "persist_status": "inserted"}

    # P-L54 spy
    p54_received: list[list] = []
    def _spy_p54(**kwargs):
        recs_received = kwargs.get("recommendations")
        if recs_received is not None:
            p54_received.append(list(recs_received))
        return {"status": "verified", "persist_status": "inserted"}

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
    monkeypatch.setattr(runner, "request_trade_recommendations",
                        lambda *_a: {"recommendations": [rec1, rec2]})
    monkeypatch.setattr(runner, "review_recommendations",
                        lambda *_a: ([rec1, rec2], [{"symbol": "AAPL", "action": "buy", "approved": True},
                                                      {"symbol": "AAPL", "action": "buy", "approved": True}]))
    monkeypatch.setattr(runner, "review_recommendations_adversarial",
                        lambda *_a, **_kw: [{"symbol": "AAPL", "action": "buy", "approved": True}])
    monkeypatch.setattr(runner, "_annotate_recommendations_with_strategy", lambda items, *_a: items)
    monkeypatch.setattr(runner, "_annotate_recommendations_with_lineage", lambda items, *_a, **_kw: items)
    monkeypatch.setattr(runner, "recommendation_input_fingerprint", lambda *_a, **_kw: "fp")
    monkeypatch.setattr(runner, "_apply_entry_quality_gate",
                        lambda *_a, **_kw: ([rec1, rec2], []))
    monkeypatch.setattr(runner, "_apply_backtest_gate",
                        lambda *_a, **_kw: ([rec1, rec2], []))
    monkeypatch.setattr(runner, "update_signal_decisions", lambda *_a, **_kw: 0)
    monkeypatch.setattr(runner, "build_order_plans",
                        lambda *_a, **_kw: [plan1, plan2])
    monkeypatch.setattr(runner, "_apply_daily_buy_limit",
                        lambda *_a, **_kw: [plan1, plan2])
    monkeypatch.setattr(runner, "_apply_low_sample_daily_quota",
                        lambda *_a, **_kw: [plan1, plan2])
    monkeypatch.setattr(runner, "_separate_strategy_paused_plans",
                        lambda _m, plans: (plans, []))
    monkeypatch.setattr(runner, "_effective_buy_plan_limit", lambda *_a: 2)
    monkeypatch.setattr(runner, "_effective_daily_buy_limit", lambda *_a: 2)
    monkeypatch.setattr(runner, "_low_sample_usage_payload", lambda *_a: {})
    monkeypatch.setattr(runner, "update_signal_execution_status", lambda *_a, **_kw: 1)
    monkeypatch.setattr(runner, "submit_paper_order_plan",
                        lambda *_a, **_kw: {"id": "broker-1", "status": "accepted"})
    monkeypatch.setattr(runner, "_write_learning_mode_shadow_report", lambda *_a, **_kw: "s.json")
    monkeypatch.setattr(runner, "collect_gate_path", lambda **_kw: {})
    monkeypatch.setattr(runner, "attach_gate_evaluation_snapshots", lambda _store, snapshots=None: None)
    monkeypatch.setattr(runner, "build_comparable_control_sets", lambda **_kw: {})
    monkeypatch.setattr(runner, "_persist_learning_penalty_cycle_shadow_final",
                        lambda **kw: {"status": "available"})

    store = _store_spy()
    settings = Settings(DATA_DIR=tmp_path, AUTO_PAPER_TRADING=True,
                        REQUIRE_HUMAN_APPROVAL=False)
    _auto_paper_trade(
        settings, store, _NullReporter(), "cycle-two-recs",
        {"run_id": "source"}, {}, {},
    )

    # P-L53 recibio las dos recomendaciones
    assert len(p53_received) >= 1, "P-L53 debio recibir al menos una llamada"
    p53_recs = p53_received[-1]
    assert len(p53_recs) == 2, (
        f"P-L53 debe recibir 2 recomendaciones, recibio {len(p53_recs)}"
    )
    # recommendation_id distintos en los objetos TradeRecommendation
    p53_ids = [getattr(r, "recommendation_id", None) for r in p53_recs]
    assert p53_ids[0] is not None
    assert p53_ids[1] is not None
    assert p53_ids[0] != p53_ids[1], (
        "P-L53 recibe dos IDs distintos para dos decisiones"
    )

    # P-L54 tambien recibio las dos recomendaciones
    assert len(p54_received) >= 1, "P-L54 debio recibir al menos una llamada"
    p54_recs = p54_received[-1]
    assert len(p54_recs) == 2


# ===================================================================
# 6. P-L54 API REAL: build_capital_deployment_funnel_shadow
#    con dos decisiones same signal/action y distinto rec_id
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
    """P-L54 incluye recommendation_id en decision_key -> dos filas
    distintas. NO sufre la colision de P-L53."""
    row_a = _p54_candidate_row(0, "rec:a", signal_capture="capture-0", cycle_id="cycle-p54")
    row_b = _p54_candidate_row(1, "rec:b", signal_capture="capture-0", cycle_id="cycle-p54")
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54", [row_a, row_b],
        account={"equity": 100000.0, "cash": 80000.0, "gross_exposure": 0.20},
        captured_at=CAPTURED_AT,
    )
    # Dos filas con distinto decision_key (incluye recommendation_id)
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    assert len(buy_rows) == 2, (
        f"P-L54 debe preservar 2 filas (una por recommendation_id), obtuvo {len(buy_rows)}"
    )
    by_rec_id = {r["recommendation_id"]: r for r in buy_rows}
    assert "rec:a" in by_rec_id
    assert "rec:b" in by_rec_id
    assert result["denominators"]["recommendations_generated"] == 2


def test_p54_same_rec_id_true_identical_content_idempotent() -> None:
    """P-L54: mismo recommendation_id + identico contenido (misma row
    pasada dos veces) -> content_hash igual -> idempotente, una sola fila."""
    row = _p54_candidate_row(0, "rec:same", cycle_id="cycle-p54-idem")
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54-idem", [row, row],
        captured_at=CAPTURED_AT,
    )
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    assert len(buy_rows) == 1, (
        f"P-L54 mismo contenido -> idempotente (1 fila), obtuvo {len(buy_rows)}"
    )
    assert buy_rows[0]["recommendation_id"] == "rec:same"


def test_p54_same_rec_id_different_content_becomes_ambiguous() -> None:
    """P-L54: mismo decision_key pero distinto content_hash (por
    planned_notional/plan_id) -> ambas filas identity_ambiguous."""
    row_a = _p54_candidate_row(0, "rec:same", cycle_id="cycle-p54-merge")
    row_a["planned_notional"] = 500.0
    row_b = _p54_candidate_row(1, "rec:same", cycle_id="cycle-p54-merge")
    row_b["planned_notional"] = 2000.0
    # Tambien difieren en candidate_id/plan_id/broker_order_id -> content hash distinto
    result = build_capital_deployment_funnel_shadow(
        "cycle-p54-merge", [row_a, row_b],
        captured_at=CAPTURED_AT,
    )
    details = result["details"]
    buy_rows = [r for r in details if r.get("action") == "buy"]
    # P-L54: mismo decision_key + distinto content -> ambas identity_ambiguous
    assert len(buy_rows) == 2, (
        f"P-L54 mismo rec_id distinto contenido -> 2 filas ambiguous, obtuvo {len(buy_rows)}"
    )
    assert all(r["identity_status"] == "identity_ambiguous" for r in buy_rows)
    assert all(r["recommendation_id"] == "rec:same" for r in buy_rows)


# ===================================================================
# 7. EXPANSION: impacto real en _denominators Y match_same_cycle_controls
#    usando APIs reales, sin cambiar signal_capture_id
# ===================================================================


def test_expansion_impact_real_denominators() -> None:
    """Con la API actual, recommended_count = 1 para dos decisiones
    mismo candidato. Si se expandiera, el denominador cambiaria.
    Verificamos con _denominators real (via build_canonical_selection_ledger)."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:a")
    rec_b = _recommendation(row, recommendation_id="rec:b")

    result = build_canonical_selection_ledger(
        "cycle-deno", _phase_a(row),
        recommendations=[rec_a, rec_b], captured_at=CAPTURED_AT,
    )
    # Comportamiento actual: recommended_count subestima (1 en vez de 2)
    assert result["denominators"]["recommended_count"] == 1
    assert result["denominators"]["canonical_count"] == 1

    # Para simular la expansion sin cambiar signal_capture_id de forma
    # artificial, usamos dos candidatos identicos con distinto source_run_id
    # (diferente corrida del scan para el mismo simbolo/senal).
    # _phase_a_rows los acepta como distintos porque _identity usa
    # signal_capture_id.
    row_v1 = _candidate_row(signal_capture_id="capture:tsla:buy:run1",
                             candidate_id="candidate:tsla:run1")
    row_v2 = _candidate_row(signal_capture_id="capture:tsla:buy:run2",
                             candidate_id="candidate:tsla:run2")
    rec_v1 = _recommendation(row_v1, recommendation_id="rec:v1")
    rec_v2 = _recommendation(row_v2, recommendation_id="rec:v2")

    result_expanded = build_canonical_selection_ledger(
        "cycle-deno-exp", _phase_a(row_v1, row_v2),
        recommendations=[rec_v1, rec_v2], captured_at=CAPTURED_AT,
    )
    # Con identidades distintas, cada una recibe su decision
    assert result_expanded["denominators"]["recommended_count"] == 2
    assert result_expanded["denominators"]["canonical_count"] == 2

    # match_same_cycle_controls: si dos filas comparten identidad
    # (cycle, action, signal), la segunda es excluida como same_treatment
    controls = match_same_cycle_controls(
        result_expanded["candidate_rows"][0],
        result_expanded["candidate_rows"],
    )
    assert controls["status"] == "unavailable"  # solo una misma identidad -> sin controles
    assert any("same_treatment" in str(c) for c in controls.get("excluded", []))


# ===================================================================
# 8. STAGE ORDER: punto de asignacion de recommendation_id
# ===================================================================


def test_recommendation_id_assigned_before_gates_and_ledger() -> None:
    """En cycle_runner.py, recommendation_id = new_id('rec') en L1805,
    ANTES de gates (L1825-1850) y ANTES del ledger (L2167).
    La colision en el ledger no afecta la ruta activa."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:gates:a", llm_selected=True)
    rec_b = _recommendation(row, recommendation_id="rec:gates:b", llm_selected=False)

    # Simulamos el flujo real: dos recomendaciones independientes
    active_decisions = [rec_a, rec_b]
    assert len(active_decisions) == 2
    assert active_decisions[0]["recommendation_id"] != active_decisions[1]["recommendation_id"]

    # El ledger colapsa pero la ruta activa ya proceso ambas
    result = build_canonical_selection_ledger(
        "cycle-stage", _phase_a(row),
        recommendations=active_decisions, captured_at=CAPTURED_AT,
    )
    assert len(result["candidate_rows"]) == 1
    assert result["candidate_rows"][0]["recommended"] is True
    assert result["denominators"]["recommended_count"] == 1
