from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.tools import post_market_review


@pytest.mark.parametrize("implicit", [False, True])
def test_missing_portfolio_fails_before_consumers(monkeypatch, tmp_path, implicit):
    settings = Settings(_env_file=None, DATA_DIR=tmp_path / "data")
    calls = []

    def history(*args, **kwargs):
        calls.append("history")
        return {"trades": [], "days": []}

    monkeypatch.setattr(post_market_review, "build_trade_history", history)
    monkeypatch.setattr(
        post_market_review, "BrokerClientFactory",
        lambda *args: SimpleNamespace(alpaca_portfolio_snapshot=lambda: None),
    )
    kwargs = {} if implicit else {"portfolio_snapshot": None, "broker_client": None}
    with pytest.raises(RuntimeError, match="post_market_portfolio_unavailable"):
        post_market_review.build_post_market_review(
            settings, tmp_path / "reports", "missing", session_date="2026-10-06",
            use_llm=False, **kwargs,
        )
    assert calls == []
    assert not settings.database_path.exists()
    assert not list((tmp_path / "reports").glob("**/*"))


def test_present_empty_portfolio_reaches_history(monkeypatch, tmp_path):
    from agente_bolsa.models import PortfolioSnapshot

    portfolio = PortfolioSnapshot(
        account_id="paper", status="ACTIVE", currency="USD", cash=100,
        portfolio_value=100, buying_power=100, positions=[], open_orders=[],
    )
    settings = Settings(_env_file=None, DATA_DIR=tmp_path / "data")

    def history(*args, **kwargs):
        assert kwargs["portfolio_snapshot"] is portfolio
        raise LookupError("history reached")

    monkeypatch.setattr(post_market_review, "build_trade_history", history)
    with pytest.raises(LookupError, match="history reached"):
        post_market_review.build_post_market_review(
            settings, tmp_path / "reports", "present", use_llm=False,
            portfolio_snapshot=portfolio, broker_client=None,
        )


def test_scheduler_missing_portfolio_is_failed_and_retryable(monkeypatch, tmp_path):
    import json

    from agente_bolsa import scheduler
    from agente_bolsa.storage import Store

    settings = Settings(_env_file=None, DATA_DIR=tmp_path / "data")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    status = SimpleNamespace(
        now_market="2026-10-06T23:00:00+00:00", as_dict=lambda: {},
    )
    monkeypatch.setattr(
        scheduler, "MarketCalendar",
        lambda *args: SimpleNamespace(should_run_daily_study=lambda: (True, status)),
    )
    monkeypatch.setattr(scheduler, "_reporter", lambda *args: SimpleNamespace(emit=lambda *args: None))
    monkeypatch.setattr(
        scheduler, "reconcile_broker_orders", lambda *args, **kwargs: {"changes": []},
    )
    monkeypatch.setattr(scheduler, "publish_trade_fill_notifications", lambda *args: {})
    monkeypatch.setattr(
        scheduler, "BrokerClientFactory",
        lambda *args: SimpleNamespace(alpaca_portfolio_snapshot=lambda: None),
    )
    monkeypatch.setattr(
        post_market_review, "build_trade_history",
        lambda *args, **kwargs: pytest.fail("history must not run"),
    )
    for _ in range(2):
        assert scheduler.post_market_review_job(
            settings, store, use_llm=False, verbose=False, force=True,
        ) is None
    assert store.get_runtime_value("post_market_review_last_session") is None
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM agent_events WHERE event_type = 'postmarket_run'"
        ).fetchall()
    terminals = [json.loads(row[0]) for row in rows if json.loads(row[0]).get("stage") == "terminal"]
    assert len(terminals) == 2
    assert all(item["status"] == "failed" for item in terminals)
    assert all("post_market_portfolio_unavailable" in item["error"] for item in terminals)
    assert not list((settings.data_dir / "reports").glob("post_market_review*"))
