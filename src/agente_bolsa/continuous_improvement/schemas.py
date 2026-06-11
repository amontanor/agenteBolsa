"""Typed contracts for continuous improvement cycles."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CycleStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COLLECTING_DATA = "COLLECTING_DATA"
    CALLING_LLM = "CALLING_LLM"
    EVALUATING_LLM_OUTPUT = "EVALUATING_LLM_OUTPUT"
    GENERATING_PROPOSALS = "GENERATING_PROPOSALS"
    VALIDATING = "VALIDATING"
    WAITING_HUMAN_REVIEW = "WAITING_HUMAN_REVIEW"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    VALIDATING = "VALIDATING"
    WAITING_HUMAN_REVIEW = "WAITING_HUMAN_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HypothesisStatus(str, Enum):
    OPEN = "OPEN"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class RuntimeStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class InitiativeStatus(str, Enum):
    OPEN = "OPEN"
    ANALYZING = "ANALYZING"
    EXPERIMENTING = "EXPERIMENTING"
    VALIDATING = "VALIDATING"
    WAITING_REVIEW = "WAITING_REVIEW"
    READY_TO_APPLY = "READY_TO_APPLY"
    MONITORING = "MONITORING"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class AgentName(str, Enum):
    ORCHESTRATOR = "OrchestratorAgent"
    CHIEF_ORCHESTRATOR = "ChiefInvestmentOrchestratorAgent"
    MARKET = "MarketEstimatorAgent"
    MARKET_REGIME = "MarketRegimeAgent"
    TECHNICAL = "TechnicalAnalystAgent"
    TECHNICAL_EDGE = "TechnicalEdgeAgent"
    SENTIMENT = "SentimentAnalystAgent"
    STRATEGY = "StrategyEvaluatorAgent"
    PARAMETER_CALIBRATION = "ParameterCalibrationAgent"
    PRE_EARNINGS = "PreEarningsSpecialistAgent"
    RISK = "RiskGuardAgent"
    RISK_CAPITAL = "RiskCapitalAgent"
    DATA_QUALITY = "DataQualityAgent"
    PROGRAMMER = "ProgrammerAgent"
    SOFTWARE_RELIABILITY = "SoftwareReliabilityAgent"
    EXPERIMENT_DESIGNER = "ExperimentDesignerAgent"
    DECISION_COMMITTEE = "DecisionCommitteeAgent"
    VALIDATION = "ValidationAgent"
    REPORT = "ReportAgent"


class Diagnosis(BaseModel):
    summary: str = ""
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    data_quality: Literal["INSUFFICIENT", "PARTIAL", "GOOD"] = "INSUFFICIENT"


class DetectedIssue(BaseModel):
    issue_id: str
    component: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"


class SpecialistHypothesis(BaseModel):
    subject: str
    summary: str
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    evidence: list[str] = Field(default_factory=list)


class SpecialistAction(BaseModel):
    action_type: Literal["PROPOSAL", "VALIDATION", "MONITORING", "ESCALATION"] = "PROPOSAL"
    title: str
    rationale: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    required_validations: list[str] = Field(default_factory=list)


class ImprovementProposalPayload(BaseModel):
    proposal_type: Literal[
        "PARAMETER_CHANGE",
        "PROMPT_CHANGE",
        "STRATEGY_RULE_CHANGE",
        "RISK_RULE_CHANGE",
        "CODE_CHANGE",
        "DATA_QUALITY_CHANGE",
        "MONITORING_CHANGE",
    ]
    target_component: str
    target_identifier: str = ""
    current_value: str = ""
    proposed_value: str = ""
    rationale: str = ""
    expected_impact: str = ""
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    required_validations: list[str] = Field(default_factory=list)
    rollback_plan: str = ""
    promotion_state: Literal["champion", "challenger", "shadow", "micro_experiment", "rejected", "retired"] = "shadow"
    evaluation_window_frozen: bool = False
    next_review_at: str = ""

    @field_validator("target_component", "target_identifier", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> str:
        return "" if value is None else str(value)


class SpecialistResponseBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    decision: Literal["APPROVE", "REJECT", "REWORK", "MONITOR", "ESCALATE"] | None = None
    decision_reason: str = ""
    deterministic_alignment: bool | None = None
    deterministic_decision: str = ""
    discrepancy_justification: str = ""
    initiative_status_target: str = ""
    proposal_status_targets: list[dict[str, Any]] = Field(default_factory=list)
    priority_adjustment: str = ""
    backlog_rank: int | None = None
    backlog_bucket: Literal["NOW", "NEXT", "LATER", "HUMAN"] | None = None
    required_follow_up: str = ""
    close_initiative: bool = False
    detected_issues: list[DetectedIssue] = Field(default_factory=list)
    hypotheses: list[SpecialistHypothesis] = Field(default_factory=list)
    actions: list[SpecialistAction] = Field(default_factory=list)
    proposals: list[ImprovementProposalPayload] = Field(default_factory=list)


class MarketEstimatorResponse(SpecialistResponseBase):
    pass


class TechnicalAnalystResponse(SpecialistResponseBase):
    pass


class SentimentAnalystResponse(SpecialistResponseBase):
    pass


class StrategyEvaluatorResponse(SpecialistResponseBase):
    pass


class ParameterCalibrationResponse(SpecialistResponseBase):
    pass


class ProgrammerAgentResponse(SpecialistResponseBase):
    pass


class LLMImprovementResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    diagnosis: Diagnosis
    detected_issues: list[DetectedIssue] = Field(default_factory=list)
    proposals: list[ImprovementProposalPayload] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)


class LLMJsonResult(BaseModel):
    ok: bool
    llm_call_id: str
    payload: Any | None = None
    raw_response: str | None = None
    error: str | None = None
    provider: str = ""
    model: str = ""
    base_url: str = ""
    fallback_used: bool = False
    prompt_tokens_estimate: int | None = None
    context_limit_tokens: int | None = None
    context_compacted: bool = False
    truncation_report: dict[str, Any] = Field(default_factory=dict)
    request_preview: dict[str, Any] = Field(default_factory=dict)


def llm_response_json_schema() -> dict[str, Any]:
    return LLMImprovementResponse.model_json_schema()


def specialist_response_json_schema(agent_name: AgentName) -> dict[str, Any]:
    model_map = {
        AgentName.MARKET: MarketEstimatorResponse,
        AgentName.TECHNICAL: TechnicalAnalystResponse,
        AgentName.SENTIMENT: SentimentAnalystResponse,
        AgentName.STRATEGY: StrategyEvaluatorResponse,
        AgentName.PARAMETER_CALIBRATION: ParameterCalibrationResponse,
        AgentName.PROGRAMMER: ProgrammerAgentResponse,
    }
    model = model_map.get(agent_name, SpecialistResponseBase)
    return model.model_json_schema()
