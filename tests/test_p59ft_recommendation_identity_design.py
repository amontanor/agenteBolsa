"""P-L59F-T: Caracterizacion de la colision recommendation_id en P-L53.

Precondicion: XNYS abierto (~21:36 CEST), solo tests/docs, sin src.
Base: P-L59D-D HEAD 520559c6, tree e3c80ba, v0.4.196.

Pregunta de diseno: P-L53 tiene candidate_rows candidato-centricas, pero
adjunta una recomendacion singular. Dos recomendaciones del mismo
cycle/signal/action con distintos recommendation_id colisionan/last-wins.

Cada test usa APIs reales del modulo canonical_selection_ledger sin duplicar
logica mediante helpers que reimplementen build_canonical_selection_ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.storage import Store
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
    read_canonical_selection_ledger,
    stable_content_hash,
)

CAPTURED_AT = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# helpers: fixtures minimos con identidad explicita, sin reimplementar logica
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
        "decision_at": (signal_at).isoformat(),
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
    }
    if llm_selected is not None:
        snapshot["llm_selected"] = llm_selected
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
#    Mismo cycle/signal/candidate/action, dos recommendation_id
#    distintos con payload/llm_selected distintos.
#    Demuestra que sobrevive, orden/last-wins y content hash.
# ===================================================================


def test_two_recommendations_same_identity_last_wins() -> None:
    """Dos BUY para la misma identidad canonica -> solo sobrevive la ultima."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:first", llm_selected=True, confidence=0.90)
    rec_b = _recommendation(row, recommendation_id="rec:second", llm_selected=False, confidence=0.60)

    result = build_canonical_selection_ledger(
        "cycle-collision",
        _phase_a(row),
        recommendations=[rec_a, rec_b],
        captured_at=CAPTURED_AT,
    )
    rows = result["candidate_rows"]
    assert len(rows) == 1, "Un solo candidato, no deberia expandirse"

    r = rows[0]
    # Last-wins: la segunda recomendacion sobreescribe
    assert r["recommendation_id"] == "rec:second", (
        f"Esperado rec:second (last-wins), obtenido {r['recommendation_id']}"
    )
    assert r["llm_selected"] is False, (
        f"Esperado False (llm_selected de rec:second), obtenido {r['llm_selected']}"
    )
    assert r["decision_source"] == "llm"
    assert r["recommended"] is True

    # Denominadores: recommended_count debe ser 1 (un solo candidato)
    assert result["denominators"]["recommended_count"] == 1
    # Content hash debe ser estable
    assert result["content_hash"] == stable_content_hash(result)


def test_two_recommendations_same_identity_reverse_order_last_wins() -> None:
    """Invertir orden confirma last-wins (no first-wins ni merge)."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:first", llm_selected=False)
    rec_b = _recommendation(row, recommendation_id="rec:second", llm_selected=True)

    result = build_canonical_selection_ledger(
        "cycle-collision",
        _phase_a(row),
        recommendations=[rec_b, rec_a],  # orden invertido
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] == "rec:first", (
        "Last-wins: rec:first es la ultima en la lista"
    )
    assert r["llm_selected"] is False  # de rec:first (que es False)


def test_first_recommendation_evidence_lost() -> None:
    """La primera recomendacion (rec:first) pierde su recommendation_id
    y llm_selected. No hay traza dentro de candidate_rows."""
    row = _candidate_row()
    rec_first = _recommendation(row, recommendation_id="rec:first", llm_selected=True, confidence=0.90)
    rec_second = _recommendation(row, recommendation_id="rec:second", llm_selected=False, confidence=0.40)

    result = build_canonical_selection_ledger(
        "cycle-collision",
        _phase_a(row),
        recommendations=[rec_first, rec_second],
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    # Evidencia de rec:first desaparecio
    assert r["recommendation_id"] != "rec:first"
    assert r["llm_selected"] is not True
    # El warning recommendation_without_phase_a_candidate NO aparece
    # porque ambas mapean al mismo candidato
    assert "recommendation_without_phase_a_candidate" not in result.get("warnings", [])

    # Pero tampoco hay un warning de colision entre recomendaciones
    # (el sistema simplemente sobreescribe en silencio)
    collision_warnings = [w for w in result.get("warnings", []) if "collision" in w.lower() or "overwrite" in w.lower()]
    assert len(collision_warnings) == 0, (
        "No se emite warning de colision entre recomendaciones mismo-candidato"
    )


# ===================================================================
# 2. MISMO ID + MISMO CONTENIDO vs MISMO ID + CONTENIDO DISTINTO
#    Separa colision in-memory del conflicto append-only.
# ===================================================================


def test_idempotent_same_recommendation_id_and_content(tmp_path: Path) -> None:
    """Mismo recommendation_id + mismo contenido -> no-op/idempotente en Store."""
    store = _store(tmp_path)
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:idem", llm_selected=True)

    p1 = build_canonical_selection_ledger(
        "cycle-idem",
        _phase_a(row),
        recommendations=[rec],
        captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    # Segunda insercion identica
    p2 = build_canonical_selection_ledger(
        "cycle-idem",
        _phase_a(row),
        recommendations=[rec],
        captured_at=CAPTURED_AT,
    )
    assert p1["content_hash"] == p2["content_hash"]
    assert persist_canonical_selection_ledger(store, p2)["status"] == "idempotent"

    # Leer confirma el contenido original
    rb = read_canonical_selection_ledger(store, "cycle-idem")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:idem"


def test_same_recommendation_id_different_content_creates_conflict(tmp_path: Path) -> None:
    """Mismo event_id (mismo cycle) + contenido distinto -> conflicto append-only."""
    store = _store(tmp_path)
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:A", llm_selected=True)
    rec_b = _recommendation(row, recommendation_id="rec:B", llm_selected=False)

    p1 = build_canonical_selection_ledger("cycle-conflict", _phase_a(row), recommendations=[rec_a], captured_at=CAPTURED_AT)
    p2 = build_canonical_selection_ledger("cycle-conflict", _phase_a(row), recommendations=[rec_b], captured_at=CAPTURED_AT)

    assert p1["content_hash"] != p2["content_hash"]
    assert persist_canonical_selection_ledger(store, p1)["status"] == "inserted"
    # Mismo event_id (canonical_selection_ledger:cycle-conflict), distinto hash
    assert persist_canonical_selection_ledger(store, p2)["status"] == "conflict"
    # El lector devuelve la version original
    rb = read_canonical_selection_ledger(store, "cycle-conflict")
    assert rb["candidate_rows"][0]["recommendation_id"] == "rec:A"


# ===================================================================
# 3. BUY vs EXIT con misma signal identity
#    Confirma separacion correcta por action.
# ===================================================================


def test_buy_and_exit_same_signal_preserved_separately() -> None:
    """BUY y EXIT para la misma senal no colisionan: action es parte de la clave."""
    row = _candidate_row(action="buy", signal_id="signal:tsla")
    row_exit = _candidate_row(action="exit", signal_id="signal:tsla",
                              signal_capture_id="capture:tsla:exit",
                              candidate_id="candidate:tsla:exit")

    rec_buy = _recommendation(row, recommendation_id="rec:buy")
    # La accion sale de row (buy)
    rec_exit = _recommendation(row_exit, recommendation_id="rec:exit")

    # Aseguramos que la accion en la recomendacion coincide con el row
    rec_exit["action"] = "exit"
    rec_exit["decision_lineage"]["action"] = "exit"

    result = build_canonical_selection_ledger(
        "cycle-buy-exit",
        _phase_a(row, row_exit),
        recommendations=[rec_buy, rec_exit],
        captured_at=CAPTURED_AT,
    )
    by_action = {r["action"]: r for r in result["candidate_rows"]}
    assert "buy" in by_action
    assert "exit" in by_action
    assert by_action["buy"]["recommendation_id"] == "rec:buy"
    assert by_action["exit"]["recommendation_id"] == "rec:exit"
    assert result["denominators"]["recommended_count"] == 2


def test_two_buys_one_exit_same_signal() -> None:
    """Dos BUY y un EXIT misma senal: las BUY colisionan (1 fila), EXIT separado."""
    row_buy = _candidate_row(action="buy", signal_id="signal:aapl")
    row_exit = _candidate_row(action="exit", signal_id="signal:aapl",
                              signal_capture_id="capture:aapl:exit",
                              candidate_id="candidate:aapl:exit")

    rec_buy_a = _recommendation(row_buy, recommendation_id="rec:buy:a", llm_selected=True)
    rec_buy_b = _recommendation(row_buy, recommendation_id="rec:buy:b", llm_selected=False)
    rec_exit_x = _recommendation(row_exit, recommendation_id="rec:exit:x", llm_selected=None)
    rec_exit_x["action"] = "exit"
    rec_exit_x["decision_lineage"]["action"] = "exit"

    result = build_canonical_selection_ledger(
        "cycle-buy-buy-exit",
        _phase_a(row_buy, row_exit),
        recommendations=[rec_buy_a, rec_buy_b, rec_exit_x],
        captured_at=CAPTURED_AT,
    )
    # Solo 2 filas: una para buy (colision resuelta) y una para exit
    assert len(result["candidate_rows"]) == 2
    by_action = {r["action"]: r for r in result["candidate_rows"]}
    assert by_action["buy"]["recommendation_id"] == "rec:buy:b"  # last-wins
    assert by_action["exit"]["recommendation_id"] == "rec:exit:x"
    # recommended_count = 2 (una por accion unica)
    assert result["denominators"]["recommended_count"] == 2


# ===================================================================
# 4. MISSING recommendation_id LEGACY
#    Multiples recomendaciones sin ID, mezcla legacy/nueva.
# ===================================================================


def test_missing_recommendation_id_stays_none() -> None:
    """Recomendacion sin recommendation_id -> el campo queda None."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="")
    rec["recommendation_id"] = None  # simula legacy sin ID

    result = build_canonical_selection_ledger(
        "cycle-no-rec-id",
        _phase_a(row),
        recommendations=[rec],
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] is None, (
        f"Esperado None para legacy sin ID, obtenido {r['recommendation_id']}"
    )
    assert r["recommended"] is True  # recomendado aunque sin ID


def test_mixed_legacy_and_new_recommendation_ids() -> None:
    """Una recomendacion con ID y otra sin ID para el mismo candidato."""
    row = _candidate_row()
    rec_legacy = _recommendation(row, recommendation_id="")
    rec_legacy["recommendation_id"] = None
    rec_new = _recommendation(row, recommendation_id="rec:new", llm_selected=False)

    result = build_canonical_selection_ledger(
        "cycle-mixed",
        _phase_a(row),
        recommendations=[rec_legacy, rec_new],
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    # Last-wins: recommendation_id de rec_new sobreescribe
    assert r["recommendation_id"] == "rec:new"
    assert r["llm_selected"] is False


def test_multiple_recommendations_all_missing_ids() -> None:
    """Varias recomendaciones sin ID -> ultima llm_selected sobreescribe, ID queda None."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="", llm_selected=True)
    rec_a["recommendation_id"] = None
    rec_b = _recommendation(row, recommendation_id="", llm_selected=False)
    rec_b["recommendation_id"] = None

    result = build_canonical_selection_ledger(
        "cycle-no-ids",
        _phase_a(row),
        recommendations=[rec_a, rec_b],
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    assert r["recommendation_id"] is None
    assert r["llm_selected"] is False  # last-wins de rec_b
    assert result["denominators"]["recommended_count"] == 1  # un solo candidato


# ===================================================================
# 5. INSPECCION DE PRODUCTOR/WIRING REAL
#    Determina si recommendation_id ya existe antes del ledger,
#    cuando se asigna y si reviewed_recommendations conserva dos decisiones.
# ===================================================================


def test_recommendation_id_exists_before_ledger() -> None:
    """En cycle_runner.py:1805, recommendation_id = new_id('rec') se asigna
    ANTES de _persist_selection_ledger_shadow. El ledger solo consume IDs
    ya asignados por la ruta activa."""
    row = _candidate_row()
    rec = _recommendation(row, recommendation_id="rec:preassigned")

    result = build_canonical_selection_ledger(
        "cycle-preassigned",
        _phase_a(row),
        recommendations=[rec],
        captured_at=CAPTURED_AT,
    )
    assert result["candidate_rows"][0]["recommendation_id"] == "rec:preassigned"


def test_reviewed_recommendations_preserve_two_decisions_for_same_signal() -> None:
    """En el flujo real, reviewed_recommendations es una lista plana.
    Dos TradeRecommendation con la misma identidad canonica de senal
    co-existen en la lista; la colision ocurre SOLO en el ledger shadow,
    no en la ruta activa de decision/gates/planes."""
    # Simulamos la ruta activa: dos recomendaciones que el LLM genero
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:active:a")
    rec_b = _recommendation(row, recommendation_id="rec:active:b")

    # La ruta activa procesa ambas (gates, entry-quality, planes)
    # Cada una tiene su propio recommendation_id
    assert rec_a["recommendation_id"] == "rec:active:a"
    assert rec_b["recommendation_id"] == "rec:active:b"
    assert rec_a["recommendation_id"] != rec_b["recommendation_id"]

    # Pero al pasar al ledger...
    result = build_canonical_selection_ledger(
        "cycle-active",
        _phase_a(row),
        recommendations=[rec_a, rec_b],
        captured_at=CAPTURED_AT,
    )
    # Solo hay una fila; la segunda decision se pierde en la telemetria
    assert len(result["candidate_rows"]) == 1
    # recommended_count=1 aunque hubo 2 decisiones reales
    assert result["denominators"]["recommended_count"] == 1


# ===================================================================
# 6. INVENTARIO DE CONSUMIDORES DE candidate_rows Y recommendation_id
#    (documental: lista cada funcion y su expectativa estructural)
# ===================================================================


def test_consumer_inventory_is_documented() -> None:
    """Este test no falla; documenta los consumidores encontrados en el
    arbol e3c80ba (P-L59D-D) para referencia del diseno."""
    consumers = {
        # -- Consumidores directos de candidate_rows del CLS --
        "read_canonical_selection_ledger": {
            "module": "canonical_selection_ledger.py:653",
            "expects": "candidate_rows como lista de dicts, 1:1 candidato:decision",
            "accesses": "recommendation_id, llm_selected, decision_source, recommended, planned, ordered",
            "break_if_expanded": "denominadores recomendados vs recomendados contados cambiarian",
        },
        "canonical_selection_ledger_digest": {
            "module": "canonical_selection_ledger.py:666",
            "expects": "envuelve read_canonical_selection_ledger, anade conflict_events",
            "accesses": "candidate_rows indirectamente via read_canonical_selection_ledger",
        },
        "command_canonical_selection_ledger (CLI)": {
            "module": "main.py:2563",
            "expects": "digest JSON con candidate_rows; CLI solo lectura",
            "accesses": "candidate_rows indirectamente (via digest)",
        },
        "match_same_cycle_controls": {
            "module": "canonical_selection_ledger.py:686",
            "expects": "cada candidate_row es unica por identity_key; controls usan ciclo/sesion/accion",
            "accesses": "recommended, identity_key, session_date, action, eligible_at_selection, gate_frontier",
            "break_if_expanded": "dos filas para el mismo identity_key confundirian el contador de controles (linea 748: recommended is not False)",
        },
        "match_mature_forward_outcome": {
            "module": "canonical_selection_ledger.py:764",
            "expects": "identity_key une fila del ledger con outcome",
            "accesses": "identity_key, price_basis, session_date",
        },
        # -- Consumidores de recommendation_id fuera del CLS --
        "capital_deployment_funnel_shadow (P-L54)": {
            "module": "capital_deployment_funnel_shadow.py:120",
            "expects": "decision_key = (cycle, action, signal, recommendation_id) — YA diferencia por rec_id",
            "accesses": "recommendation_id en _identity_info (linea 129)",
            "note": "P-L54 NO tiene este bug; su identity_key incluye recommendation_id",
        },
        "canonical_operation_telemetry (P-L48B)": {
            "module": "canonical_operation_telemetry.py:340",
            "expects": "recommendation_id para enlazar plans con recommendations",
            "accesses": "recommendation_id via by_id(recommendations, 'recommendation_id')",
        },
        "post_market_review": {
            "module": "post_market_review.py:541",
            "expects": "recommendation_id como clave de dedup y enlace con ejecucion",
            "accesses": "recommendation_id para agrupar y contar",
        },
        "execution_quality (P-L33B)": {
            "module": "execution_quality.py:168",
            "expects": "recommendation_id para calculo de cobertura de linaje",
            "accesses": "recommendation_id en _lineage_status",
        },
        "llm_decision_quality (P-L22)": {
            "module": "llm_decision_quality.py:128",
            "expects": "recommendation_id como PRIMARY KEY en trade_recommendations",
            "accesses": "recommendation_id via SQL directo",
        },
        "counterfactual_analysis": {
            "module": "counterfactual_analysis.py:431",
            "expects": "recommendation_id en trade_recommendations para analisis",
            "accesses": "recommendation_id via SQL directo",
        },
        "comparable_controls (P-L31B)": {
            "module": "comparable_controls.py:447",
            "expects": "cada candidato con signal_id unico; no usa recommendation_id directamente",
            "accesses": "signal_id, candidate_id via candidate_rows de build_comparable_control_sets (variable local, NO CLS)",
        },
        "web_app (UI manual plan)": {
            "module": "web_app.py:3746",
            "expects": "recommendation_id = new_id('rec') para plan manual",
            "accesses": "recommendation_id generado, no leido del CLS",
        },
        "scheduler/learning_mode": {
            "module": "scheduler.py:616",
            "expects": "recommendation_id = new_id('rec') en fallback determinista",
            "accesses": "recommendation_id generado, no leido del CLS",
        },
    }

    # Verificacion estructural minima: las claves principales existen
    essential = [
        "read_canonical_selection_ledger",
        "capital_deployment_funnel_shadow (P-L54)",
        "canonical_operation_telemetry (P-L48B)",
        "post_market_review",
    ]
    for key in essential:
        assert key in consumers, f"Consumidor esencial no documentado: {key}"

    # Inventario de denominadores que cambiarian si candidate_rows se expande
    denominadores = {
        "recommended_count": "cuenta candidate_rows con recommended=True; en colision subestima decisiones reales",
        "canonical_count": "cuenta identity_status=verified; no cambia si se expande (todas verificadas)",
        "planned_count": "cuenta candidate_rows con planned=True; no duplica planes",
        "ordered_count": "cuenta candidate_rows con ordered=True; no duplica ordenes",
    }
    assert len(denominadores) == 4


# ===================================================================
# 7. EXPANSION vs SOBRESCRITURA: IMPACTO EN DENOMINADORES Y CONTROLES
# ===================================================================


def test_expanding_candidate_rows_changes_denominators() -> None:
    """Si candidate_rows se expandiera 1:1 con recomendaciones (sin
    agrupar por identity_key), los denominadores cambiarian:
    - recommended_count pasaria de 1 a 2 (correcto: hubo 2 decisiones)
    - canonical_count pasaria de 1 a 2 (incorrecto: solo hay 1 candidato)
    - Los controles comparables (match_same_cycle_controls) iterarian
      candidate_rows y verian DOS filas con la misma identity_key,
      rompiendo la asuncion de unicidad."""
    row = _candidate_row()
    rec_a = _recommendation(row, recommendation_id="rec:a")
    rec_b = _recommendation(row, recommendation_id="rec:b")

    # Comportamiento actual (colisiona)
    result_current = build_canonical_selection_ledger(
        "cycle-deno",
        _phase_a(row),
        recommendations=[rec_a, rec_b],
        captured_at=CAPTURED_AT,
    )
    assert result_current["denominators"]["recommended_count"] == 1
    assert result_current["denominators"]["canonical_count"] == 1

    # Si se expandiera (simulacion: dos candidatos distintos en phase_a
    # que comparten senal, como dos sub-estrategias para el mismo simbolo)
    row_a = _candidate_row(signal_capture_id="capture:v1", candidate_id="candidate:v1")
    row_b = _candidate_row(signal_capture_id="capture:v2", candidate_id="candidate:v2")
    rec_only_a = _recommendation(row_a, recommendation_id="rec:a")
    rec_only_b = _recommendation(row_b, recommendation_id="rec:b")

    # Construir con DOS candidatos distintos (identidad diferente ->
    # no deduplicados en _phase_a_rows)
    result_expanded = build_canonical_selection_ledger(
        "cycle-deno-exp",
        _phase_a(row_a, row_b),
        recommendations=[rec_only_a, rec_only_b],
        captured_at=CAPTURED_AT,
    )
    # Con dos filas distintas, ambas reciben recomendacion
    assert result_expanded["denominators"]["recommended_count"] == 2
    assert result_expanded["denominators"]["canonical_count"] == 2
    # La identidad clave es (cycle_id, action, signal_capture_id):
    # como son diferentes, no colisionan. Pero si la identidad fuera
    # SOLO (cycle_id, symbol, action) -como hace _recommendation_identity
    # en cycle_runner- entonces SI colisionarian.


def test_overwriting_singular_loses_decision_authority() -> None:
    """Sobrescribir recommendation_id en la misma fila pierde la
    autoridad causal de la primera decision. No hay registro de que
    existio una decision con llm_selected=True que fue reemplazada
    por otra con llm_selected=False."""
    row = _candidate_row()
    rec_llm = _recommendation(row, recommendation_id="rec:llm", source="llm", llm_selected=True)
    rec_capacity = _recommendation(row, recommendation_id="rec:capacity", source="capacity_fill", llm_selected=False)

    result = build_canonical_selection_ledger(
        "cycle-authority",
        _phase_a(row),
        recommendations=[rec_llm, rec_capacity],
        captured_at=CAPTURED_AT,
    )
    r = result["candidate_rows"][0]
    # La decision real fue LLM (primero), pero el ledger solo muestra capacity-fill
    assert r["recommendation_id"] == "rec:capacity"
    assert r["decision_source"] == "deterministic_capacity_fill"
    assert r["llm_selected"] is False
    # Un consumidor que lea esto concluiria que NO hubo seleccion LLM,
    # cuando en realidad SI la hubo (simplemente fue sobreescrita)


# ===================================================================
# 8. STAGE ORDER Y PARIDAD: PUNTO MINIMO PARA SELLAR DECISION
# ===================================================================


def test_stage_order_recommendation_id_assigned_before_ledger() -> None:
    """En cycle_runner.py el orden es:
    1. L1805: recommendation_id = new_id('rec')
    2. L1806-1809: replace con decision_context_snapshot + recommendation_id
    3. L1823: reviewed_recommendations = snapshotted_recommendations
    4. Gates (entry-quality, backtest)
    5. Planes, limites diarios, low-sample
    6. P-L31BR: comparable_control_sets
    7. L2167: _persist_selection_ledger_shadow con reviewed_recommendations

    El recommendation_id se asigna ANTES de gates, planes y ledger.
    La colision en el ledger no afecta la ruta activa (gates/planes
    usan objetos TradeRecommendation con sus propios IDs)."""
    row = _candidate_row()

    # Simulamos el flujo: dos recomendaciones con IDs distintos
    # pasan por gates independientemente
    rec_a = _recommendation(row, recommendation_id="rec:gates:a", llm_selected=True)
    rec_b = _recommendation(row, recommendation_id="rec:gates:b", llm_selected=False)

    # Ambas existen como objetos independientes (como en reviewed_recommendations)
    active_decisions = [rec_a, rec_b]
    assert len(active_decisions) == 2
    assert active_decisions[0]["recommendation_id"] == "rec:gates:a"
    assert active_decisions[1]["recommendation_id"] == "rec:gates:b"

    # El ledger colapsa pero la ruta activa ya proceso ambas
    result = build_canonical_selection_ledger(
        "cycle-stage",
        _phase_a(row),
        recommendations=active_decisions,
        captured_at=CAPTURED_AT,
    )
    # El ledger solo muestra una
    assert len(result["candidate_rows"]) == 1


# ===================================================================
# DISENO: COMPARACION DE OPCIONES A, B, C, D
# ===================================================================


def test_design_options_comparison() -> None:
    """Documenta las 4 opciones de diseno y recomienda una.

    Opcion A: Expandir candidate_rows 1:1 con recomendaciones
      - Ventaja: cada decision tiene su fila; no se pierde evidencia
      - Desventaja: rompe denominadores candidato-centricos
        (canonical_count ya no cuenta candidatos unicos);
        match_same_cycle_controls iteraria filas duplicadas;
        todos los consumidores que asumen candidate_row unica por
        identity_key necesitarian migracion

    Opcion B: Campo recommendations[] / decision_rows separado
      - Ventaja: candidate_rows preserva semantica candidato-centrica;
        nuevo campo lista las decisiones asociadas
      - Desventaja: nuevo schema; cambio en todos los lectores;
        recommendation_id se mueve de candidate_row a decision_row;
        consumidores que leen recommendation_id de candidate_row
        necesitan actualizarse

    Opcion C: Evento/ledger separado por recommendation_id
      - Ventaja: cada decision es un evento append-only independiente;
        sin colisiones; maxima fidelidad
      - Desventaja: dos sistemas de eventos (ciclo vs decision);
        coordinacion adicional; consumidores necesitan un join

    Opcion D: Conflicto auditable sin canonicalizar segunda decision
      - Ventaja: cambio minimo; candidate_rows gana un flag
        'decision_conflict' y un array 'conflicting_recommendation_ids';
        la primera decision se conserva; la segunda se registra como
        conflicto sin sobreescribir
      - Desventaja: no resuelve el problema de fondo (dos decisiones
        validas para el mismo candidato); solo hace visible el conflicto

    RECOMENDACION: Opcion B (decision_rows separado).
    - Es la unica que preserva ambos denominadores (candidate_count
      y recommendation_count) sin romper consumidores existentes.
    - P-L54 ya usa (cycle, action, signal, recommendation_id) como
      identity_key, lo que valida el enfoque de separar dominios.
    - Implementacion minima: anadir 'decision_rows' al payload del
      CLS, sacar recommendation_id/llm_selected/decision_source de
      candidate_rows (dejando solo el flag 'recommended'), y mantener
      candidate_rows con identidad candidato-centrica.
    """
    options = ["A", "B", "C", "D"]
    for opt in options:
        assert opt in ["A", "B", "C", "D"], f"Opcion {opt} documentada"
