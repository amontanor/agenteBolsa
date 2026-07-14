"""Stable decision lineage shared by signals, plans and broker payloads."""

from __future__ import annotations

import hashlib
from typing import Any

from .signal_identity import canonical_identity


def _slug(value: Any) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").upper()).strip("_")


def _candidate_for_symbol(
    technical_context: dict[str, Any],
    symbol: str,
    strategy_name: str | None = None,
) -> tuple[dict[str, Any] | None, int | None]:
    normalized = str(symbol or "").upper().strip()
    normalized_strategy = str(strategy_name or "").strip().lower()
    matches: dict[tuple[str, str, str, str], tuple[dict[str, Any], int]] = {}
    for bucket in ("selected_candidates", "top_longs", "all_candidates"):
        for index, candidate in enumerate(list((technical_context or {}).get(bucket) or []), start=1):
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("symbol") or "").upper().strip() == normalized:
                candidate_strategy = str(
                    candidate.get("signal_strategy_name") or candidate.get("strategy_name") or ""
                ).strip().lower()
                if normalized_strategy and candidate_strategy != normalized_strategy:
                    continue
                rank = candidate.get("selection_rank")
                identity_key = (
                    str(candidate.get("signal_id") or "").strip(),
                    str(candidate.get("signal_capture_id") or "").strip(),
                    str(candidate.get("signal_source_run_id") or "").strip(),
                    candidate_strategy,
                )
                matches.setdefault(
                    identity_key,
                    (candidate, int(rank) if isinstance(rank, (int, float)) else index),
                )
    if len(matches) == 1:
        return next(iter(matches.values()))
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
    strategy_name = str(
        getattr(recommendation, "strategy_name", "")
        or ""
    ).strip()
    candidate, candidate_rank = _candidate_for_symbol(technical_context, symbol, strategy_name or None)
    candidate = candidate or {}
    strategy_name = strategy_name or str(candidate.get("strategy_name") or "").strip()
    strategy_version = str(candidate.get("strategy_version") or "").strip() or None
    cohort = str(getattr(recommendation, "cohort", "") or default_cohort or "").strip() or None
    identity = canonical_identity(candidate)
    signal_id = identity["signal_id"]
    decision_source = normalized_decision_source(recommendation)
    low_sample = "low_sample_exploration" in {
        str(item) for item in [
            *list(getattr(recommendation, "tags", []) or []),
            *list(getattr(recommendation, "soft_override_reasons", []) or []),
        ]
    }
    verified = bool(candidate and signal_id and identity["signal_source_run_id"] and cycle_id)
    candidate_id = str(candidate.get("candidate_id") or "").strip() or None
    if not candidate_id and cycle_id and signal_id:
        candidate_identity = "|".join((str(cycle_id), str(signal_id), str(source_run_id or "")))
        candidate_id = f"cand_{hashlib.sha256(candidate_identity.encode('utf-8')).hexdigest()[:24]}"
    fingerprint = "|".join((cycle_id, str(signal_id or ""), decision_source, policy_version))
    return {
        "lineage_id": f"lineage_{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]}",
        "signal_id": signal_id,
        "signal_capture_id": identity.get("signal_capture_id"),
        "signal_source_run_id": identity["signal_source_run_id"],
        "signal_date": identity.get("signal_date"),
        "symbol": symbol,
        "candidate_id": candidate_id,
        "cycle_id": cycle_id,
        "policy_version": policy_version,
        "strategy_name": identity["signal_strategy_name"] or strategy_name or None,
        "strategy_version": identity["signal_strategy_version"] or strategy_version,
        "decision_source": decision_source,
        "cohort": cohort,
        "low_sample_exploration": low_sample,
        "candidate_rank": candidate_rank,
        "lineage_status": "verified" if verified else "unavailable",
        "lineage_reason": (
            None
            if verified
            else (
                "missing_canonical_signal_id"
                if not signal_id
                else "missing_signal_source_run_id"
                if not identity["signal_source_run_id"]
                else "missing_cycle_id"
            )
        ),
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
