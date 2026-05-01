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
    "technical_analyst": AgentInfo("TECH", "Analisis tecnico", "research"),
    "fundamental_analyst": AgentInfo("FUND", "Fundamental", "research"),
    "hypothesis_generator": AgentInfo("HYP", "Hipotesis", "research"),
    "quant_backtester": AgentInfo("BT", "Backtest", "validation"),
    "risk_manager": AgentInfo("RISK", "Riesgo", "validation"),
    "portfolio_manager": AgentInfo("PORT", "Cartera", "execution"),
    "execution_agent": AgentInfo("EXEC", "Ejecucion", "execution"),
    "post_market_review_agent": AgentInfo("REVIEW", "Revision cierre", "learning"),
    "post_trade_analyst": AgentInfo("POST", "Post-mortem", "learning"),
    "self_improvement_engineer": AgentInfo("IMPR", "Mejora", "learning"),
}


def agent_info(agent: str) -> AgentInfo:
    return AGENTS.get(agent, AgentInfo("AGNT", agent.replace("_", " "), "unknown"))
