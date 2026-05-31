"""Event-driven orchestration for the continuous improvement lab."""

from __future__ import annotations

from typing import Any

from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .agents import (
    SPECIALIST_AGENT_CLASSES,
    hypothesis_fingerprint,
    initiative_title_from_key,
    initiative_topic_key,
)
from .schemas import AgentName, TaskStatus


class LabOrchestrator:
    def __init__(self, store: Store) -> None:
        self.store = store

    def planned_tasks_for_event(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        domain = str(event.get("domain") or "software-improvement")
        context = context or {}
        if domain == "trading-improvement":
            return self._trading_tasks(event, context)
        return self._software_tasks(event, context)

    def _trading_tasks(self, event: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = str(event.get("event_type") or "")
        manual = event_type.startswith("manual")
        evaluation = context.get("evaluation", {}) or {}
        summary = evaluation.get("summary", {}) or {}
        reports = context.get("reports", {}) or {}
        pre_earnings_report = (reports.get("pre_earnings_learning") or {})
        has_pre_earnings = bool(pre_earnings_report.get("available"))
        blocked_entry = int(summary.get("blocked_entry_quality") or 0)
        blocked_backtest = int(summary.get("blocked_backtest") or 0)
        outcomes_available = int(summary.get("outcomes_available") or 0)
        signals = int(summary.get("signals") or 0)
        duplicates = self._max_duplicate_count(context)
        blockers = evaluation.get("blockers", []) or []

        if not manual and not (
            has_pre_earnings
            or blocked_entry
            or blocked_backtest
            or outcomes_available
            or signals
            or duplicates
            or blockers
        ):
            return []

        specs: list[dict[str, Any]] = []
        specs.append(
            {
                "initiative_key": initiative_topic_key(domain="trading", focus="market_regime"),
                "title": initiative_title_from_key("trading:market_regime"),
                "owner_agent": AgentName.MARKET_REGIME.value,
                "priority": event.get("priority", "MEDIUM"),
                "target_metric": "regime_stability",
                "baseline_value": None,
                "current_value": None,
                "expected_impact": "Alinear el comite con regimen y volatilidad antes de validar mejoras.",
                "risk_level": "LOW",
                "agents": [
                    AgentName.MARKET_REGIME.value,
                    AgentName.EXPERIMENT_DESIGNER.value,
                    AgentName.DECISION_COMMITTEE.value,
                ],
                "payload": {"focus": "market_regime"},
            }
        )
        if has_pre_earnings or "pre_earnings" in str(event.get("event_type") or "") or summary.get("blocked_big_winners"):
            specs.append(
                {
                    "initiative_key": initiative_topic_key(
                        domain="trading",
                        proposal={"proposal_type": "RISK_RULE_CHANGE", "target_component": "pre_earnings_risk_veto"},
                    ),
                    "title": initiative_title_from_key("trading:pre_earnings_risk_veto"),
                    "owner_agent": AgentName.PRE_EARNINGS.value,
                    "priority": "HIGH" if summary.get("blocked_big_winners") else event.get("priority", "MEDIUM"),
                    "target_metric": "blocked_winners",
                    "baseline_value": summary.get("blocked_big_winners"),
                    "current_value": summary.get("blocked_big_winners"),
                    "expected_impact": "Reducir ganadores bloqueados en ventana pre-earnings sin elevar drawdown.",
                    "risk_level": "MEDIUM",
                    "agents": [
                        AgentName.PRE_EARNINGS.value,
                        AgentName.RISK_CAPITAL.value,
                        AgentName.EXPERIMENT_DESIGNER.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "pre_earnings_risk_veto"},
                }
            )
        if blocked_entry > 0 or signals > 0:
            specs.append(
                {
                    "initiative_key": initiative_topic_key(
                        domain="trading",
                        proposal={"proposal_type": "PARAMETER_CHANGE", "target_component": "entry_quality_filter"},
                    ),
                    "title": initiative_title_from_key("trading:entry_quality_filter"),
                    "owner_agent": AgentName.TECHNICAL_EDGE.value,
                    "priority": "HIGH" if blocked_entry else event.get("priority", "MEDIUM"),
                    "target_metric": "false_positive_rate",
                    "baseline_value": blocked_entry,
                    "current_value": blocked_entry,
                    "expected_impact": "Bajar falsos bloqueos y preservar winners en filtros de entrada.",
                    "risk_level": "LOW",
                    "agents": [
                        AgentName.TECHNICAL_EDGE.value,
                        AgentName.STRATEGY.value,
                        AgentName.EXPERIMENT_DESIGNER.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "entry_quality_filter"},
                }
            )
        if duplicates > 0:
            specs.append(
                {
                    "initiative_key": initiative_topic_key(
                        domain="trading",
                        proposal={"proposal_type": "DATA_QUALITY_CHANGE", "target_component": "signal_consolidation"},
                    ),
                    "title": initiative_title_from_key("trading:signal_consolidation"),
                    "owner_agent": AgentName.DATA_QUALITY.value,
                    "priority": "MEDIUM",
                    "target_metric": "duplicate_rate",
                    "baseline_value": duplicates,
                    "current_value": duplicates,
                    "expected_impact": "Eliminar señales duplicadas antes de medir hit rate y expectancy.",
                    "risk_level": "LOW",
                    "agents": [
                        AgentName.DATA_QUALITY.value,
                        AgentName.TECHNICAL_EDGE.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "signal_consolidation"},
                }
            )
        if has_pre_earnings:
            specs.append(
                {
                    "initiative_key": initiative_topic_key(
                        domain="trading",
                        proposal={"proposal_type": "DATA_QUALITY_CHANGE", "target_component": "analyst_estimates_pipeline"},
                    ),
                    "title": initiative_title_from_key("trading:analyst_estimates_pipeline"),
                    "owner_agent": AgentName.PRE_EARNINGS.value,
                    "priority": "MEDIUM",
                    "target_metric": "estimate_coverage",
                    "baseline_value": summary.get("analyst_estimates_coverage"),
                    "current_value": summary.get("analyst_estimates_coverage"),
                    "expected_impact": "Mejorar cobertura y calidad de estimaciones usadas para la decision.",
                    "risk_level": "LOW",
                    "agents": [
                        AgentName.PRE_EARNINGS.value,
                        AgentName.DATA_QUALITY.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "analyst_estimates_pipeline"},
                }
            )
        if outcomes_available > 0 or blockers:
            specs.append(
                {
                    "initiative_key": initiative_topic_key(
                        domain="trading",
                        proposal={"proposal_type": "MONITORING_CHANGE", "target_component": "outcome_generation"},
                    ),
                    "title": initiative_title_from_key("trading:outcome_generation"),
                    "owner_agent": AgentName.STRATEGY.value,
                    "priority": event.get("priority", "MEDIUM"),
                    "target_metric": "outcome_maturity",
                    "baseline_value": outcomes_available,
                    "current_value": outcomes_available,
                    "expected_impact": "Garantizar outcomes maduros para validar si el edge mejora de verdad.",
                    "risk_level": "LOW",
                    "agents": [
                        AgentName.STRATEGY.value,
                        AgentName.EXPERIMENT_DESIGNER.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "outcome_generation"},
                }
            )
        return self._build_tasks(event, context, specs)

    def _software_tasks(self, event: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = str(event.get("event_type") or "")
        manual = event_type.startswith("manual")
        recent_errors = context.get("events", {}).get("recent_errors", []) or []
        reports = context.get("reports", {}) or {}
        market_data_quality = reports.get("market_data_quality") or {}
        available_quality = bool(market_data_quality.get("available"))
        summary = (market_data_quality.get("payload") or {}).get("summary", {}) if available_quality else {}

        if not manual and not recent_errors and not available_quality:
            return []

        specs: list[dict[str, Any]] = [
            {
                "initiative_key": initiative_topic_key(domain="software", focus="software_reliability"),
                "title": initiative_title_from_key("software:software_reliability"),
                "owner_agent": AgentName.SOFTWARE_RELIABILITY.value,
                "priority": event.get("priority", "MEDIUM"),
                "target_metric": "runtime_error_rate",
                "baseline_value": len(recent_errors),
                "current_value": len(recent_errors),
                "expected_impact": "Reducir errores repetidos y deuda tecnica del runtime.",
                "risk_level": "LOW",
                "agents": [
                    AgentName.SOFTWARE_RELIABILITY.value,
                    AgentName.EXPERIMENT_DESIGNER.value,
                    AgentName.DECISION_COMMITTEE.value,
                ],
                "payload": {"focus": "software_reliability"},
            }
        ]
        if available_quality or any("error" in str(item.get("event_type", "")).lower() for item in recent_errors):
            specs.append(
                {
                    "initiative_key": initiative_topic_key(domain="software", focus="data_quality"),
                    "title": initiative_title_from_key("software:data_quality"),
                    "owner_agent": AgentName.DATA_QUALITY.value,
                    "priority": "MEDIUM",
                    "target_metric": "data_coverage",
                    "baseline_value": summary.get("coverage_ratio"),
                    "current_value": summary.get("coverage_ratio"),
                    "expected_impact": "Mantener cobertura y consistencia de los datos antes de validar edge.",
                    "risk_level": "LOW",
                    "agents": [
                        AgentName.DATA_QUALITY.value,
                        AgentName.EXPERIMENT_DESIGNER.value,
                        AgentName.DECISION_COMMITTEE.value,
                    ],
                    "payload": {"focus": "data_quality"},
                }
            )
        return self._build_tasks(event, context, specs)

    def _build_tasks(
        self,
        event: dict[str, Any],
        context: dict[str, Any],
        specs: list[dict[str, Any]],
        *,
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        domain = "trading" if "trading" in str(event.get("domain") or "").lower() else "software"
        existing = self.store.continuous_improvement_tasks(event_id=event["event_id"], limit=200)
        existing_keys = {
            str((item.get("payload") or {}).get("initiative_key") or "")
            for item in existing
            if (item.get("payload") or {}).get("initiative_key")
        }

        created: list[dict[str, Any]] = []
        task_ids_by_agent: dict[str, str] = {}
        for spec in specs:
            previous_initiative = self.store.continuous_improvement_initiative_by_key(spec["initiative_key"])
            if (previous_initiative or {}).get("status") in {"CLOSED", "REJECTED"}:
                continue
            if (previous_initiative or {}).get("status") == "MONITORING" and event["event_id"] in (
                previous_initiative or {}
            ).get("linked_event_ids", []):
                continue
            initiative = self.store.upsert_continuous_improvement_initiative(
                {
                    "initiative_id": new_id("ci_init"),
                    "initiative_key": spec["initiative_key"],
                    "title": spec["title"],
                    "domain": domain,
                    "status": "OPEN",
                    "owner_agent": spec["owner_agent"],
                    "priority": spec.get("priority", "MEDIUM"),
                    "target_metric": spec.get("target_metric", ""),
                    "baseline_value": spec.get("baseline_value"),
                    "current_value": spec.get("current_value"),
                    "expected_impact": spec.get("expected_impact", ""),
                    "risk_level": spec.get("risk_level", "LOW"),
                    "evidence": [f"event_type={event.get('event_type')}"],
                    "linked_event_ids": [event["event_id"]],
                    "linked_task_ids": [],
                    "linked_hypothesis_ids": [],
                    "linked_proposal_ids": [],
                    "linked_validation_ids": [],
                    "latest_decision": {"decision": "OPEN", "source": "orchestrator"},
                    "next_action": "Crear y ejecutar tareas del grupo experto.",
                }
            )
            if spec["initiative_key"] in existing_keys:
                continue
            for index, agent_name in enumerate(spec["agents"]):
                task_id = new_id("ci_task")
                task_ids_by_agent[f"{spec['initiative_key']}:{agent_name}"] = task_id
                payload = {
                    **spec.get("payload", {}),
                    "initiative_id": initiative[0],
                    "initiative_key": spec["initiative_key"],
                    "initiative_title": spec["title"],
                    "target_metric": spec.get("target_metric", ""),
                    "owner_agent": spec.get("owner_agent"),
                }
                created.append(
                    {
                        "task_id": task_id,
                        "cycle_id": cycle_id,
                        "event_id": event["event_id"],
                        "agent_name": agent_name,
                        "domain": domain,
                        "status": TaskStatus.DISCOVERED.value,
                        "priority": spec.get("priority", "MEDIUM"),
                        "dependency_ids": [],
                        "payload": payload,
                        "dependency_agent_names": spec["agents"][:index],
                    }
                )

        for item in created:
            dependency_names = item.pop("dependency_agent_names", [])
            if dependency_names:
                item["dependency_ids"] = [
                    task_ids_by_agent.get(f"{item['payload']['initiative_key']}:{name}")
                    for name in dependency_names
                    if task_ids_by_agent.get(f"{item['payload']['initiative_key']}:{name}")
                ]
                item["status"] = TaskStatus.WAITING_DEPENDENCY.value
            self.store.create_continuous_improvement_task(item)

        self.store.update_continuous_improvement_event(event["event_id"], status="PLANNED")
        return self.store.continuous_improvement_tasks(event_id=event["event_id"], limit=200)

    def create_tasks_for_event(
        self,
        *,
        cycle_id: str,
        event: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        planned = self.planned_tasks_for_event(event, context or {})
        if not planned:
            self.store.update_continuous_improvement_event(event["event_id"], status="COMPLETED")
            return []
        for task in planned:
            if task.get("cycle_id") != cycle_id:
                self.store.update_continuous_improvement_task(task["task_id"], cycle_id=cycle_id)
                task["cycle_id"] = cycle_id
        return planned

    def _max_duplicate_count(self, context: dict[str, Any]) -> int:
        observations = context.get("learning", {}).get("observations", []) or []
        return max([int(item.get("duplicate_count") or 0) for item in observations], default=0)

    def ready_tasks(self, *, limit: int = 50) -> list[dict[str, Any]]:
        tasks = self.store.continuous_improvement_tasks(
            statuses=[
                TaskStatus.DISCOVERED.value,
                TaskStatus.WAITING_DEPENDENCY.value,
                TaskStatus.ASSIGNED.value,
            ],
            limit=limit,
        )
        ready: list[dict[str, Any]] = []
        for task in tasks:
            deps = task.get("dependency_ids") or []
            if not deps:
                ready.append(task)
                continue
            dep_rows = [self.store.continuous_improvement_task(dep_id) for dep_id in deps]
            if all(dep and dep.get("status") == TaskStatus.COMPLETED.value for dep in dep_rows):
                if task["status"] == TaskStatus.WAITING_DEPENDENCY.value:
                    self.store.update_continuous_improvement_task(task["task_id"], status=TaskStatus.DISCOVERED.value)
                    task["status"] = TaskStatus.DISCOVERED.value
                ready.append(task)
        return ready

    def agent_class(self, agent_name: str) -> type:
        for enum_key, klass in SPECIALIST_AGENT_CLASSES.items():
            if enum_key.value == agent_name:
                return klass
        raise KeyError(agent_name)

    def persist_hypotheses(
        self,
        *,
        cycle_id: str,
        event: dict[str, Any],
        task: dict[str, Any],
        response: dict[str, Any],
    ) -> list[str]:
        hypothesis_ids: list[str] = []
        hypotheses = (((response.get("response") or {}).get("hypotheses")) or [])
        initiative_id = str((task.get("payload") or {}).get("initiative_id") or "")
        for item in hypotheses:
            summary = str(item.get("summary") or "")
            subject = str(item.get("subject") or "")
            if not summary or not subject:
                continue
            hypothesis_id = new_id("ci_hyp")
            fingerprint = hypothesis_fingerprint(subject, summary, str(task.get("domain") or "software"))
            stored_id, inserted = self.store.upsert_continuous_improvement_hypothesis(
                {
                    "hypothesis_id": hypothesis_id,
                    "cycle_id": cycle_id,
                    "event_id": event["event_id"],
                    "domain": task.get("domain", "software"),
                    "subject": subject,
                    "status": "OPEN",
                    "confidence": item.get("confidence", "LOW"),
                    "fingerprint": fingerprint,
                    "summary_text": summary,
                    "evidence": item.get("evidence", []),
                    "source_task_ids": [task["task_id"]],
                    "proposal_ids": [],
                }
            )
            if inserted and initiative_id:
                self.store.append_continuous_improvement_initiative_links(
                    initiative_id,
                    hypothesis_ids=[stored_id],
                    event_ids=[event["event_id"]],
                    task_ids=[task["task_id"]],
                )
            hypothesis_ids.append(stored_id)
        return hypothesis_ids

    def build_code_artifact(self, proposal: dict[str, Any]) -> str:
        payload = proposal.get("payload", {}) or {}
        return "\n".join(
            [
                f"# {proposal.get('proposal_type', 'CODE_CHANGE')}",
                "",
                f"Target component: `{proposal.get('target_component', '-')}`",
                f"Target identifier: `{proposal.get('target_identifier', '-')}`",
                "",
                "## Rationale",
                payload.get("rationale") or "",
                "",
                "## Suggested change",
                payload.get("proposed_value") or "",
                "",
                "## Rollback",
                payload.get("rollback_plan") or "",
            ]
        )


def scheduled_dedupe_key(settings: Any) -> str:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    return f"continuous-improvement:scheduled:{today}:{settings.continuous_improvement_time_local}"
