"""Stable decision lineage shared by signals, plans and broker payloads."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def _slug(value: Any) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").upper()).strip("_")


def _date_text(value: Any) -> str:
    text = str(value or "")
    return text[:10] if text else datetime.now(timezone.utc).date().isoformat()


def signal_id_for_candidate(source: str, candidate: dict[str, Any]) -> str:
    symbol = _slug(candidate.get("symbol"))
    strategy = _slug(candidate.get("strategy_name") or "unknown")
    signal_date = _date_text(
        candidate.get("last_date")
        or ((candidate.get("technical_state") or {}).get("last_date"))
    )
    return f"{source}:{signal_date}:{strategy}:{symbol}"


def _candidate_for_symbol(technical_context: dict[str, Any], symbol: str) -> tuple[dict[str, Any] | None, int | None]:
    normalized = str(symbol or "").upper().strip()
    for bucket in ("selected_candidates", "top_longs", "all_candidates"):
        for index, candidate in enumerate(list((technical_context or {}).get(bucket) or []), start=1):
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("symbol") or "").upper().strip() == normalized:
                rank = candidate.get("selection_rank")
                return candidate, int(rank) if isinstance(rank, (int, float)) else index
    return None, None


def normalized_decision_source(recommendation: Any) -> str:
    origin = str(getattr(recommendation, "decision_origin", "") or "").lower()
    source = str(getattr(recommendation, "source", "") or "").lower()
    capacity_code = str(getattr(recommendation, "capacity_fill_reason_code", "") or "")
    if capacity_code or "capacity_fill" in origin or "capacity_fill" in source:
        return "capacity_fill"
    if "deterministic" in origin or "deterministic" in source or "fallback" in origin:
        return "deterministic"
    return "llm"


def build_decision_lineage(
    recommendation: Any,
    technical_context: dict[str, Any],
    *,
    cycle_id: str,
    policy_version: str,
    default_cohort: str | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    symbol = str(getattr(recommendation, "symbol", "") or "").upper().strip()
    candidate, candidate_rank = _candidate_for_symbol(technical_context, symbol)
    candidate = candidate or {}
    strategy_name = str(
        getattr(recommendation, "strategy_name", "")
        or candidate.get("strategy_name")
        or ""
    ).strip()
    strategy_version = str(candidate.get("strategy_version") or "").strip() or None
    cohort = str(getattr(recommendation, "cohort", "") or default_cohort or "").strip() or None
    signal_source = cohort or "operational"
    signal_id = signal_id_for_candidate(
        signal_source,
        {**candidate, "symbol": symbol, "strategy_name": strategy_name or "unknown"},
    )
    decision_source = normalized_decision_source(recommendation)
    low_sample = "low_sample_exploration" in {
        str(item) for item in [
            *list(getattr(recommendation, "tags", []) or []),
            *list(getattr(recommendation, "soft_override_reasons", []) or []),
        ]
    }
    verified = bool(candidate and strategy_name and cycle_id and signal_id)
    candidate_id = None
    if cycle_id and signal_id:
        candidate_identity = "|".join((str(cycle_id), str(signal_id), str(source_run_id or "")))
        candidate_id = f"cand_{hashlib.sha256(candidate_identity.encode('utf-8')).hexdigest()[:24]}"
    fingerprint = "|".join((cycle_id, signal_id, decision_source, policy_version))
    return {
        "lineage_id": f"lineage_{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]}",
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "cycle_id": cycle_id,
        "policy_version": policy_version,
        "strategy_name": strategy_name or None,
        "strategy_version": strategy_version,
        "decision_source": decision_source,
        "cohort": cohort,
        "low_sample_exploration": low_sample,
        "candidate_rank": candidate_rank,
        "lineage_status": "verified" if verified else "legacy_unverified",
    }


def legacy_unverified_lineage(*, cycle_id: str | None = None, signal_id: str | None = None) -> dict[str, Any]:
    return {
        "lineage_id": None,
        "signal_id": signal_id,
        "cycle_id": cycle_id,
        "policy_version": None,
        "strategy_name": None,
        "strategy_version": None,
        "decision_source": None,
        "cohort": None,
        "low_sample_exploration": False,
        "candidate_rank": None,
        "lineage_status": "legacy_unverified",
    }
