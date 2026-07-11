"""Gobierno del cast de proponentes del laboratorio (P27).

Tres reglas deterministas, motivadas por la auditoria P26 (OrchestratorAgent:
969 propuestas/4 semanas con 98% de rechazo; 88.5% prosa):

1. Cap semanal de propuestas SIN evidencia medida para agentes ruidosos.
2. Contrato ejecutable obligatorio para agentes re-instruidos.
3. Retiro de agentes como proponentes (conservan su rol de evaluacion).

La configuracion vive en ``data/config/cast_governance.json`` (fuera de
``config.py``), es human-gated y esta protegida por el gate de autogobierno:
la firma no puede relajar sus propios topes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .codegen import LOW_RISK_CODEGEN_ALLOWED_PREFIXES
from .proposal_contract import TERMINAL_PROPOSAL_STATUSES, validate_experiment_contract

if TYPE_CHECKING:  # pragma: no cover - solo tipado
    from agente_bolsa.storage import Store

CAST_CAP_REASON = "cast_cap_exceeded_no_evidence"
CONTRACT_VIOLATION_REASON = "proposal_contract_violation"
NOT_A_PROPOSER_REASON = "agent_not_a_proposer"
ADMISSION_CAP_REASON = "daily_admission_cap_exceeded"
WIP_CAP_REASON = "proposal_wip_cap_exceeded"

DEFAULT_CAST_GOVERNANCE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "human_gated": True,
    "weekly_cap_no_evidence": {"OrchestratorAgent": 10},
    "contract_agents": ["SoftwareReliabilityAgent", "DataQualityAgent"],
    "contract_required_all": False,
    "max_admitted_per_day": 2,
    "max_wip": 2,
    "retired_proposers": ["StrategyEvaluatorAgent", "ExperimentDesignerAgent"],
    "notes": (
        "Gobierno del cast (P27). Solo Antonio debe cambiar topes o listas; "
        "la firma tiene prohibido modificar este fichero por autogobierno."
    ),
}

CAST_GOVERNANCE_GOVERNED_KEYS = {
    "cast_governance",
    "cast_governance_enabled",
    "weekly_cap_no_evidence",
    "retired_proposers",
    "contract_agents",
    "data/config/cast_governance.json",
}

_EVIDENCE_KEYS = ("evidence", "evidence_refs", "experiment_id", "study_path", "schema_contract_real_line")
_EVIDENCE_TEXT_MARKERS = ("docs/informe", "docs/estudio", "data/reports/", "experiment PASSED")


def load_cast_governance_config(config_path: Path, *, create: bool = True) -> dict[str, Any]:
    """Carga la config file-based con defaults seguros (patron research_mode)."""
    if create and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(DEFAULT_CAST_GOVERNANCE_CONFIG, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    if not config_path.exists():
        return dict(DEFAULT_CAST_GOVERNANCE_CONFIG)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        raw = {}
    config = {**DEFAULT_CAST_GOVERNANCE_CONFIG, **(raw if isinstance(raw, dict) else {})}
    config["enabled"] = bool(config.get("enabled"))
    config["human_gated"] = bool(config.get("human_gated", True))
    config["contract_required_all"] = bool(config.get("contract_required_all", False))
    config["max_admitted_per_day"] = max(0, int(config.get("max_admitted_per_day") or 0))
    config["max_wip"] = max(0, int(config.get("max_wip") or 0))
    caps = config.get("weekly_cap_no_evidence")
    config["weekly_cap_no_evidence"] = (
        {str(k): max(0, int(v)) for k, v in caps.items()}
        if isinstance(caps, dict)
        else dict(DEFAULT_CAST_GOVERNANCE_CONFIG["weekly_cap_no_evidence"])
    )
    for key in ("contract_agents", "retired_proposers"):
        value = config.get(key)
        config[key] = (
            [str(item) for item in value]
            if isinstance(value, list)
            else list(DEFAULT_CAST_GOVERNANCE_CONFIG[key])
        )
    return config


def measured_evidence_present(payload: dict[str, Any]) -> bool:
    """Evidencia medida = referencia explicita a un artefacto verificable.

    Cuentan: claves de evidencia con contenido, o citas a informes/estudios en
    docs/ o data/reports/. Deliberadamente NO cuentan metricas numericas sueltas
    (``current_value``/``target_value``): la familia de observaciones demostro
    que se fabrican sin medicion real.
    """
    for key in _EVIDENCE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, dict)) and value:
            return True
    text = " ".join(
        str(payload.get(field) or "")
        for field in ("proposed_value", "rationale", "expected_impact")
    ).lower()
    return any(marker.lower() in text for marker in _EVIDENCE_TEXT_MARKERS)


def resolve_proposer(payload: dict[str, Any], store: Store | None) -> str:
    """Resuelve el agente proponente: campo directo o duenio de la iniciativa."""
    direct = str(payload.get("agent_name") or payload.get("owner_agent") or "").strip()
    if direct:
        return direct
    initiative_key = str(payload.get("initiative_key") or "").strip()
    if initiative_key and store is not None:
        try:
            initiative = store.continuous_improvement_initiative_by_key(initiative_key)
        except Exception:  # noqa: BLE001 - la atribucion nunca rompe la validacion
            initiative = None
        if initiative:
            owner = str(initiative.get("owner_agent") or "").strip()
            if owner:
                return owner
    return "UNKNOWN"


def contract_violation_detail(proposal: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """Lista de incumplimientos del contrato ejecutable (P25) para un proponente re-instruido."""
    failures: list[str] = []
    proposal_type = str(proposal.get("proposal_type") or payload.get("proposal_type") or "").upper()
    if proposal_type != "CODE_CHANGE":
        failures.append(f"proposal_type={proposal_type or 'vacio'} (se exige CODE_CHANGE)")
    raw_targets = payload.get("target_files") or payload.get("files") or []
    targets = [str(item).replace("\\", "/").strip() for item in raw_targets if str(item).strip()]
    if not targets:
        failures.append("sin target_files")
    else:
        outside = [
            target
            for target in targets
            if not any(target.startswith(prefix) for prefix in LOW_RISK_CODEGEN_ALLOWED_PREFIXES)
        ]
        if outside:
            failures.append(f"targets fuera del allowlist de codegen: {', '.join(outside)}")
    if not str(payload.get("test_requirement") or "").strip():
        failures.append("sin test_requirement")
    if not str(payload.get("rollback_plan") or "").strip():
        failures.append("sin rollback_plan")
    if not measured_evidence_present(payload):
        failures.append("sin evidencia medida citada")
    return failures


def weekly_no_evidence_count(
    store: Store,
    proposer: str,
    *,
    now: datetime | None = None,
    window_days: int = 7,
) -> int:
    """Cuenta propuestas SIN evidencia del proponente en la ventana movil."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=window_days)).isoformat()
    owners: dict[str, str] = {}
    count = 0
    with store.connect() as conn:
        for row in conn.execute(
            "SELECT initiative_key, owner_agent FROM continuous_improvement_initiatives"
        ):
            owners[str(row["initiative_key"])] = str(row["owner_agent"] or "")
        rows = conn.execute(
            "SELECT payload_json FROM continuous_improvement_proposals WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        direct = str(payload.get("agent_name") or payload.get("owner_agent") or "").strip()
        owner = direct or owners.get(str(payload.get("initiative_key") or "").strip(), "")
        if owner != proposer:
            continue
        if not measured_evidence_present(payload):
            count += 1
    return count


def assess_cast_governance(
    proposal: dict[str, Any],
    payload: dict[str, Any],
    *,
    store: Store | None,
    config: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Evalua las tres reglas. Devuelve dict con reason/detail/evidence o None si pasa."""
    if not config.get("enabled"):
        return None
    proposer = resolve_proposer(payload, store)
    if proposer in set(config.get("retired_proposers") or []):
        return {
            "reason": NOT_A_PROPOSER_REASON,
            "detail": (
                f"{proposer} esta retirado como proponente (conserva su rol de "
                "evaluacion/validacion). Decision del responsable, auditoria P26."
            ),
            "evidence": {"proposer": proposer},
        }
    require_evidence_contract = bool(config.get("contract_required_all"))
    if require_evidence_contract or proposer in set(config.get("contract_agents") or []):
        if require_evidence_contract:
            contract_check = validate_experiment_contract(proposal, workspace=Path.cwd())
            failures = contract_check["failures"]
        else:
            failures = contract_violation_detail(proposal, payload)
        if failures:
            return {
                "reason": CONTRACT_VIOLATION_REASON,
                "detail": (
                    f"{proposer} debe emitir propuestas con contrato de evidencia "
                    "completo, metrica, muestra, targets y rollback verificables."
                ),
                "evidence": {"proposer": proposer, "failures": failures},
            }
        if require_evidence_contract and store is not None:
            hypothesis_id = str(contract_check["contract"].get("hypothesis_id") or "")
            matches = [
                item
                for item in store.continuous_improvement_hypotheses(limit=50000)
                if str(item.get("hypothesis_id") or "") == hypothesis_id
            ]
            if matches and str(matches[0].get("status") or "").upper() in {
                "CLOSED",
                "REJECTED",
                "RESOLVED",
                "KILLED",
            }:
                return {
                    "reason": CONTRACT_VIOLATION_REASON,
                    "detail": "La hipotesis del contrato ya esta resuelta.",
                    "evidence": {"proposer": proposer, "failures": ["hypothesis_already_resolved"]},
                }
    if require_evidence_contract and store is not None:
        caps = _admission_counts(store, now=now)
        daily_cap = int(config.get("max_admitted_per_day") or 0)
        wip_cap = int(config.get("max_wip") or 0)
        if daily_cap and caps["today"] >= daily_cap:
            return {
                "reason": ADMISSION_CAP_REASON,
                "detail": f"Cupo diario de {daily_cap} propuestas admitidas agotado.",
                "evidence": caps,
            }
        if wip_cap and caps["wip"] >= wip_cap:
            return {
                "reason": WIP_CAP_REASON,
                "detail": f"WIP maximo de {wip_cap} propuestas admitidas agotado.",
                "evidence": caps,
            }
    caps = config.get("weekly_cap_no_evidence") or {}
    cap = caps.get(proposer)
    if cap is not None and store is not None and not measured_evidence_present(payload):
        used = weekly_no_evidence_count(store, proposer, now=now)
        if used >= int(cap):
            return {
                "reason": CAST_CAP_REASON,
                "detail": (
                    f"{proposer} agoto su cupo semanal de {cap} propuestas sin "
                    "evidencia medida. Adjunta un estudio/experimento/KPI para proponer."
                ),
                "evidence": {"proposer": proposer, "weekly_cap": int(cap), "used": used},
            }
    return None


def _admission_counts(store: Store, *, now: datetime | None = None) -> dict[str, int]:
    """Count only contract-valid proposals; legacy noise does not consume new WIP."""

    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = reference.date().isoformat()
    admitted_today = 0
    wip = 0
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT proposal_type, target_component, target_identifier, status, payload_json, created_at "
            "FROM continuous_improvement_proposals"
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        proposal = {
            "proposal_type": row["proposal_type"],
            "target_component": row["target_component"],
            "target_identifier": row["target_identifier"],
            "payload": payload,
        }
        if not validate_experiment_contract(proposal)["valid"]:
            continue
        if str(row["created_at"] or "")[:10] == today:
            admitted_today += 1
        if str(row["status"] or "").upper() not in TERMINAL_PROPOSAL_STATUSES:
            wip += 1
    return {"today": admitted_today, "wip": wip}
