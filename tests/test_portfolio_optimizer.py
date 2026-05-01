from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, PositionSnapshot
from agente_bolsa.tools.portfolio_optimizer import build_portfolio_rebalance_context


def test_rebalance_context_compares_positions_and_candidates():
    portfolio = PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=5_000,
        portfolio_value=20_000,
        buying_power=10_000,
        positions=[
            PositionSnapshot(
                symbol="OLD",
                qty=10,
                market_value=1_000,
                avg_entry_price=110,
                current_price=100,
                unrealized_pl=-100,
                unrealized_plpc=-0.10,
            )
        ],
        open_orders=[],
    )
    technical = {
        "top_longs": [
            {
                "symbol": "NEW",
                "direction": "long",
                "score": 9,
                "setup_quality": "strong",
                "reasons": ["momentum positivo"],
                "technical_state": {"close": 50, "rsi_14": 60, "atr_14": 2},
                "risk_plan": {"entry_price": 50, "stop_loss": 46, "take_profit": 56},
            }
        ],
        "top_shorts": [],
    }

    context = build_portfolio_rebalance_context(Settings(), portfolio, technical, {"results": []})

    assert context["positions"][0]["symbol"] == "OLD"
    assert context["positions"][0]["drawdown_from_entry"] == -0.1
    assert context["candidate_buys"][0]["symbol"] == "NEW"
    assert context["rotation_candidates"][0]["from_symbol"] == "OLD"
    assert context["rotation_candidates"][0]["to_symbol"] == "NEW"
    assert context["rotation_candidates"][0]["score_delta"] == 9
