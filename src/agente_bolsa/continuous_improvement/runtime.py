"""Resident runtime for the continuous improvement lab."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.logging_utils import log_system_event
from agente_bolsa.market_calendar import MarketCalendar
from agente_bolsa.models import AgentEvent, new_id
from agente_bolsa.storage import Store
from agente_bolsa.tools.backtest import build_symbol_backtest
from agente_bolsa.tools.counterfactual_analysis import build_session_retrospective_report, build_walk_forward_validation_report

from .agents import (
    DataCollectorAgent,
    ChiefInvestmentOrchestratorAgent,
    PerformanceEvaluatorAgent,
    ReportAgent,
    RiskGuardAgent,
    SPECIALIST_AGENT_CLASSES,
    ValidationAgent,
    initiative_owner_from_key,
    initiative_title_from_key,
    initiative_topic_key,
    event_fingerprint,
    proposal_fingerprint,
)
from .llm_client import ImprovementLLMClient
from .memory import SharedMemory
from .orchestration import LabOrchestrator
from .experiments import AutoApplyCodeAgent
from .schemas import CycleStatus, ImprovementProposalPayload, RuntimeStatus, TaskStatus


class ContinuousImprovementLabRuntime:
    def __init__(self, settings: Settings, store: Store, *, runtime_name: str = "lab") -> None:
        self.settings = settings
        self.store = store
        self.runtime_name = runtime_name
        self.client = ImprovementLLMClient(settings)
        self.collector = DataCollectorAgent()
        self.evaluator = PerformanceEvaluatorAgent()
        self.shared_memory = SharedMemory(store)
        self.orchestrator = LabOrchestrator(store)
        self.strategist = ChiefInvestmentOrchestratorAgent(self.client, settings)
        self.guard = RiskGuardAgent()
        self.validator = ValidationAgent()
        self.reporter = ReportAgent()
        self.code_applier = AutoApplyCodeAgent()

    def _market_window(self) -> tuple[bool, str, dict[str, Any]]:
        calendar = MarketCalendar(self.settings.market_calendar, self.settings.local_timezone)
        status = calendar.status()
        payload = status.as_dict()
        if status.is_open:
            return True, "Mercado abierto dentro de ventana permitida.", payload

        now_utc = datetime.fromisoformat(status.now_utc)
        previous_close_ok = False
        next_open_ok = False

        next_open_raw = status.next_open
        if next_open_raw:
            next_open = datetime.fromisoformat(str(next_open_raw)).astimezone(timezone.utc)
            next_open_ok = next_open - timedelta(minutes=10) <= now_utc < next_open

        next_close_raw = status.next_close
        if next_close_raw:
            next_close = datetime.fromisoformat(str(next_close_raw)).astimezone(timezone.utc)
            previous_close_ok = next_close <= now_utc <= next_close + timedelta(minutes=10)

        if next_open_ok:
            return True, "Ventana de gracia activa: 10 minutos antes de apertura.", payload
        if previous_close_ok:
            return True, "Ventana de gracia activa: 10 minutos despues del cierre.", payload
        return False, "Laboratorio bloqueado: solo opera con mercado abierto o +/-10 minutos.", payload

    def describe_agents(self) -> list[dict[str, Any]]:
        descriptions = {
            "ChiefInvestmentOrchestratorAgent": "Coordina iniciativas y prioriza el comite externo.",
            "MarketRegimeAgent": "Analiza regimen, benchmark y volatilidad.",
            "TechnicalEdgeAgent": "Evalua filtros de entrada, ruido y duplicados.",
            "PreEarningsSpecialistAgent": "Analiza earnings, estimaciones y veto pre-earnings.",
            "StrategyEvaluatorAgent": "Contrasta resultados, baseline y degradacion.",
            "RiskCapitalAgent": "Revisa riesgo, drawdown y limites de capital.",
            "DataQualityAgent": "Controla cobertura, duplicados y consistencia de datos.",
            "SoftwareReliabilityAgent": "Reduce errores repetidos y deuda tecnica.",
            "ExperimentDesignerAgent": "Convierte hipotesis en experimentos seguros.",
            "DecisionCommitteeAgent": "Cierra iniciativas con decisiones trazables.",
            "MarketEstimatorAgent": "Agente legacy de analisis de mercado.",
            "TechnicalAnalystAgent": "Agente legacy de analisis tecnico.",
            "SentimentAnalystAgent": "Evalua contexto de noticias y sentimiento disponible.",
            "ProgrammerAgent": "Propone mejoras de software y artefactos revisables.",
            "RiskGuardAgent": "Aplica gates deterministas de seguridad.",
            "ValidationAgent": "Ejecuta validaciones seguras y pendientes.",
            "ReportAgent": "Genera informes de ciclo y estado operativo.",
        }
        heartbeat = self.store.continuous_improvement_runtime_state(self.runtime_name)
        return [
            {
                "agent_name": name,
                "kind": "specialist" if name in {item.value for item in SPECIALIST_AGENT_CLASSES} else "support",
                "description": descriptions.get(name, ""),
                "runtime_heartbeat": (heartbeat or {}).get("heartbeat_at"),
            }
            for name in descriptions
        ]

    def _should_skip_task(
        self,
        *,
        task: dict[str, Any],
        event: dict[str, Any],
        context: dict[str, Any],
    ) -> str | None:
        if task.get("agent_name") != "SentimentAnalystAgent":
            return None
        reports = context.get("reports", {}) or {}
        payloads = [
            item.get("payload")
            for item in reports.values()
            if isinstance(item, dict) and item.get("available") and isinstance(item.get("payload"), dict)
        ]
        if any(self._has_sentiment_signal(payload) for payload in payloads):
            return None
        return "Sin datos estructurados de sentimiento o noticias en el contexto disponible."

    def _has_sentiment_signal(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {"sentiment", "news_sentiment", "sentiment_score", "headlines", "news_items"} and item:
                    return True
                if self._has_sentiment_signal(item):
                    return True
            return False
        if isinstance(value, list):
            return any(self._has_sentiment_signal(item) for item in value)
        return False

    def _initiative_key_for_task(self, task: dict[str, Any]) -> str:
        payload = task.get("payload") or {}
        initiative_key = str(payload.get("initiative_key") or "").strip()
        if initiative_key:
            return initiative_key
        domain = "trading" if "trading" in str(task.get("domain") or "").lower() else "software"
        focus = str(payload.get("focus") or task.get("agent_name") or "general")
        return initiative_topic_key(domain=domain, focus=focus)

    def _initiative_id_for_task(self, task: dict[str, Any], *, ensure: bool = True) -> str | None:
        payload = task.get("payload") or {}
        initiative_id = str(payload.get("initiative_id") or "").strip()
        if initiative_id:
            return initiative_id
        initiative_key = self._initiative_key_for_task(task)
        initiative = self.store.continuous_improvement_initiative_by_key(initiative_key)
        if initiative:
            return initiative["initiative_id"]
        if not ensure:
            return None
        initiative_id = new_id("ci_init")
        self.store.upsert_continuous_improvement_initiative(
            {
                "initiative_id": initiative_id,
                "initiative_key": initiative_key,
                "title": initiative_title_from_key(initiative_key),
                "domain": "trading" if initiative_key.startswith("trading:") else "software",
                "status": "OPEN",
                "owner_agent": initiative_owner_from_key(initiative_key),
                "priority": str(task.get("priority") or "MEDIUM"),
                "target_metric": str(payload.get("target_metric") or "impact"),
                "baseline_value": None,
                "current_value": None,
                "expected_impact": "Iniciativa creada desde la actividad del laboratorio.",
                "risk_level": "LOW",
                "evidence": [f"task_id={task.get('task_id')}"],
                "linked_event_ids": [task.get("event_id")] if task.get("event_id") else [],
                "linked_task_ids": [task.get("task_id")] if task.get("task_id") else [],
                "linked_hypothesis_ids": [],
                "linked_proposal_ids": [],
                "linked_validation_ids": [],
                "latest_decision": {"decision": "OPEN", "source": "runtime"},
                "next_action": "Esperar actividad del grupo.",
            }
        )
        return initiative_id

    def _record_initiative_message(
        self,
        *,
        initiative_id: str | None,
        cycle_id: str | None,
        event: dict[str, Any] | None,
        task: dict[str, Any] | None,
        agent: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        if not initiative_id:
            return
        self.store.save_continuous_improvement_initiative_message(
            {
                "message_id": new_id("ci_msg"),
                "initiative_id": initiative_id,
                "cycle_id": cycle_id,
                "event_id": (event or {}).get("event_id"),
                "task_id": (task or {}).get("task_id"),
                "agent_name": agent,
                "role": "agent",
                "message_type": message_type,
                "content": payload,
            }
        )
        links: dict[str, list[str]] = {}
        if event and event.get("event_id"):
            links["event_ids"] = [event["event_id"]]
        if task and task.get("task_id"):
            links["task_ids"] = [task["task_id"]]
        if links:
            self.store.append_continuous_improvement_initiative_links(initiative_id, **links)

    def _task_required_validations(self, result: dict[str, Any]) -> list[str]:
        response = (result.get("response") or {}) if isinstance(result, dict) else {}
        actions = response.get("actions") or []
        required: list[str] = []
        for action in actions:
            if str(action.get("action_type") or "").upper() != "VALIDATION":
                continue
            for item in action.get("required_validations") or []:
                text = str(item or "").strip().lower()
                if text and text not in required:
                    required.append(text)
        return required

    def _initiative_updates_from_task_result(self, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        agent_name = str(task.get("agent_name") or "")
        response = (result.get("response") or {}) if isinstance(result, dict) else {}
        summary = str(response.get("summary") or "").strip()
        focus = str((task.get("payload") or {}).get("focus") or "").strip()
        if agent_name == "ExperimentDesignerAgent":
            required = self._task_required_validations(result)
            next_action = "Ejecutar validaciones: " + ", ".join(required) if required else "Ejecutar validaciones objetivas."
            return {
                "status": "EXPERIMENTING",
                "next_action": next_action,
                "latest_decision": {
                    "decision": "EXPERIMENTING",
                    "source": agent_name,
                    "required_validations": required,
                    "focus": focus,
                },
            }
        if agent_name == "DecisionCommitteeAgent":
            decision = self._committee_decision_from_response(response)
            return {
                "status": str(decision.get("initiative_status_target") or "WAITING_REVIEW"),
                "priority": self._priority_from_committee_decision(decision),
                "next_action": str(decision.get("required_follow_up") or summary or "Esperar validacion objetiva y cerrar la iniciativa."),
                "latest_decision": {
                    **decision,
                    "source": agent_name,
                    "focus": focus,
                },
            }
        return {
            "status": "VALIDATING",
            "next_action": "Esperar validacion objetiva y consolidar propuestas.",
            "latest_decision": {
                "decision": "VALIDATING",
                "source": agent_name or "runtime",
                "focus": focus,
            },
        }

    def _committee_decision_from_response(self, response: dict[str, Any]) -> dict[str, Any]:
        decision = str(response.get("decision") or "ESCALATE").upper()
        if decision not in {"APPROVE", "REJECT", "REWORK", "MONITOR", "ESCALATE"}:
            decision = "ESCALATE"
        return {
            "decision": decision,
            "reason": str(response.get("decision_reason") or response.get("summary") or ""),
            "initiative_status_target": str(response.get("initiative_status_target") or self._initiative_status_from_committee_decision(decision)),
            "proposal_status_targets": response.get("proposal_status_targets") or [],
            "priority_adjustment": str(response.get("priority_adjustment") or "keep"),
            "backlog_rank": response.get("backlog_rank"),
            "backlog_bucket": response.get("backlog_bucket") or self._backlog_bucket_for_committee_decision(decision),
            "required_follow_up": str(response.get("required_follow_up") or self._initiative_next_action_from_committee_decision(decision)),
            "close_initiative": bool(response.get("close_initiative")),
        }

    def _priority_from_committee_decision(self, decision: dict[str, Any]) -> str:
        bucket = str(decision.get("backlog_bucket") or "")
        if bucket in {"NOW", "HUMAN"}:
            return "HIGH"
        if bucket == "NEXT":
            return "MEDIUM"
        return "LOW"

    def _initiative_status_from_committee_decision(self, decision: str) -> str:
        return {
            "APPROVE": "READY_TO_APPLY",
            "REJECT": "REJECTED",
            "REWORK": "EXPERIMENTING",
            "MONITOR": "MONITORING",
            "ESCALATE": "WAITING_REVIEW",
        }.get(decision, "VALIDATING")

    def _initiative_next_action_from_committee_decision(self, decision: str) -> str:
        return {
            "APPROVE": "Aplicar o promover la propuesta validada.",
            "REJECT": "Cerrar la iniciativa como rechazada.",
            "REWORK": "Generar artefacto, rollback o evidencia faltante.",
            "MONITOR": "Mantener en seguimiento hasta nueva evidencia.",
            "ESCALATE": "Esperar revision humana por riesgo o ambiguedad.",
        }.get(decision, "Esperar nueva evidencia.")

    def _backlog_bucket_for_committee_decision(self, decision: str) -> str:
        return {
            "APPROVE": "NOW",
            "REWORK": "NEXT",
            "MONITOR": "LATER",
            "ESCALATE": "HUMAN",
            "REJECT": "LATER",
        }.get(decision, "NEXT")

    def _apply_committee_decision(
        self,
        *,
        cycle_id: str,
        initiative_id: str | None,
        task: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if task.get("agent_name") != "DecisionCommitteeAgent" or not initiative_id:
            return
        initiative = self.store.continuous_improvement_initiative(initiative_id)
        if not initiative:
            return
        response = (result.get("response") or {}) if isinstance(result, dict) else {}
        decision = self._committee_decision_from_response(response)
        targets = decision.get("proposal_status_targets") or []
        target_by_id = {
            str(item.get("proposal_id")): str(item.get("status") or "")
            for item in targets
            if item.get("proposal_id")
        }
        proposal_ids = list(initiative.get("linked_proposal_ids") or [])
        for proposal_id in target_by_id:
            if proposal_id not in proposal_ids:
                proposal_ids.append(proposal_id)
        affected: list[str] = []
        for proposal_id in proposal_ids:
            proposal = self.store.continuous_improvement_proposal(proposal_id)
            if not proposal:
                continue
            status = target_by_id.get(proposal_id) or self._proposal_status_from_committee_decision(decision["decision"], proposal)
            self.store.update_continuous_improvement_proposal_status(
                proposal_id,
                status=status,
                actor="DecisionCommitteeAgent",
                reason=decision["reason"],
                payload={"committee_decision": decision, "initiative_id": initiative_id},
            )
            self.store.save_continuous_improvement_decision(
                {
                    "decision_id": new_id("ci_decision"),
                    "proposal_id": proposal_id,
                    "cycle_id": proposal.get("cycle_id") or cycle_id,
                    "decision": decision["decision"],
                    "reason": decision["reason"],
                    "actor": "DecisionCommitteeAgent",
                    "payload": {
                        "initiative_id": initiative_id,
                        "initiative_key": initiative.get("initiative_key"),
                        "committee_decision": decision,
                        "affected_proposal_ids": proposal_ids,
                    },
                }
            )
            affected.append(proposal_id)
        if affected:
            self.store.append_continuous_improvement_initiative_links(initiative_id, proposal_ids=affected)

    def _proposal_status_from_committee_decision(self, decision: str, proposal: dict[str, Any]) -> str:
        current = str(proposal.get("status") or "PENDING").upper()
        if decision == "APPROVE":
            return "READY_TO_APPLY" if current == "READY_TO_APPLY" else "PASSED"
        if decision == "REJECT":
            return "REJECTED"
        if decision == "REWORK":
            return "PENDING"
        if decision == "ESCALATE":
            return "WAITING_HUMAN_REVIEW"
        return current if current else "PENDING"

    def _experiment_guidance_by_initiative(self, specialist_results: list[dict[str, Any]]) -> dict[str, list[str]]:
        guidance: dict[str, list[str]] = {}
        for item in specialist_results:
            task = item.get("task") or {}
            task_payload = task.get("payload") or {}
            initiative_key = str(task_payload.get("initiative_key") or self._initiative_key_for_task(task) or "").strip()
            if not initiative_key:
                continue
            for validation_name in self._task_required_validations(item.get("result") or {}):
                guidance.setdefault(initiative_key, [])
                if validation_name not in guidance[initiative_key]:
                    guidance[initiative_key].append(validation_name)
        return guidance

    def _proposal_symbol(self, proposal: dict[str, Any]) -> str | None:
        payload = proposal.get("payload") or {}
        candidates = [
            payload.get("symbol"),
            payload.get("target_identifier"),
            proposal.get("target_identifier"),
            proposal.get("symbol"),
        ]
        for candidate in candidates:
            text = re.sub(r"[^A-Z0-9]+", "", str(candidate or "").upper())
            if 1 <= len(text) <= 6 and text.isalpha():
                return text
        return None

    def _execute_validation_artifacts(
        self,
        *,
        proposal: dict[str, Any],
        cycle_id: str,
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        required = {str(item).lower() for item in payload.get("required_validations", []) or []}
        reports_dir = self.settings.data_dir / "reports"
        artifacts: dict[str, Any] = {}
        if "backtest" in required:
            symbol = self._proposal_symbol(proposal)
            if symbol:
                try:
                    artifacts["backtest"] = build_symbol_backtest(
                        symbol,
                        reports_dir,
                        new_id("ci_bt"),
                        start=str(payload.get("backtest_start") or payload.get("since_date") or "2026-04-01"),
                        end=(str(payload.get("backtest_end") or payload.get("end_date") or "") or None),
                        min_score=int(payload.get("min_score") or self.settings.entry_quality_min_score),
                        setup_quality=str(payload.get("setup_quality") or "strong"),
                        max_holding_days=int(payload.get("max_holding_days") or 10),
                        benchmark_symbol=str(payload.get("benchmark_symbol") or self.settings.benchmark_symbol),
                        provider=self.settings.market_data_provider,
                        fmp_api_key=self.settings.fmp_api_key,
                        gate_config={
                            "min_trades": self.settings.backtest_gate_min_trades,
                            "min_hit_rate": self.settings.backtest_gate_min_hit_rate,
                            "min_profit_factor": self.settings.backtest_gate_min_profit_factor,
                            "max_drawdown": self.settings.backtest_gate_max_drawdown,
                            "min_alpha_vs_benchmark": self.settings.backtest_gate_min_alpha_vs_benchmark,
                            "min_trade_window_alpha": self.settings.backtest_gate_min_trade_window_alpha,
                            "min_regime_trades": self.settings.backtest_gate_min_regime_trades,
                            "max_negative_regimes": self.settings.backtest_gate_max_negative_regimes,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    artifacts["backtest_error"] = str(exc)
            else:
                artifacts["backtest_error"] = "No se pudo inferir un simbolo para ejecutar backtest."
        if "baseline_compare" in required:
            try:
                artifacts["session_retrospective"] = build_session_retrospective_report(
                    self.settings,
                    self.store,
                    reports_dir,
                    new_id("ci_sr"),
                    since_date=str(payload.get("since_date") or "2026-04-01"),
                    end_date=(str(payload.get("end_date") or "") or None),
                    sessions=int(payload.get("sessions") or 8),
                    policy=str(payload.get("policy") or "proposed"),
                    full=False,
                )
            except Exception as exc:  # noqa: BLE001
                artifacts["session_retrospective_error"] = str(exc)
        if "shadow_review" in required or proposal.get("proposal_type") in {"RISK_RULE_CHANGE", "STRATEGY_RULE_CHANGE"}:
            try:
                artifacts["walk_forward_validation"] = build_walk_forward_validation_report(
                    self.settings,
                    self.store,
                    reports_dir,
                    new_id("ci_wf"),
                    since_date=str(payload.get("since_date") or "2026-04-01"),
                    end_date=(str(payload.get("end_date") or "") or None),
                    policy=str(payload.get("policy") or "proposed"),
                    train_days=int(payload.get("train_days") or 5),
                    test_days=int(payload.get("test_days") or 3),
                    full=False,
                )
            except Exception as exc:  # noqa: BLE001
                artifacts["walk_forward_validation_error"] = str(exc)
        if artifacts:
            self._record_agent_event(
                agent="ValidationAgent",
                event_type="lab_validation_artifacts_generated",
                cycle_id=cycle_id,
                payload={
                    "proposal_id": proposal.get("proposal_id"),
                    "initiative_key": payload.get("initiative_key"),
                    "artifacts": sorted(artifacts.keys()),
                },
            )
        return artifacts

    def _latest_report_payload(self, name: str) -> dict[str, Any]:
        path = self.settings.data_dir / "reports" / name
        if not path.exists():
            return {"available": False}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"available": False, "warning": f"{name} invalido"}
        return {"available": True, "path": str(path), "payload": payload}

    def enqueue_event(
        self,
        *,
        event_type: str,
        source: str,
        domain: str,
        payload: dict[str, Any],
        priority: str = "MEDIUM",
        force_unique: bool = False,
    ) -> dict[str, Any]:
        event_id = new_id("ci_event")
        if force_unique:
            payload = {**payload, "_nonce": event_id}
        fingerprint = event_fingerprint(event_type, source, payload)
        cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=self.settings.continuous_improvement_event_cooldown_seconds)).isoformat()
        stored_id, inserted = self.store.upsert_continuous_improvement_event(
            {
                "event_id": event_id,
                "event_type": event_type,
                "domain": domain,
                "status": "DISCOVERED",
                "source": source,
                "priority": priority,
                "fingerprint": fingerprint,
                "payload": payload,
                "cooldown_until": cooldown_until,
            }
        )
        event = self.store.continuous_improvement_event(stored_id)
        return {"inserted": inserted, "event": event}

    def discover_system_events(self) -> list[dict[str, Any]]:
        reports_dir = self.settings.data_dir / "reports"
        discovered: list[dict[str, Any]] = []
        report_specs = [
            ("latest_daily_learning_digest", "trading-improvement"),
            ("latest_post_market_review", "trading-improvement"),
            ("latest_market_data_quality", "software-improvement"),
        ]
        for stem, domain in report_specs:
            path = reports_dir / f"{stem}.json"
            if not path.exists():
                continue
            payload = {"path": str(path), "mtime": path.stat().st_mtime}
            result = self.enqueue_event(event_type=stem, source="runtime", domain=domain, payload=payload)
            if result.get("inserted"):
                discovered.append(result["event"])

        recent_errors = [
            item
            for item in self.store.latest_events(40)
            if "fail" in str(item.get("event_type", "")).lower() or "error" in str(item.get("payload_json", "")).lower()
        ]
        if len(recent_errors) >= 3:
            payload = {
                "sample_event_ids": [item.get("event_id") for item in recent_errors[:5]],
                "count": len(recent_errors),
            }
            result = self.enqueue_event(
                event_type="repeated_errors_detected",
                source="runtime",
                domain="software-improvement",
                payload=payload,
            )
            if result.get("inserted"):
                discovered.append(result["event"])

        market_cycle_status = self.store.get_runtime_value("scheduler_job_status:market_cycle") or {}
        if market_cycle_status:
            payload = {
                "status": market_cycle_status.get("status"),
                "updated_at": market_cycle_status.get("updated_at"),
            }
            if self._scheduler_state_changed(payload):
                result = self.enqueue_event(
                    event_type="scheduler_state_changed",
                    source="runtime",
                    domain="software-improvement",
                    payload=payload,
                )
                if result.get("inserted"):
                    discovered.append(result["event"])
        return discovered

    def _scheduler_state_changed(self, payload: dict[str, Any]) -> bool:
        for item in self.store.continuous_improvement_events(limit=200):
            if item.get("event_type") != "scheduler_state_changed":
                continue
            previous = item.get("payload") or {}
            return (
                str(previous.get("status") or "") != str(payload.get("status") or "")
                or str(previous.get("updated_at") or "") != str(payload.get("updated_at") or "")
            )
        return True

    def _start_cycle(self, *, mode: str) -> str:
        cycle_id = new_id("ci_cycle")
        self.store.create_continuous_improvement_cycle(
            {
                "cycle_id": cycle_id,
                "trace_id": new_id("ci_trace"),
                "job_id": new_id("ci_job"),
                "status": CycleStatus.RUNNING.value,
                "mode": mode,
                "dry_run": self.settings.improvement_dry_run,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return cycle_id

    def _record_agent_event(
        self,
        *,
        agent: str,
        event_type: str,
        cycle_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        self.store.record_agent_event(
            AgentEvent(
                agent=agent,
                event_type=event_type,
                cycle_id=cycle_id,
                payload=payload,
            )
        )

    def _update_runtime(self, *, status: RuntimeStatus, payload: dict[str, Any]) -> None:
        self.store.upsert_continuous_improvement_runtime_state(
            runtime_name=self.runtime_name,
            status=status.value,
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )

    def run_once(
        self,
        *,
        mode: str = "manual",
        trigger_event_type: str = "manual_trigger",
        trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.store.ensure_schema()
        if not self.settings.continuous_improvement_enabled:
            return {"ok": False, "status": "DISABLED", "reason": "CONTINUOUS_IMPROVEMENT_ENABLED=false"}
        market_allowed, market_reason, market_payload = self._market_window()
        if not market_allowed:
            self._update_runtime(
                status=RuntimeStatus.IDLE,
                payload={
                    "status": "MARKET_BLOCKED",
                    "reason": market_reason,
                    "market": market_payload,
                },
            )
            self._record_agent_event(
                agent="continuous_improvement_lab",
                event_type="lab_market_window_blocked",
                cycle_id=None,
                payload={"reason": market_reason, "market": market_payload, "mode": mode},
            )
            return {"ok": False, "status": "MARKET_BLOCKED", "reason": market_reason, "market": market_payload}

        cycle_id = self._start_cycle(mode=mode)
        self._update_runtime(status=RuntimeStatus.RUNNING, payload={"cycle_id": cycle_id, "mode": mode})
        self._record_agent_event(
            agent="continuous_improvement_lab",
            event_type="lab_cycle_started",
            cycle_id=cycle_id,
            payload={"mode": mode, "runtime": self.runtime_name, "market": market_payload, "market_reason": market_reason},
        )
        log_system_event(self.settings.logs_dir, "continuous_improvement_lab_cycle_started", {"cycle_id": cycle_id, "mode": mode})

        try:
            self.store.update_continuous_improvement_cycle(cycle_id, status=CycleStatus.COLLECTING_DATA.value)
            context = self.collector.collect(self.settings, self.store, cycle_id=cycle_id)
            evaluation = self.evaluator.evaluate(context)
            context["evaluation"] = evaluation
            self.store.update_continuous_improvement_cycle(cycle_id, context=context, evaluation=evaluation)

            if trigger_event_type.startswith("manual"):
                self.enqueue_event(
                    event_type=trigger_event_type,
                    source=mode,
                    domain="software-improvement",
                    payload=trigger_payload or {"cycle_id": cycle_id, "mode": mode},
                    force_unique=True,
                )
            self.discover_system_events()

            open_events = self.store.continuous_improvement_events(statuses=["DISCOVERED", "PLANNED"], limit=50)
            event_batch: list[dict[str, Any]] = []
            for event in open_events:
                event_batch.append(event)
                self.orchestrator.create_tasks_for_event(cycle_id=cycle_id, event=event, context=context)
                self._record_agent_event(
                    agent="OrchestratorAgent",
                    event_type="lab_event_planned",
                    cycle_id=cycle_id,
                    payload={
                        "event_id": event["event_id"],
                        "event_type": event["event_type"],
                        "domain": event["domain"],
                    },
                )

            specialist_results: list[dict[str, Any]] = []
            while True:
                ready = self.orchestrator.ready_tasks(limit=50)
                if not ready:
                    break
                for task in ready:
                    event = self.store.continuous_improvement_event(task["event_id"])
                    if not event:
                        continue
                    initiative_id = self._initiative_id_for_task(task)
                    skip_reason = self._should_skip_task(task=task, event=event, context=context)
                    if skip_reason:
                        self.store.update_continuous_improvement_task(
                            task["task_id"],
                            status=TaskStatus.CANCELLED.value,
                            finished_at=datetime.now(timezone.utc).isoformat(),
                            result={"status": "SKIPPED", "reason": skip_reason},
                        )
                        self._record_agent_event(
                            agent=task["agent_name"],
                            event_type="lab_task_skipped",
                            cycle_id=cycle_id,
                            payload={
                                "task_id": task["task_id"],
                                "event_id": event["event_id"],
                                "focus": (task.get("payload") or {}).get("focus"),
                                "reason": skip_reason,
                                "status": "CANCELLED",
                                "initiative_id": initiative_id,
                            },
                        )
                        self._record_initiative_message(
                            initiative_id=initiative_id,
                            cycle_id=cycle_id,
                            event=event,
                            task=task,
                            agent=task["agent_name"],
                            message_type="task_skipped",
                            payload={
                                "summary": skip_reason,
                                "focus": (task.get("payload") or {}).get("focus"),
                                "status": "CANCELLED",
                            },
                        )
                        continue
                    self.store.update_continuous_improvement_task(
                        task["task_id"],
                        status=TaskStatus.RUNNING.value,
                        started_at=datetime.now(timezone.utc).isoformat(),
                        attempt_count=int(task.get("attempt_count") or 0) + 1,
                    )
                    self._record_agent_event(
                        agent=task["agent_name"],
                        event_type="lab_task_started",
                        cycle_id=cycle_id,
                        payload={
                            "task_id": task["task_id"],
                            "event_id": event["event_id"],
                            "focus": (task.get("payload") or {}).get("focus"),
                            "status": "RUNNING",
                            "initiative_id": initiative_id,
                        },
                    )
                    self._record_initiative_message(
                        initiative_id=initiative_id,
                        cycle_id=cycle_id,
                        event=event,
                        task=task,
                        agent=task["agent_name"],
                        message_type="task_started",
                        payload={
                            "summary": f"{task['agent_name']} ha empezado {((task.get('payload') or {}).get('focus') or 'la tarea')}.",
                            "focus": (task.get("payload") or {}).get("focus"),
                            "status": "RUNNING",
                        },
                    )
                    if initiative_id:
                        self.store.update_continuous_improvement_initiative(
                            initiative_id,
                            status="ANALYZING",
                            next_action="Esperar salida del agente y consolidar hipotesis.",
                        )
                    agent_cls = self.orchestrator.agent_class(task["agent_name"])
                    agent = agent_cls(self.settings, self.client)
                    result = agent.run(context, event, task.get("payload") or {})
                    self.store.update_continuous_improvement_task(
                        task["task_id"],
                        status=TaskStatus.COMPLETED.value,
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        result=result,
                    )
                    self._record_agent_event(
                        agent=task["agent_name"],
                        event_type="lab_task_completed",
                        cycle_id=cycle_id,
                        payload={
                            "task_id": task["task_id"],
                            "event_id": event["event_id"],
                            "summary": ((result.get("response") or {}).get("summary") or "")[:240],
                            "status": "COMPLETED",
                            "initiative_id": initiative_id,
                        },
                    )
                    self._record_initiative_message(
                        initiative_id=initiative_id,
                        cycle_id=cycle_id,
                        event=event,
                        task=task,
                        agent=task["agent_name"],
                        message_type="task_completed",
                        payload={
                            "summary": ((result.get("response") or {}).get("summary") or "")[:500],
                            "deterministic": result.get("deterministic") or {},
                            "llm": result.get("llm") or {},
                            "response": result.get("response") or {},
                            "status": "COMPLETED",
                        },
                    )
                    if initiative_id:
                        updates = self._initiative_updates_from_task_result(task=task, result=result)
                        self.store.update_continuous_improvement_initiative(initiative_id, **updates)
                        self._apply_committee_decision(
                            cycle_id=cycle_id,
                            initiative_id=initiative_id,
                            task=task,
                            result=result,
                        )
                    specialist_results.append(
                        {
                            "task_id": task["task_id"],
                            "event_id": event["event_id"],
                            "initiative_id": initiative_id,
                            "task": task,
                            "result": result,
                        }
                    )
                    self.orchestrator.persist_hypotheses(cycle_id=cycle_id, event=event, task=task, response=result)
                    self.shared_memory.remember(
                        memory_key=f"{task['agent_name']}:{event['event_id']}",
                        domain=task.get("domain", "software"),
                        summary_text=((result.get("response") or {}).get("summary") or "")[:500],
                        payload=result,
                        source_event_id=event["event_id"],
                    )
                    event_tasks = self.store.continuous_improvement_tasks(event_id=event["event_id"], limit=50)
                    if event_tasks and all(item.get("status") == TaskStatus.COMPLETED.value for item in event_tasks):
                        self.store.update_continuous_improvement_event(event["event_id"], status="COMPLETED")

            self.store.update_continuous_improvement_cycle(cycle_id, status=CycleStatus.CALLING_LLM.value)
            self._record_agent_event(
                agent="ChiefInvestmentOrchestratorAgent",
                event_type="lab_llm_call_started",
                cycle_id=cycle_id,
                payload={
                    "provider": self.settings.improvement_llm_provider,
                    "model": self.settings.improvement_llm_orchestrator_model,
                },
            )
            llm_result = self.strategist.propose(context, evaluation)
            self.store.save_continuous_improvement_llm_response(
                {
                    "llm_call_id": llm_result.llm_call_id,
                    "cycle_id": cycle_id,
                    "provider": llm_result.provider,
                    "model": llm_result.model,
                    "status": "ok" if llm_result.ok else "failed",
                    "request": llm_result.request_preview,
                    "response": llm_result.payload.model_dump() if llm_result.payload else {},
                    "raw_response": (llm_result.raw_response or "")[:20000] or None,
                    "error": llm_result.error,
                }
            )
            self.store.update_continuous_improvement_cycle(
                cycle_id,
                llm_call_id=llm_result.llm_call_id,
                llm_status="ok" if llm_result.ok else "failed",
                status=CycleStatus.GENERATING_PROPOSALS.value,
            )
            self._record_agent_event(
                agent="ChiefInvestmentOrchestratorAgent",
                event_type="lab_llm_call_completed",
                cycle_id=cycle_id,
                payload={
                    "llm_call_id": llm_result.llm_call_id,
                    "status": "ok" if llm_result.ok else "failed",
                    "error": llm_result.error,
                },
            )

            all_payloads = []
            for item in specialist_results:
                response = (item.get("result") or {}).get("response") or {}
                all_payloads.extend(response.get("proposals") or [])
            if llm_result.payload:
                all_payloads.extend([payload.model_dump() for payload in llm_result.payload.proposals])

            proposals = self._persist_proposals(
                cycle_id=cycle_id,
                proposal_payloads=all_payloads,
                experiment_guidance=self._experiment_guidance_by_initiative(specialist_results),
            )
            validations = self._persist_validations(cycle_id=cycle_id, proposals=proposals, context=context)

            hypotheses = self.store.continuous_improvement_hypotheses(limit=200)
            tasks = self.store.continuous_improvement_tasks(limit=500)
            initiatives = self.store.continuous_improvement_initiatives(limit=200)
            report = self.reporter.build(
                cycle_id=cycle_id,
                context=context,
                evaluation=evaluation,
                event_batch=event_batch,
                tasks=tasks,
                hypotheses=hypotheses,
                proposals=proposals,
                validations=validations,
                initiatives=initiatives,
            )
            report_path = self.settings.data_dir / "reports" / "latest_continuous_improvement_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report["path"] = str(report_path)
            report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2, default=str), encoding="utf-8")

            status = self._final_status(proposals)
            self.store.update_continuous_improvement_cycle(
                cycle_id,
                status=status,
                finished_at=datetime.now(timezone.utc).isoformat(),
                report=report,
            )
            self._record_agent_event(
                agent="ReportAgent",
                event_type="lab_cycle_completed",
                cycle_id=cycle_id,
                payload={
                    "status": status,
                    "proposals": len(proposals),
                    "validations": len(validations),
                    "initiatives": len(initiatives),
                },
            )
            self._update_runtime(
                status=RuntimeStatus.IDLE,
                payload={
                    "cycle_id": cycle_id,
                    "status": status,
                    "events_pending": len(self.store.continuous_improvement_events(statuses=["DISCOVERED", "PLANNED"], limit=100)),
                    "tasks_pending": len(
                        self.store.continuous_improvement_tasks(
                            statuses=[
                                TaskStatus.DISCOVERED.value,
                                TaskStatus.WAITING_DEPENDENCY.value,
                                TaskStatus.ASSIGNED.value,
                                TaskStatus.RUNNING.value,
                            ],
                            limit=200,
                        )
                    ),
                },
            )
            return self.store.continuous_improvement_cycle(cycle_id) or {"cycle_id": cycle_id}
        except Exception as exc:
            self.store.update_continuous_improvement_cycle(
                cycle_id,
                status=CycleStatus.FAILED.value,
                finished_at=datetime.now(timezone.utc).isoformat(),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            self._record_agent_event(
                agent="continuous_improvement_lab",
                event_type="lab_cycle_failed",
                cycle_id=cycle_id,
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
            self._update_runtime(status=RuntimeStatus.FAILED, payload={"cycle_id": cycle_id, "error": str(exc)})
            log_system_event(
                self.settings.logs_dir,
                "continuous_improvement_lab_cycle_failed",
                {"cycle_id": cycle_id, "error": repr(exc)},
            )
            raise

    def _persist_proposals(
        self,
        *,
        cycle_id: str,
        proposal_payloads: list[dict[str, Any]],
        experiment_guidance: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        prepared_payloads, stats = self._prepare_proposals(proposal_payloads)
        self._record_agent_event(
            agent="OrchestratorAgent",
            event_type="lab_proposals_consolidated",
            cycle_id=cycle_id,
            payload=stats,
        )
        stored: list[dict[str, Any]] = []
        experiment_guidance = experiment_guidance or {}
        for raw in prepared_payloads:
            initiative_key = initiative_topic_key(
                domain="trading" if any(token in str(raw.get("target_component") or "").lower() for token in ["pre_earnings", "entry_quality", "signal", "strategy", "analyst", "risk"]) else "software",
                proposal=raw,
            )
            merged_validations: list[str] = []
            for item in raw.get("required_validations") or []:
                text = str(item or "").strip().lower()
                if text and text not in merged_validations:
                    merged_validations.append(text)
            for item in experiment_guidance.get(initiative_key, []):
                text = str(item or "").strip().lower()
                if text and text not in merged_validations:
                    merged_validations.append(text)
            normalized_raw = dict(raw)
            normalized_raw["required_validations"] = merged_validations
            payload = ImprovementProposalPayload.model_validate(normalized_raw)
            guard = self.guard.assess(payload, self.settings)
            proposal_id = new_id("ci_prop")
            initiative = self.store.continuous_improvement_initiative_by_key(initiative_key)
            if not initiative:
                initiative_id = new_id("ci_init")
                initiative_key_title = initiative_title_from_key(initiative_key)
                self.store.upsert_continuous_improvement_initiative(
                    {
                        "initiative_id": initiative_id,
                        "initiative_key": initiative_key,
                        "title": initiative_key_title,
                        "domain": "trading" if initiative_key.startswith("trading:") else "software",
                        "status": "OPEN",
                        "owner_agent": initiative_owner_from_key(initiative_key),
                        "priority": self._priority_from_score(int(raw.get("_initiative_score") or 0)),
                        "target_metric": payload.proposal_type.lower(),
                        "baseline_value": None,
                        "current_value": None,
                        "expected_impact": payload.expected_impact or payload.rationale,
                        "risk_level": payload.risk_level,
                        "evidence": [payload.rationale, payload.proposed_value, payload.current_value],
                        "linked_event_ids": [],
                        "linked_task_ids": [],
                        "linked_hypothesis_ids": [],
                        "linked_proposal_ids": [proposal_id],
                        "linked_validation_ids": [],
                        "latest_decision": {"decision": guard["status"], "source": "proposal_persist"},
                        "next_action": "Esperar validacion o revision humana.",
                    }
                )
                initiative = self.store.continuous_improvement_initiative_by_key(initiative_key)
            stored_id, inserted = self.store.upsert_continuous_improvement_proposal(
                {
                    "proposal_id": proposal_id,
                    "cycle_id": cycle_id,
                    "fingerprint": proposal_fingerprint(payload),
                    "proposal_type": payload.proposal_type,
                    "target_component": payload.target_component,
                    "target_identifier": payload.target_identifier,
                    "status": guard["status"],
                    "priority": self._priority_from_score(int(raw.get("_initiative_score") or 0)),
                    "risk_level": payload.risk_level,
                    "payload": {
                        **payload.model_dump(),
                        "initiative_key": initiative_key,
                        "initiative_score": int(raw.get("_initiative_score") or 0),
                        "merged_count": int(raw.get("_merged_count") or 1),
                    },
                    "guard": guard,
                }
            )
            proposal = self.store.continuous_improvement_proposal(stored_id)
            if not proposal:
                continue
            if not inserted:
                proposal["duplicate_existing"] = True
            stored.append(proposal)
            if proposal["proposal_type"] == "CODE_CHANGE":
                self.store.save_continuous_improvement_proposal_artifact(
                    {
                        "artifact_id": new_id("ci_artifact"),
                        "proposal_id": proposal["proposal_id"],
                        "artifact_type": "markdown",
                        "content_text": self.orchestrator.build_code_artifact(proposal),
                        "payload": {"generated_by": "ProgrammerAgent"},
                    }
                )
            if initiative:
                self.store.append_continuous_improvement_initiative_links(
                    initiative["initiative_id"],
                    proposal_ids=[proposal["proposal_id"]],
                )
            self._record_agent_event(
                agent="RiskGuardAgent",
                event_type="lab_proposal_persisted",
                cycle_id=cycle_id,
                payload={
                    "proposal_id": proposal["proposal_id"],
                    "proposal_type": proposal["proposal_type"],
                    "status": proposal["status"],
                    "target_component": proposal["target_component"],
                    "initiative_key": initiative_key,
                },
            )
        return stored

    def _prepare_proposals(self, proposal_payloads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not proposal_payloads:
            return [], {"input": 0, "merged": 0, "kept": 0, "dropped_by_limit": 0}

        grouped: dict[str, list[dict[str, Any]]] = {}
        component_counts: dict[str, int] = {}
        for raw in proposal_payloads:
            component = str(raw.get("target_component") or "").strip().lower()
            component_counts[component] = component_counts.get(component, 0) + 1
            grouped.setdefault(self._proposal_topic_key(raw), []).append(raw)

        merged_payloads: list[dict[str, Any]] = []
        merged_count = 0
        for items in grouped.values():
            ranked = sorted(
                items,
                key=lambda item: self._proposal_score(item, component_counts),
                reverse=True,
            )
            winner = dict(ranked[0])
            if len(ranked) > 1:
                merged_count += len(ranked) - 1
                winner["rationale"] = self._merge_texts([item.get("rationale") for item in ranked], limit=2)
                winner["proposed_value"] = self._merge_texts([item.get("proposed_value") for item in ranked], limit=2)
            winner["_merged_count"] = len(ranked)
            winner["_initiative_score"] = self._proposal_score(winner, component_counts)
            merged_payloads.append(winner)

        merged_payloads.sort(key=lambda item: int(item.get("_initiative_score") or 0), reverse=True)
        limit = max(1, int(self.settings.continuous_improvement_max_proposals_per_cycle))
        kept = merged_payloads[:limit]
        dropped_by_limit = max(0, len(merged_payloads) - len(kept))
        return kept, {
            "input": len(proposal_payloads),
            "merged": merged_count,
            "kept": len(kept),
            "dropped_by_limit": dropped_by_limit,
            "max_per_cycle": limit,
        }

    def _proposal_topic_key(self, raw: dict[str, Any]) -> str:
        proposal_type = str(raw.get("proposal_type") or "MONITORING_CHANGE").strip().lower()
        identifier = self._normalize_topic_part(raw.get("target_identifier"))
        component = self._normalize_topic_part(raw.get("target_component"))
        if "risk_veto" in identifier or "risk_veto" in component:
            topic = "risk_veto_policy"
        elif identifier:
            topic = identifier
        else:
            topic = component
        return f"{proposal_type}:{topic}"

    def _normalize_topic_part(self, value: Any) -> str:
        text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
        return text

    def _proposal_score(self, raw: dict[str, Any], component_counts: dict[str, int]) -> int:
        type_weight = {
            "RISK_RULE_CHANGE": 80,
            "DATA_QUALITY_CHANGE": 70,
            "CODE_CHANGE": 65,
            "PROMPT_CHANGE": 55,
            "STRATEGY_RULE_CHANGE": 55,
            "PARAMETER_CHANGE": 50,
            "MONITORING_CHANGE": 35,
        }
        risk_weight = {"HIGH": 0, "MEDIUM": 8, "LOW": 5}
        proposal_type = str(raw.get("proposal_type") or "MONITORING_CHANGE").upper()
        risk_level = str(raw.get("risk_level") or "MEDIUM").upper()
        component = str(raw.get("target_component") or "").strip().lower()
        rationale = " ".join(
            [
                str(raw.get("rationale") or ""),
                str(raw.get("proposed_value") or ""),
                str(raw.get("current_value") or ""),
            ]
        )
        score = type_weight.get(proposal_type, 25)
        score += risk_weight.get(risk_level, 0)
        score += min(15, component_counts.get(component, 0) * 3)
        if re.search(r"\d", rationale):
            score += 8
        if "%" in rationale:
            score += 4
        if any(term in rationale.lower() for term in ["error", "drawdown", "blocked", "coverage", "winner", "outcome"]):
            score += 6
        return score

    def _priority_from_score(self, score: int) -> str:
        if score >= 80:
            return "HIGH"
        if score >= 55:
            return "MEDIUM"
        return "LOW"

    def _merge_texts(self, values: list[Any], *, limit: int = 2) -> str:
        unique: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in unique:
                unique.append(text)
        return " | ".join(unique[:limit])

    def _persist_validations(
        self,
        *,
        cycle_id: str,
        proposals: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.store.update_continuous_improvement_cycle(cycle_id, status=CycleStatus.VALIDATING.value)
        validations: list[dict[str, Any]] = []
        for proposal in proposals:
            if proposal.get("duplicate_existing"):
                continue
            artifacts = self._execute_validation_artifacts(proposal=proposal, cycle_id=cycle_id)
            if artifacts:
                reports = context.setdefault("reports", {})
                if "walk_forward_validation" in artifacts:
                    reports["walk_forward_validation"] = self._latest_report_payload("latest_walk_forward_validation.json")
                if "session_retrospective" in artifacts:
                    reports["session_retrospective"] = self._latest_report_payload("latest_session_retrospective.json")
                if "backtest" in artifacts:
                    reports["backtest"] = {"available": True, "payload": artifacts["backtest"]}
            validation = self.validator.validate(proposal, context, self.settings, store=self.store)
            self.store.save_continuous_improvement_validation(validation)
            initiative_key = str((proposal.get("payload") or {}).get("initiative_key") or "")
            initiative = self.store.continuous_improvement_initiative_by_key(initiative_key) if initiative_key else None
            if initiative:
                self.store.append_continuous_improvement_initiative_links(
                    initiative["initiative_id"],
                    validation_ids=[validation["validation_id"]],
                )
                initiative_status = self._initiative_status_from_validation(validation["status"], validation.get("payload", {}))
                latest_decision = {
                    "decision": validation["status"],
                    "validation_id": validation["validation_id"],
                    "source": "validation",
                }
                self.store.update_continuous_improvement_initiative(
                    initiative["initiative_id"],
                    status=initiative_status if validation["status"] != "PENDING" else "VALIDATING",
                    latest_decision=latest_decision,
                    next_action=self._initiative_next_action_from_validation(validation["status"]),
                )
            if validation["status"] != "PENDING":
                try:
                    self.store.update_continuous_improvement_proposal_status(
                        proposal["proposal_id"],
                        status=validation["status"],
                        actor="ValidationAgent",
                        reason=validation.get("payload", {}).get("objective_summary") or "Validacion objetiva completada.",
                        payload=validation.get("payload", {}),
                    )
                    proposal["status"] = validation["status"]
                except KeyError:
                    pass
            applied_change = None
            if proposal.get("proposal_type") == "CODE_CHANGE" and validation["status"] == "READY_TO_APPLY":
                applied_change = self.code_applier.try_apply(
                    settings=self.settings,
                    store=self.store,
                    initiative=initiative,
                    proposal=proposal,
                    validation=validation,
                )
                applied_status = applied_change.get("status")
                if applied_status in {"APPLIED", "ROLLED_BACK", "FAILED", "BLOCKED"}:
                    proposal_status = "APPLIED" if applied_status == "APPLIED" else applied_status
                    self.store.update_continuous_improvement_proposal_status(
                        proposal["proposal_id"],
                        status=proposal_status,
                        actor="AutoApplyCodeAgent",
                        reason=applied_change.get("error") or f"Autoapply de codigo: {applied_status}",
                        payload={"applied_change": applied_change},
                    )
                    proposal["status"] = proposal_status
                    if initiative:
                        self.store.update_continuous_improvement_initiative(
                            initiative["initiative_id"],
                            status="CLOSED" if applied_status == "APPLIED" else "VALIDATING",
                            latest_decision={
                                "decision": applied_status,
                                "source": "AutoApplyCodeAgent",
                                "applied_change_id": applied_change.get("applied_change_id"),
                            },
                            next_action="" if applied_status == "APPLIED" else "Revisar fallo de autoapply.",
                        )
                    self._record_agent_event(
                        agent="AutoApplyCodeAgent",
                        event_type="lab_code_autoapply_recorded",
                        cycle_id=cycle_id,
                        payload={
                            "proposal_id": proposal["proposal_id"],
                            "status": applied_status,
                            "applied_change_id": applied_change.get("applied_change_id"),
                            "error": applied_change.get("error"),
                        },
                    )
            self._record_agent_event(
                agent="ValidationAgent",
                event_type="lab_validation_recorded",
                cycle_id=cycle_id,
                payload={
                    "validation_id": validation["validation_id"],
                    "proposal_id": validation["proposal_id"],
                    "status": validation["status"],
                    "initiative_key": initiative_key,
                },
            )
            initiative_id = (initiative or {}).get("initiative_id")
            self._record_initiative_message(
                initiative_id=initiative_id,
                cycle_id=cycle_id,
                event=None,
                task=None,
                agent="ValidationAgent",
                message_type="validation_recorded",
                payload={
                    "summary": f"Validacion {validation['status']} para {proposal.get('proposal_id')}",
                    "validation": validation,
                    "proposal": proposal,
                    "applied_change": applied_change,
                },
            )
            validations.append(validation)
        return validations

    def _initiative_status_from_validation(self, validation_status: str, payload: dict[str, Any] | None = None) -> str:
        payload = payload or {}
        objective_status = str(payload.get("objective_status") or "").upper()
        if validation_status == "REJECTED" or objective_status == "REJECTED":
            return "REJECTED"
        if validation_status == "READY_TO_APPLY" or objective_status == "READY_TO_APPLY":
            return "READY_TO_APPLY"
        if validation_status == "PASSED" or objective_status == "PASSED":
            return "WAITING_REVIEW"
        if validation_status == "WAITING_HUMAN_REVIEW":
            return "WAITING_REVIEW"
        return "VALIDATING"

    def _initiative_next_action_from_validation(self, validation_status: str) -> str:
        mapping = {
            "READY_TO_APPLY": "Lista para aplicar con rollback preparado.",
            "PASSED": "Pendiente de revision humana final.",
            "WAITING_HUMAN_REVIEW": "Esperar revision humana.",
            "REJECTED": "Cerrar o reformular la iniciativa.",
            "FAILED": "Revisar evidencia y repetir validacion.",
        }
        return mapping.get(validation_status, "Esperar validacion objetiva.")

    def _final_status(self, proposals: list[dict[str, Any]]) -> str:
        if not proposals:
            return CycleStatus.PARTIAL.value
        statuses = {item.get("status") for item in proposals}
        if "REJECTED" in statuses and len(statuses) == 1:
            return CycleStatus.PARTIAL.value
        if "REQUIRES_HUMAN_REVIEW" in statuses or "WAITING_HUMAN_REVIEW" in statuses:
            return CycleStatus.WAITING_HUMAN_REVIEW.value
        return CycleStatus.COMPLETED.value

    def tick(self) -> dict[str, Any]:
        return self.run_once(mode="scheduled", trigger_event_type="scheduled_tick", trigger_payload={"tick": datetime.now(timezone.utc).isoformat()})

    def run_forever(self, *, max_cycles: int | None = None) -> None:
        cycles = 0
        while True:
            self.tick()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
            time.sleep(max(5, self.settings.continuous_improvement_runtime_loop_sleep_seconds))
