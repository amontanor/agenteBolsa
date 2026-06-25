import json
import sqlite3

from scripts.migrate_signal_outcomes_compact import (
    build_compact_plans,
    load_rows,
    run_migration,
)

SCHEMA = """
CREATE TABLE signal_outcomes (
    signal_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    decision TEXT NOT NULL,
    features_json TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _insert(
    connection: sqlite3.Connection,
    *,
    signal_id: str,
    symbol: str = "AAA",
    strategy: str = "builtin_breakout",
    outcome: dict | None = None,
    updated_at: str = "2026-06-25T10:00:00+00:00",
) -> None:
    connection.execute(
        """
        INSERT INTO signal_outcomes (
            signal_id, source_run_id, source, symbol, signal_date, decision,
            features_json, gate_json, outcome_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id,
            f"run-{signal_id}",
            "intraday_scan",
            symbol,
            "2026-06-25",
            "candidate",
            json.dumps({"strategy_name": strategy}),
            "{}",
            json.dumps(outcome or {}, sort_keys=True, separators=(",", ":")),
            updated_at,
            updated_at,
        ),
    )


def _conflicts_file(tmp_path, items: list[dict]) -> str:
    path = tmp_path / "conflicts.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return str(path)


def test_build_compact_plans_preserves_old_outcome_on_latest_empty():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(SCHEMA)
    _insert(connection, signal_id="old", outcome={"return_5d": 0.02}, updated_at="2026-06-25T10:00:00+00:00")
    _insert(connection, signal_id="new", outcome={}, updated_at="2026-06-25T11:00:00+00:00")

    plans = build_compact_plans(load_rows(connection), conflict_keys=set())

    assert len(plans) == 1
    assert plans[0].keep.signal_id == "new"
    assert plans[0].rows_to_delete == 1
    assert json.loads(plans[0].final_outcome_json) == {"return_5d": 0.02}


def test_run_migration_apply_deletes_safe_duplicates_and_keeps_conflicts(tmp_path):
    db_path = tmp_path / "signals.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(SCHEMA)
    _insert(connection, signal_id="safe_old", outcome={"return_5d": 0.02}, updated_at="2026-06-25T10:00:00+00:00")
    _insert(connection, signal_id="safe_new", outcome={}, updated_at="2026-06-25T11:00:00+00:00")
    _insert(connection, signal_id="conflict_a", symbol="BBB", outcome={"return_5d": 0.01}, updated_at="2026-06-25T10:00:00+00:00")
    _insert(connection, signal_id="conflict_b", symbol="BBB", outcome={"return_5d": -0.01}, updated_at="2026-06-25T11:00:00+00:00")
    connection.commit()
    connection.close()
    conflicts = _conflicts_file(
        tmp_path,
        [{"signal_date": "2026-06-25", "symbol": "BBB", "strategy_name": "builtin_breakout"}],
    )

    result = run_migration(str(db_path), conflicts_path=conflicts, apply=True)

    assert result["rows_deleted"] == 1
    assert result["before"]["total_rows"] == 4
    assert result["after"]["total_rows"] == 3
    assert result["before"]["nonempty_outcome_rows"] == result["after"]["nonempty_outcome_rows"] == 3
    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    rows = {row["signal_id"]: dict(row) for row in check.execute("SELECT * FROM signal_outcomes")}
    assert set(rows) == {"safe_new", "conflict_a", "conflict_b"}
    assert json.loads(rows["safe_new"]["outcome_json"]) == {"return_5d": 0.02}
    check.close()
