"""Dry-run read-only para planificar la compactacion historica de signal_outcomes.

No escribe en la base de datos. Simula la regla de UPSERT introducida en T6:
para un mismo (signal_date, symbol, strategy), la fila mas reciente actualiza
metadatos; si su outcome_json es '{}', se preserva el outcome previo.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agente_bolsa._utils import sqlite_connect_ro, table_exists
from agente_bolsa.config import get_settings

DEFAULT_CONFLICTS_OUT = "docs/signal_outcomes_migration_conflicts_2026-06-25.json"


@dataclass(frozen=True)
class SignalOutcomeRow:
    signal_id: str
    source_run_id: str
    source: str
    symbol: str
    signal_date: str
    decision: str
    features: dict[str, Any]
    gate: dict[str, Any]
    outcome: dict[str, Any]
    created_at: str
    updated_at: str

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
class GroupPlan:
    key: tuple[str, str, str]
    row_count: int
    keep_signal_id: str
    keep_source_run_id: str
    delete_signal_ids: tuple[str, ...]
    final_outcome: dict[str, Any]
    nonempty_outcome_rows: int
    nonempty_outcome_rows_to_delete: int
    distinct_nonempty_outcomes: int
    has_conflict: bool


def _loads(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sort_key(row: SignalOutcomeRow) -> tuple[str, str, str]:
    return (row.updated_at or "", row.created_at or "", row.signal_id)


def _simulate_group(rows: list[SignalOutcomeRow]) -> GroupPlan:
    ordered = sorted(rows, key=_sort_key)
    keep = ordered[-1]
    final_outcome: dict[str, Any] = {}
    nonempty_outcomes: list[dict[str, Any]] = []
    for row in ordered:
        if row.outcome:
            final_outcome = row.outcome
            nonempty_outcomes.append(row.outcome)
    delete_ids = tuple(row.signal_id for row in ordered if row.signal_id != keep.signal_id)
    distinct_outcomes = {_canonical(outcome) for outcome in nonempty_outcomes}
    deleted_nonempty = sum(1 for row in ordered if row.signal_id != keep.signal_id and bool(row.outcome))
    return GroupPlan(
        key=keep.group_key,
        row_count=len(rows),
        keep_signal_id=keep.signal_id,
        keep_source_run_id=keep.source_run_id,
        delete_signal_ids=delete_ids,
        final_outcome=final_outcome,
        nonempty_outcome_rows=len(nonempty_outcomes),
        nonempty_outcome_rows_to_delete=deleted_nonempty,
        distinct_nonempty_outcomes=len(distinct_outcomes),
        has_conflict=len(distinct_outcomes) > 1,
    )


def build_migration_plan(rows: list[SignalOutcomeRow]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[SignalOutcomeRow]] = {}
    for row in rows:
        groups.setdefault(row.group_key, []).append(row)

    duplicate_plans = [
        _simulate_group(group_rows)
        for group_rows in groups.values()
        if len(group_rows) > 1
    ]
    conflict_plans = [plan for plan in duplicate_plans if plan.has_conflict]
    non_conflict_plans = [plan for plan in duplicate_plans if not plan.has_conflict]
    rows_to_delete = sum(plan.row_count - 1 for plan in duplicate_plans)
    rows_to_delete_safe = sum(plan.row_count - 1 for plan in non_conflict_plans)
    outcome_rows_to_merge = sum(plan.nonempty_outcome_rows_to_delete for plan in non_conflict_plans)
    conflict_deleted_outcome_rows = sum(plan.nonempty_outcome_rows_to_delete for plan in conflict_plans)
    return {
        "total_rows": len(rows),
        "total_groups": len(groups),
        "duplicate_groups": len(duplicate_plans),
        "rows_to_delete_if_compacted": rows_to_delete,
        "rows_to_delete_without_conflicts": rows_to_delete_safe,
        "nonempty_outcome_rows_to_merge_without_loss": outcome_rows_to_merge,
        "lost_outcome_rows_under_safe_rule": 0,
        "conflict_groups": len(conflict_plans),
        "conflict_deleted_nonempty_outcome_rows": conflict_deleted_outcome_rows,
        "plans": duplicate_plans,
        "conflicts": conflict_plans,
    }


def _row_from_record(record: dict[str, Any]) -> SignalOutcomeRow:
    return SignalOutcomeRow(
        signal_id=str(record["signal_id"]),
        source_run_id=str(record["source_run_id"]),
        source=str(record["source"]),
        symbol=str(record["symbol"]).upper(),
        signal_date=str(record["signal_date"])[:10],
        decision=str(record["decision"]),
        features=_loads(record["features_json"]),
        gate=_loads(record["gate_json"]),
        outcome=_loads(record["outcome_json"]),
        created_at=str(record["created_at"] or ""),
        updated_at=str(record["updated_at"] or ""),
    )


def load_signal_outcomes(db_path: str) -> list[SignalOutcomeRow]:
    connection = sqlite_connect_ro(db_path, timeout=30.0)
    try:
        if not table_exists(connection, "signal_outcomes"):
            return []
        records = connection.execute(
            """
            SELECT signal_id, source_run_id, source, symbol, signal_date,
                   decision, features_json, gate_json, outcome_json,
                   created_at, updated_at
            FROM signal_outcomes
            ORDER BY signal_date, symbol, updated_at, created_at, signal_id
            """
        ).fetchall()
    finally:
        connection.close()
    return [_row_from_record(dict(record)) for record in records]


def write_conflicts(path: str | Path, conflicts: list[GroupPlan]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "signal_date": plan.key[0],
            "symbol": plan.key[1],
            "strategy_name": plan.key[2],
            "row_count": plan.row_count,
            "keep_signal_id": plan.keep_signal_id,
            "keep_source_run_id": plan.keep_source_run_id,
            "delete_signal_ids": list(plan.delete_signal_ids),
            "nonempty_outcome_rows": plan.nonempty_outcome_rows,
            "nonempty_outcome_rows_to_delete": plan.nonempty_outcome_rows_to_delete,
            "distinct_nonempty_outcomes": plan.distinct_nonempty_outcomes,
        }
        for plan in conflicts
    ]
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def print_summary(summary: dict[str, Any], *, conflicts_out: str) -> None:
    print("\n=== signal_outcomes historical T6 migration dry-run (read-only) ===")
    print("Regla simulada: grupo=(signal_date, symbol, strategy_name); fila mas reciente conserva metadatos;")
    print("outcome_json se preserva si la escritura nueva trae '{}', y se marca conflicto si hay outcomes no vacios distintos.")
    print(f"filas totales: {summary['total_rows']}")
    print(f"grupos totales simbolo-dia-estrategia: {summary['total_groups']}")
    print(f"grupos duplicados: {summary['duplicate_groups']}")
    print(f"filas a eliminar si se compacta todo: {summary['rows_to_delete_if_compacted']}")
    print(f"filas a eliminar sin conflictos: {summary['rows_to_delete_without_conflicts']}")
    print(f"filas con outcome no vacio a fusionar sin perdida: {summary['nonempty_outcome_rows_to_merge_without_loss']}")
    print(f"filas con outcome que se perderian bajo la regla segura: {summary['lost_outcome_rows_under_safe_rule']}")
    print(f"grupos con conflicto humano: {summary['conflict_groups']}")
    print(f"filas outcome no vacio dentro de conflictos: {summary['conflict_deleted_nonempty_outcome_rows']}")
    print(f"conflictos escritos en: {conflicts_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run read-only de compactacion historica T6 para signal_outcomes.")
    parser.add_argument("--db", default=None, help="Ruta a la BD. Por defecto usa settings.")
    parser.add_argument("--conflicts-out", default=DEFAULT_CONFLICTS_OUT, help="JSON de grupos con conflicto.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or str(settings.database_path)
    rows = load_signal_outcomes(db_path)
    summary = build_migration_plan(rows)
    write_conflicts(args.conflicts_out, summary["conflicts"])
    print_summary(summary, conflicts_out=args.conflicts_out)


if __name__ == "__main__":
    main()
