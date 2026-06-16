"""Tests del motor determinista de oportunidades."""
from __future__ import annotations

from agente_bolsa.tools.opportunity_ranker import (
    OpportunityConfig,
    rank_opportunities,
    score_symbol,
)


def _snapshot():
    return {
        "as_of": "2026-06-15",
        "benchmark": "SPY",
        "symbols": {
            "SPY": {"close": 754.83, "return_20d": 0.0212, "sma_20": 745.8, "sma_50": 724.8,
                     "sma_200": 684.6, "volume_zscore_20": -0.5, "atr_14": 10.0,
                     "trend_positive": True, "above_long_trend": True},
            # Lider claro: fuerte RS, en tendencia, extension sana, volumen ok.
            "LEAD": {"close": 110.0, "return_20d": 0.12, "sma_20": 104.0, "sma_50": 98.0,
                      "sma_200": 90.0, "volume_zscore_20": 0.8, "atr_14": 2.0,
                      "trend_positive": True, "above_long_trend": True},
            # Sobre-extendido: buen retorno pero muy lejos de SMA20 -> penalizado.
            "EXT": {"close": 130.0, "return_20d": 0.15, "sma_20": 100.0, "sma_50": 95.0,
                     "sma_200": 90.0, "volume_zscore_20": 0.2, "atr_14": 3.0,
                     "trend_positive": True, "above_long_trend": True},
            # Debil: por debajo de SMA20 -> inelegible.
            "WEAK": {"close": 50.0, "return_20d": -0.05, "sma_20": 55.0, "sma_50": 58.0,
                      "sma_200": 60.0, "volume_zscore_20": -0.3, "atr_14": 1.5,
                      "trend_positive": False, "above_long_trend": False},
            # Volumen muy flojo -> inelegible.
            "NOVOL": {"close": 80.0, "return_20d": 0.08, "sma_20": 78.0, "sma_50": 76.0,
                       "sma_200": 70.0, "volume_zscore_20": -2.5, "atr_14": 2.0,
                       "trend_positive": True, "above_long_trend": True},
            # ETF de sector -> excluido por defecto.
            "XLK": {"close": 200.0, "return_20d": 0.09, "sma_20": 190.0, "sma_50": 185.0,
                     "sma_200": 170.0, "volume_zscore_20": 0.1, "atr_14": 4.0,
                     "trend_positive": True, "above_long_trend": True},
        },
    }


def test_lead_beats_overextended():
    result = rank_opportunities(_snapshot(), top_n=10)
    syms = [o["symbol"] for o in result["opportunities"]]
    assert "LEAD" in syms
    assert syms.index("LEAD") < syms.index("EXT")  # el lider sano va antes que el sobre-extendido


def test_excludes_etfs_and_ineligibles():
    result = rank_opportunities(_snapshot(), top_n=10)
    syms = [o["symbol"] for o in result["opportunities"]]
    assert "XLK" not in syms          # ETF excluido
    assert "WEAK" not in syms         # bajo SMA20
    assert "NOVOL" not in syms        # volumen muy flojo
    assert "SPY" not in syms          # benchmark no se autocompite


def test_extension_penalty_applied():
    snap = _snapshot()
    ext = score_symbol("EXT", snap["symbols"]["EXT"], 0.0212)
    assert ext.components["extension_penalty"] < 0  # hay penalizacion
    assert "sobre-extension" in ext.reason


def test_suggested_stop_from_atr():
    snap = _snapshot()
    lead = score_symbol("LEAD", snap["symbols"]["LEAD"], 0.0212, OpportunityConfig(atr_stop_multiple=2.0))
    assert lead.suggested_stop == round(110.0 - 2.0 * 2.0, 4)
    assert lead.suggested_stop_pct is not None and lead.suggested_stop_pct > 0


def test_relative_strength_sign():
    snap = _snapshot()
    lead = score_symbol("LEAD", snap["symbols"]["LEAD"], 0.0212)
    # ret20d 0.12 vs benchmark 0.0212 -> RS positivo
    assert lead.metrics["relative_return_20d"] > 0
    assert lead.eligible is True


def test_require_uptrend_200_filters():
    snap = _snapshot()
    # Forzamos un simbolo por debajo de SMA200 con config estricta.
    snap["symbols"]["BELOW200"] = {
        "close": 100.0, "return_20d": 0.10, "sma_20": 98.0, "sma_50": 99.0,
        "sma_200": 110.0, "volume_zscore_20": 0.5, "atr_14": 2.0,
        "trend_positive": True, "above_long_trend": False,
    }
    strict = OpportunityConfig(require_uptrend_200=True)
    s = score_symbol("BELOW200", snap["symbols"]["BELOW200"], 0.0212, strict)
    assert s.eligible is False
    assert s.exclusion_reason == "bajo_sma200"


def test_prioritize_candidates_orders_by_opportunity():
    from agente_bolsa.tools.opportunity_ranker import prioritize_candidates

    cands = [
        {"symbol": "LAG", "score": 99, "technical_state": {
            "close": 100, "return_20d": 0.01, "sma_20": 99, "sma_50": 98,
            "sma_200": 95, "volume_zscore_20": 0.0, "atr_14": 2}},
        {"symbol": "LEAD", "score": 10, "technical_state": {
            "close": 110, "return_20d": 0.22, "sma_20": 104, "sma_50": 98,
            "sma_200": 90, "volume_zscore_20": 0.5, "atr_14": 2}},
    ]
    out = prioritize_candidates(cands, benchmark_return_20d=0.02)
    assert [c["symbol"] for c in out] == ["LEAD", "LAG"]
    assert out[0]["opportunity_score"] > out[1]["opportunity_score"]
    # conserva campos originales
    assert out[0]["score"] == 10
