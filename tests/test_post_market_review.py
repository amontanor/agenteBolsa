from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.main import _post_market_review_text
from agente_bolsa.tools.post_market_review import _learning_candidates


def test_learning_candidates_use_day_pl_not_global_history():
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

    suggestions = _learning_candidates(
        evaluations=[],
        day_summary={"realized_pl": 10.0, "open_unrealized_pl": 5.0},
        portfolio=portfolio,
    )

    assert all("P/L realizado -" not in item["reason"] for item in suggestions)


def test_post_market_review_text_explains_actions_and_learning():
    text = _post_market_review_text(
        {
            "session_date": "2026-04-27",
            "path": "data\\reports\\post_market_review.json",
            "summary": {
                "trades_evaluated": 2,
                "buys": 1,
                "sells": 1,
                "open_positions": 1,
                "day_buy_notional": 1000.0,
                "day_sell_notional": 500.0,
                "day_realized_pl": 12.5,
                "day_realized_plpc": 0.025,
                "open_unrealized_pl": -3.0,
            },
            "trade_evaluations": [
                {
                    "side": "buy",
                    "symbol": "AAPL",
                    "notional": 1000.0,
                    "price": 200.0,
                    "stop_loss": 190.0,
                    "take_profit": 220.0,
                    "open_pl": -3.0,
                    "verdict": "neutro_de_momento",
                    "issue": None,
                }
            ],
            "proposed_improvements": [
                {
                    "id": "limit_daily_entries",
                    "priority": "high",
                    "proposal": "Limitar entradas.",
                    "reason": "Demasiadas posiciones.",
                    "suggested_config": {"MAX_ORDERS_PER_CYCLE": 2},
                }
            ],
            "next_session_guidance": ["Mantener hasta stop/take."],
            "llm_review": {"assessment": "Sesion razonable."},
        }
    )

    assert "REVISION POST-MERCADO 2026-04-27" in text
    assert "trades=2" in text
    assert "Aplicacion: no cambia codigo" in text
    assert "Mejoras propuestas:" in text
    assert "Guia para la proxima sesion:" in text
