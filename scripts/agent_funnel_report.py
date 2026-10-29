"""Read-only funnel report for the continuous improvement lab.

Thin CLI wrapper over `agente_bolsa.continuous_improvement.agent_funnel`, so the
script and the `agent-funnel` command share one implementation.

Rules: SQLite is opened `mode=ro` with `PRAGMA query_only=ON`; no writes, no
network, no broker, no LLM. `0`, `null` and `unavailable` stay distinct.

Usage:

    python scripts/agent_funnel_report.py --json
    python scripts/agent_funnel_report.py --data-dir data --json
    python scripts/agent_funnel_report.py --scoreboard-json digest.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente_bolsa.continuous_improvement.agent_funnel import (  # noqa: E402
    build_report,
    format_summary,
    load_scoreboard,
    resolve_data_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=None, help="directorio de datos (default: DATA_DIR o ./data)")
    parser.add_argument("--scoreboard-json", default=None, help="JSON con agent_learning ya calculado")
    parser.add_argument("--json", action="store_true", help="salida JSON canonica")
    args = parser.parse_args(argv)
    report = build_report(
        resolve_data_dir(args.data_dir),
        scoreboard=load_scoreboard(args.scoreboard_json),
    )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
