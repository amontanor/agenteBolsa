from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot, TradeRecommendation
from agente_bolsa.tools.trade_decision import (
    _floor_qty,
    _recommendation_from_dict,
    build_order_plans,
    validate_entry_quality,
)


def test_recommendation_normalizes_percent_exposure_to_fraction():
    recommendation = _recommendation_from_dict(
        {
            "symbol": "AAPL",
            "action": "buy",
            "confidence": 0.8,
            "reason": "test",
            "entry_price": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "target_exposure_pct": 5.0,
        }
    )

    assert recommendation is not None
    assert recommendation.target_exposure_pct == 0.05


def test_floor_qty_never_rounds_fractional_position_up():
    assert _floor_qty(13.600098938) == 13.600098938
    assert _floor_qty(13.6000989389) == 13.600098938


def test_recommendation_keeps_fractional_exposure():
    recommendation = _recommendation_from_dict(
        {
            "symbol": "AAPL",
            "action": "buy",
            "confidence": 0.8,
            "reason": "test",
            "target_exposure_pct": 0.03,
        }
    )

    assert recommendation is not None
    assert recommendation.target_exposure_pct == 0.03


def test_build_order_plans_uses_whole_share_qty_for_bracket_buys():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=333.0,
        stop_loss=300.0,
        take_profit=382.5,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(USE_BRACKET_ORDERS=True), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].qty == 3.0
    assert plans[0].notional == 999.0
    assert plans[0].risk_decision.checks["execution_sizing"]["execution_sizing"] == "whole_share_bracket"


def test_build_order_plans_skips_bracket_buy_if_whole_share_too_expensive():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="EXP",
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=2_000.0,
        stop_loss=1_900.0,
        take_profit=2_150.0,
        target_exposure_pct=0.05,
    )

    plans = build_order_plans(Settings(USE_BRACKET_ORDERS=True), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_can_exit_existing_long_position():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AAPL",
                qty=10,
                market_value=1000,
                avg_entry_price=90,
                current_price=100,
                unrealized_pl=100,
                unrealized_plpc=0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AAPL",
        action="exit",
        confidence=0.9,
        reason="Stop loss tocado: soporte perdido.",
        stop_loss=105.0,
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].side == "sell"
    assert plans[0].qty == 10
    assert plans[0].risk_decision.approved


def test_build_order_plans_blocks_plain_rotation_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=10,
                market_value=1000,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.9,
        reason="Rotacion: AMZN tiene menor score que PWR.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_allows_exceptional_bearish_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=10,
                market_value=900,
                avg_entry_price=100,
                current_price=90,
                unrealized_pl=-100,
                unrealized_plpc=-0.1,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.95,
        reason="Deterioro bajista claro: soporte perdido y drawdown severo.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].side == "sell"


def test_build_order_plans_blocks_ordinary_llm_exit_even_with_small_drawdown():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="PWR",
                qty=10,
                market_value=997,
                avg_entry_price=100,
                current_price=99.7,
                unrealized_pl=-3,
                unrealized_plpc=-0.003,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="PWR",
        action="exit",
        confidence=0.95,
        reason="Posicion sin score tecnico valido y en drawdown. Liberar capital para oportunidades de alta calidad.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert plans == []


def test_build_order_plans_allows_material_negative_news_exit():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="XYZ",
                qty=10,
                market_value=1000,
                avg_entry_price=100,
                current_price=100,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="XYZ",
        action="exit",
        confidence=0.96,
        reason="Noticia negativa material: regulatory investigation and fraud risk.",
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].risk_decision.checks["exit_policy"]["trigger"] == "material_negative_event"


def test_build_order_plans_does_not_round_sell_qty_above_available():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=10_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[
            PositionSnapshot(
                symbol="AMZN",
                qty=13.600098938,
                market_value=3571.0,
                avg_entry_price=262.79,
                current_price=262.54,
                unrealized_pl=0,
                unrealized_plpc=0,
            )
        ],
        open_orders=[],
    )
    recommendation = TradeRecommendation(
        symbol="AMZN",
        action="exit",
        confidence=0.9,
        reason="Stop loss tocado.",
        stop_loss=263.0,
    )

    plans = build_order_plans(Settings(), portfolio, [recommendation])

    assert len(plans) == 1
    assert plans[0].qty == 13.600098938
    assert plans[0].qty <= portfolio.positions[0].qty


def _quality_recommendation(symbol="AAPL"):
    return TradeRecommendation(
        symbol=symbol,
        action="buy",
        confidence=0.9,
        reason="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        target_exposure_pct=0.05,
    )


def _quality_context(**overrides):
    candidate = {
        "symbol": "AAPL",
        "direction": "long",
        "score": 14,
        "setup_quality": "strong",
        "technical_state": {
            "close": 100.0,
            "return_20d": 0.08,
            "sma_20": 95.0,
            "rsi_14": 72.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.5,
            "chart_patterns": [
                {"bias": "bullish", "status": "confirmed", "label": "doble suelo"},
            ],
        },
    }
    candidate.update(overrides)
    return {"top_longs": [candidate], "top_shorts": []}


def test_entry_quality_gate_approves_clean_strong_setup():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        _quality_context(),
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["score"] == 14


def test_entry_quality_gate_blocks_missing_technical_candidate():
    approved, reason, _checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        {"top_longs": [], "top_shorts": []},
        {"results": []},
    )

    assert approved is False
    assert "ausente" in reason


def test_entry_quality_gate_blocks_overextended_sma20_distance():
    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_MAX_SMA20_DISTANCE=0.12),
        _quality_recommendation(),
        _quality_context(
            technical_state={
                "close": 120.0,
                "return_20d": 0.2,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.0,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            }
        ),
        {"results": []},
    )

    assert approved is False
    assert "extendido" in reason
    assert checks["sma20_distance"] == 0.2


def test_entry_quality_gate_blocks_extended_entry_without_relative_strength():
    approved, reason, _checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        _quality_context(
            technical_state={
                "close": 109.0,
                "return_20d": 0.2,
                "sma_20": 100.0,
                "rsi_14": 78.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.5,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            }
        ),
        {"results": []},
    )

    assert approved is False
    assert "fuerza relativa" in reason


def test_entry_quality_gate_allows_extended_entry_with_confirmations():
    context = _quality_context(
        relative_return_20d=0.04,
        technical_state={
            "close": 109.0,
            "return_20d": 0.2,
            "sma_20": 100.0,
            "rsi_14": 78.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 0.8,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
        },
    )

    approved, reason, checks = validate_entry_quality(
        Settings(ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE=0.08),
        _quality_recommendation(),
        context,
        {"results": []},
    )

    assert approved is True
    assert reason == "entry-quality aprobado"
    assert checks["extended_entry_filter"]["min_relative_return_20d"] == 0.02


def test_entry_quality_gate_blocks_negative_confirmed_sentiment():
    approved, reason, checks = validate_entry_quality(
        Settings(),
        _quality_recommendation(),
        _quality_context(),
        {
            "results": [
                {
                    "symbol": "AAPL",
                    "sentiment": {"sentiment_score": -0.8, "confidence": 0.7},
                }
            ]
        },
    )

    assert approved is False
    assert "sentimiento negativo" in reason
    assert checks["sentiment_score"] == -0.8
