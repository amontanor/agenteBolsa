from __future__ import annotations

from pathlib import Path

from agente_bolsa import scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _grace(built, job_id: str) -> int | None:
    job = next(item for item in built.get_jobs() if item.id == job_id)
    return job.misfire_grace_time


def test_intraday_jobs_survive_observed_wake_latency(tmp_path: Path) -> None:
    """P-L139: la produccion pierde runs con 1.4-2.7 s de retraso porque el
    default de APScheduler (1 s) los descarta. Estos margenes cubren la
    latencia observada sin aceptar ciclos rancios (coalesce intacto)."""

    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    built = scheduler.build_scheduler(settings, store, use_crew=False, verbose=False)
    try:
        assert _grace(built, "market_cycle_15m") == 300
        assert _grace(built, "portfolio_watch_1m") == 120
        assert _grace(built, "trade_fill_watch") == 120
        for job in built.get_jobs():
            assert job.coalesce is True
            assert job.max_instances == 1
    finally:
        built.shutdown(wait=False)
