#!/usr/bin/env python3
"""Print the paper profitability scoreboard as JSON."""

from __future__ import annotations

import argparse
import json

from agente_bolsa.config import get_settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.profitability_scoreboard import build_profitability_scoreboard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-date", default="2026-04-01")
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = build_profitability_scoreboard(settings, store, since_date=args.since_date)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
