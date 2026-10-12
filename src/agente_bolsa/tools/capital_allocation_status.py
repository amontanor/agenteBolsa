"""Read-only JSON status for allocation evidence; never approves/promotes."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.capital_allocation_policy import load_capital_allocation_policy
from agente_bolsa.tools.capital_allocation_shadow import EVENT_TYPE, shadow_content_hash


def allocation_status(settings: Settings, *, now: datetime | None = None, limit: int = 5000) -> dict[str, Any]:
    """Summarize canonical observations without treating sessions seen as complete."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
        raise ValueError("bounded_limit_required")
    reference = now or datetime.now(timezone.utc)
    if reference.utcoffset() is None:
        raise ValueError("clock_timezone_required")
    policy = load_capital_allocation_policy(settings.data_dir, settings, now=reference)
    out = {"schema_version": "capital-allocation-status.v1", "as_of": reference.isoformat(),
           "policy_hash": policy.get("policy_hash"), "policy_mode": policy.get("status"),
           "stage": policy.get("stage"), "active": policy.get("active") is True,
           "authority": "read_only_not_approval", "readiness": "collecting",
           "reasons": list(policy.get("reasons", [])), "canonical_events": 0,
           "conflict_events": 0, "invalid_events": 0, "verified_buy_identities": 0,
           "buy_recommendations": 0, "first_at": None, "last_at": None,
           "five_complete_sessions": "unavailable", "economic_superiority": "unavailable",
           "broker_protection_reconciliation": "unavailable", "saturated": False}
    if not settings.database_path.exists():
        out["reasons"].append("observation_database_absent")
        return out
    store = Store(settings.database_path, settings.agent_logs_dir)
    try:
        conn = store.read_connection()
        with closing(conn.execute("SELECT event_type,payload_json,created_at FROM agent_events WHERE event_type IN (?,?) ORDER BY created_at DESC LIMIT ?",
            (EVENT_TYPE, EVENT_TYPE + "_conflict", limit))) as cursor:
            rows_seen = 0
            for row in cursor:
                rows_seen += 1
                if row["event_type"] != EVENT_TYPE:
                    out["conflict_events"] += 1
                    continue
                try:
                    payload = json.loads(row["payload_json"])
                    if payload.get("policy_hash") != policy.get("policy_hash"):
                        continue
                    captured = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00"))
                    if captured.utcoffset() is None or captured > reference or shadow_content_hash(payload) != payload.get("content_hash"):
                        raise ValueError("invalid_shadow")
                except (ValueError, TypeError, KeyError):
                    out["invalid_events"] += 1
                    continue
                denominators = payload.get("denominators", {})
                verified = denominators.get("verified_buy_identities")
                total = denominators.get("buy_recommendations")
                if (type(verified) is not int or type(total) is not int
                        or not 0 <= verified <= total):
                    out["invalid_events"] += 1
                    continue
                out["canonical_events"] += 1
                out["verified_buy_identities"] += verified
                out["buy_recommendations"] += total
                text = captured.astimezone(timezone.utc).isoformat()
                out["first_at"] = min(out["first_at"] or text, text)
                out["last_at"] = max(out["last_at"] or text, text)
            out["saturated"] = rows_seen == limit
    except (sqlite3.Error, OSError, RuntimeError):
        out["readiness"] = "unavailable"
        out["reasons"].append("observation_database_unavailable")
    finally:
        store.close_read_connection()
    total = out["buy_recommendations"]
    out["identity_coverage"] = out["verified_buy_identities"] / total if total else None
    if out["saturated"]:
        out["reasons"].append("bounded_read_saturated")
    if out["conflict_events"] or out["invalid_events"]:
        out["reasons"].append("canonical_observation_conflicts_or_invalid")
    # Whole-session reconciliation and economic maturity come from the separate
    # reviewed receipt, never from a count of dates in this event stream.
    out["reasons"].append("reviewed_session_and_economic_receipt_required")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Estado read-only de capital en paper; no activa políticas.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    settings = Settings(_env_file=None, DATA_DIR=str(args.data_dir))
    print(json.dumps(allocation_status(settings), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
