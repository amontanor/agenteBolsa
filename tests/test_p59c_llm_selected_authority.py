"""P-L59C: autoridad prospectiva estructurada de llm_selected.

Verifica que llm_selected nace en el productor (TradeRecommendation),
se propaga a traves del decision_context_snapshot, y es consumido
por canonical_selection_ledger sin inferir desde source textual.

Usa APIs reales: build_canonical_selection_ledger, persist/read,
build_decision_context_snapshot, Store con tmp_path, _env_file=None.
Sin red, broker, LLM, SQLite productiva.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
)
from agente_bolsa.tools.decision_context import (
    build_decision_context_snapshot,
    normalize_llm_selected,
)
from agente_bolsa.tools.trade_decision import _recommendation_from_dict

CAPTURED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cand(index: int, **overrides: Any) -> dict[str, Any]:
    symbol = overrides.pop("symbol", f"SYM{index:03d}")
    action = overrides.pop("action", "buy") if "action" in overrides else "buy"
    base: dict[str, Any] = {
        "cycle_id": "cycle-A",
        "session_date": "2026-07-26",
        "signal_capture_id": f"capture:cycle-A:{action}:{symbol}",
        "signal_id": f"signal:cycle-A:{action}:{symbol}",
        "candidate_id": f"candidate:cycle-A:{index}",
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": "builtin_breakout",
        "setup": "continuation",
        "score_universe": "domain-A",
        "score": 10.0,
        "selection_score": 0.2,
        "score_rank": 1,
        "selection_rank": 1,
        "data_quality": "good",
        "freshness": "fresh",
        "price_basis": "close_unadjusted",
        "signal_at": CAPTURED_AT.isoformat(),
        "decision_at": CAPTURED_AT.isoformat(),
        "eligible_at_selection": True,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": True,
    }
    base.update(overrides)
    return base


def _phase(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "all_candidates": rows,
        "selected_candidates": rows[: min(20, len(rows))],
    }


def _lineage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "signal_capture_id": row["signal_capture_id"],
        "signal_id": row["signal_id"],
        "candidate_id": row["candidate_id"],
    }


def _market_state(cycle_id: str = "cycle-A") -> dict[str, object]:
    return {
        "run_id": "run-A",
        "cycle_id": cycle_id,
        "as_of": CAPTURED_AT.isoformat(),
        "market_regime": "neutral",
        "volatility_regime": "normal",
        "risk_posture": "balanced",
        "data_quality": {"status": "GOOD"},
    }


def _store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "agent.sqlite3", tmp_path / "logs")
    s.ensure_schema()
    return s


def _rec_with_snapshot(
    row: dict[str, Any],
    *,
    source: str,
    llm_considered: bool | None = None,
    llm_selected: bool | None = None,
    rec_id: str | None = None,
) -> dict[str, Any]:
    """Build a recommendation dict with a real decision_context_snapshot.

    Uses build_decision_context_snapshot via a synthetic TradeRecommendation
    so the snapshot has the real schema, hash, and llm_selected embedded.
    """
    rec = TradeRecommendation(
        symbol=row["symbol"],
        action=row["action"],
        confidence=0.9,
        reason="fixture",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        source=source,
        decision_lineage=_lineage(row),
        recommendation_id=rec_id,
        llm_selected=llm_selected,
    )
    snapshot = build_decision_context_snapshot(
        rec,
        cycle_id=row["cycle_id"],
        source_run_id=row["source_run_id"],
        market_state=_market_state(cycle_id=row["cycle_id"]),
        signal_id=row["signal_id"],
        signal_capture_id=row["signal_capture_id"],
        captured_at=CAPTURED_AT,
        llm_considered=llm_considered,
        llm_selected=llm_selected,
    )
    return {
        "cycle_id": row["cycle_id"],
        "action": row["action"],
        "source": source,
        "decision_origin": source,
        "decision_lineage": _lineage(row),
        "decision_context_snapshot": snapshot,
        "recommendation_id": rec_id or f"rec:{row['symbol']}",
    }


# ===================================================================
# (A) Productor: _recommendation_from_dict fija llm_selected=True
# ===================================================================

def test_producer_llm_dict_sets_llm_selected_true():
    """El productor de recomendaciones LLM fija llm_selected=True."""
    rec = _recommendation_from_dict({
        "symbol": "AAPL",
        "action": "buy",
        "confidence": 0.85,
        "reason": "LLM selecciono AAPL",
        "entry_price": 150.0,
        "stop_loss": 145.0,
        "take_profit": 160.0,
    })
    assert rec is not None
    assert rec.llm_selected is True
    assert rec.source == "llm"


def test_producer_llm_dict_missing_confidence():
    """Confidence ausente no rompe llm_selected."""
    rec = _recommendation_from_dict({
        "symbol": "MSFT",
        "action": "buy",
    })
    assert rec is not None
    assert rec.llm_selected is True


# ===================================================================
# (B) Propagacion: TradeRecommendation -> decision_context_snapshot
# ===================================================================

def test_snapshot_carries_llm_selected_true():
    """llm_selected=True se propaga al snapshot."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
        llm_selected=True,
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=True,
    )
    assert snapshot["llm_selected"] is True


def test_snapshot_carries_llm_selected_false():
    """llm_selected=False se propaga al snapshot."""
    rec = TradeRecommendation(
        symbol="MSFT", action="buy", confidence=0.8, reason="t",
        llm_selected=False,
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=False,
    )
    assert snapshot["llm_selected"] is False


def test_snapshot_carries_llm_selected_none():
    """llm_selected=None (legacy) se propaga al snapshot."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT,
    )
    assert snapshot["llm_selected"] is None


# ===================================================================
# (C) Consumo: canonical_selection_ledger consume llm_selected del snapshot
# ===================================================================

def test_ledger_llm_selected_true_from_snapshot():
    """El ledger lee llm_selected=True del snapshot (no de source)."""
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True, llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is True
    assert result["candidate_rows"][0]["decision_source"] == "llm"


def test_ledger_llm_selected_false_from_snapshot():
    """El ledger lee llm_selected=False del snapshot."""
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="deterministic_capacity_fill",
                           llm_considered=False, llm_selected=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is False


def test_ledger_llm_selected_none_from_missing_snapshot_field():
    """Sin llm_selected en snapshot -> None (legacy/unavailable)."""
    c = _cand(0, selected_for_llm=True)
    # Construimos un snapshot sin llm_selected
    rec = TradeRecommendation(
        symbol=c["symbol"], action=c["action"], confidence=0.9, reason="t",
        source="llm", decision_lineage=_lineage(c),
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id=c["cycle_id"], source_run_id=c["source_run_id"],
        market_state=_market_state(cycle_id=c["cycle_id"]),
        captured_at=CAPTURED_AT,
    )
    r = {
        "cycle_id": c["cycle_id"], "action": c["action"],
        "source": "llm", "decision_origin": "llm",
        "decision_lineage": _lineage(c),
        "decision_context_snapshot": snapshot,
        "recommendation_id": "rec:X",
    }
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is None


# ===================================================================
# (D) Adversarial: source no manda
# ===================================================================

def test_source_llm_without_llm_selected_yields_none():
    """source='llm' sin autoridad llm_selected -> None (NO infiere True)."""
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True, llm_selected=None)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is None


def test_source_non_llm_with_llm_selected_true_yields_true():
    """source NO es 'llm' pero la autoridad dice True -> True."""
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="deterministic_capacity_fill",
                           llm_considered=False, llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is True


def test_unknown_source_without_llm_selected_yields_none():
    """Source desconocida sin autoridad -> None (nunca False)."""
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="bogus_unknown_source",
                           llm_considered=None, llm_selected=None)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["llm_selected"] is None
    # decision_source se normaliza a 'other' para fuente desconocida
    assert row["decision_source"] == "other"


# ===================================================================
# (E) Persistencia Store temporal
# ===================================================================

def test_persist_and_read_llm_selected_true(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True, llm_selected=True)
    p = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p)["status"] == "idempotent"
    rb = read_canonical_selection_ledger(store, "cycle-A")
    assert rb["status"] == "verified"
    assert rb["candidate_rows"][0]["llm_selected"] is True


def test_persist_and_read_llm_selected_false(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="deterministic_capacity_fill",
                           llm_considered=False, llm_selected=False)
    p = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p)["status"] == "inserted"
    rb = read_canonical_selection_ledger(store, "cycle-A")
    assert rb["candidate_rows"][0]["llm_selected"] is False


def test_persist_conflict_different_llm_selected(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    p1 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]),
        recommendations=[_rec_with_snapshot(c, source="llm", llm_considered=True,
                                             llm_selected=True)],
        captured_at=CAPTURED_AT,
    )
    p2 = build_canonical_selection_ledger(
        "cycle-A", _phase([c]),
        recommendations=[_rec_with_snapshot(c, source="deterministic_capacity_fill",
                                             llm_considered=False,
                                             llm_selected=False)],
        captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"


def test_build_ledger_does_not_mutate_inputs():
    c = _cand(0, selected_for_llm=True)
    orig = copy.deepcopy(c)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True, llm_selected=True)
    build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert c == orig


# ===================================================================
# (F) Fail-open: sombra no bloquea resultado activo
# ===================================================================

def test_ledger_build_succeeds_without_recommendations():
    """Sin recomendaciones, el ledger se construye sin fallo (fail-open)."""
    c = _cand(0, selected_for_llm=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), captured_at=CAPTURED_AT,
    )
    assert result["schema_version"].startswith("p-l53b")
    assert result["candidate_rows"][0]["llm_selected"] is None


def test_ledger_handles_broken_snapshot_gracefully():
    """Snapshot roto no bloquea el ledger."""
    c = _cand(0, selected_for_llm=True)
    r = {
        "cycle_id": "cycle-A", "action": "buy",
        "source": "llm", "decision_origin": "llm",
        "decision_lineage": _lineage(c),
        "decision_context_snapshot": None,  # snapshot ausente
        "recommendation_id": "rec:X",
    }
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["llm_selected"] is None
    assert row["recommended"] is True


# ===================================================================
# (G) BUY/EXIT y recommendation_id preservados
# ===================================================================

def test_buy_exit_separate_with_llm_selected():
    c_buy = _cand(0, action="buy", symbol="AAPL")
    c_exit = _cand(1, action="exit", symbol="AAPL",
                   signal_id="signal:cycle-A:exit:AAPL",
                   signal_capture_id="capture:cycle-A:exit:AAPL")
    r_buy = _rec_with_snapshot(c_buy, source="llm", llm_considered=True,
                               llm_selected=True, rec_id="rec:buy:aapl")
    r_exit = _rec_with_snapshot(c_exit, source="llm", llm_considered=True,
                                llm_selected=True, rec_id="rec:exit:aapl")
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c_buy, c_exit]),
        recommendations=[r_buy, r_exit], captured_at=CAPTURED_AT,
    )
    by_action = {r["action"]: r for r in result["candidate_rows"]}
    assert "buy" in by_action
    assert "exit" in by_action
    assert by_action["buy"]["llm_selected"] is True
    assert by_action["exit"]["llm_selected"] is True
    assert by_action["buy"]["recommendation_id"] == "rec:buy:aapl"
    assert by_action["exit"]["recommendation_id"] == "rec:exit:aapl"


def test_recommendation_id_preserved_across_persistence(tmp_path: Path):
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True,
                           llm_selected=True, rec_id="rec:specific-id-42")
    p = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    persist_canonical_selection_ledger(store, p)
    rb = read_canonical_selection_ledger(store, "cycle-A")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:specific-id-42"


# ===================================================================
# (H) selected_for_llm, llm_selected y decision_source: dimensiones separadas
# ===================================================================

def test_dimensions_independent_llm_selected_true():
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True,
                           llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["selected_for_llm"] is True   # el candidato fue seleccionado para el LLM
    assert row["llm_selected"] is True       # el LLM lo selecciono
    assert row["decision_source"] == "llm"


def test_dimensions_independent_capacity_fill():
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="deterministic_capacity_fill",
                           llm_considered=False, llm_selected=False)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["selected_for_llm"] is True    # presentado al LLM
    assert row["llm_selected"] is False        # no seleccionado por LLM
    assert row["decision_source"] == "deterministic_capacity_fill"


def test_dimensions_independent_legacy_none():
    c = _cand(0, selected_for_llm=True)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True,
                           llm_selected=None)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    assert row["selected_for_llm"] is True
    assert row["llm_selected"] is None  # legacy/unavailable
    assert row["decision_source"] == "llm"


# ===================================================================
# (I) Predecision: sin outcomes ni fills
# ===================================================================

def test_predecision_fields_exclude_outcomes():
    c = _cand(0)
    r = _rec_with_snapshot(c, source="llm", llm_considered=True,
                           llm_selected=True)
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    row = result["candidate_rows"][0]
    forbidden = {"return_1d", "return_3d", "return_5d", "return_10d",
                 "fill_price", "fill_qty", "pnl", "mfe", "mae", "first_hit"}
    for f in forbidden:
        assert f not in row, f"Campo post-decision {f} en row predecision"


# ===================================================================
# (J) P-L59C-R1: normalizacion runtime -- solo bool o None
# ===================================================================

def test_normalize_preserves_true():
    assert normalize_llm_selected(True) is True


def test_normalize_preserves_false():
    assert normalize_llm_selected(False) is False


def test_normalize_preserves_none():
    assert normalize_llm_selected(None) is None


def test_normalize_degrade_int_one_to_none():
    """1 no es bool literal -> None (fail-open)."""
    assert normalize_llm_selected(1) is None


def test_normalize_degrade_int_zero_to_none():
    """0 no es bool literal -> None."""
    assert normalize_llm_selected(0) is None


def test_normalize_degrade_string_true_to_none():
    assert normalize_llm_selected("true") is None


def test_normalize_degrade_string_false_to_none():
    assert normalize_llm_selected("false") is None


def test_normalize_degrade_list_to_none():
    assert normalize_llm_selected([True]) is None


def test_normalize_degrade_dict_to_none():
    assert normalize_llm_selected({"value": True}) is None


def test_normalize_degrade_float_to_none():
    assert normalize_llm_selected(1.0) is None


def test_normalize_never_raises_on_any_input():
    """Fail-open: cualquier tipo no lanza excepcion."""
    for value in [1, 0, -1, "true", "false", "", [], {}, (), set(), 1.5, object(), b"true"]:
        result = normalize_llm_selected(value)
        assert result is None, f"normalize_llm_selected({value!r}) -> {result!r}, expected None"


def test_ledger_normalizes_int_one_to_none_via_fixture():
    """Snapshot con llm_selected=1 (int) -> None en el ledger."""
    c = _cand(0, selected_for_llm=True)
    rec = TradeRecommendation(
        symbol=c["symbol"], action=c["action"], confidence=0.9, reason="t",
        source="llm", decision_lineage=_lineage(c),
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id=c["cycle_id"], source_run_id=c["source_run_id"],
        market_state=_market_state(cycle_id=c["cycle_id"]),
        captured_at=CAPTURED_AT,
    )
    # Malformado: inject 1 como llm_selected en el snapshot
    snapshot["llm_selected"] = 1
    r = {
        "cycle_id": c["cycle_id"], "action": c["action"],
        "source": "llm", "decision_origin": "llm",
        "decision_lineage": _lineage(c),
        "decision_context_snapshot": snapshot,
        "recommendation_id": "rec:X",
    }
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is None


def test_ledger_normalizes_string_true_to_none_via_fixture():
    """Snapshot con llm_selected='true' (str) -> None en el ledger."""
    c = _cand(0, selected_for_llm=True)
    rec = TradeRecommendation(
        symbol=c["symbol"], action=c["action"], confidence=0.9, reason="t",
        source="llm", decision_lineage=_lineage(c),
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id=c["cycle_id"], source_run_id=c["source_run_id"],
        market_state=_market_state(cycle_id=c["cycle_id"]),
        captured_at=CAPTURED_AT,
    )
    snapshot["llm_selected"] = "true"
    r = {
        "cycle_id": c["cycle_id"], "action": c["action"],
        "source": "llm", "decision_origin": "llm",
        "decision_lineage": _lineage(c),
        "decision_context_snapshot": snapshot,
        "recommendation_id": "rec:X",
    }
    result = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["llm_selected"] is None


# ===================================================================
# P-L59C-R2: snapshot normalization inside build_decision_context_snapshot
# ===================================================================

def test_snapshot_normalizes_int_to_none():
    """build_decision_context_snapshot normaliza 1 -> None."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=1,
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_normalizes_zero_to_none():
    """0 no es bool -> None."""
    rec = TradeRecommendation(
        symbol="MSFT", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=0,
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_normalizes_string_to_none():
    """'true' no es bool -> None."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected="true",
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_normalizes_list_to_none():
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=[True],
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_normalizes_float_to_none():
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=1.0,
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_preserves_true():
    """True literal se conserva."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=True,
    )
    assert snapshot["llm_selected"] is True


def test_snapshot_preserves_false():
    """False literal se conserva."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=False,
    )
    assert snapshot["llm_selected"] is False


def test_snapshot_preserves_none():
    """None se conserva."""
    rec = TradeRecommendation(
        symbol="AAPL", action="buy", confidence=0.9, reason="t",
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id="c1", source_run_id="r1",
        market_state=_market_state(cycle_id="c1"),
        captured_at=CAPTURED_AT, llm_selected=None,
    )
    assert snapshot["llm_selected"] is None


def test_snapshot_malformed_persisted_via_store_normalizes(tmp_path: Path):
    """Snapshot con llm_selected=1 persiste via Store y se lee como None."""
    store = _store(tmp_path)
    c = _cand(0, selected_for_llm=True)

    # Build a snapshot with malformed llm_selected=1 (int)
    rec = TradeRecommendation(
        symbol=c["symbol"], action=c["action"], confidence=0.9, reason="t",
        source="llm", decision_lineage=_lineage(c),
    )
    snapshot = build_decision_context_snapshot(
        rec, cycle_id=c["cycle_id"], source_run_id=c["source_run_id"],
        market_state=_market_state(cycle_id=c["cycle_id"]),
        captured_at=CAPTURED_AT, llm_selected=1,  # malformed: int instead of bool
    )
    # build_decision_context_snapshot normalizes before hashing
    assert snapshot["llm_selected"] is None  # normalized from 1

    # Now inject a direct malformed value into the snapshot to test P-L53 defense-in-depth
    snapshot["llm_selected"] = 1
    r = {
        "cycle_id": c["cycle_id"], "action": c["action"],
        "source": "llm", "decision_origin": "llm",
        "decision_lineage": _lineage(c),
        "decision_context_snapshot": snapshot,
        "recommendation_id": "rec:stored",
    }
    p = build_canonical_selection_ledger(
        "cycle-A", _phase([c]), recommendations=[r], captured_at=CAPTURED_AT,
    )
    # P-L53 normalizes via the same normalize_llm_selected imported from decision_context
    assert p["candidate_rows"][0]["llm_selected"] is None

    # Persist and read back
    assert persist_canonical_selection_ledger(store, p)["status"] == "inserted"
    rb = read_canonical_selection_ledger(store, "cycle-A")
    assert rb["candidate_rows"][0]["llm_selected"] is None


# ===================================================================
# (K) Version policy
# ===================================================================

def test_version_policy_requires_bump():
    from importlib import metadata
    dist = metadata.distribution("agente-bolsa")
    if dist:
        # Con PYTHONPATH al src del worktree, leemos __init__.py
        import agente_bolsa
        # P-L140B is the current candidate after the single-SPY dashboard.
        assert agente_bolsa.__version__ == "0.4.243"
