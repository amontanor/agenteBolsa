"""P-L158C caracterizacion: indices, cache de calendario y proyeccion barata.

El lote es observacional/persistente (N2): no toca trading, riesgo ni ejecucion.
Estas pruebas fijan el contrato que permite bajar el coste del Dashboard sin
cambiar ninguna cifra mostrada.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from agente_bolsa import web_app
from agente_bolsa.market_calendar import MarketCalendar, _cached_session_schedule
from agente_bolsa.storage import Store
from agente_bolsa.tools.improvement_dashboard import _daily_learning
from agente_bolsa.tools.performance_benchmark import (
    _xnys_schedule_cached,
    xnys_sessions_between,
)


def _store(tmp_path) -> Store:
    from agente_bolsa.config import Settings

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _index_names(store: Store) -> set[str]:
    with store.connect() as conn:
        return {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }


def _plan(store: Store, sql: str, params: tuple = ()) -> str:
    with store.connect() as conn:
        return " | ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params))


def _reference_session_date(parsed_utc: datetime, schedule) -> str | None:
    """Implementacion previa (recorrido completo) como referencia de paridad."""

    best: tuple[datetime, str] | None = None
    for session_key, row in schedule.iterrows():
        market_close = row["market_close"]
        close_utc = pd.Timestamp(market_close).to_pydatetime()
        close_utc = close_utc if close_utc.tzinfo else close_utc.replace(tzinfo=timezone.utc)
        close_utc = close_utc.astimezone(timezone.utc)
        if close_utc > parsed_utc:
            continue
        session_date = str(session_key.date())
        if best is None or close_utc > best[0]:
            best = (close_utc, session_date)
    return best[1] if best else None


def _schedule_frame(rows: list[tuple[str, str]]) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(day) for day, _ in rows])
    closes = [pd.Timestamp(close).tz_localize("UTC") for _, close in rows]
    return pd.DataFrame({"market_close": closes}, index=index)


def test_ensure_schema_creates_events_indexes_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    names = _index_names(store)
    assert "idx_agent_events_created" in names
    assert "idx_agent_events_cycle_created" in names
    assert "idx_research_evidence_updated" in names

    store.ensure_schema()
    assert _index_names(store) == names


def test_latest_events_query_uses_created_at_index(tmp_path):
    store = _store(tmp_path)
    plan = _plan(
        store,
        "SELECT event_id, agent, event_type, cycle_id, payload_json, created_at "
        "FROM agent_events ORDER BY created_at DESC LIMIT ?",
        (20,),
    )
    assert "idx_agent_events_created" in plan
    assert "TEMP B-TREE" not in plan


def test_cycle_events_query_uses_cycle_index(tmp_path):
    store = _store(tmp_path)
    plan = _plan(
        store,
        "SELECT agent, event_type, payload_json, created_at FROM agent_events "
        "WHERE cycle_id = ? ORDER BY created_at",
        ("cyc-1",),
    )
    assert "idx_agent_events_cycle_created" in plan
    assert "TEMP B-TREE" not in plan


def test_research_evidence_recent_uses_updated_index(tmp_path):
    store = _store(tmp_path)
    plan = _plan(store, "SELECT * FROM research_evidence ORDER BY updated_at DESC LIMIT ?", (20,))
    assert "idx_research_evidence_updated" in plan
    assert "TEMP B-TREE" not in plan


def test_session_close_index_matches_reference_on_ordered_schedule():
    schedule = _schedule_frame(
        [
            ("2026-07-01", "2026-07-01T20:00:00"),
            ("2026-07-02", "2026-07-02T20:00:00"),
            ("2026-07-06", "2026-07-06T20:00:00"),
        ]
    )
    closes, labels = web_app._session_close_index(schedule)
    for stamp in (
        "2026-07-01T19:59:59",
        "2026-07-01T20:00:00",
        "2026-07-02T12:00:00",
        "2026-07-05T00:00:00",
        "2026-07-07T00:00:00",
    ):
        parsed = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        assert web_app._session_date_from_close_index(parsed, closes, labels) == _reference_session_date(
            parsed, schedule
        )


def test_session_close_index_matches_reference_on_unsorted_schedule_with_ties():
    schedule = _schedule_frame(
        [
            ("2026-07-06", "2026-07-06T20:00:00"),
            ("2026-07-01", "2026-07-01T20:00:00"),
            ("2026-07-02", "2026-07-02T20:00:00"),
            ("2026-07-03", "2026-07-01T20:00:00"),
        ]
    )
    closes, labels = web_app._session_close_index(schedule)
    for stamp in ("2026-07-01T19:00:00", "2026-07-01T20:00:00", "2026-07-03T00:00:00", "2026-07-09T00:00:00"):
        parsed = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        assert web_app._session_date_from_close_index(parsed, closes, labels) == _reference_session_date(
            parsed, schedule
        )


def test_session_close_index_ignores_unparsable_closes():
    frame = _schedule_frame([("2026-07-01", "2026-07-01T20:00:00")])
    frame.loc[pd.Timestamp("2026-07-02"), "market_close"] = pd.NaT
    closes, labels = web_app._session_close_index(frame)
    assert labels == ["2026-07-01"]
    assert len(closes) == 1


def test_portfolio_session_date_without_schedule_falls_back_to_calendar():
    # Sin schedule explicito se consulta el calendario real: sigue resolviendo
    # la ultima sesion cerrada y no adivina por dia de la semana.
    assert web_app._portfolio_session_date_for_timestamp("2026-07-04T00:00:00Z") == "2026-07-02"


def test_market_calendar_session_schedule_is_cached_and_copied():
    first = MarketCalendar().session_schedule("2026-07-01", "2026-07-10")
    hits_before = _cached_session_schedule.cache_info().hits
    second = MarketCalendar().session_schedule("2026-07-01", "2026-07-10")
    assert _cached_session_schedule.cache_info().hits > hits_before
    assert list(first.index) == list(second.index)
    assert first is not second
    first.loc[first.index[0], "market_close"] = pd.NaT
    third = MarketCalendar().session_schedule("2026-07-01", "2026-07-10")
    assert pd.notna(third.iloc[0]["market_close"])


def test_xnys_sessions_between_uses_cache_and_real_holidays():
    sessions = xnys_sessions_between("2026-07-01", "2026-07-10")
    assert sessions == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]
    hits_before = _xnys_schedule_cached.cache_info().hits
    assert xnys_sessions_between("2026-07-01", "2026-07-10") == sessions
    assert _xnys_schedule_cached.cache_info().hits > hits_before


def test_learning_observation_created_dates_matches_full_reader(tmp_path):
    store = _store(tmp_path)
    for index in range(5):
        store.upsert_learning_observation(
            {
                "observation_id": f"obs-{index}",
                "signal_date": f"2026-07-{10 + index:02d}",
                "symbol": f"SYM{4 - index}",
                "source_family": "deterministic",
                "source_run_ids": [f"run-{index}"],
                "first_seen_at": "2026-07-20T12:00:00+00:00",
                "last_seen_at": "2026-07-20T12:00:00+00:00",
                "best_signal_id": f"sig-{index}",
                "best_score": 0.5,
                "decision": "candidate",
                "explanation": "p-l158c parity",
                "llm_considered": False,
                "approved_buy": False,
                "blocked_entry_quality": False,
                "blocked_backtest": False,
                "executed_buy": False,
                "duplicate_count": 0,
                "rank_path": [],
                "features": {"index": index},
                "gate": {},
                "outcome": {},
                "execution": {},
            }
        )
    full = store.learning_observations(limit=3)
    projected = store.learning_observation_created_dates(limit=3)
    assert projected == [row["created_at"] for row in full]


class _ProjectedStore:
    def __init__(self, created_dates: list[str]) -> None:
        self._created_dates = created_dates

    def learning_observation_created_dates(self, *, limit: int = 5000) -> list[str]:
        return self._created_dates[:limit]

    def learning_observations(self, *, limit: int = 5000):  # pragma: no cover - must not be used
        raise AssertionError("la ruta proyectada no debe deserializar el lector completo")

    def distilled_lessons(self, *, limit: int = 200) -> list[dict]:
        return []

    def continuous_improvement_experiments(self, *, limit: int = 200) -> list[dict]:
        return []


class _FullStore(_ProjectedStore):
    def __init__(self, created_dates: list[str]) -> None:
        super().__init__(created_dates)

    def learning_observations(self, *, limit: int = 5000):
        return [{"created_at": value} for value in self._created_dates[:limit]]


def test_daily_learning_projection_keeps_exact_numbers():
    created = ["2026-10-28T09:00:00+00:00", "2026-10-28T10:00:00+00:00", "2026-10-27T23:59:59+00:00"]
    projected = _daily_learning(_ProjectedStore(created), "2026-10-28")
    full = _daily_learning(_FullStore(created), "2026-10-28")
    assert projected == full
    assert projected["observations_today"] == 2


def test_dashboard_series_uses_one_schedule_lookup(monkeypatch):
    """El grafico no debe reconstruir el calendario por cada punto."""

    calls: list[tuple[str, str]] = []
    original = MarketCalendar.session_schedule

    def counting(self, start_date, end_date):
        calls.append((start_date, end_date))
        return original(self, start_date, end_date)

    monkeypatch.setattr(MarketCalendar, "session_schedule", counting)
    payload = {
        "timestamp": [
            int(datetime(2026, 7, day, 0, tzinfo=timezone.utc).timestamp()) for day in (1, 2, 3, 6, 7, 8, 9, 10)
        ],
        "equity": [100_000.0, 100_100.0, 100_200.0, 100_300.0, 100_400.0, 100_500.0, 100_600.0, 100_700.0],
    }
    frame = web_app._portfolio_value_series_from_alpaca(payload, current_equity=None, as_of="2026-07-11T12:00:00Z")
    assert len(calls) == 1
    assert list(frame["session_date"]) == [
        "2026-06-30",
        "2026-07-01",
        "2026-07-02",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
    ]
