"""§3 (corregido): el research_guard se controla por el flag
`research_evidence_fail_closed_for_buys` (default True). Con el flag en False NO bloquea
de inmediato (sin depender del 'required' del ultimo reporte). Con True, bloquea si la
evidencia no esta lista. Para operar en paper sin feed de research, se pone el flag False.
"""
from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.tools.research_evidence import research_block_reason
from agente_bolsa.tools.trade_decision import _effective_research_block_reason

NOT_READY = {"summary": {"required": True, "decision_ready": False}}


def test_flag_false_does_not_block():
    settings = Settings(RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=False)
    # El diagnostico base sigue marcando el reason...
    assert research_block_reason(NOT_READY) == "research_evidence_not_ready"
    # ...pero con el flag en False no se bloquea.
    assert _effective_research_block_reason(settings, NOT_READY) is None


def test_flag_true_blocks_when_not_ready():
    settings = Settings(RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=True)
    assert _effective_research_block_reason(settings, NOT_READY) == "research_evidence_not_ready"


def test_no_context_no_block_even_with_flag_true():
    settings = Settings(RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=True)
    assert _effective_research_block_reason(settings, {}) is None
    assert _effective_research_block_reason(settings, None) is None
