"""Read-only daily digest for the continuous improvement lab."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from agente_bolsa.storage import Store

from .research_agenda import build_research_agenda_snapshot

REJECTION_BUCKETS = {
    "self_safety_modification_forbidden": "self_safety",
    "self_governance_modification_forbidden": "self_governance",
    "recently_rejected_duplicate": "recently_rejected",
}
TERMINAL_PROPOSAL_STATUSES = {
    "APPLIED",
    "ARCHIVED",
    "BLOCKED",
    "DUPLICATE",
    "REJECTED",
    "REJECTED_BY_TESTS",
}
ROLLBACK_STATUSES = {"ROLLED_BACK", "ROLLBACK_REQUESTED", "ROLLBACK_FAILED"}
EXECUTABLE = "EJECUTABLE"
PROSE = "PROSA"


def build_lab_digest(
    store: Store,
    *,
    days: int = 1,
    now: datetime | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    days = max(1, int(days))
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=days)
    data_dir = data_dir or _infer_data_dir(store)
    proposals = store.continuous_improvement_proposals(limit=50000)
    experiments = store.continuous_improvement_experiments(limit=50000)
    applied_changes = store.continuous_improvement_applied_changes(limit=50000)
    decisions = store.continuous_improvement_decisions(limit=50000)

    recent_proposals_created = [item for item in proposals if _is_recent(item.get("created_at"), cutoff)]
    recent_rejected = [
        item for item in proposals if str(item.get("status") or "").upper() == "REJECTED" and _is_recent(item.get("updated_at"), cutoff)
    ]
    ready_to_apply = [
        _ready_item(store, item)
        for item in proposals
        if str(item.get("status") or "").upper() == "READY_TO_APPLY" and _is_recent(item.get("updated_at"), cutoff)
    ]
    recent_applied = [item for item in applied_changes if _is_recent(item.get("updated_at"), cutoff)]
    recent_experiments = [item for item in experiments if _is_recent(item.get("updated_at"), cutoff)]

    rejection_counts = {"self_safety": 0, "self_governance": 0, "recently_rejected": 0, "otros": 0}
    for proposal in recent_rejected:
        rejection_counts[_rejection_bucket(store, proposal)] += 1

    experiment_counts = {
        "run": len(recent_experiments),
        "passed": sum(1 for item in recent_experiments if str(item.get("status") or "").upper() in {"PASSED", "APPLIED"}),
        "failed": sum(
            1
            for item in recent_experiments
            if str(item.get("status") or "").upper() in {"FAILED", "REJECTED_BY_TESTS", "BLOCKED", "ROLLBACK_FAILED"}
        ),
    }
    applied_counts: dict[str, int] = {}
    for item in recent_applied:
        status = str(item.get("status") or "UNKNOWN").upper()
        applied_counts[status] = applied_counts.get(status, 0) + 1

    attention = [item for item in ready_to_apply if item["has_diff"]]
    approval_requests = ready_for_human_approval_requests(store, limit=200)
    return {
        "days": days,
        "generated_at": now.isoformat(),
        "window_start": cutoff.isoformat(),
        "proposals": {
            "created": len(recent_proposals_created),
            "rejected_by_reason": rejection_counts,
            "ready_to_apply": ready_to_apply,
            "ready_to_apply_count": len(ready_to_apply),
        },
        "applied_changes": {
            "total": len(recent_applied),
            "by_status": applied_counts,
        },
        "experiments": experiment_counts,
        "overlay_shadow": latest_overlay_shadow_signal(data_dir, now=now),
        "core_sleeve": latest_core_sleeve_signal(data_dir, now=now),
        "research_agenda": build_research_agenda_snapshot(data_dir, experiments, now=now),
        "requires_attention": attention,
        "approval_requests": approval_requests,
        "kpi_funnel": build_kpi_funnel(proposals, experiments, applied_changes, decisions, now=now),
        "proposal_quality": build_proposal_quality_report(store, proposals=proposals, now=now, limit=200),
    }


def write_lab_digest_file(
    store: Store,
    reports_dir: Path,
    *,
    days: int = 1,
    run_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run_date = run_date or now.date()
    digest = build_lab_digest(store, days=days, now=now, data_dir=reports_dir.parent)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"ci_digest_{run_date.isoformat()}.md"
    path.write_text(format_lab_digest_text(digest), encoding="utf-8")
    return {"ok": True, "path": str(path), "digest": digest}


def build_kpi_funnel(
    proposals: list[dict[str, Any]],
    experiments: list[dict[str, Any]],
    applied_changes: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_week_start = _week_start(now.date())
    week_starts = [current_week_start - timedelta(days=7 * offset) for offset in reversed(range(4))]
    proposals_by_id = {str(item.get("proposal_id")): item for item in proposals if item.get("proposal_id")}
    experiments_by_week = _group_by_week(experiments, "created_at")
    applied_by_week = _group_by_week(applied_changes, "created_at")
    proposals_by_week = _group_by_week(proposals, "created_at")
    decisions_by_week = _group_by_week(decisions, "created_at")

    rows: list[dict[str, Any]] = []
    for start in week_starts:
        end = start + timedelta(days=7)
        week_key = start.isoformat()
        week_proposals = proposals_by_week.get(week_key, [])
        week_experiments = experiments_by_week.get(week_key, [])
        week_applied = applied_by_week.get(week_key, [])
        proposal_ids = {str(item.get("proposal_id")) for item in week_proposals if item.get("proposal_id")}
        experiment_proposal_ids = {str(item.get("proposal_id")) for item in week_experiments if item.get("proposal_id")}
        decided_ages = _decision_ages_days(decisions_by_week.get(week_key, []), proposals_by_id)
        rows.append(
            {
                "week_start": week_key,
                "week_end": (end - timedelta(days=1)).isoformat(),
                "proposals": len(week_proposals),
                "experiments": len(week_experiments),
                "applied_changes": len(week_applied),
                "proposal_to_experiment_pct": _pct(len(experiment_proposal_ids & proposal_ids), len(proposal_ids)),
                "experiment_to_applied_pct": _pct(len(week_applied), len(week_experiments)),
                "median_days_proposal_to_decision": round(median(decided_ages), 2) if decided_ages else None,
                "rollbacks": sum(1 for item in week_applied if str(item.get("status") or "").upper() in ROLLBACK_STATUSES),
            }
        )

    wip_statuses = Counter(
        str(item.get("status") or "UNKNOWN").upper()
        for item in proposals
        if str(item.get("status") or "UNKNOWN").upper() not in TERMINAL_PROPOSAL_STATUSES
    )
    return {
        "definition": (
            "Semanas ISO; % prop->exp mide proposal_id con experimento/propuestas de la semana; "
            "% exp->aplicado mide Applied/Experimentos de la semana para cuadrar con la columna Applied. "
            "WIP actual excluye estados terminales: "
            + ", ".join(sorted(TERMINAL_PROPOSAL_STATUSES))
        ),
        "weeks": rows,
        "wip_current": {"total": sum(wip_statuses.values()), "by_status": dict(sorted(wip_statuses.items()))},
        "rollbacks_total": sum(1 for item in applied_changes if str(item.get("status") or "").upper() in ROLLBACK_STATUSES),
    }


def classify_proposal_quality(proposal: dict[str, Any]) -> dict[str, Any]:
    payload = proposal.get("payload") or {}
    text = _proposal_text(proposal).lower()
    target_identifier = str(proposal.get("target_identifier") or payload.get("target_identifier") or "").strip()
    current_value = str(payload.get("current_value") or "").strip()
    proposed_value = str(payload.get("proposed_value") or "").strip()

    if _has_diff_spec(payload, text):
        return {"class": EXECUTABLE, "reason": "diff_or_targets"}
    if target_identifier and current_value and proposed_value and current_value != proposed_value:
        return {"class": EXECUTABLE, "reason": "parameter_current_to_proposed"}
    if target_identifier and _contains_current_to_proposed(text):
        return {"class": EXECUTABLE, "reason": "text_current_to_proposed"}
    if _has_shadow_rule(payload, text):
        return {"class": EXECUTABLE, "reason": "concrete_shadow_rule"}
    return {"class": PROSE, "reason": "no_deterministic_execution_spec"}


def build_proposal_quality_report(
    store: Store,
    *,
    proposals: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    proposals = proposals if proposals is not None else store.continuous_improvement_proposals(limit=limit)
    recent = sorted(proposals, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:limit]
    initiative_owner = _initiative_owner_map(store)
    classified: list[dict[str, Any]] = []
    for proposal in recent:
        classification = classify_proposal_quality(proposal)
        row = {
            "proposal_id": proposal.get("proposal_id"),
            "class": classification["class"],
            "reason": classification["reason"],
            "proposer": _proposal_proposer(proposal, initiative_owner),
            "week_start": _week_start((_parse_iso_datetime(str(proposal.get("created_at") or "")) or now).date()).isoformat(),
            "title": _proposal_title(proposal),
            "excerpt": _proposal_excerpt(proposal),
        }
        classified.append(row)

    global_counts = Counter(item["class"] for item in classified)
    by_agent: dict[str, Counter[str]] = defaultdict(Counter)
    by_week: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = {EXECUTABLE: [], PROSE: []}
    for item in classified:
        by_agent[item["proposer"]][item["class"]] += 1
        by_week[item["week_start"]][item["class"]] += 1
        if len(examples[item["class"]]) < 5:
            examples[item["class"]].append(
                {
                    "proposal_id": item["proposal_id"],
                    "title": item["title"],
                    "reason": item["reason"],
                    "excerpt": item["excerpt"],
                }
            )

    return {
        "sample_size": len(classified),
        "generated_at": now.isoformat(),
        "global": _counter_payload(global_counts),
        "by_agent": {agent: _counter_payload(counts) for agent, counts in sorted(by_agent.items())},
        "by_week": {week: _counter_payload(counts) for week, counts in sorted(by_week.items())},
        "examples": examples,
        "classified": classified,
        "definition": (
            "EJECUTABLE si hay parametro con valor actual y propuesto, spec de diff/targets, "
            "o regla shadow con entrada/salida/stop/take-profit medible; si no, PROSA."
        ),
    }


def ready_for_human_approval_requests(store: Store, *, limit: int = 200) -> list[dict[str, Any]]:
    query = """
        SELECT artifact_id, proposal_id, artifact_type, content_text, payload_json,
               created_at, updated_at
        FROM continuous_improvement_proposal_artifacts
        WHERE artifact_type = 'code_diff_preview'
        ORDER BY updated_at DESC
        LIMIT ?
    """
    proposals = {str(item.get("proposal_id")): item for item in store.continuous_improvement_proposals(limit=50000)}
    applied_or_rolled_back = {
        str(item.get("proposal_id"))
        for item in store.continuous_improvement_applied_changes(limit=50000)
        if item.get("proposal_id") and str(item.get("status") or "").upper() in {"APPLIED", "ROLLED_BACK"}
    }
    rows: list[Any]
    with store.connect() as conn:
        rows = conn.execute(query, (limit,)).fetchall()
    requests: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        if payload.get("status") != "READY_FOR_HUMAN_REVIEW" or payload.get("tests_ok") is not True:
            continue
        proposal = proposals.get(str(row["proposal_id"])) or {}
        if str(row["proposal_id"]) in applied_or_rolled_back or str(proposal.get("status") or "").upper() in {"APPLIED", "ROLLED_BACK"}:
            continue
        target_paths = payload.get("target_paths") or _diff_target_paths(str(row["content_text"] or ""))
        requests.append(
            {
                "proposal_id": row["proposal_id"],
                "title": _proposal_title(proposal),
                "targets": list(target_paths),
                "artifact_id": row["artifact_id"],
                "updated_at": row["updated_at"],
            }
        )
    return requests


def latest_overlay_shadow_signal(data_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
    log_path = data_dir / "research" / "overlay_shadow" / "overlay_shadow_log.jsonl"
    if not log_path.exists():
        return {"available": False, "reason": f"{log_path} no existe"}
    latest: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            latest = payload
    if latest is None:
        return {"available": False, "reason": f"{log_path} no contiene JSON valido"}
    data_date_text = str(latest.get("data_date") or "")
    try:
        data_day = date.fromisoformat(data_date_text)
    except ValueError:
        return {"available": False, "reason": f"data_date invalida: {data_date_text}"}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    market_days_old = _market_days_between(data_day, now.date())
    return {
        "available": True,
        "path": str(log_path),
        "data_date": data_date_text,
        "market_days_old": market_days_old,
        "stale": market_days_old > 3,
        "price": latest.get("price"),
        "realized_vol_annualized": latest.get("realized_vol_annualized"),
        "target_exposures": latest.get("target_exposures") or {},
    }


def latest_core_sleeve_signal(data_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
    log_path = data_dir / "research" / "core_sleeve" / "core_sleeve_log.jsonl"
    if not log_path.exists():
        return {"available": False, "reason": f"{log_path} no existe"}
    latest: dict[str, Any] | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            latest = payload
    if latest is None:
        return {"available": False, "reason": f"{log_path} no contiene JSON valido"}
    data_date_text = str(latest.get("data_date") or "")
    try:
        data_day = date.fromisoformat(data_date_text)
    except ValueError:
        return {"available": False, "reason": f"data_date invalida: {data_date_text}"}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    market_days_old = _market_days_between(data_day, now.date())
    decision = latest.get("decision") if isinstance(latest.get("decision"), dict) else {}
    order = decision.get("order") if isinstance(decision.get("order"), dict) else {}
    return {
        "available": True,
        "path": str(log_path),
        "data_date": data_date_text,
        "market_days_old": market_days_old,
        "stale": market_days_old > 3,
        "status": latest.get("status"),
        "exposure": latest.get("exposure"),
        "decision_reason": decision.get("reason"),
        "decision_order_side": order.get("side"),
        "decision_order_notional": order.get("notional"),
    }


def format_lab_digest_text(digest: dict[str, Any]) -> str:
    rejected = (digest.get("proposals") or {}).get("rejected_by_reason") or {}
    ready = (digest.get("proposals") or {}).get("ready_to_apply") or []
    applied = digest.get("applied_changes") or {}
    experiments = digest.get("experiments") or {}
    attention = digest.get("requires_attention") or []
    kpis = digest.get("kpi_funnel") or {}
    quality = digest.get("proposal_quality") or {}
    approval_requests = digest.get("approval_requests") or []
    overlay = digest.get("overlay_shadow") or {}
    research_agenda = digest.get("research_agenda") or {}

    lines = [
        f"Digest diario del lab - ultimos {digest.get('days')} dia(s)",
        f"Generado: {digest.get('generated_at', 'n/d')}",
        "",
        "Propuestas",
        f"- creadas: {(digest.get('proposals') or {}).get('created', 0)}",
        (
            "- rechazadas: "
            f"self_safety={rejected.get('self_safety', 0)}, "
            f"self_governance={rejected.get('self_governance', 0)}, "
            f"recently_rejected={rejected.get('recently_rejected', 0)}, "
            f"otros={rejected.get('otros', 0)}"
        ),
        f"- READY_TO_APPLY: {len(ready)}",
    ]
    for item in ready:
        marker = "diff adjunto" if item.get("has_diff") else "sin diff"
        lines.append(f"  - {item.get('proposal_id')} | {item.get('target')} | {marker}")

    lines.extend(
        [
            "",
            "Applied changes",
            f"- total: {applied.get('total', 0)}",
            f"- por estado: {_format_counts(applied.get('by_status') or {})}",
            "",
            "Experimentos",
            f"- corridos: {experiments.get('run', 0)}",
            f"- PASSED: {experiments.get('passed', 0)}",
            f"- FAILED: {experiments.get('failed', 0)}",
            "",
            "KPIs de investigacion",
            f"- estudios_ejecutados/semana: {(research_agenda.get('kpis') or {}).get('estudios_ejecutados_semana', 0)}",
            f"- hipotesis_matadas/semana: {(research_agenda.get('kpis') or {}).get('hipotesis_matadas_semana', 0)}",
            f"- hipotesis_promovidas/semana: {(research_agenda.get('kpis') or {}).get('hipotesis_promovidas_semana', 0)}",
            "",
            "Agenda de investigacion",
            "| Hipotesis | Estado | Fecha objetivo | Notas |",
            "|---|---|---|---|",
            *[
                (
                    f"| {item.get('title', '')} | {item.get('status', '')} | "
                    f"{item.get('target_date', '')} | {item.get('notes', '')} |"
                )
                for item in research_agenda.get("items") or []
            ],
            "",
            "Overlay shadow",
        ]
    )
    if overlay.get("available"):
        exposures = overlay.get("target_exposures") or {}
        lines.extend(
            [
                f"- data_date: {overlay.get('data_date', 'n/d')}",
                f"- vol realizada anualizada: {_none_text(overlay.get('realized_vol_annualized'))}",
                (
                    "- exposiciones: "
                    f"VT10={_none_text(exposures.get('vol_target_10pct'))}, "
                    f"VT12={_none_text(exposures.get('vol_target_12pct'))}, "
                    f"SMA200={_none_text(exposures.get('regime_sma200'))}"
                ),
            ]
        )
        if overlay.get("stale"):
            lines.append(f"- ADVERTENCIA: senal overlay con {overlay.get('market_days_old')} dias de mercado; revisar supervisor.")
    else:
        lines.append(f"- No disponible: {overlay.get('reason', 'sin log overlay_shadow')}")

    core_sleeve = digest.get("core_sleeve") or {}
    lines.extend(
        [
            "",
            "Core sleeve",
        ]
    )
    if core_sleeve.get("available"):
        lines.extend(
            [
                f"- data_date: {core_sleeve.get('data_date', 'n/d')}",
                f"- status: {_none_text(core_sleeve.get('status'))}",
                f"- exposure: {_none_text(core_sleeve.get('exposure'))}",
            ]
        )
        decision_reason = core_sleeve.get("decision_reason")
        decision_order_side = core_sleeve.get("decision_order_side")
        decision_order_notional = core_sleeve.get("decision_order_notional")
        if decision_reason is not None:
            lines.append(f"- decision.reason: {decision_reason}")
            lines.append(f"- decision.order.side: {_none_text(decision_order_side)}")
            lines.append(f"- decision.order.notional: {_none_text(decision_order_notional)}")
        if core_sleeve.get("stale"):
            lines.append(f"- ADVERTENCIA: registro core sleeve con {core_sleeve.get('market_days_old')} dias de mercado; revisar supervisor.")
    else:
        lines.append(f"- No disponible: {core_sleeve.get('reason', 'sin log core_sleeve')}")

    lines.extend(
        [
            "",
            "KPI funnel - ultimas 4 semanas",
            f"- WIP actual: {(kpis.get('wip_current') or {}).get('total', 0)} | "
            f"{_format_counts((kpis.get('wip_current') or {}).get('by_status') or {})}",
            f"- Rollbacks historicos: {kpis.get('rollbacks_total', 0)}",
            "| Semana | Propuestas | Experimentos | Applied | % prop->exp | % exp->aplicado | Mediana dias a decision | Rollbacks |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in kpis.get("weeks") or []:
        lines.append(
            f"| {row.get('week_start')} | {row.get('proposals', 0)} | {row.get('experiments', 0)} | "
            f"{row.get('applied_changes', 0)} | {_pct_text(row.get('proposal_to_experiment_pct'))} | "
            f"{_pct_text(row.get('experiment_to_applied_pct'))} | {_none_text(row.get('median_days_proposal_to_decision'))} | "
            f"{row.get('rollbacks', 0)} |"
        )

    lines.extend(
        [
            "",
            "Calidad de propuestas - medicion sin enforcement",
            f"- muestra: {quality.get('sample_size', 0)}",
            f"- global: {_format_counts((quality.get('global') or {}).get('counts') or {})}",
            "- definicion: " + str(quality.get("definition") or ""),
            "",
            "Ejemplos EJECUTABLE",
        ]
    )
    lines.extend(_quality_example_lines((quality.get("examples") or {}).get(EXECUTABLE) or []))
    lines.append("")
    lines.append("Ejemplos PROSA")
    lines.extend(_quality_example_lines((quality.get("examples") or {}).get(PROSE) or []))

    lines.extend(["", "Requiere tu atencion"])
    if attention:
        for item in attention:
            lines.append(f"- {item.get('proposal_id')} | {item.get('target')} | diff listo")
    else:
        lines.append("- Nada con diff listo en la ventana.")

    lines.extend(["", "PIDE APROBACIÓN"])
    if approval_requests:
        for item in approval_requests:
            targets = ", ".join(item.get("targets") or ["sin targets"])
            lines.append(
                f"- {item.get('proposal_id')} | {item.get('title')} | targets: {targets} | "
                "accion: continuous-improvement-lab review/approve"
            )
    else:
        lines.append("- No hay propuestas READY_FOR_HUMAN_REVIEW con tests_ok=true.")
    return "\n".join(lines)


def _ready_item(store: Store, proposal: dict[str, Any]) -> dict[str, Any]:
    artifact = store.continuous_improvement_proposal_artifact(str(proposal.get("proposal_id") or ""))
    return {
        "proposal_id": proposal.get("proposal_id"),
        "target": f"{proposal.get('target_component')}/{proposal.get('target_identifier')}".rstrip("/"),
        "has_diff": _artifact_has_diff(artifact),
        "artifact_id": (artifact or {}).get("artifact_id"),
    }


def _artifact_has_diff(artifact: dict[str, Any] | None) -> bool:
    if not artifact:
        return False
    artifact_type = str(artifact.get("artifact_type") or "").lower()
    payload = artifact.get("payload") or {}
    content = str(artifact.get("content_text") or "")
    return (
        artifact_type in {"diff", "patch", "code_diff_preview"}
        or "diff --git " in content
        or ("--- " in content and "+++ " in content)
        or str(payload.get("status") or "") == "READY_FOR_HUMAN_REVIEW"
        or bool(payload.get("diff") or payload.get("patch"))
    )


def _rejection_bucket(store: Store, proposal: dict[str, Any]) -> str:
    reasons: list[str] = []
    guard = proposal.get("guard") or {}
    reasons.extend(str(item or "") for item in guard.get("reasons") or [])
    for key in ("self_safety_violation", "self_governance_violation", "recently_rejected_duplicate"):
        if guard.get(key):
            reasons.append(str((guard.get(key) or {}).get("reason") or key))
    for decision in store.continuous_improvement_decisions(proposal_id=str(proposal.get("proposal_id") or ""), limit=20):
        reasons.append(str(decision.get("reason") or ""))
        payload = decision.get("payload") or {}
        for key in ("self_safety_violation", "self_governance_violation", "recently_rejected_duplicate"):
            if payload.get(key):
                reasons.append(str((payload.get(key) or {}).get("reason") or key))
    joined = " ".join(reasons).lower()
    for reason, bucket in REJECTION_BUCKETS.items():
        if reason in joined:
            return bucket
    return "otros"


def _is_recent(value: Any, cutoff: datetime) -> bool:
    parsed = _parse_iso_datetime(str(value or ""))
    return parsed is not None and parsed >= cutoff


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infer_data_dir(store: Store) -> Path:
    database_path = Path(getattr(store, "database_path", "data/state/agente_bolsa.sqlite3"))
    if database_path.parent.name == "state":
        return database_path.parent.parent
    return Path("data")


def _market_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    try:
        import pandas_market_calendars as mcal

        schedule = mcal.get_calendar("XNYS").schedule(
            start_date=(start + timedelta(days=1)).isoformat(),
            end_date=end.isoformat(),
        )
        return int(len(schedule))
    except Exception:
        day = start + timedelta(days=1)
        count = 0
        while day <= end:
            if day.weekday() < 5:
                count += 1
            day += timedelta(days=1)
        return count


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "sin cambios"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _group_by_week(items: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        parsed = _parse_iso_datetime(str(item.get(field) or ""))
        if parsed is None:
            continue
        grouped[_week_start(parsed.date()).isoformat()].append(item)
    return grouped


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def _decision_ages_days(decisions: list[dict[str, Any]], proposals_by_id: dict[str, dict[str, Any]]) -> list[float]:
    ages: list[float] = []
    first_decision_by_proposal: dict[str, datetime] = {}
    for decision in sorted(decisions, key=lambda item: str(item.get("created_at") or "")):
        proposal_id = str(decision.get("proposal_id") or "")
        first_decision_by_proposal.setdefault(proposal_id, _parse_iso_datetime(str(decision.get("created_at") or "")) or datetime.now(timezone.utc))
    for proposal_id, decision_at in first_decision_by_proposal.items():
        proposal_at = _parse_iso_datetime(str((proposals_by_id.get(proposal_id) or {}).get("created_at") or ""))
        if proposal_at is None:
            continue
        ages.append(max(0.0, (decision_at - proposal_at).total_seconds() / 86400.0))
    return ages


def _has_diff_spec(payload: dict[str, Any], text: str) -> bool:
    for key in ("file_edits", "files", "target_files", "target_paths", "diff_targets"):
        value = payload.get(key)
        if isinstance(value, list | tuple) and value:
            return True
    if str(payload.get("patch") or "").strip() or str(payload.get("diff") or "").strip():
        return True
    return bool("diff --git" in text or re.search(r"\b(src|tests|docs)/[\w./-]+\.py\b", text))


def _contains_current_to_proposed(text: str) -> bool:
    if "->" in text or "→" in text:
        return True
    patterns = [
        r"['\"]?current_value['\"]?\s*:\s*['\"]?\d+(?:\.\d+)?[^.\n]{0,120}['\"]?target_value['\"]?\s*:\s*['\"]?\d+(?:\.\d+)?",
        r"current(?:ly)?[^.\n]{0,80}\b\d+(?:\.\d+)?[^.\n]{0,80}(?:propos|increase|decrease|set)[^.\n]{0,80}\b\d+(?:\.\d+)?",
        r"actual[^.\n]{0,80}\b\d+(?:\.\d+)?[^.\n]{0,80}propuest[^.\n]{0,80}\b\d+(?:\.\d+)?",
        r"\bde\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _has_shadow_rule(payload: dict[str, Any], text: str) -> bool:
    if "shadow" not in text and str(payload.get("promotion_state") or "").lower() != "shadow":
        return False
    rule_keys = {"entry", "exit", "stop_loss", "take_profit", "min_trades", "invalidation"}
    if rule_keys & set(payload):
        return True
    hits = sum(1 for key in rule_keys if key in text)
    return hits >= 2


def _proposal_text(proposal: dict[str, Any]) -> str:
    payload = proposal.get("payload") or {}
    parts: list[str] = [
        str(proposal.get("proposal_type") or ""),
        str(proposal.get("target_component") or ""),
        str(proposal.get("target_identifier") or ""),
    ]
    for key in (
        "current_value",
        "proposed_value",
        "rationale",
        "expected_impact",
        "rollback_plan",
        "patch",
        "diff",
        "summary",
        "title",
    ):
        parts.append(str(payload.get(key) or ""))
    for key in ("file_edits", "files", "target_files", "target_paths"):
        if payload.get(key):
            parts.append(json.dumps(payload.get(key), ensure_ascii=False, default=str))
    return "\n".join(parts)


def _proposal_excerpt(proposal: dict[str, Any], *, limit: int = 320) -> str:
    text = " ".join(_proposal_text(proposal).split())
    return text[:limit]


def _proposal_title(proposal: dict[str, Any]) -> str:
    payload = proposal.get("payload") or {}
    for key in ("title", "summary", "expected_impact", "rationale", "proposed_value"):
        value = str(payload.get(key) or "").strip()
        if value:
            return " ".join(value.split())[:120]
    target = f"{proposal.get('target_component')}/{proposal.get('target_identifier')}".strip("/")
    return target or str(proposal.get("proposal_id") or "sin titulo")


def _initiative_owner_map(store: Store) -> dict[str, str]:
    owners: dict[str, str] = {}
    try:
        initiatives = store.continuous_improvement_initiatives(limit=50000)
    except Exception:
        return owners
    for item in initiatives:
        key = str(item.get("initiative_key") or "")
        owner = str(item.get("owner_agent") or "").strip()
        if key and owner:
            owners[key] = owner
    return owners


def _proposal_proposer(proposal: dict[str, Any], initiative_owner: dict[str, str]) -> str:
    payload = proposal.get("payload") or {}
    for key in ("proposer", "source", "agent_name", "owner_agent"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    initiative_key = str(payload.get("initiative_key") or "").strip()
    if initiative_key and initiative_owner.get(initiative_key):
        return initiative_owner[initiative_key]
    return "UNKNOWN"


def _counter_payload(counter: Counter[str]) -> dict[str, Any]:
    counts = {EXECUTABLE: int(counter.get(EXECUTABLE, 0)), PROSE: int(counter.get(PROSE, 0))}
    total = counts[EXECUTABLE] + counts[PROSE]
    return {
        "counts": counts,
        "total": total,
        "executable_pct": _pct(counts[EXECUTABLE], total),
        "prose_pct": _pct(counts[PROSE], total),
    }


def _quality_example_lines(examples: list[dict[str, Any]]) -> list[str]:
    if not examples:
        return ["- Sin ejemplos en la muestra."]
    return [
        f"- {item.get('proposal_id')} | {item.get('reason')} | {item.get('title')} | {item.get('excerpt')}"
        for item in examples
    ]


def _diff_target_paths(diff_text: str) -> list[str]:
    targets: list[str] = []
    for line in str(diff_text or "").splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            rel = line[6:].strip()
            if rel != "/dev/null":
                targets.append(rel.replace("\\", "/"))
    return list(dict.fromkeys(targets))


def _pct_text(value: Any) -> str:
    if value is None:
        return "n/d"
    return f"{float(value):.2f}%"


def _none_text(value: Any) -> str:
    return "n/d" if value is None else str(value)
