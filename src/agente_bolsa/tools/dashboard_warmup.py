"""Precalentado del dashboard (P-L158E).

El primer render tras reiniciar el proceso web cuesta ~30 s en Jetson porque
las caches de pickles de apertura, el calendario XNYS y las paginas SQL estan
vacias. Este modulo rellena esas caches en un hilo de fondo al arrancar, sin
tocar la ruta de trading ni bloquear el arranque HTTP.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..config import Settings
from ..storage import Store


def warm_dashboard_caches(
    settings: Settings,
    store: Store,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calienta las caches de lectura que usa el panel. Solo lectura."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = current.date()
    timings: dict[str, Any] = {}

    def timed(name: str, fn: Callable[[], Any]) -> None:
        started = time.perf_counter()
        try:
            fn()
            timings[name] = round(time.perf_counter() - started, 3)
        except Exception as exc:  # noqa: BLE001 - el precalentado nunca debe romper
            timings[name] = round(time.perf_counter() - started, 3)
            timings[f"{name}_error"] = f"{type(exc).__name__}: {exc}"

    from .opening_performance import load_cached_spy_open_observations

    timed("spy_open_observations", lambda: load_cached_spy_open_observations(settings, now=current))

    from .performance_benchmark import xnys_sessions_between

    for label, days in (("calendar_240d", 240), ("calendar_60d", 60), ("calendar_years", 900)):
        start = (today - timedelta(days=days)).isoformat()
        timed(label, lambda s=start: xnys_sessions_between(s, today.isoformat()))

    from ..market_calendar import MarketCalendar

    calendar = MarketCalendar(settings.market_calendar, settings.local_timezone)
    timed(
        "session_schedule_220d",
        lambda: calendar.session_schedule((today - timedelta(days=220)).isoformat(), today.isoformat()),
    )

    timed("latest_events_400", lambda: store.latest_events(400))
    timed(
        "session_open_snapshots",
        lambda: store.agent_events(event_type_prefix="session_open_snapshot", limit=5000),
    )
    timed("latest_ci_cycle", store.latest_continuous_improvement_cycle)
    timed("ci_validations", lambda: store.continuous_improvement_validations(limit=20000))

    timings["total"] = round(sum(v for k, v in timings.items() if isinstance(v, (int, float)) and not k.endswith("_error")), 3)
    return timings

_LOCK = threading.Lock()
_SUMMARY: dict[str, Any] | None = None


def ensure_warmup(settings: Settings) -> dict[str, Any] | None:
    """Calienta las caches una sola vez por proceso y devuelve el resumen.

    La primera sesion paga el coste (~8 s en Jetson) en lugar de repetirlo en
    cada primera pagina; las siguientes lo encuentran ya hecho.
    """

    global _SUMMARY
    if _SUMMARY is not None:
        return _SUMMARY
    with _LOCK:
        if _SUMMARY is not None:
            return _SUMMARY
        try:
            store = Store(settings.database_path, settings.agent_logs_dir)
            _SUMMARY = warm_dashboard_caches(settings, store)
        except Exception as exc:  # noqa: BLE001 - nunca debe romper el panel
            _SUMMARY = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"dashboard_warmup {_SUMMARY}", flush=True)
    return _SUMMARY


def warmup_summary() -> dict[str, Any] | None:
    return _SUMMARY
