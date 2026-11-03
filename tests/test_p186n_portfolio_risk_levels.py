"""P-L186N: portfolio risk levels are direction-aware; orphans stay explicit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agente_bolsa import web_app
from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools import trade_history

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from p186n_portfolio_cases import BROKER_ORDERS, OPEN_POSITIONS  # noqa: E402


def _store(tmp_path: Path) -> Store:
    settings = Settings(DATA_DIR=tmp_path, _env_file=None)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    with store.connect() as conn:
        conn.executemany(
            """
            INSERT INTO broker_orders (
                broker_order_id, plan_id, cycle_id, symbol, side, status,
                payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["broker_order_id"],
                    item["plan_id"],
                    item["cycle_id"],
                    item["symbol"],
                    item["side"],
                    item["status"],
                    json.dumps(item["payload"]),
                    item["created_at"],
                )
                for item in BROKER_ORDERS
            ],
        )
    return store


def test_entry_risk_plans_are_direction_aware(tmp_path):
    store = _store(tmp_path)
    entries = trade_history._local_entry_risk_plans(store.database_path)

    assert entries["EVRG"]["long"]["stop_loss"] == pytest.approx(82.2425)
    assert entries["EVRG"]["long"]["take_profit"] == pytest.approx(89.4363)
    assert entries["APP"]["short"]["stop_loss"] == pytest.approx(261.3766)
    assert entries["APP"]["short"]["take_profit"] == pytest.approx(204.0601)
    assert entries["MO"]["long"]["stop_loss"] == pytest.approx(72.43)
    assert entries["ADM"]["long"]["stop_loss"] == pytest.approx(70.0)
    assert "short" not in entries.get("ADM", {})
    assert "APO" not in entries


def test_attach_risk_levels_uses_position_direction(tmp_path):
    store = _store(tmp_path)
    entries = trade_history._local_entry_risk_plans(store.database_path)
    positions = [dict(item) for item in OPEN_POSITIONS]

    trade_history._attach_risk_levels([], positions, entries)
    by_symbol = {item["symbol"]: item for item in positions}

    assert by_symbol["APP"]["stop_loss"] == pytest.approx(261.3766)
    assert by_symbol["ADM"]["stop_loss"] == pytest.approx(70.0)
    assert by_symbol["MO"]["take_profit"] == pytest.approx(80.555)
    assert by_symbol["APO"]["stop_loss"] is None
    assert by_symbol["APO"]["take_profit"] is None


def test_position_rows_show_short_levels_and_flag_orphans(tmp_path):
    store = _store(tmp_path)
    entries = trade_history._local_entry_risk_plans(store.database_path)
    history = {
        "open_positions": [dict(item) for item in OPEN_POSITIONS],
        "risk_levels_by_direction": entries,
    }

    rows = {row["Simbolo"]: row for row in web_app._position_rows(history)}

    assert rows["APP"]["Stop"] == pytest.approx(261.3766)
    assert rows["APP"]["Take"] == pytest.approx(204.0601)
    assert rows["APP"]["Riesgo estado"] == "plan_local"
    assert rows["APO"]["Stop"] is None
    assert rows["APO"]["Take"] is None
    assert rows["APO"]["Riesgo estado"] == "sin_plan_local"
    assert rows["EVRG"]["Riesgo estado"] == "plan_local"


def test_legacy_flat_risk_levels_still_render_for_longs(tmp_path):
    history = {
        "open_positions": [
            {
                "symbol": "APO",
                "side": "long",
                "qty": 7.0,
                "avg_entry_price": 137.55,
                "current_price": 113.125,
                "market_value": 791.875,
                "unrealized_pl": -170.975,
                "unrealized_plpc": -0.17757,
            }
        ],
        "risk_levels": {"APO": {"stop_loss": 120.0, "take_profit": 160.0}},
    }

    row = web_app._position_rows(history)[0]
    assert row["Stop"] == pytest.approx(120.0)
    assert row["Take"] == pytest.approx(160.0)
    assert row["Riesgo estado"] == "plan_local"
