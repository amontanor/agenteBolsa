"""P-L59B-T-R2: caracterizacion adversarial corregida de llm_selected y controles.

Usa exclusivamente APIs reales del candidato P-L60R1 (v0.4.195):
  - build_canonical_selection_ledger / persist / read (P-L53 shadow)
  - build_comparable_control_sets / validate (P-L31B, desplegado en prod 0.4.185)
  - match_same_cycle_controls (P-L53)
  - TradeRecommendation, OrderPlan, RiskDecision (modelos reales)
  - Store con tmp_path, _env_file=None

No duplica constantes ni logica de decision. Sin red, broker, LLM, SQLite productiva.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    match_same_cycle_controls,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
)
from agente_bolsa.tools.comparable_controls import (
    PRIMARY_REASONS,
    build_comparable_control_sets,
    build_unavailable_control_set,
    candidate_id_for,
    validate_comparable_control_set,
)
from agente_bolsa.tools.decision_context import build_decision_context_snapshot

CAPTURED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
SCHEMA_VERSION = "p-l31b.comparable-control.v2"


# ---------------------------------------------------------------------------
# Fixture builders (datos explicitos, sin logica derivada)
# ---------------------------------------------------------------------------

def _cand(index: int, **overrides: Any) -> dict[str, Any]:
    """Fixture de candidata con datos explicitos, sin logica de decision."""
    symbol = overrides.pop("symbol", f"SYM{index:03d}")
    action = "exit" if str(overrides.get("action", "buy")).lower() in {"exit", "sell"} else "buy"
    signal_at = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    base: dict[str, Any] = {
        "cycle_id": "cycle-A",
        "session_date": "2026-07-26",
        "signal_capture_id": f"capture:cycle-A:{action}:{symbol}:{index}",
        "signal_id": f"signal:cycle-A:{action}:{symbol}",
        "candidate_id": f"candidate:cycle-A:{index}",
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": "builtin_breakout",
        "setup": "continuation",
        "score_universe": "domain-A",
        "score": 10.0 + index / 100.0,
        "selection_score": 0.2 - index / 10000.0,
        "score_rank": index % 10 + 1,
        "selection_rank": index % 20 + 1,
        "data_quality": "good",
        "freshness": "fresh",
        "price_basis": "close_unadjusted",
        "signal_at": signal_at.isoformat(),
        "decision_at": (signal_at + timedelta(seconds=10)).isoformat(),
        "eligible_at_selection": True,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": False,
    }
    base.update(overrides)
    return base


def _phase(rows: list[dict[str, Any]], *, selected_indices: list[int] | None = None) -> dict[str, Any]:
    selected = selected_indices if selected_indices is not None else list(range(min(20, len(rows))))
    return {
        "all_candidates": rows,
        "selected_candidates": [rows[i] for i in selected if i < len(rows)],
    }


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "signal_id": row["signal_id"],
        "candidate_id": row["candidate_id"],
    }


def _rec(row: dict[str, Any], *, source: str, llm_considered: bool,
         rec_id: str | None = None) -> dict[str, Any]:
    """Recommendation fixture. llm_considered es dato explicito obligatorio, sin derivacion."""
    rec_id = rec_id or f"rec:{row['symbol']}"
    return {
        "cycle_id": row.get("cycle_id", "cycle-A"),
        "action": row["action"],
        "recommendation_id": rec_id,
        "source": source,
        "decision_origin": source,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": {
            "llm_considered": llm_considered,
            "gate_frontier": row["gate_frontier"],
        },
    }


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    s.ensure_schema()
    return s


# ===================================================================
# (A) llm_selected: proxy de source, brecha documentada
# ===================================================================

def test_llm_selected_true_when_source_is_llm():
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="llm", llm_considered=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is True
    assert result["candidate_rows"][0]["decision_source"] == "llm"


def test_llm_selected_false_when_source_is_capacity_fill():
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="capacity_fill", llm_considered=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is False


def test_llm_selected_false_when_source_is_fallback():
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="fallback", llm_considered=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is False


def test_llm_selected_none_when_no_recommendation():
    c = _cand(0, selected_for_llm=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is None


def test_llm_selected_is_proxy_not_independent():
    """BREACH: llm_selected se deriva de decision_source (linea 383).

    No existe booleano independiente sellado en etapa de decision.
    Capacity-fill y fallback colapsan en False.
    """
    c_llm = _cand(0, symbol="LLM_DIRECT", selected_for_llm=True)
    c_cap = _cand(1, symbol="CAPACITY", selected_for_llm=True)
    c_fb = _cand(2, symbol="FALLBACK", selected_for_llm=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c_llm, c_cap, c_fb]),
        recommendations=[
            _rec(c_llm, source="llm", llm_considered=True),
            _rec(c_cap, source="capacity_fill", llm_considered=False),
            _rec(c_fb, source="fallback", llm_considered=False),
        ], captured_at=CAPTURED_AT,
    )
    by_sym = {r["symbol"]: r for r in result["candidate_rows"]}
    assert by_sym["LLM_DIRECT"]["llm_selected"] is True
    assert by_sym["CAPACITY"]["llm_selected"] is False
    assert by_sym["FALLBACK"]["llm_selected"] is False
    # colapsan semanticamente distintos
    assert by_sym["CAPACITY"]["llm_selected"] == by_sym["FALLBACK"]["llm_selected"]


def test_source_unknown_maps_to_other_breach():
    """Source desconocida -> 'other' -> llm_selected=False (deberia ser None)."""
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="bogus_unknown_source", llm_considered=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["decision_source"] == "other"
    assert row["llm_selected"] is False  # BRECHA


# ===================================================================
# (B) Dos recs misma senal, distinto rec_id -> colision P-L53
# ===================================================================

def test_two_recommendations_same_signal_collision():
    """P-L53: identidad primaria no incluye recommendation_id -> colision.

    Esto es un hecho del codigo P-L53. P-L54B maneja dominios separados
    de decision_identity; si corrige o no la colision en su propio
    ledger no esta demostrado aqui.
    """
    c = _cand(0, action="buy", symbol="AAPL", selected_for_llm=True)
    r1 = {**c, "recommendation_id": "rec-aaa-111", "source": "llm",
          "decision_context_snapshot": {"llm_considered": True, "gate_frontier": "entry_eligibility_v1"},
          "decision_lineage": _lineage(c)}
    r2 = {**c, "recommendation_id": "rec-bbb-222", "source": "capacity_fill",
          "decision_context_snapshot": {"llm_considered": False, "gate_frontier": "entry_eligibility_v1"},
          "decision_lineage": _lineage(c)}
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r1, r2], captured_at=CAPTURED_AT,
    )
    assert len(result["candidate_rows"]) == 1
    assert result["candidate_rows"][0]["recommendation_id"] == "rec-bbb-222"


# ===================================================================
# (C) BUY vs EXIT, cross-cycle, identidad missing
# ===================================================================

def test_buy_and_exit_separate_identities():
    c_buy = _cand(0, action="buy", symbol="AAPL")
    c_exit = _cand(1, action="exit", symbol="AAPL",
                   signal_id=c_buy["signal_id"].replace("buy", "exit"))
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c_buy, c_exit]), captured_at=CAPTURED_AT,
    )
    actions = {r["action"] for r in result["candidate_rows"]}
    assert actions == {"buy", "exit"}


def test_cross_cycle_same_symbol_different_cycle_ids():
    c_a = _cand(0, cycle_id="cycle-A", symbol="AAPL")
    c_b = _cand(1, cycle_id="cycle-B", symbol="AAPL")
    result = build_canonical_selection_ledger(
        "cycle-A", {"all_candidates": [c_a, c_b]}, captured_at=CAPTURED_AT,
    )
    signal_ids = {r["signal_id"] for r in result["candidate_rows"]}
    assert c_a["signal_id"] in signal_ids
    assert c_b["signal_id"] in signal_ids


def test_identity_missing_signal_is_unavailable():
    c = _cand(0)
    c.pop("signal_id", None)
    c.pop("signal_capture_id", None)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["identity_status"] == "identity_unavailable"


def test_candidate_id_alone_not_identity():
    c = {"candidate_id": "cand:123", "action": "buy", "symbol": "XXX"}
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["identity_status"] == "identity_unavailable"


# ===================================================================
# (D) Persistencia real Store
# ===================================================================

def test_persist_and_read_ledger(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="llm", llm_considered=True)
    p = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p)["status"] == "idempotent"
    rb = read_canonical_selection_ledger(store, "cycle-A")
    assert rb["status"] == "verified"
    assert rb["candidate_rows"][0]["llm_selected"] is True


def test_persist_conflict(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    p1 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm", llm_considered=True)], captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="fallback", llm_considered=False)], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"


def test_content_hash_different_for_different_content():
    c = _cand(0, selected_for_llm=True)
    p1 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm", llm_considered=True)], captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="fallback", llm_considered=False)], captured_at=CAPTURED_AT,
    )
    assert p1["content_hash"] != p2["content_hash"]


def test_read_unwritten_returns_collecting(tmp_path: Path):
    result = read_canonical_selection_ledger(_store(tmp_path), "cycle-nonexistent")
    assert result["status"] == "collecting"


def test_build_ledger_does_not_mutate_inputs():
    c = _cand(0, selected_for_llm=True)
    orig = copy.deepcopy(c)
    build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm", llm_considered=True)], captured_at=CAPTURED_AT,
    )
    assert c == orig


# ===================================================================
# (E) match_same_cycle_controls con exclusion exacta (defecto 1 corregido)
# ===================================================================

def test_match_finds_eligible_alternatives():
    rows = [
        _cand(0, selected_for_llm=True, symbol="TREAT"),
        _cand(1, selected_for_llm=False, symbol="CTRL1"),
        _cand(2, selected_for_llm=False, symbol="CTRL2"),
    ]
    result = build_canonical_selection_ledger(
        "cycle-A", _phase(rows, selected_indices=[0]),
        recommendations=[], captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    assert matched["status"] == "verified"
    assert len(matched["controls"]) >= 1
    for ctrl in matched["controls"]:
        assert ctrl["selected_for_llm"] is False


def test_match_excludes_recommended_with_exact_reason():
    """Defecto 1 corregido: OKCTRL es realmente recomendada y queda excluida.

    Se construye un ledger donde OKCTRL recibe una recomendacion real.
    La API match_same_cycle_controls debe excluirla con razon exacta.
    """
    rows = [
        _cand(0, selected_for_llm=True, symbol="TREAT"),
        _cand(1, selected_for_llm=False, symbol="OKCTRL"),
    ]
    result = build_canonical_selection_ledger(
        "cycle-A", _phase(rows, selected_indices=[0]),
        recommendations=[_rec(rows[1], source="llm", llm_considered=True, rec_id="rec:okctrl")],
        captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    # Verificar que OKCTRL esta recomendada en el ledger
    okctrl = next(r for r in result["candidate_rows"] if r["symbol"] == "OKCTRL")
    assert okctrl["recommended"] is True

    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    excluded = matched.get("excluded", [])
    # OKCTRL debe estar excluida con razon exacta
    okctrl_exc = [e for e in excluded if "OKCTRL" in (e.get("identity_key") or "")]
    assert len(okctrl_exc) >= 1
    assert any(e["reason"] == "postdecision_recommended_not_control" for e in okctrl_exc)
    # Y no debe aparecer en controls
    ctrl_symbols = {c["symbol"] for c in matched["controls"]}
    assert "OKCTRL" not in ctrl_symbols


def test_match_excludes_cross_cycle():
    c_a = _cand(0, selected_for_llm=True, cycle_id="cycle-A", symbol="TREAT")
    c_b = _cand(1, selected_for_llm=False, cycle_id="cycle-B",
                symbol="OTHER", signal_id="signal:cycle-B:buy:OTHER")
    result = build_canonical_selection_ledger(
        "cycle-A", {"all_candidates": [c_a, c_b]},
        recommendations=[], captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    excluded_reasons = {e["reason"] for e in matched.get("excluded", [])}
    assert "cycle_mismatch" in excluded_reasons or len(matched["controls"]) == 0


# ===================================================================
# (F) build_comparable_control_sets: escenarios funcionales reales (defecto 2)
# ===================================================================

def _market(cycle: str = "cycle-1") -> dict[str, object]:
    return {
        "run_id": cycle, "as_of": "2026-07-27T09:00:00+00:00",
        "market_regime": "neutral", "volatility_regime": "normal",
        "risk_posture": "balanced", "data_quality": {"status": "GOOD"},
    }


def _trec(symbol: str, rank: int, *, cycle: str = "cycle-1") -> TradeRecommendation:
    """TradeRecommendation real con decision_context_snapshot."""
    signal_id = f"sig:{cycle}:{symbol}"
    lineage = {
        "signal_id": signal_id,
        "candidate_id": candidate_id_for(cycle, signal_id, "run-1"),
        "cycle_id": cycle, "source_run_id": "run-1", "candidate_rank": rank,
    }
    rec = TradeRecommendation(
        symbol=symbol, action="buy", confidence=0.9, reason="fixture",
        entry_price=100.0 + rank, stop_loss=95.0 + rank, take_profit=115.0 + rank,
        decision_lineage=lineage, source="llm",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id=cycle, source_run_id="run-1",
        market_state=_market(cycle),
        captured_at=CAPTURED_AT,
        signal_id=signal_id, signal_link_status="verified",
        identity_key=f"{cycle}|{symbol}",
    )
    return replace(rec, decision_context_snapshot=snapshot)


def _oplan(rec: TradeRecommendation) -> OrderPlan:
    return OrderPlan(
        symbol=rec.symbol, side="buy", notional=100.0, qty=1.0,
        entry_price=rec.entry_price or 0.0,
        stop_loss=rec.stop_loss or 0.0,
        take_profit=rec.take_profit or 0.0,
        recommendation=rec, risk_decision=RiskDecision(True, "ok", {}),
    )


def _gates(*recs: TradeRecommendation) -> list[dict[str, object]]:
    return [{"symbol": r.symbol, "action": r.action, "approved": True,
             "candidate_id": r.decision_lineage.get("candidate_id"),
             "signal_id": r.decision_lineage.get("signal_id")} for r in recs]


def _csets(treatment: TradeRecommendation, controls: list[TradeRecommendation],
           rejected: list[dict[str, object]], *, cycle: str = "cycle-1"):
    recs = [treatment, *controls]
    gates = _gates(*recs)
    return build_comparable_control_sets(
        cycle_id=cycle, recommendations=recs, plans=[_oplan(treatment)],
        rejected_order_plans=rejected, all_recommendations=recs,
        deterministic_review=gates, adversarial_review=gates,
        entry_quality_gate=gates, backtest_gate=gates,
        strategy_pause_gate=gates, geometry_gate=gates,
        risk_eligibility_gate=gates, duplicate_symbol_gate=gates,
        already_held_gate=gates, low_sample_gate=gates,
    )


def test_capacity_limit_produces_verified_control():
    """Escenario real: control excluido por capacity_limit con API real."""
    treatment = _trec("TREAT", 1)
    ctrl = _trec("CTRL", 2)
    rejected = [{"symbol": "CTRL", "reason": "max_orders_per_cycle_reached",
                 "candidate_id": ctrl.decision_lineage.get("candidate_id")}]
    sets = _csets(treatment, [ctrl], rejected)
    assert len(sets) == 1
    cset = next(iter(sets.values()))
    assert cset["schema_version"] == SCHEMA_VERSION
    assert cset["status"] == "verified"
    assert cset["selection_source"] == "actual_final_plans"
    assert cset["treatment"]["signal_id"] == treatment.decision_lineage["signal_id"]
    assert len(cset["controls"]) == 1
    assert cset["controls"][0]["non_execution_reason"] == "capacity_limit"
    assert cset["controls"][0]["gate_eligibility"] == "verified"
    validate_comparable_control_set(cset)


def test_lower_rank_produces_verified_control():
    """Escenario real: control excluido por lower_rank con API real."""
    treatment = _trec("TREAT", 1)
    ctrl = _trec("CTRL", 2)
    # lower_rank es razon directa en NON_EXECUTION_REASONS
    rejected = [{"symbol": "CTRL", "reason": "lower_rank",
                 "candidate_id": ctrl.decision_lineage.get("candidate_id")}]
    sets = _csets(treatment, [ctrl], rejected)
    assert len(sets) == 1
    cset = next(iter(sets.values()))
    assert cset["status"] == "verified"
    assert len(cset["controls"]) == 1
    assert cset["controls"][0]["non_execution_reason"] == "lower_rank"
    assert cset["controls"][0]["non_execution_reason"] in PRIMARY_REASONS
    validate_comparable_control_set(cset)


def test_gate_blocked_excluded_from_primary_controls():
    """Control con gate bloqueado NO es control primario.

    Cuando todos los candidatos rechazados tienen gates bloqueados,
    el control set queda sin controles primarios validos.
    """
    treatment = _trec("TREAT", 1)
    ctrl = _trec("CTRL", 2)
    rejected = [{"symbol": "CTRL", "reason": "max_orders_per_cycle_reached",
                 "candidate_id": ctrl.decision_lineage.get("candidate_id")}]
    gates = [
        {"symbol": "TREAT", "action": "buy", "approved": True,
         "candidate_id": treatment.decision_lineage.get("candidate_id"),
         "signal_id": treatment.decision_lineage.get("signal_id")},
        {"symbol": "CTRL", "action": "buy", "approved": False,  # bloqueado
         "candidate_id": ctrl.decision_lineage.get("candidate_id"),
         "signal_id": ctrl.decision_lineage.get("signal_id")},
    ]
    sets = build_comparable_control_sets(
        cycle_id="cycle-1", recommendations=[treatment, ctrl],
        plans=[_oplan(treatment)], rejected_order_plans=rejected,
        all_recommendations=[treatment, ctrl],
        deterministic_review=gates, adversarial_review=gates,
        entry_quality_gate=gates, backtest_gate=gates,
        strategy_pause_gate=gates, geometry_gate=gates,
        risk_eligibility_gate=gates, duplicate_symbol_gate=gates,
        already_held_gate=gates, low_sample_gate=gates,
    )
    cset = next(iter(sets.values()))
    # Cuando el unico candidato rechazado tiene gates bloqueados,
    # no hay controles primarios -> blocked_candidates recibe el bloqueado
    assert len(cset["controls"]) == 0
    assert len(cset["blocked_candidates"]) >= 1
    assert cset["blocked_candidates"][0]["blocked_reason"] == "gate_blocked"


def test_cross_cycle_control_excluded():
    """Control de otro ciclo no es control primario."""
    treatment = _trec("TREAT", 1, cycle="cycle-A")
    ctrl = _trec("CTRL", 2, cycle="cycle-B")
    rejected = [{"symbol": "CTRL", "reason": "max_orders_per_cycle_reached",
                 "candidate_id": ctrl.decision_lineage.get("candidate_id")}]
    sets = _csets(treatment, [ctrl], rejected, cycle="cycle-A")
    cset = next(iter(sets.values()))
    # Sin controles (cross-cycle no es same-cycle)
    assert len(cset["controls"]) == 0


def test_validate_rejects_invalid_schema():
    with pytest.raises(ValueError, match="schema_version"):
        validate_comparable_control_set({"schema_version": "wrong"})


def test_validate_rejects_post_decision_fields():
    cset = build_unavailable_control_set(reason="test", cycle_id="cycle-A")
    cset["treatment"] = dict(cset.get("treatment", {}))
    cset["treatment"]["return_5d"] = 0.05
    with pytest.raises(ValueError, match="post_decision"):
        validate_comparable_control_set(cset)


# ===================================================================
# (G) Stage order: verificado en test de integracion real
# ===================================================================
# El orden ejecutable real esta demostrado en
#   tests/test_market_cycle_timing_integration.py::
#   test_stage_order_full_flow_with_pl53_pl54_spies
# que ejecuta _auto_paper_trade con _patch_trading_flow y espia:
#   build_order_plans -> daily_limit -> low_sample -> strategy_pause
#   -> comparable_control_capture (P-L31B, linea 1965)
#   -> learning_penalty_shadow_final
#   -> selection_ledger_final (P-L53, linea 2255)
#   -> capital_funnel_final (P-L54B, linea 2266)
# No se duplica aqui.


# ===================================================================
# (H) Paridad y dimensiones
# ===================================================================

def test_selected_for_llm_and_llm_selected_independent():
    c = _cand(0, selected_for_llm=True)
    r = _rec(c, source="deterministic_capacity_fill", llm_considered=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["selected_for_llm"] is True
    assert row["llm_selected"] is False


def test_predecision_fields_exclude_outcomes():
    c = _cand(0)
    r = _rec(c, source="llm", llm_considered=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    forbidden = {"return_1d", "return_3d", "return_5d", "return_10d",
                 "fill_price", "fill_qty", "pnl", "mfe", "mae", "first_hit"}
    for f in forbidden:
        assert f not in row
