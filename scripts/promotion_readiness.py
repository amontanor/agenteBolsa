#!/usr/bin/env python3
"""Evaluate strict champion/challenger promotion readiness without applying changes."""

from __future__ import annotations

import argparse
import json


def main() -> int:
    from agente_bolsa.config import get_settings
    from agente_bolsa.continuous_improvement.promotion_readiness import evaluate_promotion_readiness
    from agente_bolsa.storage import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("--since-date", default="2026-04-01")
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    report = evaluate_promotion_readiness(settings, store, since_date=args.since_date)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
