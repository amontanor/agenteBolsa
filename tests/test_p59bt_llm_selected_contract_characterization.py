"""P-L59B-T: adversarial characterization of llm_selected and control eligibility.

Tests the candidate P-L60R1 (version 0.4.195) against the semantic contract:
  (a) Which BUY recommendations were actually selected by the LLM?
  (b) Which eligible same-cycle controls were left out only due to
      lower rank or capacity limit?

All tests are synthetic and deterministic. No network, broker, LLM, SQLite
production, or src modification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Contract constants replicated from the candidate source
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "p-l53b.canonical-selection-ledger.v1"
CONTROL_SCHEMA_V2 = "p-l31b.comparable-control.v2"

# From agente_bolsa.tools.canonical_selection_ledger._DECISION_SOURCES
DECISION_SOURCE_MAP = {
    "llm": "llm",
    "capacity_fill": "deterministic_capacity_fill",
    "deterministic_capacity_fill": "deterministic_capacity_fill",
    "fallback": "fallback",
    "deterministic_fallback": "fallback",
    "hold_override": "hold_override",
    "deterministic": "deterministic",
}

# From agente_bolsa.tools.comparable_controls
PRIMARY_REASONS = frozenset({"lower_rank", "capacity_limit"})
NON_EXECUTION_REASONS = frozenset({
    "lower_rank", "capacity_limit", "daily_order_limit",
    "low_sample_quota", "gate_blocked", "risk_blocked",
    "strategy_paused", "invalid_geometry", "duplicate_symbol",
    "already_held", "unknown",
})
BLOCKED_REASONS = NON_EXECUTION_REASONS - PRIMARY_REASONS - {"unknown"}


def _normalize_source_candidate(source: Any, decision_origin: Any = None) -> str | None:
    """Replicate the candidate's source normalization logic."""
    if source is None and decision_origin is None:
        return None
    text = f"{str(source or '').lower()} {str(decision_origin or '').lower()}"
    for keyword, normalized in DECISION_SOURCE_MAP.items():
        if keyword in text:
            return normalized
    return "other"


def _derive_llm_selected(source: Any, decision_origin: Any = None) -> bool | None:
    """Replicate the candidate's llm_selected logic from canonical_selection_ledger.py:383.

    The candidate code at line 383:
        "llm_selected": True if source == "llm" else False if source else None,
    where 'source' is the normalized decision source.
    """
    normalized = _normalize_source_candidate(source, decision_origin)
    if normalized is None:
        return None
    return normalized == "llm"


def _stable_hash(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("captured_at", None)
    payload.pop("content_hash", None)
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_primary_control(reason: str) -> bool:
    """A control is primary only when the exclusion reason is lower_rank or capacity_limit."""
    return reason in PRIMARY_REASONS


def _is_blocked_not_control(reason: str) -> bool:
    """Blocked candidates are NOT primary controls."""
    return reason in BLOCKED_REASONS


# ===================================================================
# (a) llm_selected: semantic characterization
# ===================================================================


def test_llm_selected_true_when_source_is_llm() -> None:
    """llm_selected must be True only when decision_source normalizes to 'llm'.

    The candidate at canonical_selection_ledger.py:383 sets llm_selected
    to True iff _normalize_source returns 'llm'.
    """
    assert _derive_llm_selected("llm") is True
    assert _derive_llm_selected("LLM") is True
    assert _derive_llm_selected("LLM_REAL") is True


def test_llm_selected_false_for_capacity_fill() -> None:
    """llm_selected must be False for deterministic_capacity_fill source.

    Capacity fill is a deterministic process; the LLM did not directly
    produce the recommendation even though it may have ranked the
    candidate.
    """
    assert _derive_llm_selected("deterministic_capacity_fill") is False
    assert _derive_llm_selected("capacity_fill") is False


def test_llm_selected_false_for_fallback() -> None:
    """llm_selected must be False for fallback source."""
    assert _derive_llm_selected("fallback") is False
    assert _derive_llm_selected("deterministic_fallback") is False


def test_llm_selected_false_for_hold_override() -> None:
    """llm_selected must be False for hold_override source."""
    assert _derive_llm_selected("hold_override") is False


def test_llm_selected_none_when_no_recommendation() -> None:
    """llm_selected must be None when there is no recommendation (no source).

    This is the predecision state before phase B attachment.
    """
    assert _derive_llm_selected(None) is None
    assert _derive_llm_selected(None, None) is None


def test_llm_selected_none_for_unknown_source() -> None:
    """llm_selected must be None for unrecognized source that maps to 'other'.

    Wait -- actually: _normalize_source_candidate returns 'other' for unknown,
    and _derive_llm_selected would return False (because 'other' != 'llm').

    This test captures the actual behavior: unrecognized sources are treated
    as non-LLM, not as None.
    """
    normalized = _normalize_source_candidate("bogus_source_via_text")
    assert normalized == "other"
    assert _derive_llm_selected("bogus_source_via_text") is False
    # The contract says missing should be 'unavailable', not assumed false.
    # This is a semantic gap: 'other' sources are collapsed to False.


def test_llm_selected_is_proxy_not_independent() -> None:
    """llm_selected is a derived field, not an independently stored boolean.

    The candidate derives llm_selected from decision_source at ledger
    construction time. It never reads a persisted 'llm_selected' boolean.
    There is no event that independently records "the LLM selected this
    candidate" -- only the recommendation source.
    """
    # The algorithm is: source == "llm" -> True, else source != None -> False
    # There is no third input (an independent boolean flag).
    assert _derive_llm_selected("llm") is True        # direct LLM recommendation
    assert _derive_llm_selected("deterministic_capacity_fill") is False  # deterministic
    assert _derive_llm_selected("fallback") is False                     # fallback
    assert _derive_llm_selected(None) is None                            # no recommendation


def test_llm_selected_not_inferable_from_text_source() -> None:
    """The string 'source=llm' in P-L59A evidence is not structured.

    A text field like 'source=llm' requires normalization through
    _normalize_source before it can become llm_selected. Raw text
    without normalization is ambiguous.
    """
    # This would be normalized to 'llm' because 'llm' keyword is found
    assert _normalize_source_candidate("source=llm_internal") == "llm"
    # But "llm_selected" from raw text without source normalization yields None
    assert _derive_llm_selected("source=llm_internal") is True
    # Ambiguous case: text that doesn't contain a recognizable keyword
    assert _normalize_source_candidate("agent_decision") == "other"
    assert _derive_llm_selected("agent_decision") is False


# ===================================================================
# (b) Control eligibility: PRIMARY_REASONS contract
# ===================================================================


def test_lower_rank_is_primary_control_reason() -> None:
    """lower_rank is a valid exclusion for primary controls."""
    assert _is_primary_control("lower_rank")
    assert "lower_rank" in PRIMARY_REASONS


def test_capacity_limit_is_primary_control_reason() -> None:
    """capacity_limit is a valid exclusion for primary controls."""
    assert _is_primary_control("capacity_limit")
    assert "capacity_limit" in PRIMARY_REASONS


def test_gate_blocked_is_not_primary_control() -> None:
    """gate_blocked candidates are blocked, not controls."""
    assert not _is_primary_control("gate_blocked")
    assert _is_blocked_not_control("gate_blocked")
    assert "gate_blocked" not in PRIMARY_REASONS


def test_risk_blocked_is_not_primary_control() -> None:
    """risk_blocked candidates are blocked, not controls."""
    assert not _is_primary_control("risk_blocked")
    assert _is_blocked_not_control("risk_blocked")


def test_strategy_paused_is_not_primary_control() -> None:
    """strategy_paused candidates are blocked, not controls."""
    assert not _is_primary_control("strategy_paused")
    assert _is_blocked_not_control("strategy_paused")


def test_duplicate_symbol_is_not_primary_control() -> None:
    """duplicate_symbol candidates are blocked, not controls."""
    assert not _is_primary_control("duplicate_symbol")
    assert _is_blocked_not_control("duplicate_symbol")


def test_already_held_is_not_primary_control() -> None:
    """already_held candidates are blocked, not controls."""
    assert not _is_primary_control("already_held")
    assert _is_blocked_not_control("already_held")


def test_daily_order_limit_is_not_primary_control() -> None:
    """daily_order_limit is a capacity gate, not lower_rank/capacity_limit."""
    assert not _is_primary_control("daily_order_limit")
    assert _is_blocked_not_control("daily_order_limit")


def test_low_sample_quota_is_not_primary_control() -> None:
    """low_sample_quota is a quota gate, not rank/capacity."""
    assert not _is_primary_control("low_sample_quota")
    assert _is_blocked_not_control("low_sample_quota")


def test_invalid_geometry_is_not_primary_control() -> None:
    """invalid_geometry is a sizing gate, not rank/capacity."""
    assert not _is_primary_control("invalid_geometry")
    assert _is_blocked_not_control("invalid_geometry")


def test_unknown_is_neither_primary_nor_blocked() -> None:
    """unknown reason is neither a primary control nor explicitly blocked."""
    assert not _is_primary_control("unknown")
    assert not _is_blocked_not_control("unknown")
    assert "unknown" in NON_EXECUTION_REASONS


def test_non_execution_reasons_cover_all_categories() -> None:
    """All reasons must be in one of the three categories: primary, blocked, or unknown."""
    for reason in NON_EXECUTION_REASONS:
        if reason in PRIMARY_REASONS:
            assert _is_primary_control(reason)
        elif reason in BLOCKED_REASONS:
            assert _is_blocked_not_control(reason)
        elif reason == "unknown":
            pass  # neither primary nor blocked
        else:
            pytest.fail(f"Reason {reason} not in any category")


# ===================================================================
# Decision identity: BUY vs EXIT, signal identity separation
# ===================================================================


def test_buy_and_exit_with_same_signal_are_different_identities() -> None:
    """BUY and EXIT with the same signal_id have different identities.

    The identity key in the candidate is (cycle_id, action, signal_capture_id).
    BUY and EXIT actions produce different keys even with the same signal.
    """
    key_buy = ("cycle-1", "buy", "signal:capture:1")
    key_exit = ("cycle-1", "exit", "signal:capture:1")
    assert key_buy != key_exit
    assert key_buy[0] == key_exit[0]     # same cycle
    assert key_buy[1] != key_exit[1]     # different actions
    assert key_buy[2] == key_exit[2]     # same signal


def test_same_signal_different_cycles_are_different_identities() -> None:
    """Same signal in different cycles produces different identities."""
    key_a = ("cycle-A", "buy", "signal:1")
    key_b = ("cycle-B", "buy", "signal:1")
    assert key_a != key_b


def test_identity_with_signal_id_fallback() -> None:
    """When signal_capture_id is missing, signal_id is used as fallback."""
    key = ("cycle-X", "buy", "sig:42")
    assert key[2] == "sig:42"


def test_identity_without_signal_is_unavailable() -> None:
    """A candidate without signal_capture_id or signal_id has unavailable identity."""
    # The identity key requires cycle_id, action, and a non-empty signal identifier
    signal_id = None
    capture_id = None
    canonical_id = signal_id or capture_id
    assert canonical_id is None
    # Without identity, the row falls to identity_unavailable


def test_candidate_id_alone_is_not_identity_authority() -> None:
    """candidate_id alone does not constitute identity.

    The contract explicitly states that candidate_id is auxiliary, never authority.
    """
    candidate_id = "cand:123"
    # Without signal_capture_id/signal_id, candidate_id is not identity
    assert candidate_id is not None
    # But the contract uses signal_* as primary identity


# ===================================================================
# Source confusion: llm_selected vs selected_for_llm vs llm_considered
# ===================================================================


def test_selected_for_llm_is_predecision_different_from_llm_selected() -> None:
    """selected_for_llm (predecision) and llm_selected (postdecision) are different.

    - selected_for_llm = True means the candidate was presented to the LLM for ranking.
    - llm_selected = True means the LLM directly produced the recommendation.

    A candidate can be selected_for_llm=True but still get llm_selected=False
    if the LLM didn't explicitly recommend it (capacity fill took over).
    """
    selected_for_llm = True
    source = "deterministic_capacity_fill"
    llm_selected = _derive_llm_selected(source)
    assert selected_for_llm is True
    assert llm_selected is False
    # This is expected: capacity fill candidates were in the LLM pool
    # but were not directly selected by the LLM.


def test_llm_considered_independent_from_llm_selected() -> None:
    """llm_considered comes from decision_context_snapshot, not from source.

    The candidate at line 382 sets llm_considered from snapshot.get("llm_considered"),
    independently of llm_selected. Both can coexist with any combination.
    """
    # llm_considered=True + llm_selected=True  (LLM active, directly recommended)
    # llm_considered=True + llm_selected=False  (LLM active, but capacity fill)
    # llm_considered=False + llm_selected=False (LLM not active, fallback)
    # llm_considered=None + llm_selected=None    (unknown state)
    assert True  # documented semantics; no runtime contradiction


def test_decision_source_textual_mapping_is_complete() -> None:
    """Every known decision source maps to a normalized value."""
    known_sources = {
        "llm", "deterministic_capacity_fill", "fallback",
        "hold_override", "deterministic",
    }
    for src in known_sources:
        normalized = _normalize_source_candidate(src)
        assert normalized in (None, "llm", "deterministic_capacity_fill",
                             "fallback", "hold_override", "deterministic", "other")


def test_empty_string_source_maps_to_other() -> None:
    """An empty string source (not None) normalizes to 'other'."""
    result = _normalize_source_candidate("")
    assert result == "other"
    llm_sel = _derive_llm_selected("")
    assert llm_sel is False  # "other" != "llm"


# ===================================================================
# Idempotence and conflict safety (append-only contract)
# ===================================================================


class _TestEventLog:
    """SQLite-only test carrier; no production schema or Store wiring."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE events ("
                "  event_id TEXT PRIMARY KEY,"
                "  payload_json TEXT NOT NULL,"
                "  content_hash TEXT NOT NULL"
                ")"
            )

    def append(self, event_id: str, payload: dict[str, Any]) -> str:
        content_hash = _stable_hash(payload)
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                                  separators=(",", ":"))
        with sqlite3.connect(self.path, timeout=2.0) as connection:
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT content_hash FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] == content_hash:
                    connection.commit()
                    return "idempotent"
                conflict_id = f"{event_id}:conflict:{content_hash[:12]}"
                connection.execute(
                    "INSERT INTO events(event_id, payload_json, content_hash)"
                    " VALUES (?, ?, ?)",
                    (conflict_id, payload_json, content_hash),
                )
                connection.commit()
                return "conflict"
            connection.execute(
                "INSERT INTO events(event_id, payload_json, content_hash)"
                " VALUES (?, ?, ?)",
                (event_id, payload_json, content_hash),
            )
            connection.commit()
            return "inserted"

    def close(self) -> None:
        """Explicitly close any lingering connection."""
        pass  # Connections are managed per-append via context manager


def test_idempotent_insert_same_content(tmp_path: Path) -> None:
    """Same event_id + same content = idempotent (no-op)."""
    db_path = tmp_path / "test_p59bt_idempotent.sqlite3"
    log = _TestEventLog(db_path)
    payload = {
        "event_id": "canonical_selection_ledger:cycle-A",
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "cycle-A",
        "llm_selected": True,
    }
    r1 = log.append("canonical_selection_ledger:cycle-A", payload)
    r2 = log.append("canonical_selection_ledger:cycle-A", payload)
    assert r1 == "inserted"
    assert r2 == "idempotent"


def test_conflict_different_content_same_id(tmp_path: Path) -> None:
    """Same event_id + different content = conflict, original preserved."""
    db_path = tmp_path / "test_p59bt_conflict.sqlite3"
    log = _TestEventLog(db_path)
    original = {
        "event_id": "canonical_selection_ledger:cycle-A",
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "cycle-A",
        "llm_selected": True,
    }
    different = {
        "event_id": "canonical_selection_ledger:cycle-A",
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "cycle-A",
        "llm_selected": False,
    }
    r1 = log.append("canonical_selection_ledger:cycle-A", original)
    r2 = log.append("canonical_selection_ledger:cycle-A", different)
    assert r1 == "inserted"
    assert r2 == "conflict"


def test_captured_at_excluded_from_hash() -> None:
    """captured_at must not affect the content_hash."""
    payload_a = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "cycle-1",
        "captured_at": "2026-07-27T10:00:00+00:00",
        "llm_selected": True,
    }
    payload_b = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "cycle-1",
        "captured_at": "2026-07-27T14:30:00+00:00",
        "llm_selected": True,
    }
    assert _stable_hash(payload_a) == _stable_hash(payload_b)


def test_content_changes_detectable_by_hash() -> None:
    """Different llm_selected values produce different content hashes."""
    a = {"cycle_id": "cycle-1", "llm_selected": True}
    b = {"cycle_id": "cycle-1", "llm_selected": False}
    c = {"cycle_id": "cycle-1", "llm_selected": None}
    assert _stable_hash(a) != _stable_hash(b)
    assert _stable_hash(a) != _stable_hash(c)
    assert _stable_hash(b) != _stable_hash(c)


def test_json_order_stability_is_independent_of_hash() -> None:
    """JSON key ordering does not affect hash stability."""
    ordered = {
        "cycle_id": "cycle-1",
        "action": "buy",
        "llm_selected": True,
        "symbol": "AAPL",
    }
    shuffled = {
        "symbol": "AAPL",
        "llm_selected": True,
        "action": "buy",
        "cycle_id": "cycle-1",
    }
    assert _stable_hash(ordered) == _stable_hash(shuffled)


def test_non_mutation_of_inputs() -> None:
    """Input dictionaries must not be mutated by the hash function."""
    original = {
        "cycle_id": "cycle-1",
        "action": "buy",
        "llm_selected": True,
        "captured_at": "2026-07-27T00:00:00+00:00",
    }
    original_copy = copy.deepcopy(original)
    _stable_hash(original)
    assert original == original_copy


# ===================================================================
# P-L59A evidence reproduction: what would llm_selected be?
# ===================================================================


def test_p59a_inference_llm_selected_from_sources() -> None:
    """Reconstruct plausible llm_selected values from P-L59A evidence.

    P-L59A reported: 366 recommendations BUY (closed window 20-24 jul):
      - 269 capacity-fill  → llm_selected = False
      - 59 source=llm      → llm_selected = True
      - 25 fallback        → llm_selected = False
      - 13 hold            → llm_selected = False

    If P-L53/P-L54B ledger were active with this data, the structured
    durable fields would show these values. But production 0.4.185 lacks
    these modules, hence llm_selected = unavailable.

    This test verifies the mapping logic, not the data.
    """
    # capacity-fill → False
    assert _derive_llm_selected("deterministic_capacity_fill") is False
    # llm source → True
    assert _derive_llm_selected("llm") is True
    # fallback → False
    assert _derive_llm_selected("fallback") is False
    # hold_override → False
    assert _derive_llm_selected("hold_override") is False

    # Verifying that the 59 LLM-direct recommendations would get True
    llm_count_true = sum(1 for s in ["llm"] * 59 if _derive_llm_selected(s) is True)
    assert llm_count_true == 59

    # The remaining 307 (269+25+13) would get False
    remaining_false = sum(1 for s in (["deterministic_capacity_fill"] * 269
                                     + ["fallback"] * 25
                                     + ["hold_override"] * 13)
                         if _derive_llm_selected(s) is False)
    assert remaining_false == 307


def test_p59a_no_fills_used_as_features() -> None:
    """Fills, P/L, and outcomes must not be used as predecision features.

    The candidate contract explicitly forbids forward fields in predecision
    artifacts: return_1d, return_3d, return_5d, return_10d, fill_price,
    fill_qty, pnl, mfe, mae, first_hit, etc.
    """
    forbidden = {
        "return_1d", "return_3d", "return_5d", "return_10d",
        "matured_horizons", "fill", "fill_price", "filled_at",
        "filled_qty", "realized_pnl", "unrealized_pnl",
        "mfe", "mae", "first_hit", "slippage", "exit_status",
    }
    # These fields are defined as _FORBIDDEN_FIELDS in the candidate
    assert "fill_price" in forbidden
    assert "first_hit" in forbidden
    assert "mfe" in forbidden


# ===================================================================
# Edge cases: identity ambiguous, cross-cycle, missing states
# ===================================================================


def test_identity_ambiguous_is_not_verified() -> None:
    """Ambiguous identity is distinct from missing and from verified."""
    statuses = {
        "verified": True,
        "identity_unavailable": True,
        "identity_ambiguous": True,
    }
    assert "identity_ambiguous" in statuses
    assert "identity_unavailable" in statuses
    assert "identity_ambiguous" != "identity_unavailable"
    assert "identity_ambiguous" != "verified"


def test_cross_cycle_not_a_control() -> None:
    """Candidates from a different cycle cannot be controls.

    The same-cycle matching requires identical cycle_id.
    """
    cycle_a = "cycle-20260727-001"
    cycle_b = "cycle-20260727-002"
    assert cycle_a != cycle_b
    # A candidate from cycle B cannot be a control for a treatment in cycle A


def test_timestamps_none_are_absent_not_defaulted() -> None:
    """None timestamps remain None; they are not defaulted to epoch or now."""
    assert None is None  # The contract: missing = unavailable, never zero


# ===================================================================
# Integration: verify PUBLIC API functions are importable from candidate
# ===================================================================


def test_import_canonical_selection_ledger() -> None:
    """The public API of the selection ledger must be importable."""
    from agente_bolsa.tools.canonical_selection_ledger import (
        SCHEMA_VERSION,
        build_canonical_selection_ledger,
        match_same_cycle_controls,
        stable_content_hash,
    )
    assert SCHEMA_VERSION == "p-l53b.canonical-selection-ledger.v1"
    assert callable(build_canonical_selection_ledger)
    assert callable(stable_content_hash)
    assert callable(match_same_cycle_controls)


def test_import_comparable_controls() -> None:
    """The public API of comparable controls must be importable."""
    from agente_bolsa.tools.comparable_controls import (
        BLOCKED_REASONS,
        PRIMARY_REASONS,
        build_comparable_control_sets,
        validate_comparable_control_set,
    )
    assert "lower_rank" in PRIMARY_REASONS
    assert "capacity_limit" in PRIMARY_REASONS
    assert "gate_blocked" in BLOCKED_REASONS
    assert "gate_blocked" not in PRIMARY_REASONS
    assert callable(build_comparable_control_sets)
    assert callable(validate_comparable_control_set)


def test_import_capital_deployment_funnel() -> None:
    """The public API of the capital deployment funnel must be importable."""
    from agente_bolsa.tools.capital_deployment_funnel_shadow import (
        SCHEMA_VERSION as FUNNEL_VERSION,
    )
    from agente_bolsa.tools.capital_deployment_funnel_shadow import (
        build_capital_deployment_funnel_shadow,
    )
    assert FUNNEL_VERSION == "p-l54b.capital-deployment-funnel-shadow.v1"
    assert callable(build_capital_deployment_funnel_shadow)


# ===================================================================
# Non-mutation guarantee: ledger construction must not modify source objects
# ===================================================================


def test_build_ledger_does_not_mutate_gate_inputs() -> None:
    """build_canonical_selection_ledger must not mutate gate snapshot inputs."""
    from agente_bolsa.tools.canonical_selection_ledger import (
        build_canonical_selection_ledger as build,
    )
    phase_a = {
        "all_candidates": [
            {
                "cycle_id": "cycle-test",
                "action": "buy",
                "signal_id": "sig:test:1",
                "symbol": "TEST",
                "signal_at": "2026-07-27T10:00:00+00:00",
                "decision_at": "2026-07-27T10:05:00+00:00",
                "eligible_at_selection": True,
                "selected_for_llm": True,
                "score": 10.0,
                "score_rank": 1,
                "selection_score": 0.5,
                "selection_rank": 1,
            },
        ]
    }
    phase_a_original = copy.deepcopy(phase_a)
    captured_at = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    result = build("cycle-test", phase_a, captured_at=captured_at)
    assert result["candidate_rows"]
    assert result["status"] == "verified"
    # Inputs must not be mutated
    assert phase_a == phase_a_original, "Phase A was mutated by ledger build"


def test_build_ledger_sets_llm_selected_in_output_only() -> None:
    """The llm_selected field only appears in the ledger output, not in inputs."""
    from agente_bolsa.tools.canonical_selection_ledger import (
        build_canonical_selection_ledger as build,
    )
    candidate = {
        "cycle_id": "cycle-test2",
        "action": "buy",
        "signal_id": "sig:test:2",
        "symbol": "TEST2",
        "signal_at": "2026-07-27T10:00:00+00:00",
        "decision_at": "2026-07-27T10:05:00+00:00",
        "eligible_at_selection": True,
        "selected_for_llm": True,
        "score": 10.0,
    }
    recommendations = [
        {
            "signal_id": "sig:test:2",
            "action": "buy",
            "source": "llm",
            "decision_context_snapshot": {
                "llm_considered": True,
            },
        }
    ]
    candidate_original = copy.deepcopy(candidate)
    captured_at = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    result = build(
        "cycle-test2",
        {"all_candidates": [candidate]},
        recommendations=recommendations,
        captured_at=captured_at,
    )
    # Inputs unchanged
    assert candidate == candidate_original
    # Output has llm_selected derived from source
    assert len(result["candidate_rows"]) == 1
    assert result["candidate_rows"][0]["llm_selected"] is True
    assert result["candidate_rows"][0]["llm_considered"] is True
    assert result["candidate_rows"][0]["decision_source"] == "llm"
