"""P-L149 guarded: veto to toxic extremes + quota for sin_patron|strong."""

from agente_bolsa.config import Settings
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.tools.trade_decision import (
    augment_recommendations_with_deterministic_fallback,
    deterministic_trade_fallback_recommendations,
)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="paper",
        status="ACTIVE",
        currency="USD",
        cash=20_000,
        portfolio_value=20_000,
        buying_power=20_000,
        positions=[],
        open_orders=[],
    )


def _candidate(symbol, *, score, return_20d=0.08, selection_score=0.04,
               confirmed=False, rank=1):
    return {
        "symbol": symbol,
        "direction": "long",
        "score": score,
        "setup_quality": "strong",
        "relative_return_20d": 0.05,
        "selection_score": selection_score,
        "selection_rank": rank,
        "technical_state": {
            "close": 100.0,
            "return_20d": return_20d,
            "sma_20": 95.0,
            "rsi_14": 66.0,
            "macd": 2.0,
            "macd_signal": 1.0,
            "volume_zscore_20": 1.2,
            "chart_patterns": [{"bias": "bullish", "status": "confirmed"}] if confirmed else [],
        },
        "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 115.0},
    }


def test_toxic_score_vetoed_with_report():
    context = {"selected_candidates": [_candidate("TOX", score=19)]}
    report: dict = {}

    recs = deterministic_trade_fallback_recommendations(
        Settings(), _portfolio(), context, selection_report=report
    )

    assert recs == []
    assert report["toxic_veto_count"] == 1
    assert report["toxic_vetoed"] == [{"symbol": "TOX", "reason": "toxic_extreme_score"}]


def test_toxic_momentum_vetoed_with_report():
    context = {"selected_candidates": [_candidate("MOM", score=15, return_20d=0.25)]}
    report: dict = {}

    recs = deterministic_trade_fallback_recommendations(
        Settings(), _portfolio(), context, selection_report=report
    )

    assert recs == []
    assert report["toxic_vetoed"] == [{"symbol": "MOM", "reason": "toxic_extreme_momentum"}]


def test_veto_boundaries_pass():
    context = {
        "selected_candidates": [
            _candidate("OK", score=17, return_20d=0.199, selection_score=0.04, rank=1),
        ]
    }

    recs = deterministic_trade_fallback_recommendations(Settings(), _portfolio(), context)

    assert [rec.symbol for rec in recs] == ["OK"]


def test_veto_disabled_restores_legacy():
    context = {"selected_candidates": [_candidate("TOX", score=19)]}

    recs = deterministic_trade_fallback_recommendations(
        Settings(TOXIC_VETO_ENABLED=False), _portfolio(), context
    )

    assert [rec.symbol for rec in recs] == ["TOX"]


def test_quota_pulls_best_sin_patron_into_limit():
    context = {
        "selected_candidates": [
            _candidate("CONF1", score=16, selection_score=0.10, rank=1, confirmed=True),
            _candidate("CONF2", score=15, selection_score=0.09, rank=2, confirmed=True),
            _candidate("EDGE", score=14, selection_score=0.01, rank=3),
        ]
    }
    report: dict = {}

    recs = deterministic_trade_fallback_recommendations(
        Settings(), _portfolio(), context, limit=2, selection_report=report
    )

    symbols = [rec.symbol for rec in recs]
    assert symbols == ["CONF1", "EDGE"]
    assert "Cuota sin_patron|strong (guarded P-L149)." in recs[1].reason
    assert report["quota"]["quota_filled"] == ["EDGE"]
    assert report["quota"]["quota_dropped"] == ["CONF2"]


def test_quota_inert_when_already_present():
    context = {
        "selected_candidates": [
            _candidate("EDGE", score=16, selection_score=0.10, rank=1),
            _candidate("CONF1", score=15, selection_score=0.09, rank=2, confirmed=True),
        ]
    }
    report: dict = {}

    recs = deterministic_trade_fallback_recommendations(
        Settings(), _portfolio(), context, limit=2, selection_report=report
    )

    assert [rec.symbol for rec in recs] == ["EDGE", "CONF1"]
    assert report["quota"]["quota_inert_reason"] == "already_present"
    assert all("Cuota sin_patron" not in rec.reason for rec in recs)


def test_quota_inert_without_candidate():
    context = {
        "selected_candidates": [
            _candidate("CONF1", score=16, selection_score=0.10, rank=1, confirmed=True),
        ]
    }
    report: dict = {}

    recs = deterministic_trade_fallback_recommendations(
        Settings(), _portfolio(), context, limit=2, selection_report=report
    )

    assert [rec.symbol for rec in recs] == ["CONF1"]
    assert report["quota"]["quota_inert_reason"] == "no_quota_candidate"


def test_augment_metadata_carries_guard_counts():
    context = {
        "selected_candidates": [
            _candidate("TOX", score=19),
            _candidate("EDGE", score=14, selection_score=0.01, rank=3),
            _candidate("CONF1", score=16, selection_score=0.10, rank=1, confirmed=True),
            _candidate("CONF2", score=15, selection_score=0.09, rank=2, confirmed=True),
        ]
    }

    merged, metadata = augment_recommendations_with_deterministic_fallback(
        Settings(), _portfolio(), context, [], limit=2
    )

    assert metadata["toxic_veto_count"] == 1
    assert metadata["toxic_vetoed"] == [{"symbol": "TOX", "reason": "toxic_extreme_score"}]
    assert metadata["sin_patron_quota"]["quota_filled"] == ["EDGE"]
    assert "EDGE" in metadata["added"]
