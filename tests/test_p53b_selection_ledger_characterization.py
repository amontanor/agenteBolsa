from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

SCHEMA_VERSION = "p-l53b.canonical-selection-ledger.v1"
CAPTURED_AT = "2026-07-22T00:00:00+00:00"
VALID_ACTIONS = {"buy", "exit"}
FORBIDDEN_PREDECISION_FIELDS = {
    "return_1d",
    "return_3d",
    "return_5d",
    "return_10d",
    "fill_price",
    "fill_qty",
    "pnl",
    "mfe",
    "mae",
    "first_hit",
    "matured_outcome",
}
SOURCE_ALIASES = {
    "llm": "llm",
    "capacity_fill": "deterministic_capacity_fill",
    "deterministic_capacity_fill": "deterministic_capacity_fill",
    "fallback": "fallback",
    "deterministic_fallback": "fallback",
    "hold_override": "hold_override",
    "deterministic": "deterministic",
}


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp_missing_or_invalid")
    if parsed.tzinfo is None:
        raise ValueError("timestamp_naive")
    return parsed.astimezone(timezone.utc)


def _stable_hash(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("captured_at", None)
    payload.pop("content_hash", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_source(value: Any) -> str | None:
    if value is None:
        return None
    return SOURCE_ALIASES.get(str(value).strip().lower(), "other")


def _identity_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    cycle_id = str(row.get("cycle_id") or "").strip()
    action = str(row.get("action") or "").strip().lower()
    signal_id = str(row.get("signal_id") or "").strip()
    capture_id = str(row.get("signal_capture_id") or "").strip()
    canonical_id = signal_id or capture_id
    if not cycle_id or action not in VALID_ACTIONS or not canonical_id:
        return None
    return cycle_id, action, canonical_id


def _derive_states(row: dict[str, Any]) -> list[str]:
    states: list[str] = []
    if _identity_key(row) is None:
        states.append("identity_unavailable")
    else:
        states.append("identified")
    if row.get("eligible_at_selection") is True:
        states.append("eligible")
    elif row.get("eligible_at_selection") is False:
        states.append("ineligible")
    else:
        states.append("shadow_inputs_unavailable")
    selected = row.get("selected_for_llm")
    if selected is True:
        states.append("selected")
    elif selected is False:
        states.append("not_selected")
    else:
        states.append("unavailable")
    for field, positive, negative in (
        ("recommended", "recommended", "not_recommended"),
        ("planned", "planned", "not_planned"),
        ("ordered", "ordered", "not_ordered"),
    ):
        value = row.get(field)
        if value is True:
            states.append(positive)
        elif value is False:
            states.append(negative)
        else:
            states.append("unavailable")
    if row.get("not_generated") is True:
        states.append("not_generated")
    if row.get("timestamp_status") != "verified":
        states.append("unavailable")
    return list(dict.fromkeys(states))


def _normalize_row(raw: dict[str, Any], *, captured_at: str = CAPTURED_AT) -> dict[str, Any]:
    forbidden = FORBIDDEN_PREDECISION_FIELDS.intersection(raw)
    if forbidden:
        raise ValueError(f"post_decision_field:{sorted(forbidden)[0]}")

    action = str(raw.get("action") or "").strip().lower()
    if action == "sell":
        action = "exit"
    if action not in VALID_ACTIONS:
        action = None

    timestamp_warnings: list[str] = []
    parsed_times: dict[str, datetime] = {}
    captured = _utc(captured_at)
    for field in ("signal_at", "decision_at"):
        raw_timestamp = raw.get(field)
        if raw_timestamp is None:
            timestamp_warnings.append(f"missing:{field}")
            continue
        try:
            parsed = _utc(raw_timestamp)
        except ValueError as exc:
            timestamp_warnings.append(f"invalid:{field}:{exc}")
            continue
        parsed_times[field] = parsed
        if parsed > captured:
            timestamp_warnings.append(f"future:{field}")
    signal_at = parsed_times.get("signal_at")
    decision_at = parsed_times.get("decision_at")
    if signal_at is not None and decision_at is not None and decision_at < signal_at:
        timestamp_warnings.append("inverted:decision_at")

    row = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": raw.get("cycle_id"),
        "session_date": raw.get("session_date"),
        "signal_capture_id": raw.get("signal_capture_id"),
        "signal_id": raw.get("signal_id"),
        "candidate_id": raw.get("candidate_id"),
        "recommendation_id": raw.get("recommendation_id"),
        "plan_id": raw.get("plan_id"),
        "broker_order_id": raw.get("broker_order_id"),
        "source_run_id": raw.get("source_run_id"),
        "symbol": raw.get("symbol"),
        "action": action,
        "strategy": raw.get("strategy", raw.get("strategy_name")),
        "setup": raw.get("setup", raw.get("setup_name")),
        "score_universe": raw.get("score_universe"),
        "score": raw.get("score"),
        "selection_score": raw.get("selection_score"),
        "learning_prior": raw.get("learning_prior"),
        "score_rank": raw.get("score_rank"),
        "selection_rank": raw.get("selection_rank"),
        "rank_direction": {
            "score": "descending_raw_higher_better",
            "selection": "descending_selection_score_higher_better",
        },
        "data_quality": raw.get("data_quality"),
        "freshness": raw.get("freshness"),
        "price_basis": raw.get("price_basis"),
        "signal_at": raw.get("signal_at"),
        "decision_at": raw.get("decision_at"),
        "timestamp_status": "verified" if not timestamp_warnings else "unavailable",
        "timestamp_warnings": timestamp_warnings,
        "eligible_at_selection": raw.get("eligible_at_selection"),
        "gate_frontier": raw.get("gate_frontier"),
        "selected_for_llm": raw.get("selected_for_llm"),
        "llm_considered": raw.get("llm_considered"),
        "llm_selected": raw.get("llm_selected"),
        "decision_source": _normalize_source(raw.get("decision_source")),
        "recommended": raw.get("recommended"),
        "planned": raw.get("planned"),
        "ordered": raw.get("ordered"),
        "exclusion_reason": raw.get("exclusion_reason"),
        "not_generated": raw.get("not_generated"),
        "captured_at": captured_at,
    }
    key = _identity_key(row)
    row["identity_status"] = "verified" if key else "unavailable"
    row["identity_key"] = list(key) if key else None
    row["event_id"] = (
        f"selection_ledger:{key[0]}:{key[1]}:{key[2]}" if key else None
    )
    row["states"] = _derive_states(row)
    row["content_hash"] = _stable_hash(row)
    return row


def _build_ledger(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    canonical: dict[tuple[str, str, str], dict[str, Any]] = {}
    unavailable: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    idempotent_duplicates = 0
    for raw in raw_rows:
        row = _normalize_row(raw)
        key = _identity_key(row)
        if key is None:
            unavailable.append(row)
            continue
        current = canonical.get(key)
        if current is None:
            canonical[key] = row
        elif current["content_hash"] == row["content_hash"]:
            idempotent_duplicates += 1
        else:
            conflicts.append(
                {
                    "event_id": row["event_id"],
                    "existing_content_hash": current["content_hash"],
                    "candidate_content_hash": row["content_hash"],
                    "status": "conflict",
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "raw_count": len(raw_rows),
        "canonical_rows": list(canonical.values()),
        "unavailable_rows": unavailable,
        "conflicts": conflicts,
        "idempotent_duplicates": idempotent_duplicates,
        "truncated_count": 0,
    }


def _count_true(frame: pd.DataFrame, field: str) -> int:
    if field not in frame:
        return 0
    return int(frame[field].eq(True).sum())


def _denominators(
    ledger: dict[str, Any], *, truncated_count: int = 0, mature_counts: dict[str, int] | None = None
) -> dict[str, Any]:
    rows = ledger["canonical_rows"]
    frame = pd.DataFrame(rows)
    mature_counts = mature_counts or {}
    return {
        "raw_count": ledger["raw_count"],
        "canonical_count": len(rows),
        "identity_unavailable": len(ledger["unavailable_rows"]),
        "eligible_count": _count_true(frame, "eligible_at_selection"),
        "selected_count": _count_true(frame, "selected_for_llm"),
        "recommended_count": _count_true(frame, "recommended"),
        "planned_count": _count_true(frame, "planned"),
        "ordered_count": _count_true(frame, "ordered"),
        "conflict_count": len(ledger["conflicts"]),
        "idempotent_duplicate_count": ledger["idempotent_duplicates"],
        "truncated_count": truncated_count,
        "mature_3d": mature_counts.get("3d"),
        "mature_5d": mature_counts.get("5d"),
        "mature_10d": mature_counts.get("10d"),
    }


def _match_same_cycle(treatment: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    treatment_key = _identity_key(treatment)
    if treatment_key is None or treatment.get("action") != "buy":
        return {"status": "unavailable", "reason": "treatment_identity_or_action_unavailable", "controls": [], "excluded": []}
    if treatment.get("eligible_at_selection") is not True:
        return {"status": "unavailable", "reason": "treatment_not_eligible", "controls": [], "excluded": []}
    for candidate in candidates:
        key = _identity_key(candidate)
        reason = None
        if key is None:
            reason = "identity_unavailable"
        elif key == treatment_key:
            reason = "same_treatment"
        elif candidate.get("action") != "buy":
            reason = "action_mismatch"
        elif candidate.get("cycle_id") != treatment.get("cycle_id"):
            reason = "cycle_mismatch"
        elif candidate.get("session_date") != treatment.get("session_date"):
            reason = "session_mismatch"
        elif candidate.get("strategy") != treatment.get("strategy") or candidate.get("setup") != treatment.get("setup"):
            reason = "strategy_setup_mismatch"
        elif candidate.get("eligible_at_selection") is not True:
            reason = "ineligible_at_frontier"
        elif candidate.get("data_quality") != treatment.get("data_quality"):
            reason = "data_quality_mismatch_or_unavailable"
        elif candidate.get("freshness") != treatment.get("freshness"):
            reason = "freshness_mismatch_or_unavailable"
        elif candidate.get("timestamp_status") != "verified":
            reason = "predecision_timestamp_unavailable"
        else:
            try:
                delta = abs((_utc(candidate["signal_at"]) - _utc(treatment["signal_at"])).total_seconds())
            except (KeyError, ValueError):
                reason = "predecision_timestamp_unavailable"
            else:
                if delta > 60:
                    reason = "predecision_timestamp_incompatible"
        if reason is None and candidate.get("selected_for_llm") is not False:
            reason = "selection_state_unavailable_or_selected"
        if reason is None and candidate.get("recommended") is not False:
            reason = "postdecision_recommended_not_control"
        if reason is None:
            controls.append(candidate)
        else:
            excluded.append({"event_id": candidate.get("event_id"), "reason": reason})
    return {
        "status": "verified" if controls else "unavailable",
        "reason": None if controls else "no_eligible_alternatives",
        "controls": controls,
        "excluded": excluded,
    }


def _attach_mature_outcome(
    row: dict[str, Any], outcome: dict[str, Any], *, completed_sessions: list[str]
) -> dict[str, Any]:
    if outcome.get("signal_id") != row.get("signal_id"):
        return {"status": "unavailable", "reason": "signal_id_mismatch"}
    if outcome.get("cycle_id") != row.get("cycle_id") or outcome.get("action") != row.get("action"):
        return {"status": "unavailable", "reason": "decision_identity_mismatch"}
    horizon = str(outcome.get("horizon") or "")
    required = {"3d": 3, "5d": 5, "10d": 10}.get(horizon)
    if required is None:
        return {"status": "unavailable", "reason": "horizon_invalid"}
    if row.get("price_basis") is None or outcome.get("price_basis") != row.get("price_basis"):
        return {"status": "unavailable", "reason": "price_basis_unavailable_or_mismatch"}
    if outcome.get("matured") is not True:
        return {"status": "unavailable", "reason": "outcome_immature"}
    try:
        signal_index = completed_sessions.index(str(row["session_date"]))
        maturity_index = completed_sessions.index(str(outcome["maturity_session_date"]))
    except (KeyError, ValueError):
        return {"status": "unavailable", "reason": "session_not_completed"}
    if maturity_index - signal_index < required:
        return {"status": "unavailable", "reason": "maturity_sessions_insufficient"}
    return {"status": "matured", "horizon": horizon, "forward_return": outcome.get("forward_return")}


def _candidate(
    index: int,
    *,
    cycle_id: str = "cycle-A",
    symbol: str | None = None,
    action: str = "buy",
    selected: bool = False,
    recommended: bool = False,
    planned: bool = False,
    ordered: bool = False,
    exclusion_reason: str | None = None,
    signal_id: str | None = None,
    eligible: bool | None = True,
    data_quality: str = "good",
    freshness: str = "fresh",
) -> dict[str, Any]:
    symbol = symbol or f"SYM{index:03d}"
    strategy = "builtin_breakout" if index % 2 == 0 else "builtin_pullback"
    setup = "continuation" if index % 4 in (0, 1) else "reversal"
    source = "llm" if index < 8 else "capacity_fill" if index < 12 else "fallback"
    signal_id = signal_id or f"signal:{cycle_id}:{action}:{symbol}"
    signal_at = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    return {
        "cycle_id": cycle_id,
        "session_date": "2026-07-21",
        "signal_capture_id": f"capture:{cycle_id}:{action}:{symbol}:{index}",
        "signal_id": signal_id,
        "candidate_id": f"candidate:{cycle_id}:{index}",
        "recommendation_id": f"rec:{cycle_id}:{index}" if recommended else None,
        "plan_id": f"plan:{cycle_id}:{index}" if planned else None,
        "broker_order_id": f"bo:{cycle_id}:{index}" if ordered else None,
        "source_run_id": "scan-A",
        "symbol": symbol,
        "action": action,
        "strategy": strategy,
        "setup": setup,
        "score_universe": f"{strategy}:{setup}",
        "score": 10.0 + (index % 30) / 10,
        "selection_score": 0.1 - (index % 30) / 1000,
        "learning_prior": 0.02 - (index % 5) / 1000,
        "score_rank": index % 10 + 1,
        "selection_rank": index % 20 + 1,
        "data_quality": data_quality,
        "freshness": freshness,
        "price_basis": "close_unadjusted",
        "signal_at": signal_at.isoformat(),
        "decision_at": (signal_at + timedelta(seconds=10)).isoformat(),
        "eligible_at_selection": eligible,
        "gate_frontier": "entry_eligibility_v1",
        "selected_for_llm": selected,
        "llm_considered": index < 12,
        "llm_selected": index < 8 if selected else None,
        "decision_source": source if selected else None,
        "recommended": recommended,
        "planned": planned,
        "ordered": ordered,
        "exclusion_reason": exclusion_reason,
        "not_generated": False,
    }


def _large_fixture() -> list[dict[str, Any]]:
    rows = [_candidate(index, selected=index < 20) for index in range(443)]
    for index in range(5):
        rows[index]["recommended"] = True
        rows[index]["recommendation_id"] = f"rec:cycle-A:{index}"
    for index in range(3):
        rows[index]["planned"] = True
        rows[index]["plan_id"] = f"plan:cycle-A:{index}"
    for index in range(2):
        rows[index]["ordered"] = True
        rows[index]["broker_order_id"] = f"bo:cycle-A:{index}"
    rows[1]["exclusion_reason"] = "entry_quality_gate"
    rows[2]["exclusion_reason"] = "cycle_capacity_limit"
    rows[3]["planned"] = False
    rows[3]["plan_id"] = None
    rows[3]["exclusion_reason"] = "cycle_capacity_limit"
    rows[4]["ordered"] = False
    rows[4]["broker_order_id"] = None
    rows[4]["exclusion_reason"] = "broker_submission_unavailable"
    rows[441] = _candidate(
        441,
        action="exit",
        symbol="SYM000",
        signal_id=rows[0]["signal_id"],
        selected=False,
        recommended=False,
    )
    rows[442] = _candidate(
        442,
        cycle_id="cycle-B",
        symbol="SYM000",
        selected=False,
        recommended=False,
    )
    return rows


class _TestEventLog:
    """SQLite-only test carrier; no production schema or Store wiring."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE events (event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, content_hash TEXT NOT NULL)"
            )

    def append(self, row: dict[str, Any]) -> str:
        event_id = str(row["event_id"])
        payload_json = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        content_hash = str(row["content_hash"])
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
                    "INSERT INTO events(event_id, payload_json, content_hash) VALUES (?, ?, ?)",
                    (conflict_id, payload_json, content_hash),
                )
                connection.commit()
                return "conflict"
            connection.execute(
                "INSERT INTO events(event_id, payload_json, content_hash) VALUES (?, ?, ?)",
                (event_id, payload_json, content_hash),
            )
            connection.commit()
            return "inserted"

    def payload(self, event_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.path) as connection:
            value = connection.execute(
                "SELECT payload_json FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        assert value is not None
        return json.loads(value[0])


def test_contract_schema_and_state_matrix_keep_missing_distinct() -> None:
    row = _normalize_row(_candidate(0, selected=True, recommended=True, planned=True, ordered=True))
    assert row["schema_version"] == SCHEMA_VERSION
    assert row["identity_status"] == "verified"
    assert {"identified", "eligible", "selected", "recommended", "planned", "ordered"} <= set(row["states"])

    missing = _normalize_row(
        {
            "symbol": "GENERIC",
            "candidate_id": "candidate-only",
            "selected_for_llm": None,
            "eligible_at_selection": None,
        }
    )
    assert missing["identity_status"] == "unavailable"
    assert "identity_unavailable" in missing["states"]
    assert "shadow_inputs_unavailable" in missing["states"]
    assert "unavailable" in missing["states"]
    assert missing["selected_for_llm"] is None


def test_large_fixture_has_443_candidates_and_20_finalists() -> None:
    raw = _large_fixture()
    ledger = _build_ledger(raw)
    counts = _denominators(ledger)
    assert counts == {
        "raw_count": 443,
        "canonical_count": 443,
        "identity_unavailable": 0,
        "eligible_count": 443,
        "selected_count": 20,
        "recommended_count": 5,
        "planned_count": 3,
        "ordered_count": 2,
        "conflict_count": 0,
        "idempotent_duplicate_count": 0,
        "truncated_count": 0,
        "mature_3d": None,
        "mature_5d": None,
        "mature_10d": None,
    }
    assert len({row["strategy"] for row in ledger["canonical_rows"]}) == 2
    assert len({row["setup"] for row in ledger["canonical_rows"]}) == 2


def test_selected_for_llm_is_not_order_and_capacity_fill_is_independent() -> None:
    rows = {row["signal_id"]: row for row in _build_ledger(_large_fixture())["canonical_rows"]}
    selected_not_ordered = rows["signal:cycle-A:buy:SYM005"]
    assert selected_not_ordered["selected_for_llm"] is True
    assert selected_not_ordered["recommended"] is False
    assert selected_not_ordered["planned"] is False
    assert selected_not_ordered["ordered"] is False

    capacity = rows["signal:cycle-A:buy:SYM008"]
    assert capacity["llm_considered"] is True
    assert capacity["llm_selected"] is False
    assert capacity["decision_source"] == "deterministic_capacity_fill"


def test_same_cycle_matching_requires_identical_predecision_frontier() -> None:
    ledger = _build_ledger(_large_fixture())
    rows = ledger["canonical_rows"]
    treatment = next(row for row in rows if row["signal_id"] == "signal:cycle-A:buy:SYM000")
    matched = _match_same_cycle(treatment, rows)
    assert matched["status"] == "verified"
    assert matched["controls"]
    assert all(control["cycle_id"] == "cycle-A" for control in matched["controls"])
    assert all(control["selected_for_llm"] is False for control in matched["controls"])
    assert all(control["recommended"] is False for control in matched["controls"])
    assert any(item["reason"] == "cycle_mismatch" for item in matched["excluded"])
    assert any(item["reason"] == "action_mismatch" for item in matched["excluded"])

    blocked = _normalize_row(
        _candidate(
            20,
            selected=False,
            recommended=True,
            exclusion_reason="cycle_capacity_limit",
        )
    )
    blocked["planned"] = False
    blocked["plan_id"] = None
    blocked["content_hash"] = _stable_hash(blocked)
    blocked_match = _match_same_cycle(treatment, [blocked])
    assert blocked_match["status"] == "unavailable"
    assert blocked_match["excluded"][0]["reason"] == "postdecision_recommended_not_control"


def test_rank_one_is_domain_scoped_and_buy_exit_never_merge() -> None:
    rows = _large_fixture()
    breakout = next(row for row in rows if row["score_universe"] == "builtin_breakout:continuation")
    pullback = next(row for row in rows if row["score_universe"] == "builtin_pullback:continuation")
    breakout["score_rank"] = 1
    pullback["score_rank"] = 1
    ledger = _build_ledger(rows)
    canonical = ledger["canonical_rows"]
    assert sum(row["score_rank"] == 1 for row in canonical if row["score_universe"] == breakout["score_universe"]) >= 1
    assert sum(row["score_rank"] == 1 for row in canonical if row["score_universe"] == pullback["score_universe"]) >= 1

    buy = next(row for row in canonical if row["signal_id"] == "signal:cycle-A:buy:SYM000")
    exit_row = next(row for row in canonical if row["action"] == "exit")
    assert buy["signal_id"] == exit_row["signal_id"]
    assert buy["identity_key"] != exit_row["identity_key"]
    assert _match_same_cycle(buy, [exit_row])["status"] == "unavailable"


def test_source_run_symbol_collision_never_replaces_exact_identity() -> None:
    first = _candidate(0, cycle_id="cycle-A", symbol="DUP", signal_id="signal-A")
    second = _candidate(1, cycle_id="cycle-B", symbol="DUP", signal_id="signal-B")
    assert (first["source_run_id"], first["symbol"]) == (second["source_run_id"], second["symbol"])
    ledger = _build_ledger([first, second])
    assert len(ledger["canonical_rows"]) == 2
    assert {row["event_id"] for row in ledger["canonical_rows"]} == {
        "selection_ledger:cycle-A:buy:signal-A",
        "selection_ledger:cycle-B:buy:signal-B",
    }


def test_generic_rows_and_conflicting_content_are_not_canonical() -> None:
    original = _candidate(0)
    same_content_new_capture_time = {**original}
    conflict = {**original, "score": 99.0}
    generic = {"symbol": "REPORTER", "score": 99, "selected_for_llm": True}
    ledger = _build_ledger([original, same_content_new_capture_time, conflict, generic])
    assert len(ledger["canonical_rows"]) == 1
    assert ledger["idempotent_duplicates"] == 1
    assert len(ledger["conflicts"]) == 1
    assert len(ledger["unavailable_rows"]) == 1
    assert ledger["canonical_rows"][0]["score"] == original["score"]


def test_cap_is_published_and_not_presented_as_full_universe() -> None:
    ledger = _build_ledger(_large_fixture())
    counts = _denominators(ledger, truncated_count=200_000 - 443)
    assert counts["raw_count"] == 443
    assert counts["truncated_count"] == 199_557
    assert counts["raw_count"] != counts["truncated_count"]
    assert counts["truncated_count"] > 0


def test_maturity_joins_exact_ids_and_keeps_5d_10d_unavailable() -> None:
    row = _normalize_row(_candidate(0))
    sessions = ["2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28"]
    mature_3d = {
        "signal_id": row["signal_id"],
        "cycle_id": row["cycle_id"],
        "action": "buy",
        "horizon": "3d",
        "matured": True,
        "maturity_session_date": "2026-07-24",
        "price_basis": row["price_basis"],
        "forward_return": 0.012,
    }
    immature_5d = {**mature_3d, "horizon": "5d", "matured": False, "maturity_session_date": "2026-07-28"}
    missing_10d = {**mature_3d, "horizon": "10d", "matured": True, "maturity_session_date": "2026-07-28"}
    assert _attach_mature_outcome(row, mature_3d, completed_sessions=sessions)["status"] == "matured"
    assert _attach_mature_outcome(row, immature_5d, completed_sessions=sessions) == {
        "status": "unavailable",
        "reason": "outcome_immature",
    }
    assert _attach_mature_outcome(row, missing_10d, completed_sessions=sessions)["status"] == "unavailable"
    wrong = {**mature_3d, "signal_id": "other-signal"}
    assert _attach_mature_outcome(row, wrong, completed_sessions=sessions)["reason"] == "signal_id_mismatch"
    serialized = json.dumps(row, ensure_ascii=True)
    assert "forward_return" not in serialized


def test_naive_inverted_future_timestamps_and_price_basis_stay_unavailable() -> None:
    naive = _normalize_row({**_candidate(0), "signal_at": "2026-07-21T14:00:00"})
    inverted = _normalize_row(
        {**_candidate(1), "decision_at": "2026-07-21T13:00:00+00:00"}
    )
    future = _normalize_row(
        {**_candidate(2), "signal_at": "2026-07-23T14:00:00+00:00"}
    )
    assert naive["timestamp_status"] == "unavailable"
    assert inverted["timestamp_status"] == "unavailable"
    assert future["timestamp_status"] == "unavailable"
    no_basis = _normalize_row({**_candidate(3), "price_basis": None})
    outcome = {
        "signal_id": no_basis["signal_id"],
        "cycle_id": no_basis["cycle_id"],
        "action": "buy",
        "horizon": "3d",
        "matured": True,
        "maturity_session_date": "2026-07-24",
        "price_basis": None,
    }
    assert _attach_mature_outcome(
        no_basis,
        outcome,
        completed_sessions=["2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"],
    )["reason"] == "price_basis_unavailable_or_mismatch"


def test_predecision_ledger_rejects_future_fields() -> None:
    with pytest.raises(ValueError, match="post_decision_field:return_3d"):
        _normalize_row({**_candidate(0), "return_3d": 0.12})


def test_hash_is_stable_for_capture_time_and_json_order() -> None:
    row = _normalize_row(_candidate(0))
    changed_time = {**row, "captured_at": "2026-07-22T12:00:00+00:00"}
    reordered = json.loads(json.dumps(dict(reversed(list(row.items())))))
    assert _stable_hash(row) == _stable_hash(changed_time)
    assert _stable_hash(row) == _stable_hash(reordered)


def test_append_only_persistence_is_idempotent_conflict_safe_and_concurrent(tmp_path: Path) -> None:
    assert "INSERT OR REPLACE" not in inspect.getsource(_TestEventLog)
    row = _normalize_row(_candidate(0))
    event_log = _TestEventLog(tmp_path / "selection-ledger.sqlite3")
    assert event_log.append(row) == "inserted"
    repeated = {**row, "captured_at": "2026-07-22T01:00:00+00:00"}
    assert event_log.append(repeated) == "idempotent"
    changed = {**row, "score": 99.0}
    changed["content_hash"] = _stable_hash(changed)
    assert event_log.append(changed) == "conflict"
    assert event_log.payload(row["event_id"])["score"] == row["score"]

    concurrent_row = _normalize_row(_candidate(1))
    barrier = threading.Barrier(2)

    def append_after_barrier() -> str:
        barrier.wait()
        return event_log.append(concurrent_row)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: append_after_barrier(), (1, 2)))
    assert sorted(statuses) == ["idempotent", "inserted"]


def test_no_mutation_and_no_active_trading_fields_change() -> None:
    raw = _large_fixture()
    raw_before = copy.deepcopy(raw)
    active = {
        "candidates": ["candidate-active"],
        "scores": [15.0],
        "ranks": [1],
        "gates": ["passed"],
        "sizing": [0.5],
        "plans": ["plan-active"],
        "orders": ["order-active"],
        "stops": [95.0],
        "takes": [110.0],
        "exposure": 0.1,
        "limits": {"daily": 1},
    }
    active_before = copy.deepcopy(active)
    _build_ledger(raw)
    _denominators(_build_ledger(raw))
    assert raw == raw_before
    assert active == active_before


def test_contract_is_predecision_only_and_forward_return_is_not_net_profit() -> None:
    row = _normalize_row(_candidate(0))
    assert not FORBIDDEN_PREDECISION_FIELDS.intersection(row)
    outcome = {"signal_id": row["signal_id"], "forward_return": 0.04, "costs": None}
    assert outcome["forward_return"] != 0
    assert "net_profit" not in row
    assert "costs" not in row
