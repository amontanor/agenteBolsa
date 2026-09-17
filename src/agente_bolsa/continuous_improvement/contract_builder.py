"""Deterministic evidence-contract provider for the improvement lab (P-L120).

Problem: `cast_governance.json` sets `contract_required_all=true`, but the LLM
proposers (OrchestratorAgent, SoftwareReliabilityAgent) emit prose without a
measurable contract. Result: 100% `proposal_contract_violation` (400/400 rows
share the same 12 failures) and the learning loop never closes.

This module never invents measurements. It reuses contracts already built and
validated by the deterministic `findings_to_proposals` bridge and attaches them
to runtime raw proposals with an EXACT target match. Anything unmeasurable stays
unadmitted (`admissible=False` with reasons); `None`/missing is never turned
into zero or a guessed value.
"""
from __future__ import annotations

from typing import Any

from .codegen import _is_low_risk_codegen_path
from .proposal_contract import validate_experiment_contract

#: Proposal classes this provider may complete. Trading-affecting proposals are
#: deferred to L3 (promotion loop); only low-risk CODE_CHANGE may be completed.
COMPLETABLE_PROPOSAL_TYPES = frozenset({"CODE_CHANGE"})


def bridge_contracts_by_target(
    settings: Any,
    store: Any,
    *,
    origin_run_id: str,
    source_event_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map target_identifier -> validated experiment contract from the bridge."""
    from .findings_to_proposals import build_code_change_candidates, measured_findings

    findings = measured_findings(
        settings,
        store,
        origin_run_id=origin_run_id,
        source_event_ids=list(source_event_ids or []),
    )
    contracts: dict[str, dict[str, Any]] = {}
    for candidate in build_code_change_candidates(findings):
        target = str(candidate.get("target_identifier") or "").strip()
        contract = candidate.get("experiment_contract")
        if not target or not isinstance(contract, dict):
            continue
        probe = {
            "proposal_type": "CODE_CHANGE",
            "target_component": str(candidate.get("target_component") or ""),
            "target_identifier": target,
            "payload": {
                "expected_impact": str(candidate.get("expected_impact") or ""),
                "proposed_value": str(candidate.get("proposed_value") or ""),
                "target_files": [target],
                "experiment_contract": contract,
            },
        }
        if validate_experiment_contract(probe)["valid"]:
            contracts[target] = contract
    return contracts


def attach_bridge_contract(
    raw: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach a validated bridge contract to one raw proposal on exact match."""
    outcome: dict[str, Any] = {"attached": False, "reasons": []}
    proposal_type = str(raw.get("proposal_type") or "").upper()
    if proposal_type not in COMPLETABLE_PROPOSAL_TYPES:
        outcome["reasons"].append(f"proposal_type_deferred:{proposal_type or 'vacio'}")
        return dict(raw), outcome
    if (raw.get("payload") or raw).get("experiment_contract"):
        outcome["reasons"].append("contract_already_present")
        return dict(raw), outcome
    target = str(raw.get("target_identifier") or "").strip().replace("\\", "/")
    contract = contracts.get(target)
    if contract is None:
        outcome["reasons"].append("no_measured_evidence_for_target")
        return dict(raw), outcome
    if not _is_low_risk_codegen_path(target):
        outcome["reasons"].append(f"target_outside_low_risk_allowlist:{target}")
        return dict(raw), outcome
    contract_targets = [str(p).replace("\\", "/") for p in (contract.get("target_paths") or [])]
    if target not in contract_targets:
        outcome["reasons"].append("contract_target_mismatch")
        return dict(raw), outcome
    enriched = dict(raw)
    enriched["experiment_contract"] = dict(contract)
    payload = dict(raw.get("payload") or {})
    payload["experiment_contract"] = dict(contract)
    enriched["payload"] = payload
    outcome["attached"] = True
    return enriched, outcome


def enrich_raws(
    raws: list[dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Attach bridge contracts to every exactly-matched raw proposal."""
    enriched: list[dict[str, Any]] = []
    attached = 0
    for raw in raws:
        new_raw, outcome = attach_bridge_contract(raw, contracts)
        enriched.append(new_raw)
        if outcome["attached"]:
            attached += 1
    return enriched, {"attached": attached, "unbuildable": len(raws) - attached}
