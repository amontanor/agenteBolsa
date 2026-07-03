"""Estudio read-only del coste de tokens del LLM de decision (P29).

No cambia ningun prompt ni flujo de trading: solo mide desde `llm_usage` y
`order_plans` para responder: cuantos tokens cuesta cada llamada de decision,
como se distribuyen, y cuantos tokens cuesta cada plan de orden producido.

Uso (desde la raiz del proyecto, con el venv):

    python scripts/study_decision_token_cost.py --days 14
    python scripts/study_decision_token_cost.py --days 14 --json-out data/reports/decision_token_cost.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path("data/state/agente_bolsa.sqlite3")


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct * (len(ordered) - 1)))))
    return ordered[index]


def build_report(db_path: Path, days: int) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT created_at, request_count, prompt_tokens, completion_tokens, total_tokens
        FROM llm_usage
        WHERE created_at >= ?
          AND (source = 'trade_decision' OR role = 'decision')
        ORDER BY created_at
        """,
        (cutoff,),
    ).fetchall()
    plans = con.execute(
        "SELECT COUNT(*) AS n FROM order_plans WHERE created_at >= ?",
        (cutoff,),
    ).fetchone()
    con.close()

    per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "prompt": 0, "completion": 0, "total": 0})
    prompt_sizes: list[int] = []
    totals = {"calls": 0, "requests": 0, "prompt": 0, "completion": 0, "total": 0}
    for row in rows:
        day = str(row["created_at"])[:10]
        bucket = per_day[day]
        bucket["calls"] += 1
        bucket["prompt"] += int(row["prompt_tokens"] or 0)
        bucket["completion"] += int(row["completion_tokens"] or 0)
        bucket["total"] += int(row["total_tokens"] or 0)
        prompt_sizes.append(int(row["prompt_tokens"] or 0))
        totals["calls"] += 1
        totals["requests"] += int(row["request_count"] or 0)
        totals["prompt"] += int(row["prompt_tokens"] or 0)
        totals["completion"] += int(row["completion_tokens"] or 0)
        totals["total"] += int(row["total_tokens"] or 0)

    plan_count = int(plans["n"] or 0) if plans else 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "cutoff": cutoff,
        "totals": totals,
        "prompt_tokens_per_call": {
            "avg": int(totals["prompt"] / totals["calls"]) if totals["calls"] else 0,
            "p50": _percentile(prompt_sizes, 0.50),
            "p90": _percentile(prompt_sizes, 0.90),
            "max": max(prompt_sizes) if prompt_sizes else 0,
        },
        "order_plans_in_window": plan_count,
        "tokens_per_order_plan": int(totals["total"] / plan_count) if plan_count else None,
        "tokens_per_call": int(totals["total"] / totals["calls"]) if totals["calls"] else 0,
        "per_day": dict(sorted(per_day.items())),
    }


def format_report(report: dict) -> str:
    totals = report["totals"]
    ppc = report["prompt_tokens_per_call"]
    lines = [
        f"Coste de tokens del LLM de decision - ultimos {report['window_days']} dias",
        "",
        f"- llamadas: {totals['calls']} (requests: {totals['requests']})",
        f"- tokens: prompt={totals['prompt']:,} completion={totals['completion']:,} total={totals['total']:,}",
        f"- prompt/llamada: avg={ppc['avg']:,} p50={ppc['p50']:,} p90={ppc['p90']:,} max={ppc['max']:,}",
        f"- tokens/llamada (total): {report['tokens_per_call']:,}",
        f"- order_plans en ventana: {report['order_plans_in_window']}",
        (
            f"- tokens por plan de orden producido: {report['tokens_per_order_plan']:,}"
            if report["tokens_per_order_plan"] is not None
            else "- tokens por plan de orden producido: n/d (0 planes en ventana)"
        ),
        "",
        "| Dia | Llamadas | Prompt | Completion | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for day, bucket in report["per_day"].items():
        lines.append(
            f"| {day} | {bucket['calls']} | {bucket['prompt']:,} | {bucket['completion']:,} | {bucket['total']:,} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.db, max(1, args.days))
    print(format_report(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON escrito en {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
