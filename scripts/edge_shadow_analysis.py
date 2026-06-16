#!/usr/bin/env python3
"""Edge audit for executed paper buys and blocked backtest cohorts."""

from __future__ import annotations

import argparse
import json

from agente_bolsa.config import get_settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.edge_analysis import linked_executed_buy_signals, veto_forward_cohorts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-date", default="2026-04-01")
    args = parser.parse_args()

    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    executed = linked_executed_buy_signals(settings, store, since_date=args.since_date)
    vetoes = veto_forward_cohorts(settings, store, since_date=args.since_date)
    print(
        json.dumps(
            {
                "since_date": args.since_date,
                "executed_buy_linkage": {
                    "linked": len(executed["linked_rows"]),
                    "unmatched": len(executed["unmatched_order_ids"]),
                    "benchmark_points": executed["benchmark_points"],
                },
                "setup_quality_edge": executed["setup_quality"],
                "setup_key_edge": executed["setup_key"],
                "tag_edge": executed["tag"],
                "regime_edge": executed["regime"],
                "regime_note": "persisted market_regime is used first; missing historical rows fall back to benchmark trend regime.",
                "backtest_veto_forward": vetoes["by_reason"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
