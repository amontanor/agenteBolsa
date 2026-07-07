"""§2: en paper, el plan no bloquea en duro el PARTIAL por falta de macro/news.

La revision determinista ya trata ese PARTIAL como micro-experimento; bloquearlo en
`build_buy_order_plans` era incoherente y dejaba el sistema en 0 trades. Se mantiene el
bloqueo para INSUFFICIENT (integridad) y en modo live.
"""
from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.tools.trade_decision import (
    _effective_market_state_block_reason,
    _fallback_market_state_block_reason,
)

PARTIAL_MACRO = {"data_quality": {"status": "PARTIAL", "notes": ["missing macro/news feed"]}}
INSUFFICIENT = {"data_quality": {"status": "INSUFFICIENT"}}


def test_paper_relaxes_partial_missing_macro(tmp_path):
    paper = Settings(DATA_DIR=tmp_path, TRADING_MODE="paper")
    # El diagnostico base no cambia: el reason sigue existiendo.
    assert (
        _fallback_market_state_block_reason(PARTIAL_MACRO)
        == "market_state_partial_missing_macro_or_news"
    )
    # Pero en paper el plan NO lo bloquea (lo deja pasar como micro).
    assert _effective_market_state_block_reason(paper, PARTIAL_MACRO) is None


def test_live_keeps_partial_block(tmp_path):
    live = Settings(DATA_DIR=tmp_path, TRADING_MODE="live")
    assert (
        _effective_market_state_block_reason(live, PARTIAL_MACRO)
        == "market_state_partial_missing_macro_or_news"
    )


def test_insufficient_always_blocks_even_in_paper(tmp_path):
    paper = Settings(DATA_DIR=tmp_path, TRADING_MODE="paper")
    assert (
        _effective_market_state_block_reason(paper, INSUFFICIENT)
        == "market_state_data_quality_insufficient"
    )
