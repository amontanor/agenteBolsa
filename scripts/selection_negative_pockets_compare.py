#!/usr/bin/env python3
"""Compare deterministic selection before/after negative-pocket penalties."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.tools.daily_learning import load_daily_learning_context
from agente_bolsa.tools.operational_health import load_operational_response_context
from agente_bolsa.tools.trade_decision import _select_deterministic_candidates


def _is_negative_pocket(candidate: dict) -> dict[str, bool]:
    technical = candidate.get("technical_state", {}) or {}
    chart_patterns = technical.get("chart_patterns", []) or []
    confirmed_pattern = any(
        item.get("bias") == "bullish" and item.get("status") == "confirmed"
        for item in chart_patterns
    )
    volume_z = technical.get("volume_zscore_20")
    sma20_distance = None
    close = technical.get("close")
    sma20 = technical.get("sma_20")
    try:
        if close and sma20:
            sma20_distance = (float(close) - float(sma20)) / float(sma20)
    except (TypeError, ValueError, ZeroDivisionError):
        sma20_distance = None
    rsi = technical.get("rsi_14")
    return {
        "confirmed_pattern": bool(confirmed_pattern),
        "volume_z_lt0": isinstance(volume_z, (int, float)) and float(volume_z) < 0.0,
        "sma20_dist_0_6pct": sma20_distance is not None and 0.0 <= sma20_distance < 0.06,
        "rsi_60_75": isinstance(rsi, (int, float)) and 60.0 <= float(rsi) < 75.0,
    }


def _summary(rows: list[dict]) -> dict:
    flagged = []
    counts = {"confirmed_pattern": 0, "volume_z_lt0": 0, "sma20_dist_0_6pct": 0, "rsi_60_75": 0}
    for row in rows:
        pockets = _is_negative_pocket(row)
        active = [key for key, value in pockets.items() if value]
        for key in active:
            counts[key] += 1
        if active:
            flagged.append(
                {
                    "symbol": row.get("symbol"),
                    "selection_score": row.get("selection_score"),
                    "selection_rank": row.get("selection_rank"),
                    "negative_pocket_penalty_total": row.get("negative_pocket_penalty_total"),
                    "active_pockets": active,
                }
            )
    return {"selected": len(rows), "flagged": len(flagged), "counts": counts, "symbols": flagged}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    data_dir = Path("data")
    report = json.loads((data_dir / "reports" / "latest_closed_market_technical_study.json").read_text(encoding="utf-8"))
    learning = load_daily_learning_context(data_dir)
    operational = load_operational_response_context(data_dir)

    settings_before = Settings(DATA_DIR=data_dir, SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=False)
    settings_after = Settings(DATA_DIR=data_dir, SELECTION_NEGATIVE_POCKET_PENALTY_ENABLED=True)
    limit = int(args.limit or settings_after.max_daily_buy_orders)
    before, _ = _select_deterministic_candidates(
        report.get("all_candidates", []) or [],
        learning,
        operational,
        limit=limit,
        settings=settings_before,
    )
    after, _ = _select_deterministic_candidates(
        report.get("all_candidates", []) or [],
        learning,
        operational,
        limit=limit,
        settings=settings_after,
    )
    print(
        json.dumps(
            {
                "limit": limit,
                "before": _summary(before),
                "after": _summary(after),
                "before_symbols": [row.get("symbol") for row in before],
                "after_symbols": [row.get("symbol") for row in after],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
