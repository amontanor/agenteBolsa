from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa.storage import Store
from agente_bolsa.tools.signal_learning import update_signal_execution_status


def _store(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    return store


def _recommendation(signal_id: str, symbol: str) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        action="buy",
        decision_lineage={
            "signal_id": signal_id,
            "signal_source_run_id": "cycle-1",
            "cycle_id": "cycle-1",
            "lineage_status": "verified",
        },
    )


def test_execution_carrier_requires_exact_recommendation_identity(tmp_path):
    """Characterization: the base API cannot carry a signal_id to the writer.

    The production call currently accepts only approved_symbols.  This test is
    intentionally red against the P-L80A base and records the missing
    producer-to-storage contract before the implementation is added.
    """

    store = _store(tmp_path)
    signal_id = "learning_experiment:2026-08-03:BUILTIN_BREAKOUT:CONTROL"
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="cycle-1",
        source="learning_experiment",
        symbol="CONTROL",
        signal_date="2026-08-03",
        decision="approved_buy",
        features={
            "decision_lineage": {
                "signal_id": signal_id,
                "signal_source_run_id": "cycle-1",
                "cycle_id": "cycle-1",
                "lineage_status": "verified",
            }
        },
        gate={},
    )

    updated = update_signal_execution_status(
        store,
        source_run_id="cycle-1",
        approved_recommendations=[_recommendation(signal_id, "CONTROL")],
        cycle_id="cycle-1",
        effective_max_orders_per_cycle=1,
        effective_max_daily_buy_orders=1,
    )

    assert updated == 1
    row = store.signal_outcome_by_id(signal_id)
    assert row["gate"]["execution"]["status"] == "approved_not_planned"

