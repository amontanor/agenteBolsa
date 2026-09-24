"""Human-readable agent names used in logs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentInfo:
    code: str
    title: str
    lane: str


AGENTS: dict[str, AgentInfo] = {
    "orchestrator": AgentInfo("ORCH", "Orquestador", "control"),
    "compliance_guardian": AgentInfo("GUARD", "Seguridad", "control"),
    "market_data_researcher": AgentInfo("DATA", "Datos mercado", "research"),
    "macro_news_researcher": AgentInfo("MACRO", "Macro/noticias", "research"),
    "web_research_agent": AgentInfo("WEB", "Web research", "research"),
    "source_reliability_agent": AgentInfo("SRC", "Fuentes", "research"),
    "fundamental_filings_agent": AgentInfo("FILE", "Filings", "research"),
    "macro_calendar_agent": AgentInfo("MCAL", "Calendario macro", "research"),
    "technical_analyst": AgentInfo("TECH", "Analisis tecnico", "research"),
    "market_regime_strategist": AgentInfo("REGIME", "Regimen", "research"),
    "opportunity_scout": AgentInfo("SCOUT", "Oportunidades", "research"),
    "fundamental_analyst": AgentInfo("FUND", "Fundamental", "research"),
    "hypothesis_generator": AgentInfo("HYP", "Hipotesis", "research"),
    "quant_backtester": AgentInfo("BT", "Backtest", "validation"),
    "parameter_calibration_specialist": AgentInfo("CAL", "Calibracion", "validation"),
    "risk_manager": AgentInfo("RISK", "Riesgo", "validation"),
    "decision_committee": AgentInfo("COMMIT", "Comite", "validation"),
    "portfolio_manager": AgentInfo("PORT", "Cartera", "execution"),
    "execution_agent": AgentInfo("EXEC", "Ejecucion", "execution"),
    "post_market_review_agent": AgentInfo("REVIEW", "Revision cierre", "learning"),
    "post_trade_analyst": AgentInfo("POST", "Post-mortem", "learning"),
    "lesson_curator_agent": AgentInfo("LESSON", "Curator lecciones", "learning"),
    "self_improvement_engineer": AgentInfo("IMPR", "Mejora", "learning"),
}

# AgentName belongs to the historical continuous-improvement contract and uses
# CamelCase values. Keep the old values stable; only map names whose modern
# counterpart is demonstrated by the same responsibility. ``None`` is
# intentional: an unmapped legacy identity must not be guessed or collapsed.
LEGACY_AGENT_NAME_CROSSWALK: dict[str, str | None] = {
    "OrchestratorAgent": "orchestrator",
    "ChiefInvestmentOrchestratorAgent": None,
    "MarketEstimatorAgent": None,
    "MarketRegimeAgent": "market_regime_strategist",
    "TechnicalAnalystAgent": "technical_analyst",
    "TechnicalEdgeAgent": None,
    "SentimentAnalystAgent": None,
    "StrategyEvaluatorAgent": None,
    "ParameterCalibrationAgent": "parameter_calibration_specialist",
    "PreEarningsSpecialistAgent": None,
    "RiskGuardAgent": None,
    "RiskCapitalAgent": None,
    "DataQualityAgent": None,
    "ProgrammerAgent": None,
    "SoftwareReliabilityAgent": None,
    "ExperimentDesignerAgent": None,
    "DecisionCommitteeAgent": "decision_committee",
    "ValidationAgent": None,
    "ReportAgent": None,
}


def canonical_agent_id(value: object) -> str | None:
    """Return a modern registry ID without rewriting unknown history."""

    raw = getattr(value, "value", value)
    name = str(raw or "").strip()
    if name in AGENTS:
        return name
    return LEGACY_AGENT_NAME_CROSSWALK.get(name)


def agent_info(agent: str) -> AgentInfo:
    return AGENTS.get(agent, AgentInfo("AGNT", agent.replace("_", " "), "unknown"))
