"""QA boundaries for the P-L76 pre-close rehearsal."""

from __future__ import annotations

import inspect

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.tools import broker_reconciliation, fill_provider, fill_watch


def test_fill_watch_preserves_provider_neutral_post_submit_order() -> None:
    watcher_source = inspect.getsource(fill_watch.run_trade_fill_watch)
    reconciliation_source = inspect.getsource(broker_reconciliation.reconcile_broker_orders)

    assert watcher_source.index("snapshot_order") < watcher_source.index("apply_broker_order_snapshot")
    assert watcher_source.index("apply_broker_order_snapshot") < watcher_source.rindex(
        "publish_trade_fill_notifications"
    )
    assert "OrderStatusProvider" in watcher_source
    assert "Alpaca" not in watcher_source
    assert "reconciliation_finalization" in reconciliation_source
    assert "finalization_pending" in reconciliation_source


def test_fill_watch_provider_and_scheduler_boundaries_are_explicit() -> None:
    provider_source = inspect.getsource(fill_provider.AlpacaOrderStatusProvider)
    scheduler_source = inspect.getsource(scheduler.build_scheduler)
    job_source = inspect.getsource(scheduler.trade_fill_watch_job)

    assert "_normalize_base_url" in provider_source
    assert "allow_redirects=False" in provider_source
    assert "timeout=int(timeout_seconds)" in provider_source
    assert "trade_fill_watch" in scheduler_source
    assert "max_instances=1" in scheduler_source
    assert "coalesce=True" in scheduler_source
    assert "trade_fill_watch_enabled" in job_source
    assert Settings(_env_file=None).trade_fill_watch_enabled is False
