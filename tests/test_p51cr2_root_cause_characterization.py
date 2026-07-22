"""Characterization of the exact-session boundary behind P-L51CR2 regressions."""

from __future__ import annotations

from pathlib import Path

from test_p51br1_combined_integration import (
    SESSION,
    _persisted_cycle_orders,
    _store,
)

from agente_bolsa.tools.canonical_operation_telemetry import build_canonical_operation_telemetry


def test_real_store_rows_outside_session_are_not_reconstructed_as_operations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The producer must keep an exact session boundary, including provenance."""

    monkeypatch.setattr(
        "agente_bolsa.storage._utc_iso",
        lambda: "2026-07-22T03:00:00+00:00",
    )
    store = _store(tmp_path)
    _persisted_cycle_orders(store)

    telemetry = build_canonical_operation_telemetry(store, SESSION)

    assert telemetry["denominators"]["broker_order_count"] == 0
    assert telemetry["denominators"]["buy_order_count"] == 0
    assert telemetry["denominators"]["sell_order_count"] == 0
    assert telemetry["operations"] == []
