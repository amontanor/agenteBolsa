import json

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot, TradeRecommendation
from agente_bolsa.tools.trade_decision import build_order_plans


def test_build_order_plans_blocks_buys_when_research_is_not_ready(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latest_research_evidence.json").write_text(
        json.dumps(
            {
                "as_of": "2026-06-15T12:00:00+00:00",
                "summary": {
                    "required": True,
                    "decision_ready": False,
                    "symbols_missing_fresh_evidence": ["AAPL"],
                    "symbols_low_reliability": [],
                },
            }
        ),
        encoding="utf-8",
    )
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
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        target_exposure_pct=0.05,
    )
    rejected = []

    plans = build_order_plans(settings, portfolio, [recommendation], rejected=rejected)

    assert plans == []
    assert rejected[0]["stage"] == "research_guard"
    assert rejected[0]["reason"] == "research_evidence_missing_or_stale"
