"""§3: en paper, el research_guard (evidencia no-lista/obsoleta) no bloquea el plan.

Es un gate de contexto externo (frescura de research), no de integridad ni de calidad
del trade. Sin §3, en cuanto §2 relaja market_state, este gate volvía a dejar 0 trades
(el fichero real tenía required=True, decision_ready=False). Se mantiene en live.
"""
from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.tools.research_evidence import research_block_reason
from agente_bolsa.tools.trade_decision import _effective_research_block_reason

NOT_READY = {"summary": {"required": True, "decision_ready": False}}


def test_paper_relaxes_research_not_ready():
    paper = Settings(TRADING_MODE="paper")
    # El diagnostico base no cambia.
    assert research_block_reason(NOT_READY) == "research_evidence_not_ready"
    # Pero en paper no bloquea.
    assert _effective_research_block_reason(paper, NOT_READY) is None


def test_live_keeps_research_block():
    live = Settings(TRADING_MODE="live")
    assert _effective_research_block_reason(live, NOT_READY) == "research_evidence_not_ready"


def test_no_context_no_block():
    paper = Settings(TRADING_MODE="paper")
    assert _effective_research_block_reason(paper, {}) is None
    assert _effective_research_block_reason(paper, None) is None
