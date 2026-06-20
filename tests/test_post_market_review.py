from agente_bolsa.main import _post_market_review_text
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.tools.post_market_review import _learning_candidates, _mandatory_market_review


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


def test_mandatory_market_review_classifies_data_and_criteria_failures():
    review = _mandatory_market_review(
        {
            "session_date": "2026-06-12",
            "summary": {"trades_evaluated": 1, "buys": 1, "sells": 0, "day_realized_pl": 0.0, "open_unrealized_pl": -5.0},
            "trade_evaluations": [
                {
                    "symbol": "FRT",
                    "side": "buy",
                    "open_pl": -5.0,
                    "verdict": "debil_de_momento",
                    "issue": "Entrada debil.",
                }
            ],
            "signal_update": {"updated": 0},
            "daily_learning": {
                "digest": {
                    "same_session_opportunity_ledger": {
                        "summary": {"candidates": 2, "non_executed": 1},
                        "top_non_executed": [
                            {
                                "symbol": "AAPL",
                                "same_session_return": 0.04,
                                "reason_not_executed": "market_state_guard: partial",
                            }
                        ],
                    }
                }
            },
            "operational_learning": {
                "traceability_audit": {"complete": False, "issue_counts": {"missing_signal_context": 1}},
                "broker_memory_reconciliation": {"complete": False, "issue_counts": {"duplicate_fills": 1}},
            },
        }
    )

    assert review["required"] is True
    assert review["recommendations_reviewed"]["non_executed_candidates"] == 1
    assert {item["kind"] for item in review["what_failed_due_to_data"]} == {
        "trade_memory_traceability",
        "broker_memory_reconciliation",
        "signal_outcomes_not_updated",
    }
    assert {item["kind"] for item in review["what_failed_due_to_criteria"]} == {
        "weak_executed_trades",
        "positive_non_executed_opportunities",
    }
