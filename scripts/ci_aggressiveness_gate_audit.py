"""Retroactive audit for CI proposals that bypassed deterministic gates."""

from __future__ import annotations

import argparse
import json

from agente_bolsa.config import get_settings
from agente_bolsa.continuous_improvement.aggressiveness_gate import (
    reject_ready_aggressiveness_without_evidence,
    reject_ready_constitutional_holes,
)
from agente_bolsa.storage import Store


def run_audit(*, dry_run: bool) -> dict[str, object]:
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    if dry_run:
        return {"dry_run": True, "message": "Dry-run informativo; ejecuta sin --dry-run para persistir decisiones."}
    constitutional = reject_ready_constitutional_holes(store)
    aggressiveness = reject_ready_aggressiveness_without_evidence(store, settings=settings)
    return {
        "dry_run": False,
        "constitutional_rejected": constitutional,
        "aggressiveness_rejected": aggressiveness,
        "constitutional_count": len(constitutional),
        "aggressiveness_count": len(aggressiveness),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audita READY_TO_APPLY contra gates constitucionales y de agresividad.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run_audit(dry_run=args.dry_run), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
