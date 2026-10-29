"""Deterministic agent objective contracts for the improvement lab.

An objective contract states what one agent is judged by: the primary metric,
its explicit denominator, the maturity horizon, whether a same-cycle control is
required and the minimum sample before a value is reportable.

Rules this module enforces:

- Measurement only. A contract never decides readiness, never authorizes a
  change, never promotes a policy and never writes to storage.
- A zero denominator is `collecting`, never `0 %`: `unavailable` and zero are
  different facts.
- Missing or unwired sources stay `unavailable` with an explicit reason; the
  module never invents a metric.
- The output is deterministic for a frozen `now`, so it can be hashed.

The configuration lives in `<data_dir>/config/agent_objectives.json` and only
the operator (or an authorized lot) may change it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONFIG_RELPATH = ("config", "agent_objectives.json")
VALID_STATUSES = frozenset({"shadow", "guarded_active", "active", "retired", "unavailable"})
VALID_SOURCES = frozenset({"agent_learning", "proposal_funnel", "unavailable"})
VALID_DIRECTIONS = frozenset({"higher_is_better", "lower_is_better", "target_range"})

# Denomination fields understood by the evaluator, in scoreboard vocabulary.
SCOREBOARD_DENOMINATORS = frozenset(
    {"matured", "matured_with_control", "signals", "control_sets_verified"}
)


def config_path(data_dir: str | Path) -> Path:
    """Return the versioned objective-config path for one data directory."""

    return Path(data_dir).joinpath(*CONFIG_RELPATH)


def empty_config() -> dict[str, Any]:
    """Return the safe empty contract: no objectives, nothing evaluable."""

    return {"schema_version": SCHEMA_VERSION, "agents": [], "status": "unavailable"}


def load_agent_objectives(data_dir: str | Path) -> dict[str, Any]:
    """Load the objective contract, failing soft to an empty contract.

    A missing, unreadable or malformed file is telemetry-unavailable, not a
    crash: the lab keeps running and the report says why it cannot measure.
    """

    path = config_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {**empty_config(), "reason": "config_missing", "config_path": str(path)}
    except (OSError, ValueError) as exc:
        return {
            **empty_config(),
            "reason": "config_unreadable",
            "config_path": str(path),
            "error": repr(exc),
        }
    if not isinstance(raw, dict):
        return {**empty_config(), "reason": "config_not_object", "config_path": str(path)}
    agents = raw.get("agents")
    if not isinstance(agents, list):
        return {**empty_config(), "reason": "agents_not_list", "config_path": str(path)}
    return {
        "schema_version": int(raw.get("schema_version") or SCHEMA_VERSION),
        "status": str(raw.get("status") or "shadow"),
        "notes": str(raw.get("notes") or ""),
        "agents": [item for item in agents if isinstance(item, dict)],
        "config_path": str(path),
        "reason": "",
    }


def objective_by_agent(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the contract by exact agent name, keeping the last duplicate.

    Duplicates are a configuration defect; the funnel report surfaces the count
    instead of silently resolving them here.
    """

    indexed: dict[str, dict[str, Any]] = {}
    for item in config.get("agents") or []:
        name = str(item.get("agent") or "").strip()
        if name:
            indexed[name] = item
    return indexed


def duplicate_agents(config: dict[str, Any]) -> list[str]:
    """Return agent names declared more than once."""

    seen: set[str] = set()
    duplicates: list[str] = []
    for item in config.get("agents") or []:
        name = str(item.get("agent") or "").strip()
        if not name:
            continue
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    return duplicates


def _status_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_STATUSES else "unavailable"


def _source_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SOURCES else "unavailable"


def _direction_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_DIRECTIONS else "higher_is_better"


def _min_sample(value: Any, fallback: int = 30) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _scoreboard_entries(scoreboard: dict[str, Any], agent: str) -> list[dict[str, Any]]:
    rows = scoreboard.get("agents") if isinstance(scoreboard, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("agent_name") or "").strip() == agent
    ]


def _scoreboard_denominator(entries: Iterable[dict[str, Any]], field: str) -> int:
    total = 0
    for entry in entries:
        if field == "control_sets_verified":
            control = entry.get("comparable_control_sets")
            verified = control.get("verified") if isinstance(control, dict) else 0
            total += int(verified or 0)
            continue
        total += int(entry.get(field) or 0)
    return total


def _proposal_denominator(stats: dict[str, Any] | None, field: str) -> int:
    if not isinstance(stats, dict):
        return 0
    return int(stats.get(field) or 0)


def _evaluate_one(
    contract: dict[str, Any],
    scoreboard: dict[str, Any],
    proposal_stats: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    agent = str(contract.get("agent") or "").strip()
    status = _status_value(contract.get("status"))
    source = _source_value(contract.get("source"))
    direction = _direction_value(contract.get("direction"))
    denominator_field = str(contract.get("denominator") or "").strip()
    min_sample = _min_sample(contract.get("min_sample"))
    base = {
        "agent": agent,
        "primary_metric": str(contract.get("primary_metric") or ""),
        "denominator_field": denominator_field,
        "direction": direction,
        "min_sample": min_sample,
        "contract_status": status,
        "source": source,
        "require_same_cycle_control": bool(contract.get("require_control")),
        "maturity_horizon": str(contract.get("maturity_horizon") or ""),
    }
    if status in {"retired", "unavailable"}:
        return {
            **base,
            "status": status,
            "denominator": None,
            "sample_shortfall": None,
            "reason": "contract_not_measurable",
        }

    stats = (proposal_stats or {}).get(agent)
    if source == "agent_learning":
        if not isinstance(scoreboard, dict) or not scoreboard:
            return {**base, "status": "unavailable", "denominator": None, "sample_shortfall": None, "reason": "scoreboard_unavailable"}
        if denominator_field not in SCOREBOARD_DENOMINATORS:
            return {**base, "status": "unavailable", "denominator": None, "sample_shortfall": None, "reason": "denominator_not_supported"}
        entries = _scoreboard_entries(scoreboard, agent)
        if not entries:
            return {
                **base,
                "status": "unavailable",
                "denominator": 0,
                "sample_shortfall": min_sample,
                "reason": "agent_not_attributed",
            }
        denominator = _scoreboard_denominator(entries, denominator_field)
    elif source == "proposal_funnel":
        if stats is None:
            return {
                **base,
                "status": "unavailable",
                "denominator": None,
                "sample_shortfall": None,
                "reason": "proposal_stats_not_provided",
            }
        denominator = _proposal_denominator(stats, denominator_field)
    else:
        return {
            **base,
            "status": "unavailable",
            "denominator": None,
            "sample_shortfall": None,
            "reason": "metric_not_computable",
        }

    if denominator <= 0:
        return {
            **base,
            "status": "collecting",
            "denominator": 0,
            "sample_shortfall": min_sample,
            "reason": "denominator_zero",
        }
    if denominator < min_sample:
        return {
            **base,
            "status": "collecting",
            "denominator": denominator,
            "sample_shortfall": min_sample - denominator,
            "reason": "sample_below_minimum",
        }
    return {
        **base,
        "status": "available",
        "denominator": denominator,
        "sample_shortfall": 0,
        "reason": "",
    }


def evaluate_agent_objectives(
    scoreboard: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
    *,
    proposal_stats: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate every contract against canonical measurements.

    `scoreboard` is the output of `build_agent_learning_scoreboard`;
    `proposal_stats` is the per-agent funnel produced by the read-only report.
    Neither input is mutated and no value is inferred from free text.
    """

    contract = config or empty_config()
    board = scoreboard if isinstance(scoreboard, dict) else {}
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    evaluated: list[dict[str, Any]] = []
    for item in contract.get("agents") or []:
        if not isinstance(item, dict):
            continue
        evaluated.append(_evaluate_one(item, board, proposal_stats))
    counts: dict[str, int] = {}
    for row in evaluated:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    if not evaluated:
        status = "unavailable"
    elif counts.get("available"):
        status = "available" if not (counts.get("unavailable") or counts.get("collecting")) else "partial"
    elif counts.get("collecting"):
        status = "collecting"
    else:
        status = "unavailable"
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "agent_objectives",
        "measurement_only": True,
        "status": status,
        "generated_at": generated_at,
        "agents_total": len(evaluated),
        "agents": evaluated,
        "counts": dict(sorted(counts.items())),
        "duplicate_agents": duplicate_agents(contract),
        "config_path": str(contract.get("config_path") or ""),
        "config_reason": str(contract.get("reason") or ""),
    }
