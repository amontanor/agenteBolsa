"""Session-owned, read-only Dashboard loading without blocking Streamlit."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .tools.broker import BrokerClientFactory
from .tools.trade_history import build_trade_history


def load_dashboard_data(settings: Any, portfolio_ready: Future | None = None) -> dict[str, Any]:
    """Read independent remote resources concurrently, then reuse the portfolio."""
    started = perf_counter()
    result: dict[str, Any] = {"portfolio": None, "history": {}, "portfolio_history": {}}
    errors: list[str] = []
    timings: dict[str, float] = {}

    def timed_read(name: str, callback: Any) -> tuple[Any, float]:
        read_started = perf_counter()
        try:
            return callback(), perf_counter() - read_started
        except Exception as exc:
            raise RuntimeError(f"{name}: {exc}") from exc

    # Separate clients: SDK HTTP sessions are not shared between threads.
    reads = {
        "portfolio": BrokerClientFactory(settings).alpaca_portfolio_snapshot,
        "fills": lambda: BrokerClientFactory(settings).alpaca_trade_activities(limit=1000),
        "portfolio_history": lambda: BrokerClientFactory(settings).alpaca_portfolio_history(
            period="3M", timeframe="1D"
        ),
    }
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="dashboard-read") as pool:
        futures = {name: pool.submit(timed_read, name, read) for name, read in reads.items()}
        values = {}
        for name, future in futures.items():
            try:
                values[name], timings[name] = future.result()
                if name == "portfolio" and portfolio_ready is not None:
                    portfolio_ready.set_result({
                        "portfolio": values[name], "history": {}, "portfolio_history": {},
                        "fetched_at": datetime.now(timezone.utc).isoformat(), "timings": {},
                    })
            except Exception as exc:
                errors.append(str(exc))
    result["portfolio"] = values.get("portfolio")
    result["portfolio_history"] = values.get("portfolio_history", {})
    if result["portfolio"] is not None and "fills" in values:
        try:
            result["history"] = build_trade_history(
                settings, limit=1000, start_date="2026-04-01",
                portfolio=result["portfolio"], fills=values["fills"],
            )
        except Exception as exc:
            errors.append(f"Historico/P/L: {exc}")
    result["errors"] = errors
    result["timings"] = {**timings, "total": perf_counter() - started}
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return result


class DashboardLoadState:
    """One request at a time per browser session; retain data during refresh/failure."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self.errors: list[str] = []
        self.future: Future | None = None
        self.portfolio_ready: Future | None = None
        self.executor: ThreadPoolExecutor | None = None
        self.started_at = 0.0
        self.completed_at: float | None = None
        self.refresh_requested = False

    @property
    def loading(self) -> bool:
        return self.future is not None

    def update(self, settings: Any, refresh_after: float) -> bool:
        """Return whether polling frequency must change. Never wait for remote I/O."""
        now = perf_counter()
        if self.future is not None:
            if not self.future.done():
                if self.portfolio_ready is not None and self.portfolio_ready.done():
                    if self.data is None:
                        self.data = self.portfolio_ready.result()
                        self.portfolio_ready = None
                        return True
                    self.portfolio_ready = None
                return False
            try:
                result = self.future.result()
                self.errors = result["errors"]
                if self.data is None or result["portfolio"] is not None:
                    self.data = result
            except Exception as exc:
                self.errors = [str(exc)]
            finally:
                self.future = None
                self.portfolio_ready = None
                if self.executor is not None:
                    self.executor.shutdown(wait=False)
                    self.executor = None
                self.completed_at = now
            return True
        if (self.completed_at is None or self.refresh_requested
                or now - self.completed_at >= refresh_after):
            self.refresh_requested = False
            self.started_at = now
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dashboard-load")
            self.portfolio_ready = Future()
            self.future = self.executor.submit(load_dashboard_data, settings, self.portfolio_ready)
            return True
        return False
