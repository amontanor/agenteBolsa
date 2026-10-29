"""Fail-open CrewAI task observability for the advisory group."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from .agent_contribution import (
    SCHEMA_VERSION as CONTRIBUTION_SCHEMA_VERSION,
)
from .agent_contribution import (
    build_agent_contribution,
    extract_structured_contributions,
    persist_agent_contribution,
    summarize_agent_contributions,
)
from .agent_run import AgentRunTracker, safe_refs, sanitize_error
from .models import new_id

LOGGER = logging.getLogger(__name__)
TASK_SCHEMA_VERSION = "crew_task_execution.v2"


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _output_payload(output: Any) -> Any:
    for attr in ("json_dict", "raw", "output"):
        if hasattr(output, attr):
            value = getattr(output, attr)
            if value is not None:
                return _json_value(value)
    return _json_value(output)


class CrewTaskObserver:
    """Track one concrete run for every LLM-backed CrewAI task."""

    def __init__(
        self,
        store: Any,
        *,
        cycle_id: str,
        parent_run_id: str,
        model: str | None,
        candidate_ids: set[str] | None = None,
    ) -> None:
        self.store = store
        self.cycle_id = str(cycle_id)
        self.parent_run_id = str(parent_run_id)
        self.model = model
        self.candidate_ids = {str(item) for item in (candidate_ids or set()) if str(item).strip()}
        self._tasks: dict[tuple[str, str], dict[str, Any]] = {}
        self._task_ids: dict[str, tuple[str, str]] = {}
        self._task_roles: dict[tuple[str, str], tuple[str, str]] = {}
        self._contributions: list[dict[str, Any]] = []

    def _task_key(self, task_name: str, agent_name: str) -> tuple[str, str]:
        return str(task_name), str(agent_name)

    def bind_task_identity(self, task_name: str, agent_name: str, agent_role: str) -> None:
        """Map the CrewAI agent role back to the catalogue agent key (P-L178)."""

        self._task_roles[(str(task_name), str(agent_role))] = (str(task_name), str(agent_name))

    def resolve_task_identity(self, task_name: str, agent_role: str) -> tuple[str, str]:
        return self._task_roles.get((str(task_name), str(agent_role)), (str(task_name), str(agent_role)))

    def _record_event(self, task: dict[str, Any], status: str, **extra: Any) -> None:
        payload = {
            "schema_version": TASK_SCHEMA_VERSION,
            "cycle_id": self.cycle_id,
            "parent_run_id": self.parent_run_id,
            "agent_run_id": task["agent_run_id"],
            "agent_name": task["agent_name"],
            "task_name": task["task_name"],
            "layer": task["layer"],
            "status": status,
            "execution_start_observed": task["tracker"] is not None,
            "started_at": task["tracker"].started_at.isoformat() if task["tracker"] else None,
            "as_of": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        event_id = f"agent_task_execution:{task['agent_run_id']}:{status}"
        try:
            self.store.record_append_only_event(
                event_id=event_id,
                event_type="agent_task_execution",
                cycle_id=self.cycle_id,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - telemetry is fail-open by design.
            LOGGER.exception("No se pudo persistir observabilidad de tarea %s", task["task_name"])

    def register_task(
        self, task_name: str, agent_name: str, layer: str, *, task_id: str | None = None
    ) -> None:
        """Construction records no start event and makes no execution claim."""
        key = self._task_key(task_name, agent_name)
        if key in self._tasks:
            return
        self._tasks[key] = {
            "task_name": str(task_name),
            "agent_name": str(agent_name),
            "layer": str(layer),
            "agent_run_id": new_id("agent_run"),
            "tracker": None,
            "terminal": None,
            "output_hash": None,
            "contribution_count": 0,
        }
        if task_id is not None:
            self._task_ids[task_id] = key

    def on_execution_event(self, task_id: str | None, status: str, reason: Any = None) -> None:
        """Bind real CrewAI events by exact Task ID, never by role or text."""
        key = self._task_ids.get(task_id) if task_id else None
        if key is None:
            return
        task = self._tasks[key]
        if status == "started":
            self.on_task_start(*key, task["layer"])
        elif status == "error":
            self.on_task_failed(*key, reason)

    def on_task_start(self, task_name: str, agent_name: str, layer: str) -> None:
        self.register_task(task_name, agent_name, layer)
        task = self._tasks[self._task_key(task_name, agent_name)]
        if task["tracker"] is not None or task["terminal"] is not None:
            return
        task["tracker"] = AgentRunTracker(
            self.store,
            role=agent_name,
            agent_name=agent_name,
            task_name=task_name,
            cycle_id=self.cycle_id,
            execution_kind="llm",
            parent_run_id=self.parent_run_id,
            model=self.model,
            agent_run_id=task["agent_run_id"],
            input_refs=[self.cycle_id, f"task:{task_name}", f"agent:{agent_name}"],
        )
        self._record_event(task, "started")

    def _settle_tracker(self, task: dict[str, Any], action: str, reason: Any) -> str:
        """Finish a tracker without ever raising (P-L141).

        El tracker puede ser ya terminal por via directa (p. ej. __exit__
        marco failed) mientras la tarea del observer sigue abierta: ese fue
        el ValueError agent_run_terminal_conflict:failed->blocked que mato
        el ciclo del 17-sep. Se conserva el terminal real y se registra el
        intento superado; el observador jamas tumba el ciclo.
        """

        tracker = task.get("tracker")
        if tracker is None:
            return "no_tracker"
        try:
            if action == "block":
                tracker.block(reason=reason)
            elif action == "fail":
                tracker.fail(reason=reason, error_code="crew_task_failed")
            elif action == "skip":
                tracker.skip(reason=reason)
            else:
                tracker.succeed()
            return action
        except ValueError as exc:
            existing = getattr(tracker, "_terminal", None) or "unknown_terminal"
            self._record_event(task, f"{action}_superseded", reason=f"{reason}:{exc}")
            return str(existing)

    def on_task_complete(self, task_name: str, agent_name: str, output: Any) -> Any:
        key = self._task_key(task_name, agent_name)
        task = self._tasks.get(key)
        if task is None:
            self.register_task(task_name, agent_name, "unavailable")
            task = self._tasks[key]
        if task["terminal"] is not None:
            return output
        raw = _output_payload(output)
        encoded = json.dumps(raw, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        output_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        count = 0
        for item in extract_structured_contributions(raw):
            try:
                payload = build_agent_contribution(
                    item,
                    cycle_id=self.cycle_id,
                    agent_run_id=task["agent_run_id"],
                    agent_name=agent_name,
                    as_of=datetime.now(timezone.utc),
                )
                persist_agent_contribution(self.store, payload)
            except Exception:  # noqa: BLE001 - telemetry cannot break advisory execution.
                LOGGER.exception("No se pudo validar o persistir contribucion de %s", agent_name)
                continue
            self._contributions.append(payload)
            count += 1
        if task["tracker"] is not None:
            task["tracker"].add_outputs(output_refs=[f"crew-output:{output_hash}"])
            settled = self._settle_tracker(task, "succeed", None)
            task["terminal"] = "succeeded" if settled == "succeed" else settled
        else:
            task["terminal"] = "succeeded"
        task["output_hash"] = output_hash
        task["contribution_count"] = count
        self._record_event(task, "succeeded", output_hash=output_hash, contribution_count=count)
        return output

    def on_task_failed(self, task_name: str, agent_name: str, reason: Any) -> None:
        key = self._task_key(task_name, agent_name)
        task = self._tasks.get(key)
        if task is None:
            self.register_task(task_name, agent_name, "unavailable")
            task = self._tasks[key]
        if task["terminal"] is not None:
            return
        if task["tracker"] is not None:
            settled = self._settle_tracker(task, "fail", reason)
            if settled != "fail":
                task["terminal"] = settled
                self._record_event(task, settled, reason=sanitize_error(reason)[:500])
                return
        task["terminal"] = "failed"
        self._record_event(task, "failed", reason=sanitize_error(reason)[:500])

    def finalize(self, *, failed: bool = False, reason: str | None = None) -> dict[str, Any]:
        for task in self._tasks.values():
            if task["terminal"] is not None:
                continue
            if task["tracker"] is None:
                task["terminal"] = "skipped"
                self._record_event(task, "skipped", reason="task_not_executed")
            elif failed:
                settled = self._settle_tracker(task, "block", reason or "crew_failed")
                task["terminal"] = "blocked" if settled == "block" else settled
                self._record_event(task, task["terminal"], reason=reason or "crew_failed")
            else:
                settled = self._settle_tracker(task, "skip", "task_not_executed")
                task["terminal"] = "skipped" if settled == "skip" else settled
                self._record_event(task, task["terminal"], reason="task_not_executed")
        return self.summary()

    def summary(self) -> dict[str, Any]:
        run_payloads = []
        all_events = []
        try:
            all_events = self.store.agent_events(event_type_prefix="agent_run_", limit=50000)
        except Exception:  # noqa: BLE001
            pass
        for task in self._tasks.values():
            run_payloads.extend(
                row.get("payload") or {}
                for row in all_events
                if (row.get("payload") or {}).get("agent_run_id") == task["agent_run_id"]
                and str((row.get("payload") or {}).get("status") or "")
                in {"succeeded", "failed", "blocked", "skipped", "timeout"}
            )
        tasks = [
            {
                "task_name": task["task_name"],
                "agent_name": task["agent_name"],
                "layer": task["layer"],
                "agent_run_id": task["agent_run_id"],
                "status": task["terminal"] or ("started" if task["tracker"] else "not_started"),
                "execution_start_observed": task["tracker"] is not None,
                "output_hash": task["output_hash"],
                "contribution_count": task["contribution_count"],
            }
            for task in self._tasks.values()
        ]
        return {
            "schema_version": TASK_SCHEMA_VERSION,
            "contribution_schema_version": CONTRIBUTION_SCHEMA_VERSION,
            "cycle_id": self.cycle_id,
            "parent_run_id": self.parent_run_id,
            "tasks": tasks,
            "task_count": len(tasks),
            "terminal_count": sum(1 for task in tasks if task["status"] in {"succeeded", "failed", "blocked", "skipped", "timeout"}),
            "contribution_count": len(self._contributions),
            "agents": summarize_agent_contributions(
                self._contributions,
                run_payloads=run_payloads,
                candidate_ids=self.candidate_ids,
            ),
            "refs": safe_refs([self.cycle_id, self.parent_run_id]),
        }
