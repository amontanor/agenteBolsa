"""Append-only lifecycle telemetry for central agent executions."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Literal

from .agent_registry import canonical_agent_id
from .models import AgentEvent, new_id

SCHEMA_VERSION = "p-l29b.agent-run.v1"
AGENT_PRODUCER_SCHEMA_VERSION = "p-l101.agent-producer.v1"
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "timeout", "skipped", "blocked"})
EXECUTION_KINDS = frozenset({"deterministic", "llm", "fallback", "human", "system"})
ORPHAN_TTL = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)
_SECRET_RE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"
)


def sanitize_error(value: Any) -> str:
    """Remove common credential shapes and cap diagnostic payload size."""

    text = str(value or "")[:2000]
    return _SECRET_RE.sub(
        lambda match: (match.group(1) or match.group(2) or "") + "[REDACTED]", text
    )


def safe_refs(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    """Keep only compact identifiers, hashes and safe relative paths."""

    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip().replace("\\", "/")
        if not text or len(text) > 300 or text.startswith(("/", "~")) or ".." in text.split("/"):
            continue
        if any(
            marker in text.lower() for marker in ("api_key=", "authorization:", "bearer ", ".env")
        ):
            continue
        result.append(text)
    return list(dict.fromkeys(result))


def safe_data_ref(value: Any, *, data_dir: Any) -> str | None:
    """Return a report path relative to the configured data root.

    Runtime reports are often absolute paths on Linux (for example
    ``/data/reports/report.json``).  Telemetry must keep the useful report
    identity without persisting arbitrary absolute filesystem paths.
    """

    text = str(value or "").strip().replace("\\", "/")
    root = str(data_dir or "").strip().replace("\\", "/").rstrip("/")
    if not text or not root:
        return None
    if text == root:
        return None
    prefix = f"{root}/"
    if text.startswith(prefix):
        relative = text[len(prefix) :]
    elif text.startswith("/"):
        # Unknown absolute roots are reduced to a basename; never leak the
        # host path into append-only lifecycle telemetry.
        relative = text.rsplit("/", 1)[-1]
    else:
        relative = text
    return safe_refs([relative])[0] if safe_refs([relative]) else None


class AgentRunTracker:
    """Best-effort, exactly-once lifecycle writer backed by AgentEvent."""

    def __init__(
        self,
        store: Any,
        *,
        role: str,
        task_name: str,
        execution_kind: str,
        cycle_id: str | None = None,
        agent_name: str | None = None,
        agent_run_id: str | None = None,
        parent_run_id: str | None = None,
        retry_of: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_refs: list[Any] | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        if execution_kind not in EXECUTION_KINDS:
            raise ValueError(f"execution_kind_invalid:{execution_kind}")
        if execution_kind == "fallback" and not str(fallback_reason or "").strip():
            raise ValueError("fallback_reason_required")
        self.store = store
        self.agent_run_id = agent_run_id or new_id("agent_run")
        self.role = str(role).strip()
        self.agent_name = str(agent_name or role).strip()
        self.task_name = str(task_name).strip()
        self.cycle_id = cycle_id
        self.execution_kind = execution_kind
        self.parent_run_id = parent_run_id
        self.retry_of = retry_of
        self.provider = provider
        self.model = model
        self.input_refs = safe_refs(input_refs)
        self.output_refs: list[str] = []
        self.finding_ids: list[str] = []
        self.proposal_ids: list[str] = []
        self.llm_calls = 0
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.estimated_cost: float | None = None
        self.fallback_reason = sanitize_error(fallback_reason) or None
        self.started_at = datetime.now(timezone.utc)
        self._monotonic_started = time.monotonic()
        self._terminal: str | None = None
        self.effective_execution_kind = execution_kind
        self.start_event_id = new_id("evt")
        existing = self._existing_run_events()
        starts = [item for item in existing if item.get("event_type") == "agent_run_started"]
        terminals = [
            item
            for item in existing
            if str(item.get("event_type") or "").removeprefix("agent_run_") in TERMINAL_STATUSES
        ]
        if starts:
            prior = starts[-1]
            payload = prior.get("payload") or {}
            identity = (
                "role",
                "agent_name",
                "task_name",
                "cycle_id",
                "execution_kind",
                "provider",
                "model",
            )
            current = self._payload("started")
            if any(payload.get(key) != current.get(key) for key in identity):
                self._emit("agent_run_conflict", "started", reason="incompatible_duplicate_start")
                raise ValueError("agent_run_start_conflict")
            self.start_event_id = str(prior.get("event_id"))
            parsed = _parse_utc(payload.get("started_at"))
            if parsed:
                self.started_at = parsed
        else:
            self._emit("agent_run_started", "started", event_id=self.start_event_id)
        if terminals:
            self._terminal = str((terminals[-1].get("payload") or {}).get("status") or "") or None

    def __enter__(self) -> AgentRunTracker:
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, _traceback: Any) -> bool:
        if self._terminal is None:
            if exc is None:
                self.succeed()
            elif isinstance(exc, TimeoutError):
                self.timeout(reason=exc)
            else:
                self.fail(reason=exc)
        return False

    def add_outputs(
        self,
        *,
        output_refs: list[Any] | None = None,
        finding_ids: list[Any] | None = None,
        proposal_ids: list[Any] | None = None,
        llm_calls: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self.output_refs = safe_refs([*self.output_refs, *(output_refs or [])])
        self.finding_ids = safe_refs([*self.finding_ids, *(finding_ids or [])])
        self.proposal_ids = safe_refs([*self.proposal_ids, *(proposal_ids or [])])
        if llm_calls is not None:
            self.llm_calls = max(0, int(llm_calls))
        if input_tokens is not None:
            self.input_tokens = _nullable_nonnegative_int(input_tokens)
        if output_tokens is not None:
            self.output_tokens = _nullable_nonnegative_int(output_tokens)

    def producer_contract(self) -> dict[str, Any]:
        """Return the exact producer identity for downstream signal carriers."""

        return {
            "schema_version": AGENT_PRODUCER_SCHEMA_VERSION,
            "canonical_agent_id": canonical_agent_id(self.agent_name),
            "raw_role": self.role,
            "agent_run_id": self.agent_run_id,
            "cycle_id": self.cycle_id,
            "execution_kind": self.effective_execution_kind,
            "provider": self.provider,
            "model": self.model,
            "parent_run_id": self.parent_run_id,
            "retry_of": self.retry_of,
            "fallback_reason": self.fallback_reason,
        }

    def set_effective_identity(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        execution_kind: str | None = None,
    ) -> None:
        """Attach the identity actually resolved before terminal persistence."""

        if self._terminal is not None:
            raise ValueError("agent_run_identity_after_terminal")
        if provider is not None:
            self.provider = str(provider).strip() or None
        if model is not None:
            self.model = str(model).strip() or None
        if execution_kind is not None:
            if execution_kind not in EXECUTION_KINDS:
                raise ValueError(f"execution_kind_invalid:{execution_kind}")
            self.effective_execution_kind = execution_kind

    def succeed(self, *, reason: Any = None) -> None:
        self._finish("succeeded", reason=reason)

    def fail(self, *, reason: Any, error_code: str | None = None) -> None:
        self._finish("failed", reason=reason, error_code=error_code)

    def timeout(self, *, reason: Any, error_code: str | None = "timeout") -> None:
        self._finish("timeout", reason=reason, error_code=error_code)

    def skip(self, *, reason: Any) -> None:
        self._finish("skipped", reason=reason)

    def block(self, *, reason: Any) -> None:
        self._finish("blocked", reason=reason)

    def fallback_started(self, *, reason: Any) -> None:
        """Record a linked fallback without pretending it is an independent run."""
        self.fallback_reason = sanitize_error(reason) or "fallback"
        self._emit("agent_run_fallback_started", self._terminal or "started", reason=reason)

    def _finish(self, status: str, *, reason: Any = None, error_code: str | None = None) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"terminal_status_invalid:{status}")
        if self._terminal is not None:
            if self._terminal == status:
                return
            self._emit("agent_run_conflict", status, reason=f"existing_terminal:{self._terminal}")
            raise ValueError(f"agent_run_terminal_conflict:{self._terminal}->{status}")
        self._terminal = status
        self._emit(
            f"agent_run_{status}", status, reason=reason, error_code=error_code, terminal=True
        )

    def _payload(
        self,
        status: str,
        *,
        reason: Any = None,
        error_code: str | None = None,
        terminal: bool = False,
    ) -> dict[str, Any]:
        finished_at = datetime.now(timezone.utc) if terminal else None
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_run_id": self.agent_run_id,
            "parent_run_id": self.parent_run_id,
            "retry_of": self.retry_of,
            "role": self.role,
            "agent_name": self.agent_name,
            "task_name": self.task_name,
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat() if finished_at else None,
            "duration_seconds": max(0.0, time.monotonic() - self._monotonic_started)
            if terminal
            else None,
            "status": status,
            "execution_kind": self.execution_kind,
            "effective_execution_kind": self.effective_execution_kind,
            "provider": self.provider,
            "model": self.model,
            "input_refs": self.input_refs,
            "output_refs": self.output_refs,
            "finding_ids": self.finding_ids,
            "proposal_ids": self.proposal_ids,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "fallback_reason": self.fallback_reason,
            "error_code": sanitize_error(error_code) or None,
            "reason": sanitize_error(reason) or None,
        }

    def _emit(
        self,
        event_type: str,
        status: str,
        *,
        event_id: str | None = None,
        reason: Any = None,
        error_code: str | None = None,
        terminal: bool = False,
    ) -> None:
        try:
            self.store.record_agent_event(
                AgentEvent(
                    event_id=event_id or new_id("evt"),
                    agent=self.agent_name,
                    event_type=event_type,
                    cycle_id=self.cycle_id,
                    payload=self._payload(
                        status, reason=reason, error_code=error_code, terminal=terminal
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - telemetry cannot change the main result.
            LOGGER.exception("agent_run telemetry persistence failed for %s", self.agent_run_id)

    def _existing_run_events(self) -> list[dict[str, Any]]:
        try:
            return [
                row
                for row in self.store.agent_events(
                    event_type_prefix="agent_run_",
                    agent_run_id=self.agent_run_id,
                    limit=None,
                )
                if (row.get("payload") or {}).get("agent_run_id") == self.agent_run_id
            ]
        except Exception:  # noqa: BLE001 - lookup is best-effort telemetry only.
            return []


def build_agent_run_productivity(
    store: Any, *, now: datetime | None = None, orphan_ttl: timedelta = ORPHAN_TTL
) -> dict[str, Any]:
    """Reconstruct new run events without interpreting historical AgentEvents."""

    run_states: dict[str, dict[str, Any]] = {}
    event_rows_read = 0
    event_iterator = getattr(store, "iter_agent_events", None)
    rows = (
        event_iterator(event_type_prefix="agent_run_", limit=None)
        if callable(event_iterator)
        else store.agent_events(event_type_prefix="agent_run_", limit=None)
    )
    for row in rows:
        event_rows_read += 1
        payload = row.get("payload") or {}
        if payload.get("schema_version") != SCHEMA_VERSION or not payload.get("agent_run_id"):
            continue
        run_id = str(payload["agent_run_id"])
        event_type = str(row.get("event_type") or "")
        state = run_states.setdefault(
            run_id,
            {
                "starts": 0,
                "terminals": 0,
                "latest_start": None,
                "latest_terminal": None,
                "latest_payload": None,
                "fallback": False,
            },
        )
        state["latest_payload"] = payload
        if event_type == "agent_run_started":
            state["starts"] += 1
            state["latest_start"] = payload
        elif event_type.removeprefix("agent_run_") in TERMINAL_STATUSES:
            state["terminals"] += 1
            state["latest_terminal"] = payload
        elif event_type == "agent_run_fallback_started":
            state["fallback"] = True
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    runs: list[dict[str, Any]] = []
    orphan_runs = invalid_runs = 0
    for run_id in list(run_states):
        state = run_states.pop(run_id)
        starts = int(state["starts"])
        terminals = int(state["terminals"])
        source = (
            state["latest_terminal"]
            or state["latest_start"]
            or state["latest_payload"]
            or {}
        )
        started_at = _parse_utc(source.get("started_at"))
        old_open = bool(
            starts and not terminals and started_at and current - started_at > orphan_ttl
        )
        invalid = not starts or starts > 1 or terminals > 1
        orphan_runs += old_open
        invalid_runs += invalid
        fallback = source.get("execution_kind") == "fallback" or bool(state["fallback"])
        raw_role = str(source.get("role") or "unknown").strip() or "unknown"
        canonical_role = canonical_agent_id(raw_role)
        runs.append(
            {
                **source,
                "agent_run_id": run_id,
                # Keep the event identity untouched while exposing the
                # canonical registry identity to report consumers.
                "role_raw": raw_role,
                "canonical_role": canonical_role,
                "open": bool(starts and not terminals),
                "orphan": old_open,
                "invalid": invalid,
                "fallback": fallback,
            }
        )
    terminal = [item for item in runs if item.get("status") in TERMINAL_STATUSES]
    durations = sorted(
        float(item["duration_seconds"])
        for item in terminal
        if isinstance(item.get("duration_seconds"), (int, float))
    )
    by_role: dict[str, dict[str, Any]] = {}
    for item in runs:
        role = str(
            item.get("canonical_role")
            or item.get("role_raw")
            or item.get("role")
            or "unknown"
        )
        role = role.strip() or "unknown"
        raw_role = (
            str(item.get("role_raw") or item.get("role") or "unknown").strip()
            or "unknown"
        )
        bucket = by_role.setdefault(
            role,
            {
                "runs": 0,
                "states": {},
                "durations": [],
                "outputs": 0,
                "findings": 0,
                "proposals": 0,
                "fallbacks": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "tokens_available_runs": 0,
                "execution_kinds": {},
                "empty_outputs": 0,
                "empty_success_outputs": 0,
                "raw_roles": {},
            },
        )
        bucket["runs"] += 1
        bucket["raw_roles"][raw_role] = bucket["raw_roles"].get(raw_role, 0) + 1
        state = str(item.get("status") or "started")
        bucket["states"][state] = bucket["states"].get(state, 0) + 1
        execution_kind = str(
            item.get("effective_execution_kind") or item.get("execution_kind") or "unknown"
        )
        bucket["execution_kinds"][execution_kind] = (
            bucket["execution_kinds"].get(execution_kind, 0) + 1
        )
        if isinstance(item.get("duration_seconds"), (int, float)):
            bucket["durations"].append(float(item["duration_seconds"]))
        bucket["outputs"] += len(item.get("output_refs") or [])
        bucket["findings"] += len(item.get("finding_ids") or [])
        bucket["proposals"] += len(item.get("proposal_ids") or [])
        bucket["empty_outputs"] += state in TERMINAL_STATUSES and not (
            item.get("output_refs") or item.get("finding_ids") or item.get("proposal_ids")
        )
        bucket["empty_success_outputs"] += state == "succeeded" and not (
            item.get("output_refs") or item.get("finding_ids") or item.get("proposal_ids")
        )
        bucket["fallbacks"] += bool(item.get("fallback"))
        if item.get("input_tokens") is not None or item.get("output_tokens") is not None:
            bucket["tokens_available_runs"] += 1
            bucket["input_tokens"] += int(item.get("input_tokens") or 0)
            bucket["output_tokens"] += int(item.get("output_tokens") or 0)
    rendered_roles = {}
    for role, bucket in by_role.items():
        role_durations = sorted(bucket.pop("durations"))
        rendered_roles[role] = {
            **bucket,
            "median_duration": median(role_durations) if role_durations else None,
            "p95_duration": _percentile(role_durations, 0.95),
        }
    statuses = {
        status: sum(item.get("status") == status for item in runs) for status in TERMINAL_STATUSES
    }
    closed = len(terminal)
    runs_by_id = {str(item.get("agent_run_id")): item for item in runs}
    recovered_fallback_runs = sum(
        1
        for item in runs
        if item.get("execution_kind") == "fallback"
        and item.get("status") == "succeeded"
        and (runs_by_id.get(str(item.get("parent_run_id"))) or {}).get("status") == "failed"
    )
    attributed = sum(bool(item.get("proposal_ids")) for item in runs)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_rows_read": event_rows_read,
        "events_truncated": False,
        "total_runs": len(runs),
        "terminal_runs": closed,
        "open_runs": sum(bool(item.get("open")) for item in runs),
        "orphan_runs": orphan_runs,
        "invalid_runs": invalid_runs,
        **statuses,
        "fallback_runs": sum(bool(item.get("fallback")) for item in runs),
        "recovered_fallback_runs": recovered_fallback_runs,
        "success_rate": round(statuses["succeeded"] / closed, 4) if closed else None,
        "failure_rate": round(statuses["failed"] / closed, 4) if closed else None,
        "fallback_rate": round(sum(bool(item.get("fallback")) for item in runs) / len(runs), 4)
        if runs
        else None,
        "empty_output_count": sum(
            not (item.get("output_refs") or item.get("finding_ids") or item.get("proposal_ids"))
            for item in terminal
        ),
        "empty_success_output_count": sum(
            item.get("status") == "succeeded"
            and not (item.get("output_refs") or item.get("finding_ids") or item.get("proposal_ids"))
            for item in terminal
        ),
        "median_duration": median(durations) if durations else None,
        "p95_duration": _percentile(durations, 0.95),
        "runs_with_findings": sum(bool(item.get("finding_ids")) for item in runs),
        "runs_with_proposals": attributed,
        "attribution_link_coverage": round(attributed / len(runs), 4) if runs else None,
        "role_normalization": {
            "scheme": "canonical_agent_id_crosswalk_v1",
            "raw_field": "role",
            "canonical_field": "canonical_role",
        },
        "runs_by_role": rendered_roles,
    }


def _nullable_nonnegative_int(value: Any) -> int | None:
    return None if value is None else max(0, int(value))


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: list[float], fraction: Literal[0.95]) -> float | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int((len(values) * fraction) + 0.999999) - 1))
    return values[index]
