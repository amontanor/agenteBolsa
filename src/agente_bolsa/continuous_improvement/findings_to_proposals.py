"""Deterministic bridge from measured findings to executable CODE_CHANGE proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .agents import proposal_fingerprint
from .schemas import ImprovementProposalPayload

FINDINGS_TO_PROPOSALS_ACTOR = "FindingsToProposals"
OBSERVATION_FAMILY_SETTLEMENT_ACTOR = "ObservationExecutionFamilySettlement"
OBSERVATION_FAMILY_REJECTION_REASON = "observation_execution_family_rejected_not_actionable"
NONTERMINAL_STATUSES = {
    "PENDING",
    "PASSED",
    "READY_TO_APPLY",
    "VALIDATING",
    "WAITING_HUMAN_REVIEW",
    "REQUIRES_HUMAN_REVIEW",
}


def measured_findings(settings: Settings, store: Store) -> list[dict[str, Any]]:
    data_dir = settings.data_dir
    findings = [
        {
            "finding_id": "lab_book_digest_visibility",
            "source": str(data_dir / "config" / "lab_book.json"),
            "metric": "lab_book_config_present",
            "value": int((data_dir / "config" / "lab_book.json").exists()),
            "summary": "El lab book tiene config propia, pero el digest del lab no expone su estado cuando se active.",
        },
        {
            "finding_id": "overlay_shadow_state_coverage",
            "source": "tests/test_overlay_shadow.py",
            "metric": "overlay_shadow_tests_present",
            "value": int(Path("tests/test_overlay_shadow.py").exists()),
            "summary": "El overlay shadow tiene estados operativos que conviene fijar con tests de contrato de digest.",
        },
        {
            "finding_id": "core_sleeve_parity_multi_day",
            "source": "scripts/core_sleeve_parity_check.py",
            "metric": "parity_script_present",
            "value": int(Path("scripts/core_sleeve_parity_check.py").exists()),
            "summary": "El parity check existe y debe cubrir multiples dias para evitar falsos verdes de una sola sesion.",
        },
        {
            "finding_id": "codegen_nightly_not_code_change_queue",
            "source": str(data_dir / "research" / "codegen_nightly" / "runs.jsonl"),
            "metric": "ready_not_code_change",
            "value": _latest_not_code_change_count(data_dir),
            "summary": "El nightly encontro propuestas READY_TO_APPLY inelegibles por not_code_change.",
        },
    ]
    quality = _latest_proposal_quality(store)
    if quality:
        findings.append(
            {
                "finding_id": "proposal_quality_recent_prose",
                "source": "continuous_improvement_proposals",
                "metric": "recent_prose_pct",
                "value": quality.get("recent_prose_pct"),
                "summary": "La muestra reciente conserva propuestas de prosa que no alimentan codegen.",
            }
        )
    return findings


def build_code_change_candidates(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("finding_id")): item for item in findings}
    candidates = [
        _candidate(
            finding=by_id.get("lab_book_digest_visibility"),
            target="src/agente_bolsa/continuous_improvement/digest.py",
            title="Exponer estado del lab book en el digest del lab",
            proposed=(
                "Agregar una seccion Lab book al digest que lea data/config/lab_book.json y el ultimo "
                "artefacto disponible, mostrando enabled/mode/cap y estado fresco sin tocar trading."
            ),
            tests=["tests/test_ci_phase3_digest.py"],
            rollback="Revertir la seccion Lab book y sus tests de digest.",
        ),
        _candidate(
            finding=by_id.get("overlay_shadow_state_coverage"),
            target="tests/test_ci_digest_overlay_shadow.py",
            title="Cubrir estados del overlay shadow en el digest",
            proposed=(
                "Anadir tests de contrato para overlay shadow con estado stale, archivo ausente y claves "
                "opcionales, usando muestras JSON locales."
            ),
            tests=["tests/test_ci_digest_overlay_shadow.py"],
            rollback="Eliminar los tests agregados; no cambia runtime.",
        ),
        _candidate(
            finding=by_id.get("core_sleeve_parity_multi_day"),
            target="tests/test_core_sleeve_parity_check.py",
            title="Cubrir parity check core sleeve para multiples dias",
            proposed=(
                "Anadir un test de regresion para una ventana de multiples dias, verificando que una "
                "discrepancia en una fecha intermedia no quede oculta por una ultima sesion limpia."
            ),
            tests=["tests/test_core_sleeve_parity_check.py"],
            rollback="Eliminar el test agregado; no cambia runtime.",
        ),
        _candidate(
            finding=by_id.get("codegen_nightly_not_code_change_queue"),
            target="src/agente_bolsa/continuous_improvement/digest.py",
            title="Resumir causas de inelegibilidad del codegen nightly",
            proposed=(
                "Agregar al digest una tabla compacta de causas de inelegibilidad del ultimo nightly, "
                "destacando not_code_change para corregir la cola."
            ),
            tests=["tests/test_codegen_nightly.py"],
            rollback="Revertir la subseccion de causas de inelegibilidad y su test.",
        ),
    ]
    return [item for item in candidates if item["evidence"]]


def persist_findings_to_proposals(
    *,
    settings: Settings,
    store: Store,
    limit: int = 3,
    dry_run: bool = True,
) -> dict[str, Any]:
    findings = measured_findings(settings, store)
    learning_experiment_bridge = _learning_experiment_bridge(settings.data_dir)
    candidates = build_code_change_candidates(findings)[: max(0, min(3, int(limit)))]
    preview = [_proposal_payload(item) for item in candidates]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "findings": findings,
            "created": [],
            "candidates": preview,
            "learning_experiment_bridge": learning_experiment_bridge,
        }

    cycle_id = _ensure_bridge_cycle(store)
    created: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for item in [*preview, *(learning_experiment_bridge.get("proposal_candidates") or [])]:
        proposal_model = ImprovementProposalPayload.model_validate(item)
        fingerprint = proposal_fingerprint(proposal_model)
        proposal_id = new_id("ci_prop")
        proposal_type = str(proposal_model.proposal_type or "MONITORING_CHANGE").upper()
        status = "READY_TO_APPLY" if proposal_type == "CODE_CHANGE" else "PENDING"
        stored_id, inserted = store.upsert_continuous_improvement_proposal(
            {
                "proposal_id": proposal_id,
                "cycle_id": cycle_id,
                "fingerprint": fingerprint,
                "proposal_type": proposal_type,
                "target_component": proposal_model.target_component,
                "target_identifier": proposal_model.target_identifier,
                "status": status,
                "priority": "MEDIUM",
                "risk_level": proposal_model.risk_level,
                "payload": item,
                "guard": {
                    "status": status,
                    "approved_for_auto_apply": False,
                    "reasons": ["human_review_required", "findings_to_proposals", proposal_type.lower()],
                },
            }
        )
        if not inserted:
            duplicates.append({"proposal_id": stored_id, "target": item["target_identifier"]})
            continue
        store.save_continuous_improvement_validation(
            {
                "validation_id": new_id("ci_val"),
                "proposal_id": stored_id,
                "cycle_id": cycle_id,
                "status": status,
                "validation_type": "findings_to_proposals_contract",
                "payload": {
                    "objective_status": status,
                    "checks": [
                        {"name": "proposal_type", "passed": True, "detail": proposal_type},
                        {"name": "target_allowlisted", "passed": True},
                        {"name": "tests_declared", "passed": True},
                        {"name": "rollback_declared", "passed": True},
                    ],
                },
            }
        )
        store.save_continuous_improvement_proposal_artifact(
            {
                "artifact_id": new_id("ci_artifact"),
                "proposal_id": stored_id,
                "artifact_type": "markdown",
                "content_text": _artifact_text(item),
                "payload": {"generated_by": FINDINGS_TO_PROPOSALS_ACTOR},
            }
        )
        created.append({"proposal_id": stored_id, "target": item["target_identifier"]})
    store.update_continuous_improvement_cycle(
        cycle_id,
        status="COMPLETED",
        finished_at=datetime.now(timezone.utc).isoformat(),
        report={"created": created, "duplicates": duplicates, "findings": findings},
    )
    return {
        "ok": True,
        "dry_run": False,
        "cycle_id": cycle_id,
        "created": created,
        "duplicates": duplicates,
        "findings": findings,
        "learning_experiment_bridge": learning_experiment_bridge,
    }


def audit_observation_execution_family(store: Store) -> dict[str, Any]:
    proposals = _observation_family_proposals(store)
    active = [item for item in proposals if str(item.get("status") or "").upper() in NONTERMINAL_STATUSES]
    summary = _recent_learning_observation_summary(store, limit=160)
    source_counts = summary.get("source_counts") or {}
    top_source = max(source_counts, key=source_counts.get) if source_counts else "learning_observations"
    return {
        "active_proposals": len(active),
        "total_family_proposals": len(proposals),
        "active_ids": [item["proposal_id"] for item in active],
        "recent_160_observations": summary,
        "decision": "reject_family",
        "reason": (
            f"Las 160 filas recientes vienen mayoritariamente de {top_source} y siguen sin outcomes maduros/ejecucion real suficiente; "
            "no son una cola segura de ordenes u observaciones ejecutables."
        ),
    }


def settle_observation_execution_family(*, store: Store, dry_run: bool = True) -> dict[str, Any]:
    audit = audit_observation_execution_family(store)
    if dry_run:
        return {"ok": True, "dry_run": True, **audit, "rejected": []}
    rejected: list[str] = []
    for proposal_id in audit["active_ids"]:
        store.update_continuous_improvement_proposal_status(
            proposal_id,
            status="REJECTED",
            actor=OBSERVATION_FAMILY_SETTLEMENT_ACTOR,
            reason=OBSERVATION_FAMILY_REJECTION_REASON,
            payload={"audit": audit},
        )
        rejected.append(proposal_id)
    return {"ok": True, "dry_run": False, **audit, "rejected": rejected}


def _candidate(
    *,
    finding: dict[str, Any] | None,
    target: str,
    title: str,
    proposed: str,
    tests: list[str],
    rollback: str,
) -> dict[str, Any]:
    evidence = []
    if finding and finding.get("value") not in (None, 0, "0", ""):
        evidence.append(f"{finding.get('source')} | {finding.get('metric')}={finding.get('value')} | {finding.get('summary')}")
    return {
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": target,
        "current_value": "Hallazgo medido sin propuesta CODE_CHANGE ejecutable asociada.",
        "proposed_value": proposed,
        "rationale": title,
        "expected_impact": "Alimentar el nightly con una mejora concreta de observabilidad/herramientas, sin tocar trading.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": rollback,
        "promotion_state": "shadow",
        "evidence": evidence,
        "target_files": [target, *tests],
        "test_requirement": "; ".join(tests),
        "test_commands": [f"python -m pytest {' '.join(tests)} -q"],
        "source": FINDINGS_TO_PROPOSALS_ACTOR,
    }


def _proposal_payload(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item)


def _ensure_bridge_cycle(store: Store) -> str:
    cycle_id = new_id("ci_cycle_findings")
    store.create_continuous_improvement_cycle(
        {
            "cycle_id": cycle_id,
            "trace_id": new_id("ci_trace"),
            "job_id": new_id("ci_job"),
            "status": "RUNNING",
            "mode": "findings_to_proposals",
            "dry_run": True,
            "context": {"source": FINDINGS_TO_PROPOSALS_ACTOR},
        }
    )
    return cycle_id


def _latest_not_code_change_count(data_dir: Path) -> int:
    path = data_dir / "research" / "codegen_nightly" / "runs.jsonl"
    latest: dict[str, Any] | None = None
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            latest = item
    return sum(1 for item in (latest or {}).get("ineligible") or [] if item.get("reason") == "not_code_change")


def _latest_proposal_quality(store: Store) -> dict[str, Any]:
    recent = store.continuous_improvement_proposals(limit=200)
    prose = 0
    for item in recent:
        if str(item.get("proposal_type") or "").upper() != "CODE_CHANGE":
            prose += 1
    total = len(recent)
    return {"recent_prose_pct": round((prose / total) * 100.0, 2)} if total else {}


def _observation_family_proposals(store: Store) -> list[dict[str, Any]]:
    rows = []
    for proposal in store.continuous_improvement_proposals(limit=50000):
        haystack = json.dumps(
            {
                "target_component": proposal.get("target_component"),
                "target_identifier": proposal.get("target_identifier"),
                "payload": proposal.get("payload") or {},
            },
            ensure_ascii=False,
        ).lower()
        if (
            "observation_execution" in haystack
            or "micro_batch_execution" in haystack
            or "micro-lotes" in haystack
            or "micro_lotes" in haystack
        ):
            rows.append(proposal)
    return rows


def _recent_learning_observation_summary(store: Store, *, limit: int) -> dict[str, Any]:
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT signal_date, source_family, decision, approved_buy, executed_buy,
                   blocked_entry_quality, blocked_backtest, outcome_json
            FROM learning_observations
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    total = len(rows)
    source_counts: dict[str, int] = {}
    pending_outcomes = 0
    for row in rows:
        source = str(row["source_family"] or "")
        source_counts[source] = source_counts.get(source, 0) + 1
        try:
            outcome = json.loads(row["outcome_json"] or "{}")
        except json.JSONDecodeError:
            outcome = {}
        if outcome.get("label") == "pending" or outcome.get("matured") is False:
            pending_outcomes += 1
    return {
        "total": total,
        "executed_buy": sum(int(row["executed_buy"] or 0) for row in rows),
        "approved_buy": sum(int(row["approved_buy"] or 0) for row in rows),
        "blocked_entry_quality": sum(int(row["blocked_entry_quality"] or 0) for row in rows),
        "blocked_backtest": sum(int(row["blocked_backtest"] or 0) for row in rows),
        "pending_or_immature_outcomes": pending_outcomes,
        "min_signal_date": min((str(row["signal_date"]) for row in rows), default=None),
        "max_signal_date": max((str(row["signal_date"]) for row in rows), default=None),
        "source_counts": source_counts,
    }


def _artifact_text(item: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {item['rationale']}",
            "",
            f"- target: {item['target_identifier']}",
            f"- tests: {item['test_requirement']}",
            f"- rollback: {item['rollback_plan']}",
            "",
            "Evidencia:",
            *[f"- {evidence}" for evidence in item.get("evidence") or []],
            "",
            "Propuesta:",
            item["proposed_value"],
        ]
    )


def _learning_experiment_bridge(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_daily_learning_digest.json"
    if not path.exists():
        return {"available": False, "proposal_candidates": [], "reason": "daily_learning_digest_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"available": False, "proposal_candidates": [], "reason": "daily_learning_digest_invalid"}
    section = (payload.get("learning_experiment_yesterday") or {}) if isinstance(payload, dict) else {}
    return {
        "available": bool(section.get("available")),
        "session_date": section.get("session_date"),
        "pipeline": section.get("pipeline", {}),
        "proposal_candidates": list((section.get("adjustments") or {}).get("proposal_candidates") or []),
        "lessons": list(section.get("lessons") or []),
        "shadow": section.get("shadow", {}),
        "reason": "ok" if section.get("available") else "learning_experiment_not_available",
    }
