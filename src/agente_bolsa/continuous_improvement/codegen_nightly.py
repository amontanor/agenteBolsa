"""Nightly codegen orchestrator for review-only diffs."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.logging_utils import log_system_event
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .agents import (
    self_governance_modification_violation,
    self_safety_modification_violation,
)
from .aggressiveness_gate import assess_aggressiveness_evidence
from .codegen import (
    _candidate_paths_from_proposal,
    _is_low_risk_codegen_path,
    generate_code_diff_for_proposal,
)

DEFAULT_CODEGEN_NIGHTLY_CONFIG_PATH = Path("data/config/codegen_nightly.json")
CODEGEN_NIGHTLY_RUN_LOG = Path("research/codegen_nightly/runs.jsonl")
CODEGEN_NIGHTLY_ACTOR = "CodegenNightly"
CODEGEN_NIGHTLY_CLEANUP_ACTOR = "CodegenNightlyCleanup"
DEMO_CLEANUP_PROPOSAL_ID = "ci_prop_codegen_demo_51f112150ca0"
P15_HOTFIX_PROPOSAL_ID = "ci_prop_p15_core_sleeve_null_order_digest"
P15_HOTFIX_COMMIT = "fa126d40"
TERMINAL_STATUSES = {"APPLIED", "ARCHIVED", "BLOCKED", "DUPLICATE", "REJECTED", "REJECTED_BY_TESTS", "ROLLED_BACK"}

CodegenGenerator = Callable[..., dict[str, Any]]

DEFAULT_CODEGEN_NIGHTLY_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_proposals_per_day": 2,
    "daily_token_budget": 64000,
    "estimated_tokens_per_proposal": 32000,
    "human_gated": True,
    "notes": "Parametros fuera del allowlist de codegen; solo Antonio debe cambiar cupos.",
}


def load_codegen_nightly_config(config_path: Path, *, create: bool = True) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        if not create:
            return dict(DEFAULT_CODEGEN_NIGHTLY_CONFIG)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CODEGEN_NIGHTLY_CONFIG, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return dict(DEFAULT_CODEGEN_NIGHTLY_CONFIG)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raw = {}
    config = dict(DEFAULT_CODEGEN_NIGHTLY_CONFIG)
    if isinstance(raw, dict):
        config.update(raw)
    config["max_proposals_per_day"] = max(0, int(config.get("max_proposals_per_day") or 0))
    config["daily_token_budget"] = max(0, int(config.get("daily_token_budget") or 0))
    config["estimated_tokens_per_proposal"] = max(1, int(config.get("estimated_tokens_per_proposal") or 1))
    config["enabled"] = bool(config.get("enabled"))
    config["human_gated"] = bool(config.get("human_gated", True))
    return config


def run_codegen_nightly(
    *,
    settings: Settings,
    store: Store,
    config_path: Path | None = None,
    generator: CodegenGenerator | None = None,
    now: datetime | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Generate reviewable diffs for eligible proposals. Never approves or applies."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    config_path = config_path or settings.data_dir / "config" / "codegen_nightly.json"
    config = load_codegen_nightly_config(config_path)
    cleanup_report = cleanup_codegen_states(store) if cleanup else {"changed": [], "checks": [], "inconsistent": []}
    log_path = settings.data_dir / CODEGEN_NIGHTLY_RUN_LOG

    base_result: dict[str, Any] = {
        "run_id": new_id("ci_codegen_nightly"),
        "created_at": now.isoformat(),
        "config_path": str(config_path),
        "config": {
            "enabled": config["enabled"],
            "max_proposals_per_day": config["max_proposals_per_day"],
            "daily_token_budget": config["daily_token_budget"],
            "estimated_tokens_per_proposal": config["estimated_tokens_per_proposal"],
            "human_gated": config["human_gated"],
        },
        "cleanup": cleanup_report,
        "attempts": [],
        "successes": 0,
        "failures": 0,
        "skipped": [],
        "ready_for_human_review": [],
        "approved_or_applied": False,
    }
    if settings.allow_auto_apply_improvements is not False:
        result = {
            **base_result,
            "ok": False,
            "status": "BLOCKED_AUTO_APPLY_ENABLED",
            "reason": "ALLOW_AUTO_APPLY_IMPROVEMENTS debe estar false para generar diffs nightly.",
        }
        _record_codegen_nightly_run(log_path, result)
        log_system_event(settings.logs_dir, "codegen_nightly_blocked", result)
        return result
    if config["human_gated"] is not True:
        result = {
            **base_result,
            "ok": False,
            "status": "BLOCKED_HUMAN_GATE_DISABLED",
            "reason": "human_gated debe permanecer true; los cupos requieren edicion humana explicita.",
        }
        _record_codegen_nightly_run(log_path, result)
        log_system_event(settings.logs_dir, "codegen_nightly_blocked", result)
        return result
    if not config["enabled"]:
        result = {**base_result, "ok": True, "status": "DISABLED", "reason": "codegen nightly deshabilitado por config."}
        _record_codegen_nightly_run(log_path, result)
        log_system_event(settings.logs_dir, "codegen_nightly_run", result)
        return result

    prior = _runs_for_day(log_path, now.date().isoformat())
    prior_attempts = sum(len(item.get("attempts") or []) for item in prior)
    prior_tokens = sum(int(item.get("estimated_tokens_used") or 0) for item in prior)
    max_remaining = max(0, int(config["max_proposals_per_day"]) - prior_attempts)
    token_remaining = max(0, int(config["daily_token_budget"]) - prior_tokens)
    estimate = int(config["estimated_tokens_per_proposal"])
    eligible_report = eligible_codegen_proposals(settings=settings, store=store)
    selected = []
    for item in eligible_report["eligible"]:
        if len(selected) >= max_remaining:
            break
        if token_remaining < estimate:
            base_result["skipped"].append(
                {"proposal_id": item["proposal_id"], "reason": "token_budget_exhausted", "token_remaining": token_remaining}
            )
            break
        selected.append(item)
        token_remaining -= estimate

    run_generator = generator or generate_code_diff_for_proposal
    estimated_tokens_used = 0
    for item in selected:
        proposal_id = str(item["proposal_id"])
        try:
            result = run_generator(settings=settings, store=store, proposal_id=proposal_id)
        except Exception as exc:  # noqa: BLE001 - nightly records failures and continues with the next proposal.
            result = {"ok": False, "status": "FAILED", "error": str(exc)}
        status = str(result.get("status") or "UNKNOWN")
        artifact = result.get("artifact") or {}
        attempt = {
            "proposal_id": proposal_id,
            "status": status,
            "ok": bool(result.get("ok")),
            "artifact_id": artifact.get("artifact_id"),
            "artifact_type": artifact.get("artifact_type"),
            "error": result.get("error"),
        }
        base_result["attempts"].append(attempt)
        estimated_tokens_used += estimate
        if status == "READY_FOR_HUMAN_REVIEW":
            base_result["successes"] += 1
            base_result["ready_for_human_review"].append(proposal_id)
        else:
            base_result["failures"] += 1

    result = {
        **base_result,
        "ok": True,
        "status": "COMPLETED",
        "eligible": len(eligible_report["eligible"]),
        "ineligible": eligible_report["ineligible"],
        "selected": len(selected),
        "daily_prior_attempts": prior_attempts,
        "estimated_tokens_used": estimated_tokens_used,
    }
    _record_codegen_nightly_run(log_path, result)
    log_system_event(settings.logs_dir, "codegen_nightly_run", result)
    return result


def eligible_codegen_proposals(*, settings: Settings, store: Store, limit: int = 200) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    for summary in store.continuous_improvement_proposals(status="READY_TO_APPLY", limit=limit):
        proposal = store.continuous_improvement_proposal(str(summary["proposal_id"])) or summary
        reason = _ineligible_reason(settings=settings, store=store, proposal=proposal)
        item = {"proposal_id": proposal.get("proposal_id"), "target": proposal.get("target_identifier")}
        if reason:
            ineligible.append({**item, "reason": reason})
        else:
            eligible.append(item)
    return {"eligible": eligible, "ineligible": ineligible}


def cleanup_codegen_states(store: Store) -> dict[str, Any]:
    changed: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    demo = store.continuous_improvement_proposal(DEMO_CLEANUP_PROPOSAL_ID)
    if demo and str(demo.get("status") or "").upper() not in TERMINAL_STATUSES:
        store.update_continuous_improvement_proposal_status(
            DEMO_CLEANUP_PROPOSAL_ID,
            status="REJECTED",
            actor=CODEGEN_NIGHTLY_CLEANUP_ACTOR,
            reason="demo_cleanup",
            payload={"cleanup": "demo_cleanup"},
        )
        changed.append({"proposal_id": DEMO_CLEANUP_PROPOSAL_ID, "status": "REJECTED", "reason": "demo_cleanup"})
    p15 = store.continuous_improvement_proposal(P15_HOTFIX_PROPOSAL_ID)
    p15_ok = False
    if p15:
        p15_ok = str(p15.get("status") or "").upper() == "APPLIED"
        decisions = store.continuous_improvement_decisions(proposal_id=P15_HOTFIX_PROPOSAL_ID, limit=20)
        p15_ok = p15_ok and any(P15_HOTFIX_COMMIT in json.dumps(item, ensure_ascii=False) for item in decisions)
    checks.append(
        {
            "proposal_id": P15_HOTFIX_PROPOSAL_ID,
            "ok": p15_ok,
            "expected_status": "APPLIED",
            "expected_commit": P15_HOTFIX_COMMIT,
        }
    )
    return {"changed": changed, "checks": checks, "inconsistent": [] if p15_ok else [checks[-1]]}


def latest_codegen_nightly_run(data_dir: Path) -> dict[str, Any]:
    log_path = data_dir / CODEGEN_NIGHTLY_RUN_LOG
    if not log_path.exists():
        return {"available": False, "reason": f"{log_path} no existe"}
    latest: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            latest = item
    if latest is None:
        return {"available": False, "reason": f"{log_path} sin JSON valido"}
    return {"available": True, **latest}


def _ineligible_reason(*, settings: Settings, store: Store, proposal: dict[str, Any]) -> str | None:
    if str(proposal.get("proposal_type") or "").upper() != "CODE_CHANGE":
        return "not_code_change"
    if not _has_positive_validation(proposal):
        return "no_positive_validation"
    targets = _candidate_paths_from_proposal(proposal)
    if not targets:
        return "no_targets"
    if any(not _is_low_risk_codegen_path(path) for path in targets):
        return "target_outside_codegen_allowlist"
    if _has_previous_codegen_rejection(store, str(proposal.get("proposal_id") or "")):
        return "previous_codegen_rejection"
    payload = proposal.get("payload") or {}
    target_component = str(proposal.get("target_component") or payload.get("target_component") or "")
    target_identifier = str(proposal.get("target_identifier") or payload.get("target_identifier") or "")
    if self_safety_modification_violation(
        target_component=target_component,
        target_identifier=target_identifier,
        payload=payload,
    ):
        return "self_safety_violation"
    if self_governance_modification_violation(
        target_component=target_component,
        target_identifier=target_identifier,
        payload=payload,
    ):
        return "self_governance_violation"
    assessment = assess_aggressiveness_evidence(proposal, settings=settings, store=store)
    if assessment.requires_evidence and not assessment.has_edge_evidence:
        return "aggressiveness_without_edge_evidence"
    return None


def _has_positive_validation(proposal: dict[str, Any]) -> bool:
    positive = {"READY_TO_APPLY", "PASSED", "READY_FOR_HUMAN_REVIEW"}
    for validation in proposal.get("validations") or []:
        if str(validation.get("status") or "").upper() in positive:
            return True
        payload = validation.get("payload") or {}
        if str(payload.get("objective_status") or "").upper() in positive:
            return True
    return False


def _has_previous_codegen_rejection(store: Store, proposal_id: str) -> bool:
    if not proposal_id:
        return True
    for decision in store.continuous_improvement_decisions(proposal_id=proposal_id, limit=100):
        if str(decision.get("decision") or "").upper() in {"REJECTED", "REJECTED_BY_TESTS", "BLOCKED"}:
            return True
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT artifact_type, payload_json
            FROM continuous_improvement_proposal_artifacts
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            """,
            (proposal_id,),
        ).fetchall()
    for row in rows:
        artifact_type = str(row["artifact_type"] or "")
        payload = json.loads(row["payload_json"] or "{}")
        if artifact_type == "code_diff_human_approval_rejected":
            return True
        if str(payload.get("status") or "").upper() in {"REJECTED_BY_HUMAN_REVIEW", "REJECTED", "BLOCKED_BY_HUMAN_REVIEW"}:
            return True
    return False


def _record_codegen_nightly_run(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=True, sort_keys=True, default=str))
        handle.write("\n")


def _runs_for_day(path: Path, day: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(item.get("created_at") or "")[:10] == day:
            rows.append(item)
    return rows
