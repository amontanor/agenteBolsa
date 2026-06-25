"""Compacta grupos historicos sin conflicto de signal_outcomes.

Por defecto ejecuta dry-run. Con --apply abre una transaccion y aplica solo los
grupos (signal_date, symbol, strategy) que:

- tienen mas de una fila,
- no estan en el fichero de conflictos del dry-run,
- no contienen outcomes no vacios distintos.

La regla de fusion replica T6: los metadatos de la fila mas reciente ganan y un
outcome no vacio previo se preserva si la fila mas reciente tiene '{}'.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agente_bolsa.config import get_settings

DEFAULT_CONFLICTS_PATH = "docs/signal_outcomes_migration_conflicts_2026-06-25.json"


@dataclass(frozen=True)
class SignalOutcomeRow:
    signal_id: str
    source_run_id: str
    source: str
    symbol: str
    signal_date: str
    decision: str
    features_json: str
    gate_json: str
    outcome_json: str
    created_at: str
    updated_at: str

    @property
    def features(self) -> dict[str, Any]:
        return _loads(self.features_json)

    @property
    def outcome(self) -> dict[str, Any]:
        return _loads(self.outcome_json)

    @property
    def strategy_name(self) -> str:
        strategy = str(self.features.get("strategy_name") or "").strip()
        if strategy:
            return strategy
        parts = self.signal_id.split(":")
        return parts[2] if len(parts) >= 4 else "unknown"

    @property
    def group_key(self) -> tuple[str, str, str]:
        return (self.signal_date[:10], self.symbol.upper(), self.strategy_name)


@dataclass(frozen=True)
class CompactPlan:
    key: tuple[str, str, str]
    keep: SignalOutcomeRow
    delete_rows: tuple[SignalOutcomeRow, ...]
    final_outcome_json: str
    nonempty_outcome_rows: int
    deleted_nonempty_outcome_rows: int
    keep_promoted_to_nonempty: bool
    deleted_forward_return_rows: int
    keep_promoted_to_forward_return: bool

    @property
    def rows_to_delete(self) -> int:
        return len(self.delete_rows)


def _loads(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_outcome(raw: str) -> str:
    return _dumps(_loads(raw))


def _is_nonempty_outcome(raw: str) -> bool:
    return bool(_loads(raw))


def _has_forward_return(raw: str) -> bool:
    outcome = _loads(raw)
    return any(key.startswith("return_") and value is not None for key, value in outcome.items())


def _sort_key(row: SignalOutcomeRow) -> tuple[str, str, str]:
    return (row.updated_at or "", row.created_at or "", row.signal_id)


def load_conflict_keys(path: str | Path) -> set[tuple[str, str, str]]:
    conflict_path = Path(path)
    if not conflict_path.exists():
        raise FileNotFoundError(f"No existe el fichero de conflictos: {conflict_path}")
    raw = json.loads(conflict_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("El fichero de conflictos debe contener una lista JSON.")
    keys: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        keys.add(
            (
                str(item.get("signal_date") or "")[:10],
                str(item.get("symbol") or "").upper(),
                str(item.get("strategy_name") or "unknown"),
            )
        )
    return keys


def load_rows(connection: sqlite3.Connection) -> list[SignalOutcomeRow]:
    rows = connection.execute(
        """
        SELECT signal_id, source_run_id, source, symbol, signal_date,
               decision, features_json, gate_json, outcome_json, created_at, updated_at
        FROM signal_outcomes
        ORDER BY signal_date, symbol, updated_at, created_at, signal_id
        """
    ).fetchall()
    return [
        SignalOutcomeRow(
            signal_id=str(row["signal_id"]),
            source_run_id=str(row["source_run_id"]),
            source=str(row["source"]),
            symbol=str(row["symbol"]).upper(),
            signal_date=str(row["signal_date"])[:10],
            decision=str(row["decision"]),
            features_json=str(row["features_json"] or "{}"),
            gate_json=str(row["gate_json"] or "{}"),
            outcome_json=str(row["outcome_json"] or "{}"),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )
        for row in rows
    ]


def build_compact_plans(
    rows: list[SignalOutcomeRow],
    conflict_keys: set[tuple[str, str, str]],
    *,
    max_created_at: str | None = None,
) -> list[CompactPlan]:
    groups: dict[tuple[str, str, str], list[SignalOutcomeRow]] = {}
    for row in rows:
        if max_created_at and row.created_at >= max_created_at:
            continue
        groups.setdefault(row.group_key, []).append(row)

    plans: list[CompactPlan] = []
    for key, group_rows in groups.items():
        if len(group_rows) <= 1 or key in conflict_keys:
            continue
        distinct_nonempty = {
            _canonical_outcome(row.outcome_json)
            for row in group_rows
            if _is_nonempty_outcome(row.outcome_json)
        }
        if len(distinct_nonempty) > 1:
            continue
        ordered = sorted(group_rows, key=_sort_key)
        keep = ordered[-1]
        final_outcome = {}
        for row in ordered:
            outcome = row.outcome
            if outcome:
                final_outcome = outcome
        plans.append(
            CompactPlan(
                key=key,
                keep=keep,
                delete_rows=tuple(row for row in ordered if row.signal_id != keep.signal_id),
                final_outcome_json=_dumps(final_outcome),
                nonempty_outcome_rows=sum(1 for row in ordered if _is_nonempty_outcome(row.outcome_json)),
                deleted_nonempty_outcome_rows=sum(
                    1
                    for row in ordered
                    if row.signal_id != keep.signal_id and _is_nonempty_outcome(row.outcome_json)
                ),
                keep_promoted_to_nonempty=(not _is_nonempty_outcome(keep.outcome_json) and bool(final_outcome)),
                deleted_forward_return_rows=sum(
                    1
                    for row in ordered
                    if row.signal_id != keep.signal_id and _has_forward_return(row.outcome_json)
                ),
                keep_promoted_to_forward_return=(
                    not _has_forward_return(keep.outcome_json)
                    and any(key.startswith("return_") and value is not None for key, value in final_outcome.items())
                ),
            )
        )
    return plans


def _counts(
    connection: sqlite3.Connection,
    conflict_keys: set[tuple[str, str, str]],
    *,
    max_created_at: str | None = None,
) -> dict[str, Any]:
    cutoff_clause = "WHERE created_at < ?" if max_created_at else ""
    cutoff_params: list[Any] = [max_created_at] if max_created_at else []
    total_rows = int(connection.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0])
    scoped_rows = int(
        connection.execute(
            f"SELECT COUNT(*) FROM signal_outcomes {cutoff_clause}",
            cutoff_params,
        ).fetchone()[0]
    )
    nonempty_rows = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM signal_outcomes
            WHERE COALESCE(outcome_json, '{}') != '{}'
              AND COALESCE(outcome_json, '') != ''
            """
        ).fetchone()[0]
    )
    forward_return_rows = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM signal_outcomes
            WHERE outcome_json LIKE '%"return_%'
            """
        ).fetchone()[0]
    )
    conflict_counts: Counter[tuple[str, str, str]] = Counter()
    if conflict_keys:
        for row in load_rows(connection):
            if row.group_key in conflict_keys:
                conflict_counts[row.group_key] += 1
    return {
        "total_rows": total_rows,
        "scoped_rows": scoped_rows,
        "nonempty_outcome_rows": nonempty_rows,
        "forward_return_rows": forward_return_rows,
        "conflict_counts": dict(conflict_counts),
    }


def summarize_plans(plans: list[CompactPlan], *, conflict_keys: set[tuple[str, str, str]]) -> dict[str, Any]:
    return {
        "conflict_groups_loaded": len(conflict_keys),
        "groups_to_compact": len(plans),
        "rows_to_delete": sum(plan.rows_to_delete for plan in plans),
        "groups_with_outcome": sum(1 for plan in plans if plan.final_outcome_json != "{}"),
        "nonempty_outcome_rows_in_plans": sum(plan.nonempty_outcome_rows for plan in plans),
        "deleted_nonempty_outcome_rows": sum(plan.deleted_nonempty_outcome_rows for plan in plans),
        "keep_promotions_to_nonempty": sum(1 for plan in plans if plan.keep_promoted_to_nonempty),
        "deleted_forward_return_rows": sum(plan.deleted_forward_return_rows for plan in plans),
        "keep_promotions_to_forward_return": sum(1 for plan in plans if plan.keep_promoted_to_forward_return),
    }


def _verify_plan_outcomes(plans: list[CompactPlan]) -> None:
    for plan in plans:
        deleted_outcomes = {
            _canonical_outcome(row.outcome_json)
            for row in plan.delete_rows
            if _is_nonempty_outcome(row.outcome_json)
        }
        if not deleted_outcomes:
            continue
        if deleted_outcomes != {plan.final_outcome_json}:
            raise RuntimeError(f"outcome_payload_would_be_lost:{plan.key}")


def apply_plans(
    connection: sqlite3.Connection,
    plans: list[CompactPlan],
    conflict_keys: set[tuple[str, str, str]],
    *,
    max_created_at: str | None = None,
    transaction_open: bool = False,
    before_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _verify_plan_outcomes(plans)
    expected_delete = sum(plan.rows_to_delete for plan in plans)
    expected_deleted_nonempty = sum(plan.deleted_nonempty_outcome_rows for plan in plans)
    expected_promotions = sum(1 for plan in plans if plan.keep_promoted_to_nonempty)
    expected_deleted_forward = sum(plan.deleted_forward_return_rows for plan in plans)
    expected_forward_promotions = sum(1 for plan in plans if plan.keep_promoted_to_forward_return)
    if not transaction_open:
        connection.execute("BEGIN IMMEDIATE")
    try:
        before = before_counts or _counts(connection, conflict_keys, max_created_at=max_created_at)
        for plan in plans:
            connection.execute(
                """
                UPDATE signal_outcomes
                SET outcome_json = ?,
                    updated_at = ?
                WHERE signal_id = ?
                """,
                (plan.final_outcome_json, plan.keep.updated_at, plan.keep.signal_id),
            )
            connection.executemany(
                "DELETE FROM signal_outcomes WHERE signal_id = ?",
                [(row.signal_id,) for row in plan.delete_rows],
            )
        after = _counts(connection, conflict_keys, max_created_at=max_created_at)
        actual_delete = before["total_rows"] - after["total_rows"]
        if actual_delete != expected_delete:
            raise RuntimeError(f"row_count_mismatch: expected_delete={expected_delete} actual_delete={actual_delete}")
        expected_nonempty_after = before["nonempty_outcome_rows"] - expected_deleted_nonempty + expected_promotions
        if after["nonempty_outcome_rows"] != expected_nonempty_after:
            raise RuntimeError(
                "nonempty_outcome_count_unexpected: "
                f"before={before['nonempty_outcome_rows']} expected_after={expected_nonempty_after} "
                f"actual_after={after['nonempty_outcome_rows']}"
            )
        expected_forward_after = before["forward_return_rows"] - expected_deleted_forward + expected_forward_promotions
        if after["forward_return_rows"] != expected_forward_after:
            raise RuntimeError("forward_return_row_count_unexpected")
        if before["conflict_counts"] != after["conflict_counts"]:
            raise RuntimeError("conflict_groups_changed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "before": {key: value for key, value in before.items() if key != "conflict_counts"},
        "after": {key: value for key, value in after.items() if key != "conflict_counts"},
        "rows_deleted": expected_delete,
        "deleted_nonempty_outcome_rows": expected_deleted_nonempty,
        "keep_promotions_to_nonempty": expected_promotions,
        "deleted_forward_return_rows": expected_deleted_forward,
        "keep_promotions_to_forward_return": expected_forward_promotions,
        "conflict_groups_checked": len(conflict_keys),
        "applied": True,
    }


def run_migration(
    db_path: str,
    *,
    conflicts_path: str,
    apply: bool,
    max_created_at: str | None = None,
) -> dict[str, Any]:
    conflict_keys = load_conflict_keys(conflicts_path)
    connection = sqlite3.connect(db_path, timeout=60.0)
    connection.row_factory = sqlite3.Row
    try:
        if apply:
            connection.execute("BEGIN IMMEDIATE")
        rows = load_rows(connection)
        plans = build_compact_plans(rows, conflict_keys, max_created_at=max_created_at)
        summary = summarize_plans(plans, conflict_keys=conflict_keys)
        counts_before = _counts(connection, conflict_keys, max_created_at=max_created_at)
        result: dict[str, Any] = {
            **summary,
            "db_path": db_path,
            "conflicts_path": conflicts_path,
            "max_created_at": max_created_at,
            "before": {key: value for key, value in counts_before.items() if key != "conflict_counts"},
            "apply": apply,
        }
        if apply:
            result.update(
                apply_plans(
                    connection,
                    plans,
                    conflict_keys,
                    max_created_at=max_created_at,
                    transaction_open=True,
                    before_counts=counts_before,
                )
            )
        return result
    finally:
        connection.close()


def print_result(result: dict[str, Any]) -> None:
    mode = "APPLY" if result.get("apply") else "DRY-RUN"
    print(f"\n=== signal_outcomes compact T6 safe groups ({mode}) ===")
    print(f"db: {result['db_path']}")
    print(f"conflicts: {result['conflicts_path']}")
    print(f"max_created_at: {result.get('max_created_at') or 'sin cutoff'}")
    print(f"conflict_groups_loaded: {result['conflict_groups_loaded']}")
    print(f"groups_to_compact: {result['groups_to_compact']}")
    print(f"rows_to_delete: {result['rows_to_delete']}")
    print(f"groups_with_outcome: {result['groups_with_outcome']}")
    print(f"nonempty_outcome_rows_in_plans: {result['nonempty_outcome_rows_in_plans']}")
    print(f"deleted_nonempty_outcome_rows: {result['deleted_nonempty_outcome_rows']}")
    print(f"keep_promotions_to_nonempty: {result['keep_promotions_to_nonempty']}")
    print(f"deleted_forward_return_rows: {result['deleted_forward_return_rows']}")
    print(f"keep_promotions_to_forward_return: {result['keep_promotions_to_forward_return']}")
    print(f"before_total_rows: {result['before']['total_rows']}")
    print(f"before_scoped_rows: {result['before']['scoped_rows']}")
    print(f"before_nonempty_outcome_rows: {result['before']['nonempty_outcome_rows']}")
    print(f"before_forward_return_rows: {result['before']['forward_return_rows']}")
    if result.get("applied"):
        print(f"after_total_rows: {result['after']['total_rows']}")
        print(f"after_scoped_rows: {result['after']['scoped_rows']}")
        print(f"after_nonempty_outcome_rows: {result['after']['nonempty_outcome_rows']}")
        print(f"after_forward_return_rows: {result['after']['forward_return_rows']}")
        print(f"rows_deleted: {result['rows_deleted']}")
        print(f"conflict_groups_checked: {result['conflict_groups_checked']}")
        print("verifications: OK")
    else:
        print("apply: false (no se escribio en la BD)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compacta grupos historicos T6 sin conflicto en signal_outcomes.")
    parser.add_argument("--db", default=None, help="Ruta a la BD. Por defecto usa settings.")
    parser.add_argument("--conflicts", default=DEFAULT_CONFLICTS_PATH, help="JSON de grupos conflictivos a excluir.")
    parser.add_argument(
        "--max-created-at",
        default=None,
        help="Cutoff exclusivo de created_at para acotar el universo aprobado, ej. 2026-06-25T18:00:00+00:00.",
    )
    parser.add_argument("--apply", action="store_true", help="Aplica cambios. Por defecto solo dry-run.")
    parser.add_argument("--json", action="store_true", help="Imprime resultado JSON.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    result = run_migration(
        db_path,
        conflicts_path=args.conflicts,
        apply=bool(args.apply),
        max_created_at=args.max_created_at,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print_result(result)


if __name__ == "__main__":
    main()
