from scripts.migrate_signal_outcomes_dryrun import (
    SignalOutcomeRow,
    build_migration_plan,
)


def _row(
    *,
    signal_id: str,
    updated_at: str,
    symbol: str = "AAA",
    signal_date: str = "2026-06-25",
    strategy: str = "builtin_breakout",
    outcome: dict | None = None,
) -> SignalOutcomeRow:
    return SignalOutcomeRow(
        signal_id=signal_id,
        source_run_id=f"run-{updated_at}",
        source="technical_study",
        symbol=symbol,
        signal_date=signal_date,
        decision="candidate",
        features={"strategy_name": strategy},
        gate={},
        outcome=outcome or {},
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_build_migration_plan_preserves_old_outcome_when_latest_is_empty():
    rows = [
        _row(signal_id="old", updated_at="2026-06-25T10:00:00", outcome={"return_5d": 0.02}),
        _row(signal_id="new", updated_at="2026-06-25T11:00:00", outcome={}),
    ]

    summary = build_migration_plan(rows)
    plan = summary["plans"][0]

    assert summary["total_rows"] == 2
    assert summary["duplicate_groups"] == 1
    assert summary["rows_to_delete_if_compacted"] == 1
    assert summary["rows_to_delete_without_conflicts"] == 1
    assert summary["nonempty_outcome_rows_to_merge_without_loss"] == 1
    assert summary["lost_outcome_rows_under_safe_rule"] == 0
    assert summary["conflict_groups"] == 0
    assert plan.keep_signal_id == "new"
    assert plan.final_outcome == {"return_5d": 0.02}


def test_build_migration_plan_marks_distinct_nonempty_outcomes_as_conflict():
    rows = [
        _row(signal_id="first", updated_at="2026-06-25T10:00:00", outcome={"return_5d": 0.02}),
        _row(signal_id="second", updated_at="2026-06-25T11:00:00", outcome={"return_5d": -0.01}),
        _row(signal_id="other", updated_at="2026-06-25T12:00:00", symbol="BBB", outcome={}),
    ]

    summary = build_migration_plan(rows)
    conflict = summary["conflicts"][0]

    assert summary["total_rows"] == 3
    assert summary["duplicate_groups"] == 1
    assert summary["conflict_groups"] == 1
    assert summary["rows_to_delete_without_conflicts"] == 0
    assert summary["conflict_deleted_nonempty_outcome_rows"] == 1
    assert conflict.key == ("2026-06-25", "AAA", "builtin_breakout")
    assert conflict.distinct_nonempty_outcomes == 2
