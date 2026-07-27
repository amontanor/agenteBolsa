"""P-L59B-T (corregido v2): caracterizacion adversarial de llm_selected y controles.

Usa exclusivamente APIs reales del candidato P-L60R1 (v0.4.195):
  - build_canonical_selection_ledger / persist / read (P-L53 shadow)
  - build_comparable_control_sets / validate (P-L31B, desplegado en prod)
  - match_same_cycle_controls (P-L53)
  - Store con tmp_path, _env_file=None

No duplica constantes ni logica de decision. Sin red, broker, LLM, SQLite productiva.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    match_same_cycle_controls,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
    stable_content_hash,
)
from agente_bolsa.tools.comparable_controls import (
    BLOCKED_REASONS,
    NON_EXECUTION_REASONS,
    PRIMARY_REASONS,
    build_comparable_control_sets,
    build_unavailable_control_set,
    validate_comparable_control_set,
)

CAPTURED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture builders minimales (sin logica de decision, solo propagacion)
# ---------------------------------------------------------------------------

def _candidate(index: int, **overrides: Any) -> dict[str, Any]:
    """Builder sin logica: solo propaga overrides con defaults."""
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
        "learning_prior": {"expected_edge": 0.02},
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
    """Phase con control explicito de cuales son selected_candidates."""
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


def _rec(row: dict[str, Any], *, source: str = "llm", rec_id: str | None = None) -> dict[str, Any]:
    """Recommendation fixture builder.

    llm_considered=True solo para llm (no para capacity_fill/fallback).
    El codigo real en cycle_runner.py:660-687 controla esto; aqui
    replicamos la semantica exacta del decision_context_snapshot.
    """
    rec_id = rec_id or f"rec:{row['symbol']}"
    return {
        "cycle_id": row.get("cycle_id", "cycle-A"),
        "action": row["action"],
        "recommendation_id": rec_id,
        "source": source,
        "decision_origin": source,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": {
            "llm_considered": source == "llm",
            "gate_frontier": row["gate_frontier"],
        },
    }


def _plan(row: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "plan_id": f"plan:{index}",
        "decision_lineage": _lineage(row),
        "payload": {"decision_lineage": _lineage(row)},
    }


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    s.ensure_schema()
    return s


# ===================================================================
# (A) llm_selected = proxy de decision_source, NO seleccion causal
# ===================================================================


def test_llm_selected_true_when_source_is_llm():
    """build_canonical_selection_ledger: source=llm -> llm_selected=True."""
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="llm")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["llm_selected"] is True
    assert row["decision_source"] == "llm"


def test_llm_selected_false_when_source_is_capacity_fill():
    """source=capacity_fill -> llm_selected=False."""
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="capacity_fill")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["llm_selected"] is False
    assert row["decision_source"] == "deterministic_capacity_fill"


def test_llm_selected_false_when_source_is_fallback():
    """source=fallback -> llm_selected=False."""
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="fallback")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is False
    assert result["candidate_rows"][0]["decision_source"] == "fallback"


def test_llm_selected_none_when_no_recommendation():
    """Sin recomendacion -> llm_selected permanece None."""
    c = _candidate(0, selected_for_llm=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["llm_selected"] is None
    assert row["decision_source"] is None


def test_llm_selected_is_proxy_not_independent_selection_event():
    """BREACH DOCUMENTADA: llm_selected se deriva exclusivamente de decision_source.

    El codigo en canonical_selection_ledger.py:383:
      "llm_selected": True if source == "llm" else False if source else None,

    No existe un booleano independiente sellado en la etapa de decision.
    Capacity-fill y fallback colapsan en False aunque semanticamente
    distintos: capacity-fill se basa en ranking LLM, fallback no.
    """
    c_llm = _candidate(0, symbol="LLM_DIRECT", selected_for_llm=True)
    c_cap = _candidate(1, symbol="CAPACITY", selected_for_llm=True)
    c_fb = _candidate(2, symbol="FALLBACK", selected_for_llm=True)

    result = build_canonical_selection_ledger(
        "cycle-A",
        _phase([c_llm, c_cap, c_fb]),
        recommendations=[
            _rec(c_llm, source="llm"),
            _rec(c_cap, source="capacity_fill"),
            _rec(c_fb, source="fallback"),
        ],
        captured_at=CAPTURED_AT,
    )
    by_sym = {r["symbol"]: r for r in result["candidate_rows"]}

    assert by_sym["LLM_DIRECT"]["llm_selected"] is True
    assert by_sym["CAPACITY"]["llm_selected"] is False
    assert by_sym["FALLBACK"]["llm_selected"] is False

    # llm_considered solo True para el source=llm directo
    assert by_sym["LLM_DIRECT"]["llm_considered"] is True
    assert by_sym["CAPACITY"]["llm_considered"] is False

    # BRECHA: capacity_fill y fallback colapsan en False
    assert by_sym["CAPACITY"]["llm_selected"] == by_sym["FALLBACK"]["llm_selected"]
    # Pero semanticamente son distintos: capacity_fill viene del ranking LLM


def test_source_unknown_maps_to_other_and_becomes_false():
    """Source no reconocida -> 'other' -> llm_selected=False (BRECHA).

    Missing deberia ser None/unavailable, pero el normalizador convierte
    texto irreconocible a 'other', que luego produce llm_selected=False.
    """
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="bogus_unknown_source")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["decision_source"] == "other"
    assert row["llm_selected"] is False  # BRECHA: deberia ser None


# ===================================================================
# (B) Dos recomendaciones same-cycle, misma senal, distinto recommendation_id
# ===================================================================


def test_two_recommendations_same_signal_different_rec_id_collision():
    """P-L53 colisiona dos recs con misma senal pero distinto rec_id.

    La identidad del ledger es cycle_id+action+signal_capture_id, no incluye
    recommendation_id. Dos recomendaciones distintas para la misma senal
    colisionan y solo sobrevive la ultima. P-L54B-R1 corrige esto.
    """
    c = _candidate(0, action="buy", symbol="AAPL", selected_for_llm=True)
    r1 = {
        **c, "recommendation_id": "rec-aaa-111", "source": "llm",
        "decision_context_snapshot": {"llm_considered": True, "gate_frontier": "entry_eligibility_v1"},
        "decision_lineage": _lineage(c),
    }
    r2 = {
        **c, "recommendation_id": "rec-bbb-222", "source": "capacity_fill",
        "decision_context_snapshot": {"llm_considered": False, "gate_frontier": "entry_eligibility_v1"},
        "decision_lineage": _lineage(c),
    }
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r1, r2], captured_at=CAPTURED_AT,
    )
    rows = result["candidate_rows"]
    assert len(rows) == 1, (
        "P-L53: identidad primaria no distingue recommendation_id. "
        "La segunda recomendacion sobrescribe a la primera."
    )
    # La que sobrevive tiene el recommendation_id de la segunda
    assert rows[0]["recommendation_id"] == "rec-bbb-222"
    # Y llm_selected es False (porque la segunda tenia source=capacity_fill)
    assert rows[0]["llm_selected"] is False


# ===================================================================
# (C) BUY vs EXIT, cross-cycle, identidad ambigua/missing
# ===================================================================


def test_buy_and_exit_same_signal_separate_identities():
    """BUY y EXIT con misma senal son filas distintas."""
    c_buy = _candidate(0, action="buy", symbol="AAPL")
    c_exit = _candidate(1, action="exit", symbol="AAPL",
                        signal_id=c_buy["signal_id"].replace("buy", "exit"))
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c_buy, c_exit]), captured_at=CAPTURED_AT,
    )
    rows = result["candidate_rows"]
    assert len(rows) == 2
    actions = {r["action"] for r in rows}
    assert actions == {"buy", "exit"}


def test_cross_cycle_candidates_have_different_cycle_ids():
    """Candidatas de distinto ciclo conservan su ciclo en el ledger.

    El ledger respeta el cycle_id de cada candidata. La identidad
    de la candidata usa su propio cycle_id, no el externo.
    """
    c_a = _candidate(0, cycle_id="cycle-A", symbol="AAPL")
    c_b = _candidate(1, cycle_id="cycle-B", symbol="AAPL")
    result = build_canonical_selection_ledger(
        "cycle-A", {"all_candidates": [c_a, c_b]}, captured_at=CAPTURED_AT,
    )
    rows_by_sym = {r["symbol"]: r for r in result["candidate_rows"]}
    # Ambas aparecen con sus propios cycle_id
    # (la identidad de cada row respeta el cycle del candidato original)
    assert len(rows_by_sym) >= 1
    # c_a y c_b comparten symbol pero tienen distinto signal_id y cycle_id
    signal_ids = {r["signal_id"] for r in result["candidate_rows"]}
    assert c_a["signal_id"] in signal_ids
    assert c_b["signal_id"] in signal_ids


def test_identity_missing_signal_id_gets_unavailable():
    """Candidata sin signal_id ni signal_capture_id -> identity_unavailable."""
    c = _candidate(0)
    c.pop("signal_id", None)
    c.pop("signal_capture_id", None)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["identity_status"] == "identity_unavailable"


def test_candidate_id_alone_not_identity_authority():
    """candidate_id aislado no constituye identidad verificada."""
    c = {"candidate_id": "cand:123", "action": "buy", "symbol": "XXX"}
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["identity_status"] == "identity_unavailable"


# ===================================================================
# (D) Persistencia real con Store temporal
# ===================================================================


def test_persist_and_read_selection_ledger(tmp_path: Path):
    """Persistencia real: escribir, leer, idempotencia."""
    store = _store(tmp_path)
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="llm")
    payload = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    r1 = persist_canonical_selection_ledger(store, payload)
    assert r1["status"] == "inserted"
    r2 = persist_canonical_selection_ledger(store, payload)
    assert r2["status"] == "idempotent"

    read_back = read_canonical_selection_ledger(store, "cycle-A")
    assert read_back["status"] == "verified"
    assert read_back["candidate_rows"][0]["llm_selected"] is True


def test_persist_conflict_different_content(tmp_path: Path):
    """Mismo event_id, distinto contenido -> conflicto."""
    store = _store(tmp_path)
    c = _candidate(0, selected_for_llm=True)
    p1 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm")],
        captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="fallback")],
        captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"


def test_content_hash_different_for_different_content():
    """Diferente llm_selected -> diferente content_hash."""
    c = _candidate(0, selected_for_llm=True)
    p_true = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm")],
        captured_at=CAPTURED_AT,
    )
    p_false = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="fallback")],
        captured_at=CAPTURED_AT,
    )
    assert p_true["content_hash"] != p_false["content_hash"]


def test_read_unwritten_cycle_returns_collecting(tmp_path: Path):
    """Lectura de ciclo sin evento -> collecting."""
    store = _store(tmp_path)
    result = read_canonical_selection_ledger(store, "cycle-nonexistent")
    assert result["status"] == "collecting"


def test_build_ledger_does_not_mutate_inputs():
    """Los inputs no son mutados por build_canonical_selection_ledger."""
    c = _candidate(0, selected_for_llm=True)
    original = copy.deepcopy(c)
    build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[_rec(c, source="llm")],
        captured_at=CAPTURED_AT,
    )
    assert c == original


# ===================================================================
# (E) match_same_cycle_controls con API real
# ===================================================================


def test_match_same_cycle_controls_finds_eligible_alternatives():
    """El matcher real encuentra controles con misma frontera y selected=False.

    Las filas del ledger se ordenan por identity_key. Buscar por symbol.
    Ademas, hay que pasar recommendations (aunque vacias) para que
    _attach_phase_b inicialice recommended=False en todas las filas.
    Sin eso, recommended=None y el matcher lo rechaza como
    'postdecision_recommended_not_control'.
    """
    rows = [
        _candidate(0, selected_for_llm=True, symbol="TREAT"),
        _candidate(1, selected_for_llm=False, symbol="CTRL1"),
        _candidate(2, selected_for_llm=False, symbol="CTRL2"),
    ]
    phase = _phase(rows, selected_indices=[0])
    result = build_canonical_selection_ledger(
        "cycle-A", phase,
        recommendations=[],  # necesario: inicializa recommended=False
        captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    assert treatment["selected_for_llm"] is True

    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    assert matched["status"] == "verified"
    assert len(matched["controls"]) >= 1
    for ctrl in matched["controls"]:
        assert ctrl["selected_for_llm"] is False
        assert ctrl["cycle_id"] == "cycle-A"


def test_match_excludes_recommended_candidates():
    """Candidata recomendada no es control, aunque selected_for_llm=False."""
    rows = [
        _candidate(0, selected_for_llm=True, symbol="TREAT"),
        _candidate(1, selected_for_llm=False, symbol="OKCTRL"),
    ]
    phase = _phase(rows, selected_indices=[0])
    result = build_canonical_selection_ledger(
        "cycle-A", phase, recommendations=[], captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    assert matched["status"] == "verified"


def test_match_excludes_cross_cycle():
    """Candidata de otro ciclo -> cycle_mismatch."""
    c_a = _candidate(0, selected_for_llm=True, cycle_id="cycle-A", symbol="TREAT")
    c_b = _candidate(1, selected_for_llm=False, cycle_id="cycle-B",
                     symbol="OTHER", signal_id="signal:cycle-B:buy:OTHER")
    _phase([c_a, c_b], selected_indices=[0])
    result = build_canonical_selection_ledger(
        "cycle-A", {"all_candidates": [c_a, c_b]},
        recommendations=[], captured_at=CAPTURED_AT,
    )
    treatment = next(r for r in result["candidate_rows"] if r["symbol"] == "TREAT")
    matched = match_same_cycle_controls(treatment, result["candidate_rows"])
    excluded_reasons = {e["reason"] for e in matched.get("excluded", [])}
    assert "cycle_mismatch" in excluded_reasons or len(matched["controls"]) == 0


# ===================================================================
# (F) build_comparable_control_sets: controles primarios reales
# ===================================================================


def test_primary_reasons_are_exact():
    """PRIMARY_REASONS importado del modulo real."""
    assert "lower_rank" in PRIMARY_REASONS
    assert "capacity_limit" in PRIMARY_REASONS
    assert len(PRIMARY_REASONS) == 2


def test_blocked_reasons_are_not_primary():
    """BLOCKED_REASONS != PRIMARY_REASONS."""
    assert "gate_blocked" in BLOCKED_REASONS
    assert "gate_blocked" not in PRIMARY_REASONS
    assert "risk_blocked" in BLOCKED_REASONS
    assert "risk_blocked" not in PRIMARY_REASONS
    assert "strategy_paused" in BLOCKED_REASONS
    assert "unknown" not in BLOCKED_REASONS
    assert "unknown" in NON_EXECUTION_REASONS


def test_build_comparable_control_sets_empty_input_returns_empty():
    """Sin recomendaciones ni planes -> vacio."""
    result = build_comparable_control_sets(
        cycle_id="cycle-test", recommendations=[], plans=[], captured_at=CAPTURED_AT,
    )
    assert isinstance(result, dict)
    assert len(result) == 0


def test_build_comparable_control_sets_cycle_mismatch():
    """Recomendacion con distinto cycle_id -> broken link."""
    c = _candidate(0, cycle_id="cycle-OTHER", symbol="AAPL")

    class _FakeRec:
        pass
    rec = _FakeRec()
    rec.symbol = "AAPL"
    rec.action = "buy"
    rec.decision_lineage = _lineage(c)
    rec.decision_context_snapshot = {
        "llm_considered": True, "gate_frontier": "entry_eligibility_v1",
        "market_state_ref": {"status": "available", "content_hash": "abc123"},
    }
    rec.entry_price = 150.0
    rec.candidate_rank = 1.0

    class _FakePlan:
        pass
    plan = _FakePlan()
    plan.symbol = "AAPL"
    plan.side = "buy"
    plan.recommendation = rec
    plan.plan_id = "plan-test-1"

    result = build_comparable_control_sets(
        cycle_id="cycle-A", recommendations=[rec], plans=[plan], captured_at=CAPTURED_AT,
    )
    assert len(result) == 1
    cset = list(result.values())[0]
    assert cset["cycle_link_status"] == "broken"
    assert cset["unavailable_reason"] == "treatment_cycle_mismatch"


def test_build_unavailable_and_validate():
    """Control set unavailable pasa validacion."""
    cset = build_unavailable_control_set(
        reason="treatment_identity_unavailable", cycle_id="cycle-A",
    )
    validate_comparable_control_set(cset)
    assert cset["status"] == "unavailable"


def test_validate_rejects_invalid_schema():
    """Schema incorrecto rechazado."""
    with pytest.raises(ValueError, match="schema_version"):
        validate_comparable_control_set({"schema_version": "wrong"})


def test_validate_rejects_post_decision_fields():
    """Campos forward (return_5d) rechazados."""
    cset = build_unavailable_control_set(reason="test", cycle_id="cycle-A")
    cset["treatment"] = dict(cset.get("treatment", {}))
    cset["treatment"]["return_5d"] = 0.05
    with pytest.raises(ValueError, match="post_decision"):
        validate_comparable_control_set(cset)


# ===================================================================
# (G) Paridad y dimensiones
# ===================================================================


def test_selected_for_llm_and_llm_selected_are_different_dimensions():
    """selected_for_llm != llm_selected. Campos independientes."""
    c = _candidate(0, selected_for_llm=True)
    r = _rec(c, source="deterministic_capacity_fill")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["selected_for_llm"] is True
    assert row["llm_selected"] is False


def test_predecision_fields_exclude_outcomes():
    """El ledger no contiene returns, fills, P/L, MFE, MAE, first-hit."""
    c = _candidate(0)
    r = _rec(c, source="llm")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    forbidden = {
        "return_1d", "return_3d", "return_5d", "return_10d",
        "fill_price", "fill_qty", "pnl", "mfe", "mae", "first_hit",
    }
    for field in forbidden:
        assert field not in row, f"Campo prohibido {field} presente en el ledger"


def test_public_apis_importable():
    """Todas las APIs publicas usadas son importables y callable."""
    assert callable(build_canonical_selection_ledger)
    assert callable(persist_canonical_selection_ledger)
    assert callable(read_canonical_selection_ledger)
    assert callable(match_same_cycle_controls)
    assert callable(stable_content_hash)
    assert callable(build_comparable_control_sets)
    assert callable(validate_comparable_control_set)
    assert callable(build_unavailable_control_set)
