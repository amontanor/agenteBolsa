"""P-L158F: indices de rendimiento compartidos con la linea Jetson.

Solo esquema (N2): no cambia decisiones, gates ni ejecucion. Fija que los
lectores del panel usan indice y no un escaneo con ordenacion temporal.
"""

from __future__ import annotations

from agente_bolsa.storage import Store


def _store(tmp_path) -> Store:
    from agente_bolsa.config import Settings

    settings = Settings(DATA_DIR=tmp_path)
    settings.ensure_runtime_dirs()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _plans(store: Store, sql: str, params: tuple = ()) -> str:
    with store.connect() as conn:
        return " | ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params))


def _index_names(store: Store) -> set[str]:
    with store.connect() as conn:
        return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


EXPECTED = {
    "idx_agent_events_type_created",
    "idx_ci_cycles_created",
    "idx_trade_recommendations_cycle_created",
    "idx_learning_observations_cover",
}


def test_schema_creates_performance_indexes_idempotently(tmp_path):
    store = _store(tmp_path)
    names = _index_names(store)
    assert EXPECTED <= names

    store.ensure_schema()
    assert _index_names(store) == names


def test_event_prefix_reads_use_type_index(tmp_path):
    store = _store(tmp_path)
    plan = _plans(
        store,
        "SELECT event_id FROM agent_events WHERE event_type >= ? AND event_type < ? "
        "ORDER BY created_at DESC, event_id DESC LIMIT ?",
        ("session_open_snapshot", "session_open_snapshot\uffff", 5000),
    )
    assert "idx_agent_events_type_created" in plan
    # El indice filtra por tipo; ordenar las pocas filas que casan es barato y
    # SQLite usa un B-tree temporal solo para esas filas.
    assert "SCAN agent_events" not in plan


def test_latest_cycle_uses_created_index(tmp_path):
    store = _store(tmp_path)
    plan = _plans(
        store,
        "SELECT cycle_id FROM continuous_improvement_cycles ORDER BY created_at DESC LIMIT 1",
    )
    assert "idx_ci_cycles_created" in plan
    assert "TEMP B-TREE" not in plan


def test_recommendations_by_cycle_use_cycle_index(tmp_path):
    store = _store(tmp_path)
    plan = _plans(
        store,
        "SELECT symbol FROM trade_recommendations WHERE cycle_id = ? ORDER BY created_at",
        ("cyc-1",),
    )
    assert "idx_trade_recommendations_cycle_created" in plan
    assert "TEMP B-TREE" not in plan


def test_observations_projection_is_covered_by_index(tmp_path):
    store = _store(tmp_path)
    plan = _plans(
        store,
        "SELECT created_at FROM learning_observations "
        "ORDER BY signal_date DESC, symbol ASC LIMIT ?",
        (5000,),
    )
    assert "idx_learning_observations_cover" in plan
    assert "COVERING INDEX" in plan
