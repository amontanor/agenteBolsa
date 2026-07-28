"""QA combinada P-L58R1 para seguridad de medición y paridad activa.

Estas pruebas usan únicamente builders/lectores ya existentes y SQLite temporal.
Su objetivo es hacer explícitas las fronteras entre selección, operaciones,
salidas y cierre contable después de fusionar los tres candidatos.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from test_p43cr1_ordering import _run_exit, _successful_order
from test_p43cr1_ordering import _Store as ExitStore
from test_p48br1_adversarial_qa import _raw_fixture
from test_p51b_canonical_trade_attribution import _valid_fixture
from test_p51b_trade_attribution_shadow import _snapshot as p51_snapshot
from test_p53b_selection_ledger_shadow import _candidate, _recommendation
from test_p57a_null_safety import _patch_scoreboard_dependencies

from agente_bolsa import cycle_runner, scheduler
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import profitability_scoreboard
from agente_bolsa.tools.canonical_eod_account_snapshot import (
    COST_FIELDS,
    build_canonical_eod_account_snapshot,
    persist_canonical_eod_account_snapshot,
)
from agente_bolsa.tools.canonical_operation_telemetry import (
    build_canonical_operation_telemetry,
    persist_canonical_operation_telemetry,
)
from agente_bolsa.tools.canonical_selection_ledger import (
    build_canonical_selection_ledger,
    persist_canonical_selection_ledger,
)
from agente_bolsa.tools.canonical_trade_attribution import (
    persist_canonical_trade_attribution,
)

SESSION = "2026-07-21"
CAPTURED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "data" / "state" / "combined.sqlite3", tmp_path / "data" / "logs")
    store.ensure_schema()
    return store


def test_combined_events_keep_domains_and_exact_ids_separate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    buy_a = _candidate(0, cycle_id="cycle-A", action="buy", symbol="AAA", selected=True)
    exit_a = _candidate(1, cycle_id="cycle-A", action="exit", symbol="AAA")
    buy_b = _candidate(2, cycle_id="cycle-B", action="buy", symbol="AAA", selected=True)

    for cycle_id, row in (("cycle-A", buy_a), ("cycle-B", buy_b)):
        ledger = build_canonical_selection_ledger(
            cycle_id,
            {"all_candidates": [row], "selected_candidates": [row]},
            recommendations=[_recommendation(row, 0)],
            captured_at=CAPTURED_AT,
        )
        assert persist_canonical_selection_ledger(store, ledger)["status"] == "inserted"

    # BUY and EXIT share a descriptive symbol but remain different decisions.
    exit_ledger = build_canonical_selection_ledger(
        "cycle-A",
        {"all_candidates": [exit_a], "selected_candidates": []},
        captured_at=CAPTURED_AT,
    )
    assert persist_canonical_selection_ledger(store, exit_ledger)["status"] == "conflict"

    attribution = p51_snapshot(_valid_fixture())
    assert persist_canonical_trade_attribution(store, attribution)["status"] == "inserted"

    snapshot = build_canonical_eod_account_snapshot(
        session_date=SESSION,
        account_id="paper",
        currency="USD",
        window_start_at="2026-07-21T13:30:00Z",
        window_end_at="2026-07-21T20:00:00Z",
        generated_at="2026-07-21T20:00:00Z",
        as_of="2026-07-21T20:00:00Z",
        captured_at=CAPTURED_AT,
        equity_start=1000.0,
        equity_end=1094.75,
        cash_start=900.0,
        cash_end=900.0,
        open_pl_start=0.0,
        open_pl_end=0.0,
        gross_realized_pl=100.0,
        costs={
            field: value
            for field, value in zip(COST_FIELDS, (1.0, 0.5, 2.0, 1.5, 0.25), strict=True)
        },
        external_flow_ledger=[],
        contributions=[
            {
                "broker_order_id": "buy-1",
                "lot_identity": "lot-1",
                "amount": 94.75,
                "currency": "USD",
                "origin": "canonical_trade_attribution",
            }
        ],
        positions=[],
        benchmark={"symbol": "SPY", "quality": "unknown", "price_basis": None},
    )
    assert persist_canonical_eod_account_snapshot(store, snapshot)["status"] == "inserted"

    telemetry = build_canonical_operation_telemetry(
        None, SESSION, source_data=_raw_fixture(), captured_at=CAPTURED_AT
    )
    assert persist_canonical_operation_telemetry(store, telemetry)["status"] == "inserted"
    event_ids = {
        event["event_id"]
        for event in store.agent_events(limit=1000)
        if event.get("event_type", "").startswith("canonical_")
    }
    assert "canonical_selection_ledger:cycle-A" in event_ids
    assert "canonical_selection_ledger:cycle-B" in event_ids
    assert f"canonical_trade_attribution:{SESSION}" in event_ids
    assert f"canonical_eod_account_snapshot:{SESSION}" in event_ids
    assert f"canonical_operation_telemetry:{SESSION}" in event_ids


def test_combined_exit_order_and_null_scoreboard_are_independent(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    exits = _run_exit(monkeypatch, ExitStore(calls), _successful_order)
    assert exits[0]["status"] == "accepted"
    assert calls == ["submit", "save_broker_order", "persist_time_stop_exit_authority"]

    settings = Settings(_env_file=None, DATA_DIR=tmp_path / "scoreboard-data")
    store = _store(tmp_path / "scoreboard")
    store.upsert_performance_daily(
        {
            "session_date": SESSION,
            "equity": 990.0,
            "pnl_pct": None,
            "previous_equity": None,
            "spy_pct": 0.007092,
            "alpha": None,
            "max_dd": None,
        }
    )
    _patch_scoreboard_dependencies(monkeypatch)
    performance = profitability_scoreboard._performance_summary(settings, store, since_date=SESSION)
    assert performance["cumulative_pnl_pct"] is None
    assert performance["cumulative_alpha"] is None
    assert performance["cumulative_spy_pct"] == 0.007092


def test_combined_stage_order_keeps_shadows_out_of_active_and_pmr_routes() -> None:
    exit_source = inspect.getsource(scheduler._execute_stop_take_exits)
    assert exit_source.index("save_broker_order") < exit_source.index(
        "persist_time_stop_exit_authority_after_order"
    )

    cycle_source = inspect.getsource(cycle_runner._auto_paper_trade)
    assert cycle_source.rfind("_persist_selection_ledger_shadow") > cycle_source.rfind(
        "submit_paper_order_plan"
    )

    pmr_source = inspect.getsource(scheduler.post_market_review_job)
    stages = [
        "canonical_operation_telemetry",
        "canonical_trade_attribution",
        "canonical_eod_account_snapshot",
        "_persist_daily_performance",
        "_run_post_market_measurement_pipeline",
        "_run_macro_thesis",
    ]
    offsets = [pmr_source.index(stage) for stage in stages]
    assert offsets == sorted(offsets)
    assert "canonical_selection_ledger" not in pmr_source
