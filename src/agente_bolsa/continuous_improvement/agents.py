"""Specialized agents for the continuous improvement lab."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store

from .llm_client import ImprovementLLMClient
from .context_compaction import compact_ci_context_for_llm
from .schemas import (
    AgentName,
    ImprovementProposalPayload,
    LLMJsonResult,
    ProgrammerAgentResponse,
    ParameterCalibrationResponse,
    SpecialistResponseBase,
    StrategyEvaluatorResponse,
    TechnicalAnalystResponse,
    MarketEstimatorResponse,
    SentimentAnalystResponse,
    specialist_response_json_schema,
)


SPECIALIST_RESPONSE_MODELS = {
    AgentName.MARKET: MarketEstimatorResponse,
    AgentName.MARKET_REGIME: MarketEstimatorResponse,
    AgentName.TECHNICAL: TechnicalAnalystResponse,
    AgentName.TECHNICAL_EDGE: TechnicalAnalystResponse,
    AgentName.SENTIMENT: SentimentAnalystResponse,
    AgentName.STRATEGY: StrategyEvaluatorResponse,
    AgentName.PARAMETER_CALIBRATION: ParameterCalibrationResponse,
    AgentName.PRE_EARNINGS: StrategyEvaluatorResponse,
    AgentName.RISK_CAPITAL: StrategyEvaluatorResponse,
    AgentName.DATA_QUALITY: ProgrammerAgentResponse,
    AgentName.PROGRAMMER: ProgrammerAgentResponse,
    AgentName.SOFTWARE_RELIABILITY: ProgrammerAgentResponse,
    AgentName.EXPERIMENT_DESIGNER: SpecialistResponseBase,
    AgentName.DECISION_COMMITTEE: SpecialistResponseBase,
}


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        return {
            "available": True,
            "path": str(path),
            "payload": json.loads(path.read_text(encoding="utf-8")),
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "error": str(exc)}


def _load_latest_prefixed_report(reports_dir: Path, prefix: str) -> dict[str, Any]:
    candidates = [
        path
        for path in reports_dir.glob(f"{prefix}_*.json")
        if not path.name.endswith(".manifest.json")
    ]
    if not candidates:
        return {"available": False, "path": str(reports_dir / f"{prefix}_*.json")}
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return _load_json_file(latest)


def proposal_fingerprint(proposal: ImprovementProposalPayload) -> str:
    base = {
        "proposal_type": proposal.proposal_type,
        "target_component": proposal.target_component,
        "target_identifier": proposal.target_identifier,
        "proposed_value": proposal.proposed_value,
    }
    raw = json.dumps(base, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def hypothesis_fingerprint(subject: str, summary: str, domain: str) -> str:
    raw = json.dumps({"subject": subject, "summary": summary, "domain": domain}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def event_fingerprint(event_type: str, source: str, payload: dict[str, Any]) -> str:
    compact = {"event_type": event_type, "source": source, "payload": payload}
    raw = json.dumps(compact, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def initiative_topic_key(*, domain: str, source: str | None = None, proposal: dict[str, Any] | None = None, focus: str | None = None) -> str:
    domain_key = re.sub(r"[^a-z0-9]+", "_", str(domain or "trading").strip().lower()).strip("_") or "trading"
    topic = ""
    proposal = proposal or {}
    if proposal:
        proposal_type = str(proposal.get("proposal_type") or "monitoring_change").strip().lower()
        component = re.sub(r"[^a-z0-9]+", "_", str(proposal.get("target_component") or "").strip().lower()).strip("_")
        identifier = re.sub(r"[^a-z0-9]+", "_", str(proposal.get("target_identifier") or "").strip().lower()).strip("_")
        if "risk_veto" in component or "risk_veto" in identifier:
            topic = "pre_earnings_risk_veto"
        elif "entry_quality" in component or "entry_quality" in identifier:
            topic = "entry_quality_filter"
        elif "estimate" in component or "analyst" in component or "earnings" in component:
            topic = "analyst_estimates_pipeline"
        elif "duplicate" in component or "signal_consolid" in component:
            topic = "signal_consolidation"
        elif "outcome" in component:
            topic = "outcome_generation"
        elif "error" in component or "runtime" in component:
            topic = "runtime_reliability"
        elif identifier:
            topic = identifier
        else:
            topic = component or proposal_type
    if not topic and focus:
        topic = re.sub(r"[^a-z0-9]+", "_", str(focus).strip().lower()).strip("_")
    if not topic and source:
        topic = re.sub(r"[^a-z0-9]+", "_", str(source).strip().lower()).strip("_")
    return f"{domain_key}:{topic or 'general'}"


def initiative_title_from_key(key: str) -> str:
    topic = key.split(":", 1)[-1]
    titles = {
        "pre_earnings_risk_veto": "Recalibrar veto pre-earnings",
        "entry_quality_filter": "Recalibrar filtro de calidad de entrada",
        "analyst_estimates_pipeline": "Mejorar cobertura de estimaciones",
        "signal_consolidation": "Consolidar señales duplicadas",
        "outcome_generation": "Mejorar generación de outcomes",
        "runtime_reliability": "Reducir errores y deuda técnica",
        "market_regime": "Seguir régimen de mercado",
        "strategy_evaluation": "Evaluar estabilidad de estrategia",
        "opportunistic_parameters": "Calibrar perfil oportunista",
        "risk_capital": "Revisar riesgo y capital",
        "data_quality": "Reforzar calidad de datos",
        "software_reliability": "Reforzar fiabilidad del runtime",
    }
    return titles.get(topic, topic.replace("_", " ").strip().title() or "Iniciativa")


def initiative_owner_from_key(key: str) -> str:
    topic = key.split(":", 1)[-1]
    mapping = {
        "pre_earnings_risk_veto": AgentName.PRE_EARNINGS.value,
        "entry_quality_filter": AgentName.TECHNICAL_EDGE.value,
        "analyst_estimates_pipeline": AgentName.PRE_EARNINGS.value,
        "signal_consolidation": AgentName.DATA_QUALITY.value,
        "outcome_generation": AgentName.STRATEGY.value,
        "runtime_reliability": AgentName.SOFTWARE_RELIABILITY.value,
        "market_regime": AgentName.MARKET_REGIME.value,
        "strategy_evaluation": AgentName.STRATEGY.value,
        "opportunistic_parameters": AgentName.PARAMETER_CALIBRATION.value,
        "risk_capital": AgentName.RISK_CAPITAL.value,
        "data_quality": AgentName.DATA_QUALITY.value,
        "software_reliability": AgentName.SOFTWARE_RELIABILITY.value,
    }
    return mapping.get(topic, AgentName.ORCHESTRATOR.value)


def _compact_signal(item: dict[str, Any]) -> dict[str, Any]:
    features = item.get("features") or {}
    outcome = item.get("outcome") or {}
    exit_policy = outcome.get("exit_policy_v2") or {}
    return {
        "signal_id": item.get("signal_id"),
        "source_run_id": item.get("source_run_id"),
        "source": item.get("source"),
        "symbol": item.get("symbol"),
        "signal_date": item.get("signal_date"),
        "decision": item.get("decision"),
        "score": features.get("score"),
        "setup_name": features.get("setup_name"),
        "setup_quality": features.get("setup_quality"),
        "selected_for_llm": features.get("selected_for_llm"),
        "return_5d": outcome.get("return_5d"),
        "return_10d": outcome.get("return_10d"),
        "mfe_10d": outcome.get("mfe_10d"),
        "mae_10d": outcome.get("mae_10d"),
        "exit_policy_v2_reason": exit_policy.get("exit_reason"),
        "exit_policy_v2_return": exit_policy.get("return_pct"),
        "verdict": outcome.get("verdict"),
        "outcome_available": outcome.get("available"),
        "created_at": item.get("created_at"),
    }


def _compact_observation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": item.get("observation_id"),
        "signal_date": item.get("signal_date"),
        "symbol": item.get("symbol"),
        "source_family": item.get("source_family"),
        "decision": item.get("decision"),
        "best_score": item.get("best_score"),
        "llm_considered": item.get("llm_considered"),
        "approved_buy": item.get("approved_buy"),
        "blocked_entry_quality": item.get("blocked_entry_quality"),
        "blocked_backtest": item.get("blocked_backtest"),
        "executed_buy": item.get("executed_buy"),
        "duplicate_count": item.get("duplicate_count"),
        "explanation": item.get("explanation"),
        "created_at": item.get("created_at"),
    }


def _compact_cycle(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "cycle_id": item.get("cycle_id"),
        "status": item.get("status"),
        "mode": item.get("mode"),
        "dry_run": item.get("dry_run"),
        "llm_status": item.get("llm_status"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "report_summary": {
            "proposals": len((item.get("report") or {}).get("proposals", []) or []),
            "pending": len((item.get("report") or {}).get("pending", []) or []),
        },
    }


class DataCollectorAgent:
    def collect(self, settings: Settings, store: Store, *, cycle_id: str) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        reports_dir = settings.data_dir / "reports"
        latest_events = store.latest_events(80)
        latest_cycle = store.latest_continuous_improvement_cycle()
        if latest_cycle and latest_cycle.get("cycle_id") == cycle_id:
            latest_cycle = None
        signals = store.signal_outcomes(limit=160, since_date=since)
        observations = store.learning_observations(since_date=since, limit=160)
        def _runtime_error_event(item: dict[str, Any]) -> bool:
            event_type = str(item.get("event_type", "")).lower()
            payload_text = str(item.get("payload_json", "")).lower()
            if event_type in {"entry_quality_gate_completed", "stop_take_exit_executed"}:
                return False
            return "fail" in event_type or "error" in event_type or '"error"' in payload_text

        recent_errors = [item for item in latest_events if _runtime_error_event(item)][:30]
        operational_incidents = [
            item
            for item in latest_events
            if str(item.get("event_type", "")).lower() in {"entry_quality_gate_completed", "stop_take_exit_executed"}
        ][:30]
        return {
            "cycle_id": cycle_id,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source": "sqlite_and_reports",
            "settings": {
                "trading_mode": settings.trading_mode,
                "allow_live_trading": settings.allow_live_trading,
                "auto_paper_trading": settings.auto_paper_trading,
                "require_human_approval": settings.require_human_approval,
                "allow_auto_apply_improvements": settings.allow_auto_apply_improvements,
                "improvement_dry_run": settings.improvement_dry_run,
                "backtest_gate_enabled": settings.backtest_gate_enabled,
                "entry_quality_gate_enabled": settings.entry_quality_gate_enabled,
                "entry_score_v2_enabled": settings.entry_score_v2_enabled,
                "exit_policy_v2_enabled": settings.exit_policy_v2_enabled,
                "trade_aggressiveness_profile": settings.trade_aggressiveness_profile,
                "trade_selection_top_n": settings.trade_selection_top_n,
                "max_orders_per_cycle": settings.max_orders_per_cycle,
                "max_daily_buy_orders": settings.max_daily_buy_orders,
                "max_position_exposure": settings.max_position_exposure,
                "max_risk_per_trade": settings.max_risk_per_trade,
                "max_total_open_risk": settings.max_total_open_risk,
                "entry_score_v2_min": settings.entry_score_v2_min,
                "entry_score_v2_micro_min": settings.entry_score_v2_micro_min,
                "entry_score_v2_min_reward_risk": settings.entry_score_v2_min_reward_risk,
                "micro_experiment_size_multiplier": settings.micro_experiment_size_multiplier,
                "backtest_gate_paper_soft_override_enabled": settings.backtest_gate_paper_soft_override_enabled,
                "news_sentiment_fail_closed_for_buys": settings.news_sentiment_fail_closed_for_buys,
            },
            "database": store.status(),
            "runtime": {
                "latest_cycle": _compact_cycle(latest_cycle),
                "lab_runtime": store.continuous_improvement_runtime_state(),
                "scheduler_market_cycle": store.get_runtime_value("scheduler_job_status:market_cycle"),
                "scheduler_daily_study": store.get_runtime_value("scheduler_job_status:daily_study"),
                "scheduler_post_market_review": store.get_runtime_value("scheduler_job_status:post_market_review"),
            },
            "events": {
                "latest": latest_events,
                "recent_errors": recent_errors,
                "operational_incidents": operational_incidents,
            },
            "reports": {
                "daily_learning": _load_json_file(reports_dir / "latest_daily_learning_digest.json"),
                "operational_health": _load_json_file(reports_dir / "latest_operational_health.json"),
                "operational_learning": _load_json_file(reports_dir / "latest_operational_learning.json"),
                "live_readiness": _load_json_file(reports_dir / "latest_live_readiness.json"),
                "market_data_quality": _load_json_file(reports_dir / "latest_market_data_quality.json"),
                "post_market_review": _load_json_file(reports_dir / "latest_post_market_review.json"),
                "pre_earnings_learning": _load_json_file(reports_dir / "latest_pre_earnings_learning_digest.json"),
                "walk_forward_validation": _load_json_file(reports_dir / "latest_walk_forward_validation.json"),
                "session_retrospective": _load_json_file(reports_dir / "latest_session_retrospective.json"),
                "winner_coverage": _load_latest_prefixed_report(reports_dir, "winner_coverage"),
                "fallback_blockers": _load_latest_prefixed_report(reports_dir, "fallback_blockers"),
            },
            "learning": {
                "signals": [_compact_signal(item) for item in signals],
                "observations": [_compact_observation(item) for item in observations],
                "policy_candidates": store.learning_policy_candidates(limit=100),
            },
            "existing_proposals": store.continuous_improvement_proposals(limit=100),
            "initiatives": store.continuous_improvement_initiatives(limit=100),
            "initiative_messages": store.continuous_improvement_initiative_messages(limit=200),
            "hypotheses": store.continuous_improvement_hypotheses(limit=100),
            "memories": store.continuous_improvement_memories(),
        }


class PerformanceEvaluatorAgent:
    def score_dynamic_agents(self, store: Any) -> list[dict[str, Any]]:
        """Puntua y retira agentes dinamicos inutiles (T2.2)."""

        from .dynamic_agents import score_dynamic_agents

        return score_dynamic_agents(store)

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        signals = context.get("learning", {}).get("signals", []) or []
        observations = context.get("learning", {}).get("observations", []) or []
        recent_errors = context.get("events", {}).get("recent_errors", []) or []
        executed = [item for item in observations if item.get("executed_buy")]
        micro = [item for item in observations if str(item.get("decision") or "") in {"approved_buy_micro", "executed_buy_micro"}]
        soft_backtest = [item for item in observations if str(item.get("decision") or "") == "approved_buy_soft_backtest"]
        blocked_entry = [item for item in observations if item.get("blocked_entry_quality")]
        blocked_backtest = [item for item in observations if item.get("blocked_backtest")]
        outcomes_available = [item for item in signals if item.get("outcome_available") and item.get("verdict")]
        exit_policy_available = [item for item in signals if item.get("exit_policy_v2_reason")]
        blockers: list[dict[str, Any]] = []
        if recent_errors:
            blockers.append(
                {
                    "kind": "repeated_errors",
                    "severity": "MEDIUM",
                    "detail": f"{len(recent_errors)} eventos recientes contienen error o fallo.",
                }
            )
        if signals and not outcomes_available:
            blockers.append(
                {
                    "kind": "insufficient_outcomes",
                    "severity": "LOW",
                    "detail": "Hay señales recientes, pero pocos resultados maduros para medir impacto.",
                }
            )
        if len(blocked_entry) > max(5, len(observations) * 0.5):
            blockers.append(
                {
                    "kind": "entry_quality_blocks_high",
                    "severity": "MEDIUM",
                    "detail": "El filtro de calidad de entrada bloquea una proporción alta de observaciones.",
                }
            )
        return {
            "summary": {
                "signals": len(signals),
                "observations": len(observations),
                "executed_observations": len(executed),
                "micro_observations": len(micro),
                "soft_backtest_overrides": len(soft_backtest),
                "blocked_entry_quality": len(blocked_entry),
                "blocked_backtest": len(blocked_backtest),
                "outcomes_available": len(outcomes_available),
                "exit_policy_v2_available": len(exit_policy_available),
                "recent_errors": len(recent_errors),
                "operational_incidents": len(context.get("events", {}).get("operational_incidents", []) or []),
            },
            "blockers": blockers,
            "data_quality": "GOOD" if outcomes_available else "PARTIAL" if signals or observations else "INSUFFICIENT",
        }


class SpecialistAgent:
    agent_name: AgentName
    domain: str

    def __init__(self, settings: Settings, client: ImprovementLLMClient) -> None:
        self.settings = settings
        self.client = client

    def run(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        deterministic = self._deterministic(context, event, task_payload)
        llm_result = self._maybe_llm(context, event, task_payload, deterministic)
        response = deterministic
        if llm_result.payload is not None:
            response = llm_result.payload.model_dump()
        return {
            "agent_name": self.agent_name.value,
            "domain": self.domain,
            "deterministic": deterministic,
            "llm": llm_result.model_dump(),
            "response": response,
        }

    def _maybe_llm(
        self,
        context: dict[str, Any],
        event: dict[str, Any],
        task_payload: dict[str, Any],
        deterministic: dict[str, Any],
    ) -> LLMJsonResult:
        if self.agent_name not in SPECIALIST_RESPONSE_MODELS:
            return LLMJsonResult(ok=False, llm_call_id=new_id("ci_llm_skip"), error="agent_llm_not_supported")
        if not self.settings.improvement_llm_enabled:
            return LLMJsonResult(ok=False, llm_call_id=new_id("ci_llm_skip"), error="llm_disabled")
        user_payload = compact_ci_context_for_llm(
            context=context,
            evaluation=context.get("evaluation", {}),
            event=event,
            task_payload=task_payload,
            deterministic_baseline=deterministic,
            target_tokens=self.settings.improvement_llm_context_target_tokens,
            hard_limit_tokens=self.settings.improvement_llm_context_hard_limit_tokens,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"Eres {self.agent_name.value} dentro de un laboratorio de mejora continua. "
                    "Devuelve solo JSON valido segun el esquema. No inventes datos, no propongas trading real "
                    "ni cambios destructivos."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=True, default=str),
            },
        ]
        return self.client.generate_json(
            messages,
            specialist_response_json_schema(self.agent_name),
            response_model=SPECIALIST_RESPONSE_MODELS.get(self.agent_name, SpecialistResponseBase),
        )

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MarketEstimatorAgent(SpecialistAgent):
    agent_name = AgentName.MARKET
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        summary = context.get("evaluation", {}).get("summary", {})
        return MarketEstimatorResponse(
            summary="Lectura de mercado basada en digest y estabilidad reciente.",
            confidence="MEDIUM" if summary.get("outcomes_available", 0) else "LOW",
            hypotheses=[
                {
                    "subject": "market_regime",
                    "summary": "El entorno reciente requiere priorizar estabilidad sobre agresividad si hay pocos outcomes maduros.",
                    "confidence": "MEDIUM" if summary.get("outcomes_available", 0) else "LOW",
                    "evidence": [f"outcomes_available={summary.get('outcomes_available', 0)}"],
                }
            ],
            actions=[
                {
                    "action_type": "MONITORING",
                    "title": "Seguir estabilidad de régimen",
                    "rationale": "El sistema debe contrastar señales con evidencia reciente antes de ampliar riesgo.",
                    "risk_level": "LOW",
                }
            ],
        ).model_dump()


class TechnicalAnalystAgent(SpecialistAgent):
    agent_name = AgentName.TECHNICAL
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        summary = context.get("evaluation", {}).get("summary", {})
        blocked = summary.get("blocked_entry_quality", 0)
        observations = max(summary.get("observations", 0), 1)
        ratio = blocked / observations
        issues = []
        proposals = []
        if ratio >= 0.5:
            issues.append(
                {
                    "issue_id": "entry-quality-overblocking",
                    "component": "entry_quality_gate",
                    "description": "La capa de calidad de entrada está bloqueando demasiadas observaciones.",
                    "evidence": [f"blocked={blocked}", f"observations={observations}", f"ratio={ratio:.2f}"],
                    "severity": "MEDIUM",
                }
            )
            proposals.append(
                {
                    "proposal_type": "PARAMETER_CHANGE",
                    "target_component": "entry_quality_gate",
                    "target_identifier": "threshold_review",
                    "current_value": f"blocked_ratio={ratio:.2f}",
                    "proposed_value": "Revisar umbrales del gate con backtest y baseline antes de relajar filtros.",
                    "rationale": "Un bloqueo alto puede estar filtrando demasiado o reflejar degradación real; necesita validación.",
                    "expected_impact": "Ajustar sensibilidad del filtro sin empeorar drawdown.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["backtest", "baseline_compare"],
                    "rollback_plan": "Restaurar umbrales actuales si el backtest empeora drawdown o hit rate.",
                }
            )
        return TechnicalAnalystResponse(
            summary="Analisis tecnico de ruido, filtros y setups.",
            confidence="MEDIUM",
            detected_issues=issues,
            hypotheses=[
                {
                    "subject": "technical_signal_quality",
                    "summary": (
                        "La calidad tecnica necesita seguimiento sobre filtros y ruido, "
                        "especialmente cuando el ratio de bloqueo sube."
                    ),
                    "confidence": "MEDIUM",
                    "evidence": [f"blocked_ratio={ratio:.2f}"],
                }
            ],
            proposals=proposals,
        ).model_dump()


class SentimentAnalystAgent(SpecialistAgent):
    agent_name = AgentName.SENTIMENT
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        return SentimentAnalystResponse(
            summary="No hay una memoria de sentimiento persistida suficientemente rica; se mantiene como observación.",
            confidence="LOW",
            actions=[
                {
                    "action_type": "MONITORING",
                    "title": "Persistir señales de sentimiento",
                    "rationale": "Sin una serie histórica compacta de sentimiento no se puede atribuir impacto de noticias.",
                    "risk_level": "LOW",
                }
            ],
        ).model_dump()


class StrategyEvaluatorAgent(SpecialistAgent):
    agent_name = AgentName.STRATEGY
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        summary = context.get("evaluation", {}).get("summary", {})
        blockers = context.get("evaluation", {}).get("blockers", [])
        proposals = []
        if blockers:
            proposals.append(
                {
                    "proposal_type": "MONITORING_CHANGE",
                    "target_component": "strategy_evaluation",
                    "target_identifier": "validation_backlog",
                    "current_value": str(blockers),
                    "proposed_value": "Crear validaciones adicionales para hipótesis abiertas y degradación detectada.",
                    "rationale": "Las señales de degradación deben traducirse en validaciones explícitas del pipeline.",
                    "expected_impact": "Mejor trazabilidad del deterioro y respuesta más rápida.",
                    "risk_level": "LOW",
                    "required_validations": ["tests"],
                    "rollback_plan": "Eliminar la validación si genera ruido sin valor operativo.",
                }
            )
        return StrategyEvaluatorResponse(
            summary="Evaluación de estabilidad, baseline y bloqueos recientes.",
            confidence="MEDIUM" if summary.get("outcomes_available", 0) else "LOW",
            hypotheses=[
                {
                    "subject": "strategy_stability",
                    "summary": "La estabilidad de estrategia es parcial mientras falten outcomes maduros suficientes.",
                    "confidence": "MEDIUM" if summary.get("outcomes_available", 0) else "LOW",
                    "evidence": [f"outcomes_available={summary.get('outcomes_available', 0)}"],
                }
            ],
            proposals=proposals,
        ).model_dump()


class ParameterCalibrationAgent(SpecialistAgent):
    agent_name = AgentName.PARAMETER_CALIBRATION
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        settings = context.get("settings", {}) or {}
        summary = context.get("evaluation", {}).get("summary", {}) or {}
        observations = context.get("learning", {}).get("observations", []) or []
        signals = int(summary.get("signals") or 0)
        outcomes = int(summary.get("outcomes_available") or 0)
        micro = int(summary.get("micro_observations") or 0)
        soft_backtest = int(summary.get("soft_backtest_overrides") or 0)
        blocked_entry = int(summary.get("blocked_entry_quality") or 0)
        blocked_backtest = int(summary.get("blocked_backtest") or 0)
        profile = str(settings.get("trade_aggressiveness_profile") or "conservative")
        executed = int(summary.get("executed_observations") or 0)
        approved_like = [
            item
            for item in observations
            if str(item.get("decision") or "") in {"approved_buy", "approved_buy_micro", "approved_buy_soft_backtest", "executed_buy", "executed_buy_micro"}
        ]

        proposals: list[dict[str, Any]] = []
        actions = [
            {
                "action_type": "MONITORING",
                "title": "Auditar perfil oportunista",
                "rationale": "Los nuevos parametros deben medirse por conversion, outcomes, micro-operaciones y drawdown antes de volver a tocar riesgo.",
                "risk_level": "LOW",
                "required_validations": ["baseline_compare"],
            }
        ]

        if profile == "opportunistic" and outcomes < 10:
            proposals.append(
                {
                    "proposal_type": "MONITORING_CHANGE",
                    "target_component": "opportunistic_profile",
                    "target_identifier": "minimum_evidence_window",
                    "current_value": f"profile={profile}; outcomes={outcomes}; micro={micro}; soft_backtest={soft_backtest}",
                    "proposed_value": "Mantener perfil oportunista hasta 10 sesiones o 20 operaciones/micro-operaciones antes de recalibrar thresholds.",
                    "rationale": "Aun no hay outcomes suficientes para saber si el cambio mejora expectancy o solo aumenta actividad.",
                    "expected_impact": "Evitar sobreajuste inmediato y forzar medicion objetiva del nuevo perfil.",
                    "risk_level": "LOW",
                    "required_validations": ["baseline_compare", "walk_forward"],
                    "rollback_plan": "Volver a conservative si aparecen drawdown, errores operativos o degradacion de outcomes.",
                }
            )
        if profile == "opportunistic" and signals >= 30 and not approved_like and not (blocked_entry or blocked_backtest):
            proposals.append(
                {
                    "proposal_type": "PARAMETER_CHANGE",
                    "target_component": "opportunistic_profile",
                    "target_identifier": "decision_bandwidth",
                    "current_value": f"trade_selection_top_n={settings.get('trade_selection_top_n')}; max_orders={settings.get('max_orders_per_cycle')}",
                    "proposed_value": "Revisar si el LLM/fallback esta ignorando candidatos seleccionados pese a perfil oportunista; no aumentar tamano por posicion.",
                    "rationale": "Si hay muchas senales y ninguna aprobacion, el cuello de botella puede estar en priorizacion o prompt, no en riesgo.",
                    "expected_impact": "Mejor conversion de oportunidades sin subir exposicion por posicion.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["baseline_compare", "shadow_review"],
                    "rollback_plan": "Mantener limites actuales si la revision no mejora conversion con coste controlado.",
                }
            )
        if outcomes >= 10 and (micro or soft_backtest) and executed == 0:
            proposals.append(
                {
                    "proposal_type": "PARAMETER_CHANGE",
                    "target_component": "opportunistic_profile",
                    "target_identifier": "micro_execution_conversion",
                    "current_value": f"micro={micro}; soft_backtest={soft_backtest}; executed={executed}",
                    "proposed_value": "Investigar por que las oportunidades micro no llegan a ejecucion paper; validar daily caps, broker orders y trazabilidad.",
                    "rationale": "Un perfil oportunista sin conversion a ejecucion no aprende de mercado real.",
                    "expected_impact": "Cerrar el bucle entre senal, orden paper, outcome y recalibracion.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["tests", "paper_audit"],
                    "rollback_plan": "Desactivar micro overrides si no se puede auditar la ejecucion.",
                }
            )

        return ParameterCalibrationResponse(
            summary="Calibracion del perfil oportunista y sus parametros operativos.",
            confidence="MEDIUM" if signals or outcomes else "LOW",
            hypotheses=[
                {
                    "subject": "opportunistic_parameter_learning",
                    "summary": "El grupo debe medir si mas ancho de seleccion y micro-operaciones aumentan conversion sin deteriorar riesgo.",
                    "confidence": "MEDIUM" if profile == "opportunistic" else "LOW",
                    "evidence": [
                        f"profile={profile}",
                        f"signals={signals}",
                        f"outcomes={outcomes}",
                        f"micro={micro}",
                        f"soft_backtest={soft_backtest}",
                    ],
                }
            ],
            actions=actions,
            proposals=proposals,
        ).model_dump()


class ProgrammerAgent(SpecialistAgent):
    agent_name = AgentName.PROGRAMMER
    domain = "software-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        recent_errors = context.get("events", {}).get("recent_errors", []) or []
        data_quality = (context.get("reports", {}).get("market_data_quality") or {}).get("payload", {})
        issues = []
        proposals = []
        if recent_errors:
            issues.append(
                {
                    "issue_id": "repeated_runtime_errors",
                    "component": "software_runtime",
                    "description": "Hay errores repetidos en eventos recientes y deberían convertirse en deuda técnica accionable.",
                    "evidence": [str(item.get("event_type")) for item in recent_errors[:5]],
                    "severity": "MEDIUM",
                }
            )
            proposals.append(
                {
                    "proposal_type": "CODE_CHANGE",
                    "target_component": "software_runtime",
                    "target_identifier": "error_handling_review",
                    "current_value": f"errors={len(recent_errors)}",
                    "proposed_value": "Reforzar manejo de errores, observabilidad y tests en las rutas que repiten fallos.",
                    "rationale": "Errores repetidos deben traducirse en cambios de software propuestos y testeables.",
                    "expected_impact": "Menos fallos operativos y mejor diagnosis.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["tests"],
                    "rollback_plan": "Revertir cambios si aumentan ruido o complejidad sin eliminar fallos.",
                }
            )
        if data_quality:
            summary = data_quality.get("summary", {}) or {}
            coverage_ratio = summary.get("coverage_ratio")
            if isinstance(coverage_ratio, (int, float)) and coverage_ratio < 0.95:
                proposals.append(
                    {
                        "proposal_type": "DATA_QUALITY_CHANGE",
                        "target_component": "market_data_pipeline",
                        "target_identifier": "coverage_guard",
                        "current_value": f"coverage_ratio={coverage_ratio:.3f}",
                        "proposed_value": "Añadir checks y alertas más estrictas para cobertura de datos antes del scan.",
                        "rationale": "Una cobertura baja deteriora señales y decisiones posteriores.",
                        "expected_impact": "Mayor estabilidad de datos antes del análisis técnico.",
                        "risk_level": "LOW",
                        "required_validations": ["tests"],
                        "rollback_plan": "Retirar el guard si bloquea sesiones sin aportar señal útil.",
                    }
                )
        return ProgrammerAgentResponse(
            summary="Análisis de deuda técnica y propuestas de software derivadas del estado operativo.",
            confidence="MEDIUM" if recent_errors else "LOW",
            detected_issues=issues,
            hypotheses=[
                {
                    "subject": "software_runtime_reliability",
                    "summary": (
                        "El runtime necesita observabilidad y deuda tecnica accionable cuando se acumulan errores, "
                        "o vigilancia continua si todavia no hay evidencia suficiente."
                    ),
                    "confidence": "MEDIUM" if recent_errors else "LOW",
                    "evidence": [f"recent_errors={len(recent_errors)}"],
                }
            ],
            proposals=proposals,
        ).model_dump()


class MarketRegimeAgent(MarketEstimatorAgent):
    agent_name = AgentName.MARKET_REGIME

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        summary = context.get("evaluation", {}).get("summary", {})
        return SpecialistResponseBase(
            summary="Lectura de regimen de mercado y estabilidad relativa.",
            confidence="MEDIUM" if summary.get("signals", 0) else "LOW",
            hypotheses=[
                {
                    "subject": "market_regime",
                    "summary": "El regimen debe vigilarse junto al ancho de señal y la estabilidad reciente de outcomes.",
                    "confidence": "MEDIUM" if summary.get("outcomes_available", 0) else "LOW",
                    "evidence": [f"signals={summary.get('signals', 0)}", f"outcomes={summary.get('outcomes_available', 0)}"],
                }
            ],
            actions=[
                {
                    "action_type": "MONITORING",
                    "title": "Seguir regimen y volatilidad",
                    "rationale": "El comite necesita confirmar si el contexto favorece agresividad o proteccion.",
                    "risk_level": "LOW",
                }
            ],
        ).model_dump()


class TechnicalEdgeAgent(TechnicalAnalystAgent):
    agent_name = AgentName.TECHNICAL_EDGE

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        summary = context.get("evaluation", {}).get("summary", {})
        reports = context.get("reports", {}) or {}
        winner_report = (reports.get("winner_coverage") or {}).get("payload", {}) if (reports.get("winner_coverage") or {}).get("available") else {}
        blocker_report = (reports.get("fallback_blockers") or {}).get("payload", {}) if (reports.get("fallback_blockers") or {}).get("available") else {}
        winner_summary = winner_report.get("summary", {}) or {}
        blocker_summary = blocker_report.get("summary", {}) or {}
        fallback_blocker_sessions = sum(
            int(item.get("sessions") or 0)
            for item in list(winner_summary.get("fallback_blocker_summary") or [])[:10]
            if isinstance(item, dict)
        )
        selection_miss_sessions = sum(
            int(item.get("sessions") or 0)
            for item in list(winner_summary.get("selection_miss_summary") or [])[:10]
            if isinstance(item, dict)
        )
        selected_blocked_sessions = int(blocker_summary.get("selected_blocked_sessions") or 0)
        observations = max(summary.get("observations", 0), 1)
        blocked = summary.get("blocked_entry_quality", 0)
        duplicate_share = summary.get("duplicate_share", 0)
        proposals = []
        if blocked > 0:
            proposals.append(
                {
                    "proposal_type": "MONITORING_CHANGE",
                    "target_component": "entry_quality_filter",
                    "target_identifier": "blocked_winner_ratio",
                    "current_value": f"blocked={blocked}/obs={observations}",
                    "proposed_value": "Registrar falsos bloqueos y comparar winners evitados frente a losers evitados.",
                    "rationale": "El filtro debe aprender sobre falsos bloqueos, no solo sobre bloqueos absolutos.",
                    "expected_impact": "Mejor calibracion de entradas y menor perdida de winners.",
                    "risk_level": "LOW",
                    "required_validations": ["tests"],
                    "rollback_plan": "Volver a la configuracion vigente si el analisis no añade señal.",
                }
            )
        if fallback_blocker_sessions or selected_blocked_sessions:
            proposals.append(
                {
                    "proposal_type": "PARAMETER_CHANGE",
                    "target_component": "entry_quality_filter",
                    "target_identifier": "counterfactual_false_blockers",
                    "current_value": (
                        f"winner_blocker_sessions={fallback_blocker_sessions}; "
                        f"selected_blocked_sessions={selected_blocked_sessions}"
                    ),
                    "proposed_value": (
                        "Usar reportes winner_coverage/fallback_blockers para investigar excepciones estrechas "
                        "sobre SMA20, entry_score_v2, prior_error y score_min antes de tocar umbrales globales."
                    ),
                    "rationale": (
                        "La ventana reciente puede no tener outcomes maduros, pero los contrafactuales historicos "
                        "muestran coste real de oportunidad en ganadoras bloqueadas."
                    ),
                    "expected_impact": "Reducir falsos bloqueos de ganadoras sin abrir filtros globales ruidosos.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["backtest", "baseline_compare"],
                    "rollback_plan": "Mantener reglas champion si las excepciones aumentan negativos o drawdown.",
                }
            )
        if selection_miss_sessions:
            top_reasons = ", ".join(
                f"{item.get('reason')}={int(item.get('sessions') or 0)}"
                for item in list(winner_summary.get("selection_miss_summary") or [])[:3]
                if isinstance(item, dict)
            )
            proposals.append(
                {
                    "proposal_type": "PARAMETER_CHANGE",
                    "target_component": "deterministic_selector",
                    "target_identifier": "counterfactual_selection_misses",
                    "current_value": f"selection_miss_sessions={selection_miss_sessions}; {top_reasons}",
                    "proposed_value": (
                        "Separar oportunidades perdidas por ranking/direccion de los bloqueos de entrada; "
                        "evaluar boosts estrechos de ranking solo si la cohorte historica supera negativos y drawdown."
                    ),
                    "rationale": (
                        "Las ganadoras no capturadas no siempre fallan por entry_quality: algunas quedan fuera del limite "
                        "de seleccion o nacen como short/bearish, y requieren diagnostico distinto."
                    ),
                    "expected_impact": "Dirigir la mejora hacia ranking/seleccion sin relajar filtros de compra globales.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["backtest", "baseline_compare"],
                    "rollback_plan": "No cambiar ranking champion si la cohorte ampliada no mejora expectancy ajustada por riesgo.",
                }
            )
        if duplicate_share:
            proposals.append(
                {
                    "proposal_type": "DATA_QUALITY_CHANGE",
                    "target_component": "signal_consolidation",
                    "target_identifier": "duplicate_detection",
                    "current_value": f"duplicate_share={duplicate_share}",
                    "proposed_value": "Consolidar señales por simbolo y sesion antes de medir rendimiento.",
                    "rationale": "Los duplicados inflan el conteo y distorsionan hit rate y expectancy.",
                    "expected_impact": "Metrica mas limpia y decisiones de entrada mas fiables.",
                    "risk_level": "LOW",
                    "required_validations": ["tests", "data_quality_review"],
                    "rollback_plan": "Desactivar la consolidacion si elimina observaciones utiles.",
                }
            )
        return SpecialistResponseBase(
            summary="Analisis tecnico del edge, filtros y ruido de señales.",
            confidence="MEDIUM" if summary.get("observations", 0) else "LOW",
            hypotheses=[
                {
                    "subject": "technical_edge",
                    "summary": "La calidad tecnica depende de separar ruido, duplicados y falsos bloqueos.",
                    "confidence": "MEDIUM",
                    "evidence": [
                        f"blocked_entry_quality={blocked}",
                        f"observations={observations}",
                        f"winner_blocker_sessions={fallback_blocker_sessions}",
                        f"selected_blocked_sessions={selected_blocked_sessions}",
                    ],
                }
            ],
            proposals=proposals,
        ).model_dump()


class PreEarningsSpecialistAgent(SpecialistAgent):
    agent_name = AgentName.PRE_EARNINGS
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        reports = context.get("reports", {}) or {}
        digest = (reports.get("pre_earnings_learning") or {}).get("payload", {}) if (reports.get("pre_earnings_learning") or {}).get("available") else {}
        summary = digest.get("summary", {}) or {}
        blocked_big_winners = summary.get("blocked_big_winners", 0)
        proposals = []
        if blocked_big_winners:
            proposals.append(
                {
                    "proposal_type": "RISK_RULE_CHANGE",
                    "target_component": "pre_earnings_risk_veto",
                    "target_identifier": "blocked_big_winners",
                    "current_value": f"blocked_big_winners={blocked_big_winners}",
                    "proposed_value": "Revisar la logica de veto pre-earnings en shadow para separar winners bloqueados de ruido.",
                    "rationale": "Si el veto bloquea demasiados ganadores, la estrategia pierde expectancy aunque mejore seguridad.",
                    "expected_impact": "Reducir ganadores bloqueados sin aumentar drawdown.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["backtest", "baseline_compare", "shadow_review"],
                    "rollback_plan": "Restaurar el veto actual si empeora drawdown o net expectancy.",
                }
            )
        return SpecialistResponseBase(
            summary="Analisis de earnings, estimaciones y ventanas de veto.",
            confidence="MEDIUM" if digest else "LOW",
            hypotheses=[
                {
                    "subject": "pre_earnings_veto",
                    "summary": "El veto pre-earnings debe calibrarse con winners bloqueados y no solo con proteccion general.",
                    "confidence": "MEDIUM" if blocked_big_winners else "LOW",
                    "evidence": [f"blocked_big_winners={blocked_big_winners}"] if digest else ["sin digest pre-earnings"],
                }
            ],
            proposals=proposals,
            actions=[
                {
                    "action_type": "VALIDATION",
                    "title": "Comparar veto actual contra shadow",
                    "rationale": "Necesita validacion objetiva antes de relajar o endurecer el veto.",
                    "risk_level": "LOW",
                }
            ],
        ).model_dump()


class RiskCapitalAgent(SpecialistAgent):
    agent_name = AgentName.RISK_CAPITAL
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        evaluation = context.get("evaluation", {}) or {}
        summary = evaluation.get("summary", {}) or {}
        blocked_entry = int(summary.get("blocked_entry_quality") or 0)
        blocked_backtest = int(summary.get("blocked_backtest") or 0)
        proposals = []
        if blocked_entry or blocked_backtest:
            proposals.append(
                {
                    "proposal_type": "RISK_RULE_CHANGE",
                    "target_component": "risk_capital",
                    "target_identifier": "risk_gate_tuning",
                    "current_value": f"blocked_entry={blocked_entry}, blocked_backtest={blocked_backtest}",
                    "proposed_value": "Revisar límites de capital y veto con baseline y sensibilidad por régimen.",
                    "rationale": "El riesgo debe alinearse con el regimen y con el coste real de bloquear oportunidades.",
                    "expected_impact": "Mejor balance entre proteccion y captura de upside.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["backtest", "baseline_compare", "shadow_review"],
                    "rollback_plan": "Volver a limites actuales si el drawdown se deteriora.",
                }
            )
        return SpecialistResponseBase(
            summary="Analisis de riesgo y asignacion de capital.",
            confidence="MEDIUM" if (blocked_entry or blocked_backtest) else "LOW",
            hypotheses=[
                {
                    "subject": "risk_capital_alignment",
                    "summary": "El capital y el riesgo deben moverse con evidencia de bloqueos y degradacion real.",
                    "confidence": "MEDIUM" if (blocked_entry or blocked_backtest) else "LOW",
                    "evidence": [f"blocked_entry={blocked_entry}", f"blocked_backtest={blocked_backtest}"],
                }
            ],
            proposals=proposals,
        ).model_dump()


class DataQualityAgent(SpecialistAgent):
    agent_name = AgentName.DATA_QUALITY
    domain = "software-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        quality = (context.get("reports", {}).get("market_data_quality") or {}).get("payload", {}) if (context.get("reports", {}).get("market_data_quality") or {}).get("available") else {}
        summary = quality.get("summary", {}) or {}
        coverage_ratio = summary.get("coverage_ratio")
        duplicate_ratio = summary.get("duplicate_ratio")
        proposals = []
        if isinstance(coverage_ratio, (int, float)) and coverage_ratio < 0.98:
            proposals.append(
                {
                    "proposal_type": "DATA_QUALITY_CHANGE",
                    "target_component": "market_data_pipeline",
                    "target_identifier": "coverage_guard",
                    "current_value": f"coverage_ratio={coverage_ratio:.3f}",
                    "proposed_value": "Añadir alarmas y checkpoints para cobertura antes de analizar señales.",
                    "rationale": "Sin cobertura estable las decisiones de trading se degradan y las métricas engañan.",
                    "expected_impact": "Menos ruido y mejores entradas downstream.",
                    "risk_level": "LOW",
                    "required_validations": ["tests", "data_quality_review"],
                    "rollback_plan": "Desactivar el guard si bloquea sesiones sin aportar señal útil.",
                }
            )
        if isinstance(duplicate_ratio, (int, float)) and duplicate_ratio > 0:
            proposals.append(
                {
                    "proposal_type": "MONITORING_CHANGE",
                    "target_component": "signal_consolidation",
                    "target_identifier": "duplicate_ratio",
                    "current_value": f"duplicate_ratio={duplicate_ratio:.3f}",
                    "proposed_value": "Consolidar entradas repetidas por simbolo y sesion antes del scoring.",
                    "rationale": "Los duplicados falsean hit rate y hacen el aprendizaje menos fiable.",
                    "expected_impact": "Series mas limpias y decisiones mas consistentes.",
                    "risk_level": "LOW",
                    "required_validations": ["tests"],
                    "rollback_plan": "Revertir la consolidacion si reduce demasiado la cobertura.",
                }
            )
        return SpecialistResponseBase(
            summary="Control de calidad de datos, cobertura y duplicados.",
            confidence="MEDIUM" if quality else "LOW",
            hypotheses=[
                {
                    "subject": "data_quality",
                    "summary": "La calidad de datos necesita vigilancia antes de confiar en el edge de trading.",
                    "confidence": "MEDIUM" if quality else "LOW",
                    "evidence": [
                        f"coverage_ratio={coverage_ratio}" if coverage_ratio is not None else "coverage_ratio=unknown",
                        f"duplicate_ratio={duplicate_ratio}" if duplicate_ratio is not None else "duplicate_ratio=unknown",
                    ],
                }
            ],
            proposals=proposals,
        ).model_dump()


class SoftwareReliabilityAgent(ProgrammerAgent):
    agent_name = AgentName.SOFTWARE_RELIABILITY
    domain = "software-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        recent_errors = context.get("events", {}).get("recent_errors", []) or []
        proposals = []
        if recent_errors:
            proposals.append(
                {
                    "proposal_type": "CODE_CHANGE",
                    "target_component": "software_runtime",
                    "target_identifier": "error_handling_review",
                    "current_value": f"errors={len(recent_errors)}",
                    "proposed_value": "Mejorar manejo de errores y observabilidad en las rutas repetidas.",
                    "rationale": "Los errores repetidos merecen seguimiento y cambios revisables, no solo alertas.",
                    "expected_impact": "Menos fallos operativos y diagnosis mas rapida.",
                    "risk_level": "MEDIUM",
                    "required_validations": ["tests"],
                    "rollback_plan": "Revertir si el cambio añade complejidad sin reducir fallos.",
                }
            )
        return SpecialistResponseBase(
            summary="Analisis de fiabilidad del runtime y deuda tecnica.",
            confidence="MEDIUM" if recent_errors else "LOW",
            hypotheses=[
                {
                    "subject": "software_reliability",
                    "summary": "La fiabilidad mejora si cada error repetido se convierte en deuda técnica accionable.",
                    "confidence": "MEDIUM" if recent_errors else "LOW",
                    "evidence": [f"recent_errors={len(recent_errors)}"],
                }
            ],
            proposals=proposals,
        ).model_dump()


class ExperimentDesignerAgent(SpecialistAgent):
    agent_name = AgentName.EXPERIMENT_DESIGNER
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        evaluation = context.get("evaluation", {}) or {}
        blockers = evaluation.get("blockers", []) or []
        focus = str(task_payload.get("focus") or "")
        required_validations = self._required_validations_for_focus(focus, str(task_payload.get("initiative_key") or ""))
        return SpecialistResponseBase(
            summary="Diseño de experimentos y validaciones seguras para las iniciativas abiertas.",
            confidence="MEDIUM" if blockers else "LOW",
            actions=[
                {
                    "action_type": "VALIDATION",
                    "title": "Planificar backtest y shadow mode",
                    "rationale": "Cada iniciativa debe cerrarse con una validacion objetiva y trazable.",
                    "risk_level": "LOW",
                    "required_validations": required_validations,
                }
            ],
            hypotheses=[
                {
                    "subject": "experiment_design",
                    "summary": "Los experimentos deben comparar baseline, shadow y propuesta con la misma ventana y costes.",
                    "confidence": "HIGH",
                    "evidence": [f"blockers={len(blockers)}"],
                }
            ],
        ).model_dump()

    def _required_validations_for_focus(self, focus: str, initiative_key: str) -> list[str]:
        key = f"{initiative_key}:{focus}".lower()
        if any(token in key for token in {"pre_earnings", "risk_veto", "risk_capital"}):
            return ["backtest", "baseline_compare", "shadow_review"]
        if any(token in key for token in {"entry_quality", "market_regime", "outcome_generation"}):
            return ["backtest", "baseline_compare"]
        if any(token in key for token in {"data_quality", "signal_consolidation", "analyst_estimates"}):
            return ["tests", "data_quality_review"]
        if any(token in key for token in {"software_reliability", "runtime_reliability", "software"}):
            return ["tests"]
        return ["baseline_compare"]


class DecisionCommitteeAgent(SpecialistAgent):
    agent_name = AgentName.DECISION_COMMITTEE
    domain = "trading-improvement"

    def _deterministic(self, context: dict[str, Any], event: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
        proposals = context.get("existing_proposals", []) or []
        initiative_key = str(task_payload.get("initiative_key") or "").strip()
        scoped = [
            item
            for item in proposals
            if not initiative_key or str((item.get("payload") or {}).get("initiative_key") or "") == initiative_key
        ]
        considered = scoped or proposals
        pending = [item for item in considered if item.get("status") in {"PENDING", "REQUIRES_HUMAN_REVIEW"}]
        decision = self._decision_for_proposals(considered)
        proposal_targets = [
            {
                "proposal_id": item.get("proposal_id"),
                "status": self._proposal_status_for_decision(decision, item),
            }
            for item in considered
            if item.get("proposal_id")
        ]
        bucket = self._backlog_bucket(decision)
        return SpecialistResponseBase(
            summary=f"Decision {decision} del comite sobre iniciativas y propuestas.",
            confidence="MEDIUM" if considered else "LOW",
            decision=decision,
            decision_reason=self._decision_reason(decision, considered),
            deterministic_alignment=True,
            deterministic_decision=decision,
            discrepancy_justification="",
            initiative_status_target=self._initiative_status_for_decision(decision),
            proposal_status_targets=proposal_targets,
            priority_adjustment=self._priority_adjustment(decision, considered),
            backlog_rank=self._backlog_rank(decision, considered),
            backlog_bucket=bucket,
            required_follow_up=self._follow_up_for_decision(decision),
            close_initiative=decision in {"REJECT", "MONITOR"},
            actions=[
                {
                    "action_type": "ESCALATION" if decision == "ESCALATE" else "MONITORING",
                    "title": self._follow_up_for_decision(decision),
                    "rationale": "La decision final depende del estado de validacion, riesgo y rollback.",
                    "risk_level": "HIGH" if decision == "ESCALATE" else "LOW",
                }
            ],
            hypotheses=[
                {
                    "subject": "decision_governance",
                    "summary": "La decision final debe depender del estado de validacion y del impacto medido.",
                    "confidence": "HIGH",
                    "evidence": [f"pending_proposals={len(pending)}"],
                }
            ],
        ).model_dump()

    def _decision_for_proposals(self, proposals: list[dict[str, Any]]) -> str:
        if not proposals:
            return "MONITOR"
        statuses = {str(item.get("status") or "").upper() for item in proposals}
        risk_levels = {str(item.get("risk_level") or "").upper() for item in proposals}
        guards = [item.get("guard") or {} for item in proposals]
        if "REJECTED" in statuses or any((guard.get("status") == "REJECTED") for guard in guards):
            return "REJECT"
        if "HIGH" in risk_levels or "REQUIRES_HUMAN_REVIEW" in statuses or "WAITING_HUMAN_REVIEW" in statuses:
            return "ESCALATE"
        if "READY_TO_APPLY" in statuses or "PASSED" in statuses:
            return "APPROVE"
        if "PENDING" in statuses:
            return "REWORK"
        return "MONITOR"

    def _proposal_status_for_decision(self, decision: str, proposal: dict[str, Any]) -> str:
        current = str(proposal.get("status") or "PENDING").upper()
        if decision == "APPROVE":
            return "READY_TO_APPLY" if current == "READY_TO_APPLY" else "PASSED"
        if decision == "REJECT":
            return "REJECTED"
        if decision == "REWORK":
            return "PENDING"
        if decision == "ESCALATE":
            return "WAITING_HUMAN_REVIEW"
        return current if current not in {"", "PENDING"} else "PENDING"

    def _initiative_status_for_decision(self, decision: str) -> str:
        return {
            "APPROVE": "READY_TO_APPLY",
            "REJECT": "REJECTED",
            "REWORK": "EXPERIMENTING",
            "MONITOR": "MONITORING",
            "ESCALATE": "WAITING_REVIEW",
        }.get(decision, "VALIDATING")

    def _decision_reason(self, decision: str, proposals: list[dict[str, Any]]) -> str:
        return f"decision={decision}; proposals={len(proposals)}; statuses={[item.get('status') for item in proposals]}"

    def _priority_adjustment(self, decision: str, proposals: list[dict[str, Any]]) -> str:
        if decision in {"APPROVE", "ESCALATE"}:
            return "raise"
        if decision in {"REJECT", "MONITOR"}:
            return "lower"
        return "keep"

    def _backlog_bucket(self, decision: str) -> str:
        return {
            "APPROVE": "NOW",
            "REWORK": "NEXT",
            "MONITOR": "LATER",
            "ESCALATE": "HUMAN",
            "REJECT": "LATER",
        }.get(decision, "NEXT")

    def _backlog_rank(self, decision: str, proposals: list[dict[str, Any]]) -> int:
        base = {"APPROVE": 10, "ESCALATE": 20, "REWORK": 40, "MONITOR": 70, "REJECT": 90}.get(decision, 50)
        return base + min(9, len(proposals))

    def _follow_up_for_decision(self, decision: str) -> str:
        return {
            "APPROVE": "Aplicar o promover la propuesta validada.",
            "REJECT": "Cerrar la iniciativa como rechazada.",
            "REWORK": "Generar artefacto, rollback o evidencia faltante.",
            "MONITOR": "Mantener en seguimiento hasta nueva evidencia.",
            "ESCALATE": "Esperar revision humana por riesgo o ambiguedad.",
        }.get(decision, "Esperar nueva evidencia.")


class ImprovementStrategistAgent:
    def __init__(self, client: ImprovementLLMClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def propose(self, context: dict[str, Any], evaluation: dict[str, Any]) -> LLMJsonResult:
        system = (
            "Eres el motor externo de mejora continua de un sistema de trading en modo seguro. "
            "Debes devolver solo JSON valido con el esquema pedido. No inventes metricas, no propongas "
            "trading real, no propongas cambios destructivos y no bases PnL en texto generado."
        )
        safety_rules = {
            "no_live_trading": True,
            "no_real_orders": True,
            "no_destructive_changes": True,
            "code_changes_require_human_review": self.settings.require_human_approval_for_code_changes,
            "dry_run_first": self.settings.improvement_dry_run,
            "allow_auto_apply_improvements": self.settings.allow_auto_apply_improvements,
            "allow_live_trading": self.settings.allow_live_trading,
        }
        user_payload = compact_ci_context_for_llm(
            context=context,
            evaluation=evaluation,
            safety_rules=safety_rules,
            target_tokens=self.settings.improvement_llm_context_target_tokens,
            hard_limit_tokens=self.settings.improvement_llm_context_hard_limit_tokens,
        )
        return self.client.generate_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True, default=str)},
            ],
            {},
            model=self.settings.improvement_llm_orchestrator_model,
        )


class ChiefInvestmentOrchestratorAgent(ImprovementStrategistAgent):
    pass


class RiskGuardAgent:
    DANGEROUS_TERMS = {
        "live trading",
        "trading real",
        "real order",
        "orden real",
        "market order",
        "rm -rf",
        "drop table",
        "delete database",
        "disable risk",
        "saltarse riesgo",
    }

    def assess(self, proposal: ImprovementProposalPayload, settings: Settings) -> dict[str, Any]:
        text = " ".join(
            [
                proposal.proposal_type,
                proposal.target_component,
                proposal.target_identifier,
                proposal.current_value,
                proposal.proposed_value,
                proposal.rationale,
                proposal.rollback_plan,
            ]
        ).lower()
        reasons: list[str] = []
        if any(term in text for term in self.DANGEROUS_TERMS):
            reasons.append("dangerous_term")
        if proposal.proposal_type == "CODE_CHANGE" and settings.require_human_approval_for_code_changes:
            reasons.append("code_change_autonomy_disabled")
        if proposal.risk_level == "HIGH" and settings.require_human_approval_for_high_risk:
            reasons.append("high_risk_autonomy_disabled")
        if settings.allow_live_trading:
            reasons.append("environment_allows_live_trading")
        if not settings.improvement_dry_run:
            reasons.append("autonomous_apply_enabled")

        rejected = "dangerous_term" in reasons
        if rejected:
            status = "REJECTED"
        elif (
            proposal.proposal_type == "CODE_CHANGE"
            and proposal.risk_level == "HIGH"
            and settings.require_human_approval_for_high_risk
        ):
            status = "WAITING_HUMAN_REVIEW"
        elif proposal.proposal_type == "CODE_CHANGE" and settings.require_human_approval_for_code_changes:
            status = "WAITING_HUMAN_REVIEW"
        else:
            status = "PENDING"
        return {
            "status": status,
            "approved_for_auto_apply": not rejected and proposal.proposal_type == "CODE_CHANGE" and settings.allow_auto_apply_improvements and not settings.improvement_dry_run and not settings.require_human_approval_for_code_changes and not settings.allow_live_trading,
            "reasons": reasons,
            "dry_run": settings.improvement_dry_run,
        }


class ValidationAgent:
    CANONICAL_VALIDATION_ALIASES = {
        "backtest": "in_sample",
        "baseline_compare": "out_of_sample",
        "shadow_review": "walk_forward",
        "paper_audit": "paper_or_shadow_window",
    }
    CHAMPION_CHALLENGER_REQUIRED = [
        "in_sample",
        "walk_forward",
        "out_of_sample",
        "paper_or_shadow_window",
        "risk_review",
    ]

    def validate(
        self,
        proposal: dict[str, Any],
        context: dict[str, Any],
        settings: Settings,
        store: Store | None = None,
    ) -> dict[str, Any]:
        payload = {**(proposal.get("payload", {}) or {}), "proposal_id": proposal.get("proposal_id")}
        proposal_type = str(proposal.get("proposal_type") or payload.get("proposal_type") or "MONITORING_CHANGE")
        target_component = str(proposal.get("target_component") or payload.get("target_component") or "").strip()
        required = self._normalize_required_validations(
            payload.get("required_validations") or self._default_required_validations(proposal_type)
        )
        required_lower = {str(item).lower() for item in required}
        objective = self._objective_validation(
            proposal_type=proposal_type,
            target_component=target_component,
            payload=payload,
            context=context,
            settings=settings,
            store=store,
        )
        checks = [
            {
                "name": "safety_flags",
                "passed": (
                    not settings.allow_live_trading
                    and (
                        (
                            proposal_type == "CODE_CHANGE"
                            and settings.allow_auto_apply_improvements
                            and not settings.improvement_dry_run
                            and not settings.require_human_approval_for_code_changes
                        )
                        or (
                            proposal_type != "CODE_CHANGE"
                            and settings.improvement_dry_run
                            and not settings.allow_auto_apply_improvements
                        )
                    )
                ),
                "detail": (
                    "Auto-apply de codigo habilitado con live trading bloqueado."
                    if proposal_type == "CODE_CHANGE"
                    else "Dry-run activo, auto-apply desactivado y live trading bloqueado."
                ),
            },
            {
                "name": "rollback_plan_present",
                "passed": bool(str(payload.get("rollback_plan") or "").strip()),
                "detail": "Toda propuesta debe tener rollback.",
            },
        ]
        checks.extend(objective["checks"])
        if bool(payload.get("evaluation_window_frozen")) and bool(payload.get("frozen_conflict")):
            checks.append(
                {
                    "name": "evaluation_window_frozen",
                    "passed": False,
                    "detail": "La propuesta intenta cambiar parametros durante una ventana de evaluacion congelada.",
                }
            )
        tuning_count = int(payload.get("parameter_tuning_count") or payload.get("threshold_change_count") or 0)
        if tuning_count > 2:
            checks.append(
                {
                    "name": "repeated_parameter_tuning",
                    "passed": False,
                    "detail": "Demasiados cambios de parametros dentro de la ventana; riesgo alto de sobreajuste.",
                    "evidence": {"tuning_count": tuning_count},
                }
            )
        if proposal_type == "CODE_CHANGE":
            checks.append(
                {
                    "name": "code_change_human_review",
                    "passed": True,
                    "detail": "CODE_CHANGE requiere artefacto aplicable, tests y flags explicitos de autonomia.",
                }
            )
        elif proposal_type != "MONITORING_CHANGE" and not required_lower:
            checks.append(
                {
                    "name": "explicit_validation_plan_required",
                    "passed": False,
                    "detail": "La propuesta necesita un plan de validacion explicito antes de cerrarse.",
                }
            )
        passed = all(item["passed"] for item in checks)
        next_status = self._select_status(
            proposal_type=proposal_type,
            passed=passed,
            objective_status=objective["status"],
            settings=settings,
            proposal=proposal,
        )
        return {
            "validation_id": new_id("ci_val"),
            "proposal_id": proposal["proposal_id"],
            "cycle_id": proposal["cycle_id"],
            "validation_type": "deterministic_gate",
            "status": next_status,
            "payload": {
                "checks": checks,
                "required_validations": required,
                "data_quality": (context.get("evaluation") or {}).get("data_quality"),
                "objective_status": objective["status"],
                "objective_evidence": objective["evidence"],
                "objective_summary": objective["summary"],
                "target_component": target_component,
            },
        }

    def _select_status(
        self,
        *,
        proposal_type: str,
        passed: bool,
        objective_status: str,
        settings: Settings,
        proposal: dict[str, Any],
    ) -> str:
        risk_level = str(proposal.get("risk_level") or "").upper()
        if proposal_type == "CODE_CHANGE":
            if objective_status == "REJECTED":
                return "REJECTED"
            if risk_level == "HIGH" and settings.require_human_approval_for_high_risk:
                return "WAITING_HUMAN_REVIEW"
            if settings.require_human_approval_for_code_changes:
                return "WAITING_HUMAN_REVIEW"
            return objective_status if passed and objective_status == "READY_TO_APPLY" else "PENDING"
        if objective_status == "REJECTED":
            return "REJECTED"
        if not passed:
            return "PENDING"
        if settings.allow_auto_apply_improvements and objective_status == "PASSED":
            return "READY_TO_APPLY"
        return "PASSED"

    def _objective_validation(
        self,
        *,
        proposal_type: str,
        target_component: str,
        payload: dict[str, Any],
        context: dict[str, Any],
        settings: Settings,
        store: Store | None,
    ) -> dict[str, Any]:
        reports = context.get("reports", {}) or {}
        evaluation = context.get("evaluation", {}) or {}
        summary = evaluation.get("summary", {}) or {}
        learning = context.get("learning", {}) or {}
        observations = learning.get("observations", []) or []

        daily = self._report_payload(reports.get("daily_learning"))
        backtest = self._report_payload(reports.get("backtest"))
        operational = self._report_payload(reports.get("operational_learning"))
        pre_earnings = self._report_payload(reports.get("pre_earnings_learning"))
        market_quality = self._report_payload(reports.get("market_data_quality"))
        post_market = self._report_payload(reports.get("post_market_review"))
        live_readiness = self._report_payload(reports.get("live_readiness"))
        walk_forward = self._report_payload(reports.get("walk_forward_validation"))
        session_retrospective = self._report_payload(reports.get("session_retrospective"))
        required_lower = {
            str(item).lower()
            for item in self._normalize_required_validations(
                payload.get("required_validations") or self._default_required_validations(proposal_type)
            )
        }

        evidence: dict[str, Any] = {
            "daily_learning": self._compact_report(daily),
            "backtest": self._compact_report(backtest),
            "operational_learning": self._compact_report(operational),
            "pre_earnings_learning": self._compact_report(pre_earnings),
            "market_data_quality": self._compact_report(market_quality),
            "post_market_review": self._compact_report(post_market),
            "live_readiness": self._compact_report(live_readiness),
            "walk_forward_validation": self._compact_report(walk_forward),
            "session_retrospective": self._compact_report(session_retrospective),
            "summary": {
                "signals": summary.get("signals", 0),
                "observations": summary.get("observations", 0),
                "outcomes_available": summary.get("outcomes_available", 0),
                "blocked_entry_quality": summary.get("blocked_entry_quality", 0),
                "blocked_backtest": summary.get("blocked_backtest", 0),
                "recent_errors": summary.get("recent_errors", 0),
                "duplicate_observations": sum(int(item.get("duplicate_count") or 0) for item in observations),
            },
        }

        checks: list[dict[str, Any]] = []
        objective_status = "PENDING"
        summary_text = "No hay evidencia objetiva suficiente."

        duplicate_count = evidence["summary"]["duplicate_observations"]
        duplicate_ratio = (
            round(duplicate_count / max(int(evidence["summary"]["signals"] or 0), 1), 4)
            if evidence["summary"]["signals"]
            else 0.0
        )

        if proposal_type == "RISK_RULE_CHANGE" and "pre_earnings" in target_component:
            checks, objective_status, summary_text = self._validate_pre_earnings_veto(
                pre_earnings=pre_earnings,
                summary=summary,
                payload=payload,
            )
        elif proposal_type == "PARAMETER_CHANGE" and "entry_quality" in target_component:
            checks, objective_status, summary_text = self._validate_entry_quality(
                daily=daily,
                summary=summary,
                duplicate_ratio=duplicate_ratio,
            )
        elif proposal_type == "DATA_QUALITY_CHANGE" and "signal_consolidation" in target_component:
            checks, objective_status, summary_text = self._validate_signal_consolidation(
                daily=daily,
                duplicate_ratio=duplicate_ratio,
            )
        elif proposal_type == "DATA_QUALITY_CHANGE" and "analyst_estimates" in target_component:
            checks, objective_status, summary_text = self._validate_estimate_pipeline(
                pre_earnings=pre_earnings,
            )
        elif proposal_type == "MONITORING_CHANGE" and "outcome_generation" in target_component:
            checks, objective_status, summary_text = self._validate_outcomes(
                summary=summary,
                daily=daily,
                operational=operational,
            )
        elif proposal_type == "CODE_CHANGE":
            checks, objective_status, summary_text = self._validate_code_change(payload, store, operational, live_readiness)
        else:
            checks, objective_status, summary_text = self._validate_generic(
                proposal_type=proposal_type,
                payload=payload,
                daily=daily,
                operational=operational,
                pre_earnings=pre_earnings,
                market_quality=market_quality,
                post_market=post_market,
                summary=summary,
                duplicate_ratio=duplicate_ratio,
                walk_forward=walk_forward,
                session_retrospective=session_retrospective,
            )

        if "in_sample" in required_lower and not self._has_backtest_evidence(
            daily=daily,
            backtest=backtest,
            operational=operational,
            pre_earnings=pre_earnings,
            walk_forward=walk_forward,
        ):
            checks.append(
                {
                    "name": "in_sample",
                    "passed": False,
                    "detail": "Backtest requerido, pero no hay reporte objetivo disponible.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "out_of_sample" in required_lower and not self._has_baseline_evidence(
            daily=daily,
            operational=operational,
            session_retrospective=session_retrospective,
        ):
            checks.append(
                {
                    "name": "out_of_sample",
                    "passed": False,
                    "detail": "Comparacion contra baseline requerida, pero no hay evidencia objetiva disponible.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "walk_forward" in required_lower and not self._has_shadow_evidence(
            operational=operational,
            session_retrospective=session_retrospective,
        ):
            checks.append(
                {
                    "name": "walk_forward",
                    "passed": False,
                    "detail": "Revision shadow requerida, pero no hay evaluacion shadow disponible.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "paper_or_shadow_window" in required_lower and not self._has_paper_or_shadow_window_evidence(
            operational=operational,
            daily=daily,
            post_market=post_market,
        ):
            checks.append(
                {
                    "name": "paper_or_shadow_window",
                    "passed": False,
                    "detail": "Falta ventana paper/shadow con evidencia operativa suficiente.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "risk_review" in required_lower and not self._has_risk_review_evidence(
            live_readiness=live_readiness,
            market_quality=market_quality,
        ):
            checks.append(
                {
                    "name": "risk_review",
                    "passed": False,
                    "detail": "Falta revision objetiva de riesgo/readiness para promover el challenger.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "data_quality_review" in required_lower and not self._has_data_quality_evidence(
            daily=daily,
            market_quality=market_quality,
            duplicate_ratio=duplicate_ratio,
        ):
            checks.append(
                {
                    "name": "data_quality_review",
                    "passed": False,
                    "detail": "Revision de calidad de datos requerida, pero no hay evidencia suficiente.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status
        if "tests" in required_lower and proposal_type != "CODE_CHANGE":
            checks.append(
                {
                    "name": "tests_evidence",
                    "passed": False,
                    "detail": "Tests requeridos, pero esta version no ejecuta tests ni muta el repo automaticamente.",
                }
            )
            objective_status = "PENDING" if objective_status == "PASSED" else objective_status

        if not checks:
            checks = [
                {
                    "name": "objective_evidence",
                    "passed": False,
                    "detail": "No se encontro evidencia objetiva suficiente.",
                }
            ]

        return {"checks": checks, "status": objective_status, "summary": summary_text, "evidence": evidence}

    def _report_payload(self, report: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(report, dict) or not report.get("available"):
            return {}
        payload = report.get("payload")
        return payload if isinstance(payload, dict) else {}

    def _compact_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {"available": False}
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        return {
            "available": True,
            "as_of": payload.get("as_of"),
            "summary": summary,
            "metrics": metrics,
        }

    def _has_backtest_evidence(
        self,
        *,
        daily: dict[str, Any],
        backtest: dict[str, Any],
        operational: dict[str, Any],
        pre_earnings: dict[str, Any],
        walk_forward: dict[str, Any] | None = None,
    ) -> bool:
        if walk_forward and walk_forward.get("summary"):
            return True
        return bool(
            backtest.get("metrics")
            or daily.get("entry_quality_filter_calibration_3d")
            or daily.get("backtest_filter_calibration_3d")
            or pre_earnings.get("metrics")
        )

    def _has_baseline_evidence(
        self,
        *,
        daily: dict[str, Any],
        operational: dict[str, Any],
        session_retrospective: dict[str, Any] | None = None,
    ) -> bool:
        if session_retrospective and session_retrospective.get("summary"):
            return True
        return bool(daily.get("summary") or operational.get("shadow_evaluation"))

    def _has_shadow_evidence(
        self,
        *,
        operational: dict[str, Any],
        session_retrospective: dict[str, Any] | None = None,
    ) -> bool:
        if session_retrospective and session_retrospective.get("sessions"):
            return True
        return bool((operational.get("shadow_evaluation") or {}).get("metrics_by_rule"))

    def _has_data_quality_evidence(
        self,
        *,
        daily: dict[str, Any],
        market_quality: dict[str, Any],
        duplicate_ratio: float,
    ) -> bool:
        if duplicate_ratio > 0:
            return True
        if market_quality:
            return True
        return bool(daily.get("summary"))

    def _has_paper_or_shadow_window_evidence(
        self,
        *,
        operational: dict[str, Any],
        daily: dict[str, Any],
        post_market: dict[str, Any],
    ) -> bool:
        if (operational.get("shadow_evaluation") or {}).get("metrics_by_rule"):
            return True
        if daily.get("summary"):
            return True
        return bool(post_market.get("summary"))

    def _has_risk_review_evidence(
        self,
        *,
        live_readiness: dict[str, Any],
        market_quality: dict[str, Any],
    ) -> bool:
        if live_readiness:
            return True
        return bool(market_quality)

    def _validate_pre_earnings_veto(
        self,
        *,
        pre_earnings: dict[str, Any],
        summary: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        metrics = pre_earnings.get("metrics", {}) if isinstance(pre_earnings.get("metrics"), dict) else {}
        blocked_big_winners = int(metrics.get("blocked_big_winners") or summary.get("blocked_big_winners") or 0)
        actionable_false_positive_rate = metrics.get("actionable_false_positive_rate")
        risk_veto_review = list(pre_earnings.get("risk_veto_review") or [])
        if blocked_big_winners > 0:
            checks.append(
                {
                    "name": "blocked_big_winners_detected",
                    "passed": True,
                    "detail": "Existen ganadores bloqueados por el veto pre-earnings.",
                    "evidence": {"blocked_big_winners": blocked_big_winners},
                }
            )
        else:
            checks.append(
                {
                    "name": "blocked_big_winners_detected",
                    "passed": False,
                    "detail": "No hay ganadores bloqueados suficientes para justificar el ajuste del veto.",
                    "evidence": {"blocked_big_winners": blocked_big_winners},
                }
            )
        if actionable_false_positive_rate is not None:
            checks.append(
                {
                    "name": "actionable_false_positive_rate",
                    "passed": float(actionable_false_positive_rate) <= 0.25,
                    "detail": f"Tasa de falsos positivos accionables: {float(actionable_false_positive_rate):.4f}.",
                    "evidence": {"actionable_false_positive_rate": actionable_false_positive_rate},
                }
            )
        if risk_veto_review:
            checks.append(
                {
                    "name": "risk_veto_review_available",
                    "passed": True,
                    "detail": "Existe revisión pre-earnings suficiente para comparar veto actual contra shadow.",
                    "evidence": {"reviewed_items": len(risk_veto_review)},
                }
            )
        passed = blocked_big_winners > 0 and (actionable_false_positive_rate is None or float(actionable_false_positive_rate) <= 0.25)
        if not risk_veto_review:
            passed = False
        status = "READY_TO_APPLY" if passed and blocked_big_winners >= 2 and float(actionable_false_positive_rate or 0.0) <= 0.20 else ("PASSED" if passed else "PENDING")
        summary_text = (
            "El veto pre-earnings tiene ganadores bloqueados medibles y una revisión suficiente para justificar calibración."
            if passed
            else "Falta evidencia suficiente para afinar el veto pre-earnings con seguridad."
        )
        return checks, status, summary_text

    def _validate_entry_quality(
        self,
        *,
        daily: dict[str, Any],
        summary: dict[str, Any],
        duplicate_ratio: float,
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        calibration = daily.get("entry_quality_filter_calibration_3d") or {}
        backtest_calibration = daily.get("backtest_filter_calibration_3d") or {}
        blocked_entry_quality = int(summary.get("blocked_entry_quality") or 0)
        calibration_signals = int(calibration.get("signals") or 0)
        backtest_signals = int(backtest_calibration.get("signals") or 0)
        if blocked_entry_quality > 0:
            checks.append(
                {
                    "name": "blocked_entry_quality_detected",
                    "passed": True,
                    "detail": "El filtro de entrada esta bloqueando observaciones en el contexto actual.",
                    "evidence": {"blocked_entry_quality": blocked_entry_quality},
                }
            )
        else:
            checks.append(
                {
                    "name": "blocked_entry_quality_detected",
                    "passed": False,
                    "detail": "No hay bloqueos de calidad de entrada suficientes para justificar el ajuste.",
                    "evidence": {"blocked_entry_quality": blocked_entry_quality},
                }
            )
        if calibration_signals:
            checks.append(
                {
                    "name": "entry_quality_calibration_present",
                    "passed": True,
                    "detail": "Existe calibracion objetiva del filtro de entrada en 3d.",
                    "evidence": {"signals": calibration_signals, "top_tags": calibration.get("top_tags", [])[:3]},
                }
            )
        if backtest_signals:
            checks.append(
                {
                    "name": "backtest_calibration_present",
                    "passed": True,
                    "detail": "Existe calibracion de backtest del filtro en 3d.",
                    "evidence": {"signals": backtest_signals, "top_tags": backtest_calibration.get("top_tags", [])[:3]},
                }
            )
        issue_visible = blocked_entry_quality > 0 or duplicate_ratio > 0
        passed = issue_visible and (calibration_signals > 0 or backtest_signals > 0)
        status = "READY_TO_APPLY" if passed and (calibration_signals >= 5 or backtest_signals >= 5) else ("PASSED" if passed else "PENDING")
        summary_text = (
            "El filtro de entrada tiene evidencia objetiva y puede ajustarse con revisiones controladas."
            if passed
            else "La evidencia actual no basta para calibrar el filtro de entrada."
        )
        return checks, status, summary_text

    def _validate_signal_consolidation(
        self,
        *,
        daily: dict[str, Any],
        duplicate_ratio: float,
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        summary = daily.get("summary") or {}
        duplicate_signals = float(summary.get("duplicate_signals") or duplicate_ratio)
        canonical_observations = int(summary.get("canonical_observations") or 0)
        if duplicate_signals > 0:
            checks.append(
                {
                    "name": "duplicate_signals_present",
                    "passed": True,
                    "detail": "Hay duplicados reales que consolidar.",
                    "evidence": {"duplicate_signals": duplicate_signals, "duplicate_ratio": duplicate_ratio},
                }
            )
        else:
            checks.append(
                {
                    "name": "duplicate_signals_present",
                    "passed": False,
                    "detail": "No se observan duplicados suficientes para justificar la iniciativa.",
                    "evidence": {"duplicate_signals": duplicate_signals, "duplicate_ratio": duplicate_ratio},
                }
            )
        if canonical_observations > 0:
            checks.append(
                {
                    "name": "canonical_observations_available",
                    "passed": True,
                    "detail": "Existen observaciones canonicas suficientes para medir la consolidacion.",
                    "evidence": {"canonical_observations": canonical_observations},
                }
            )
        passed = duplicate_signals > 0 and canonical_observations > 0
        status = "READY_TO_APPLY" if passed and duplicate_signals >= 3 else ("PASSED" if passed else "PENDING")
        summary_text = (
            "La consolidacion de señales esta justificada por duplicados medibles."
            if passed
            else "Falta volumen o duplicados para validar la consolidacion."
        )
        return checks, status, summary_text

    def _validate_estimate_pipeline(
        self,
        *,
        pre_earnings: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        metrics = pre_earnings.get("metrics", {}) if isinstance(pre_earnings.get("metrics"), dict) else {}
        coverage = metrics.get("estimate_coverage_rate")
        missing = int(metrics.get("estimate_missing_rows") or 0)
        errors = int(metrics.get("estimate_error_rows") or 0)
        if coverage is not None:
            checks.append(
                {
                    "name": "estimate_coverage_available",
                    "passed": True,
                    "detail": "La cobertura de estimaciones esta medida objetivamente.",
                    "evidence": {"estimate_coverage_rate": coverage},
                }
            )
        if missing > 0 or errors > 0:
            checks.append(
                {
                    "name": "estimate_gaps_detected",
                    "passed": True,
                    "detail": "Hay huecos o errores suficientes para justificar la mejora del pipeline.",
                    "evidence": {"missing": missing, "errors": errors},
                }
            )
        passed = coverage is not None and (missing > 0 or errors > 0)
        status = "READY_TO_APPLY" if passed and float(coverage or 0.0) >= 0.60 and missing > 0 else ("PASSED" if passed else "PENDING")
        summary_text = (
            "El pipeline de estimaciones presenta huecos medibles y puede priorizarse."
            if passed
            else "No hay suficiente evidencia para priorizar el pipeline de estimaciones."
        )
        return checks, status, summary_text

    def _validate_outcomes(
        self,
        *,
        summary: dict[str, Any],
        daily: dict[str, Any],
        operational: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        outcomes_available = int(summary.get("outcomes_available") or 0)
        calibration = daily.get("summary") or {}
        shadow_eval = operational.get("shadow_evaluation") or {}
        if outcomes_available > 0:
            checks.append(
                {
                    "name": "outcomes_available",
                    "passed": True,
                    "detail": "Existen outcomes suficientes para validar el ciclo de mejora.",
                    "evidence": {"outcomes_available": outcomes_available},
                }
            )
        if calibration:
            checks.append(
                {
                    "name": "daily_digest_available",
                    "passed": True,
                    "detail": "El digest diario esta disponible como baseline de comparacion.",
                    "evidence": calibration,
                }
            )
        if shadow_eval:
            checks.append(
                {
                    "name": "shadow_evaluation_available",
                    "passed": True,
                    "detail": "La evaluacion shadow esta disponible para contraste.",
                    "evidence": {"rules_evaluated": shadow_eval.get("rules_evaluated", 0)},
                }
            )
        passed = outcomes_available > 0
        status = "READY_TO_APPLY" if passed and outcomes_available >= 10 else ("PASSED" if passed else "PENDING")
        summary_text = (
            "Los outcomes ya permiten medir mejora real."
            if passed
            else "Aun faltan outcomes maduros para validar la generacion de resultados."
        )
        return checks, status, summary_text

    def _validate_code_change(
        self,
        payload: dict[str, Any],
        store: Store | None,
        operational: dict[str, Any],
        live_readiness: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        has_apply_payload = bool(payload.get("file_edits") or payload.get("files") or str(payload.get("patch") or "").strip())
        tests = payload.get("test_commands") or []
        files = payload.get("file_edits") or payload.get("files") or []
        checks.extend(
            [
                {
                    "name": "code_artifact_applicable",
                    "passed": has_apply_payload,
                    "detail": "La propuesta incluye patch o file_edits aplicable.",
                },
                {
                    "name": "code_tests_declared",
                    "passed": bool(tests),
                    "detail": "La propuesta declara comandos de test para validar el cambio.",
                },
                {
                    "name": "code_files_declared",
                    "passed": bool(files or payload.get("patch")),
                    "detail": "La propuesta declara archivos o patch objetivo.",
                },
            ]
        )
        if store is not None:
            artifact = store.continuous_improvement_proposal_artifact(str(payload.get("proposal_id") or ""))
            if artifact:
                checks.append(
                    {
                        "name": "artifact_present",
                        "passed": True,
                        "detail": "Existe artefacto de propuesta para trazabilidad.",
                        "evidence": {"artifact_type": artifact.get("artifact_type")},
                    }
                )
        if operational:
            checks.append(
                {
                    "name": "operational_learning_available",
                    "passed": True,
                    "detail": "Hay evidencia operativa para revisar la propuesta de software.",
                }
            )
        if live_readiness:
            checks.append(
                {
                    "name": "live_readiness_available",
                    "passed": True,
                    "detail": "Existe chequeo de readiness para contexto operativo.",
                }
            )
        ready = has_apply_payload and bool(tests)
        if ready:
            return checks, "READY_TO_APPLY", "La propuesta de codigo tiene artefacto aplicable y tests declarados."
        return checks, "PENDING", "La propuesta de codigo aun no tiene artefacto aplicable y tests."

    def _validate_generic(
        self,
        *,
        proposal_type: str,
        payload: dict[str, Any],
        daily: dict[str, Any],
        operational: dict[str, Any],
        pre_earnings: dict[str, Any],
        market_quality: dict[str, Any],
        post_market: dict[str, Any],
        summary: dict[str, Any],
        duplicate_ratio: float,
        walk_forward: dict[str, Any] | None = None,
        session_retrospective: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        checks: list[dict[str, Any]] = []
        if daily:
            checks.append({"name": "daily_learning_available", "passed": True, "detail": "Digest diario disponible."})
        if operational:
            checks.append({"name": "operational_learning_available", "passed": True, "detail": "Aprendizaje operacional disponible."})
        if pre_earnings:
            checks.append({"name": "pre_earnings_available", "passed": True, "detail": "Contexto pre-earnings disponible."})
        if market_quality:
            checks.append({"name": "market_data_quality_available", "passed": True, "detail": "Informe de calidad de datos disponible."})
        if post_market:
            checks.append({"name": "post_market_review_available", "passed": True, "detail": "Post-market review disponible."})
        if walk_forward:
            checks.append({"name": "walk_forward_validation_available", "passed": True, "detail": "Walk-forward disponible."})
        if session_retrospective:
            checks.append({"name": "session_retrospective_available", "passed": True, "detail": "Retrospectiva disponible."})
        objective_signal = bool(daily or operational or pre_earnings or market_quality or post_market or summary.get("observations") or duplicate_ratio)
        status = "READY_TO_APPLY" if objective_signal and (walk_forward or session_retrospective) else ("PASSED" if objective_signal else "PENDING")
        summary_text = (
            f"La propuesta {proposal_type} dispone de evidencia operativa suficiente para revision."
            if objective_signal
            else "No hay evidencia objetiva suficiente para esta propuesta."
        )
        return checks, status, summary_text

    def _default_required_validations(self, proposal_type: str) -> list[str]:
        mapping = {
            "CODE_CHANGE": ["tests"],
            "DATA_QUALITY_CHANGE": ["tests", "data_quality_review"],
            "PROMPT_CHANGE": ["tests", "shadow_review"],
            "RISK_RULE_CHANGE": list(self.CHAMPION_CHALLENGER_REQUIRED),
            "PARAMETER_CHANGE": list(self.CHAMPION_CHALLENGER_REQUIRED),
            "STRATEGY_RULE_CHANGE": list(self.CHAMPION_CHALLENGER_REQUIRED),
        }
        return list(mapping.get(proposal_type, []))

    def _normalize_required_validations(self, values: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for item in values or []:
            text = str(item or "").strip().lower()
            if not text:
                continue
            canonical = self.CANONICAL_VALIDATION_ALIASES.get(text, text)
            if canonical not in normalized:
                normalized.append(canonical)
        return normalized


class ReportAgent:
    def build(
        self,
        *,
        cycle_id: str,
        context: dict[str, Any],
        evaluation: dict[str, Any],
        event_batch: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
        validations: list[dict[str, Any]],
        initiatives: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        by_agent: dict[str, int] = {}
        for task in tasks:
            by_agent[task["agent_name"]] = by_agent.get(task["agent_name"], 0) + 1
        decision_counts: dict[str, int] = {}
        backlog_buckets: dict[str, int] = {}
        validations_by_proposal: dict[str, dict[str, Any]] = {}
        for validation in validations:
            proposal_id = str(validation.get("proposal_id") or "")
            if proposal_id and proposal_id not in validations_by_proposal:
                validations_by_proposal[proposal_id] = validation
        initiative_by_proposal: dict[str, dict[str, Any]] = {}
        for initiative in initiatives or []:
            decision = initiative.get("latest_decision") or {}
            decision_name = str(decision.get("decision") or initiative.get("status") or "UNKNOWN")
            decision_counts[decision_name] = decision_counts.get(decision_name, 0) + 1
            bucket = str(decision.get("backlog_bucket") or "UNKNOWN")
            backlog_buckets[bucket] = backlog_buckets.get(bucket, 0) + 1
            for proposal_id in initiative.get("linked_proposal_ids") or []:
                initiative_by_proposal[str(proposal_id)] = initiative
        promotion_counts: dict[str, int] = {}
        challengers: list[dict[str, Any]] = []
        current_champion = None
        for proposal in proposals:
            payload = proposal.get("payload") or {}
            promotion_state = str(payload.get("promotion_state") or "").lower() or "unclassified"
            promotion_counts[promotion_state] = promotion_counts.get(promotion_state, 0) + 1
            if promotion_state == "champion" and current_champion is None:
                current_champion = {
                    "proposal_id": proposal.get("proposal_id"),
                    "target_component": proposal.get("target_component"),
                    "status": proposal.get("status"),
                }
            if promotion_state in {"challenger", "shadow", "micro_experiment"}:
                validation = validations_by_proposal.get(str(proposal.get("proposal_id") or ""))
                validation_payload = (validation or {}).get("payload") or {}
                failed_checks = [
                    item.get("name")
                    for item in validation_payload.get("checks", []) or []
                    if item.get("passed") is False and item.get("name")
                ]
                initiative = initiative_by_proposal.get(str(proposal.get("proposal_id") or ""))
                latest_decision = (initiative or {}).get("latest_decision") or {}
                challengers.append(
                    {
                        "proposal_id": proposal.get("proposal_id"),
                        "target_component": proposal.get("target_component"),
                        "promotion_state": promotion_state,
                        "status": proposal.get("status"),
                        "required_validations": payload.get("required_validations", []),
                        "evaluation_window_frozen": bool(payload.get("evaluation_window_frozen")),
                        "latest_validation_status": (validation or {}).get("status"),
                        "latest_objective_status": validation_payload.get("objective_status"),
                        "blocking_checks": failed_checks,
                        "committee_decision": latest_decision.get("decision"),
                        "committee_bucket": latest_decision.get("backlog_bucket"),
                        "next_action": (initiative or {}).get("next_action"),
                        "next_review_at": payload.get("next_review_at"),
                    }
                )
        return {
            "cycle_id": cycle_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "real_data": {
                "database": context.get("database", {}),
                "summary": evaluation.get("summary", {}),
            },
            "events": event_batch,
            "tasks": tasks,
            "hypotheses": hypotheses,
            "proposals": proposals,
            "validations": validations,
            "initiatives": initiatives or [],
            "pending": [
                item
                for item in proposals
                if item.get("status") in {"PENDING", "REQUIRES_HUMAN_REVIEW", "WAITING_HUMAN_REVIEW"}
            ],
            "governance": {
                "decision_counts": decision_counts,
                "backlog_buckets": backlog_buckets,
                "champion_challenger": {
                    "current_champion": current_champion,
                    "promotion_counts": promotion_counts,
                    "challengers": challengers[:10],
                },
                "actionable_initiatives": [
                    item
                    for item in initiatives or []
                    if (item.get("latest_decision") or {}).get("backlog_bucket") in {"NOW", "HUMAN"}
                ],
            },
            "agent_summary": by_agent,
        }


SPECIALIST_AGENT_CLASSES: dict[AgentName, type[SpecialistAgent]] = {
    AgentName.MARKET: MarketEstimatorAgent,
    AgentName.MARKET_REGIME: MarketRegimeAgent,
    AgentName.TECHNICAL: TechnicalAnalystAgent,
    AgentName.TECHNICAL_EDGE: TechnicalEdgeAgent,
    AgentName.SENTIMENT: SentimentAnalystAgent,
    AgentName.STRATEGY: StrategyEvaluatorAgent,
    AgentName.PARAMETER_CALIBRATION: ParameterCalibrationAgent,
    AgentName.PRE_EARNINGS: PreEarningsSpecialistAgent,
    AgentName.PROGRAMMER: ProgrammerAgent,
    AgentName.RISK_CAPITAL: RiskCapitalAgent,
    AgentName.DATA_QUALITY: DataQualityAgent,
    AgentName.SOFTWARE_RELIABILITY: SoftwareReliabilityAgent,
    AgentName.EXPERIMENT_DESIGNER: ExperimentDesignerAgent,
    AgentName.DECISION_COMMITTEE: DecisionCommitteeAgent,
}
