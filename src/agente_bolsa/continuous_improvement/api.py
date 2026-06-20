"""HTTP API for the continuous improvement lab."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agente_bolsa.config import get_settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_health import build_production_health_report

from .experiments import AutoApplyCodeAgent
from .orchestrator import ContinuousImprovementOrchestrator
from .runtime import ContinuousImprovementLabRuntime

BASE_PATH = "/api/continuous-improvement"


def _store() -> Store:
    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _runtime() -> ContinuousImprovementLabRuntime:
    settings = get_settings()
    return ContinuousImprovementLabRuntime(settings, _store())


def status_payload() -> dict[str, Any]:
    settings = get_settings()
    store = _store()
    runtime_state = store.continuous_improvement_runtime_state()
    initiatives = store.continuous_improvement_initiatives(limit=500)
    open_initiatives = [item for item in initiatives if item.get("status") in {"OPEN", "ANALYZING", "EXPERIMENTING"}]
    validating_initiatives = [item for item in initiatives if item.get("status") == "VALIDATING"]
    review_initiatives = [item for item in initiatives if item.get("status") == "WAITING_REVIEW"]
    ready_initiatives = [item for item in initiatives if item.get("status") == "READY_TO_APPLY"]
    monitoring_initiatives = [item for item in initiatives if item.get("status") == "MONITORING"]
    applied_changes = store.continuous_improvement_applied_changes(limit=500)
    committee_decisions = store.continuous_improvement_decisions(actor="DecisionCommitteeAgent", limit=500)
    decision_counts: dict[str, int] = {}
    backlog_buckets: dict[str, int] = {}
    for item in committee_decisions:
        decision_counts[str(item.get("decision") or "UNKNOWN")] = decision_counts.get(str(item.get("decision") or "UNKNOWN"), 0) + 1
        bucket = str(((item.get("payload") or {}).get("committee_decision") or {}).get("backlog_bucket") or "UNKNOWN")
        backlog_buckets[bucket] = backlog_buckets.get(bucket, 0) + 1
    return {
        "enabled": settings.continuous_improvement_enabled,
        "dry_run": settings.improvement_dry_run,
        "llm_enabled": settings.improvement_llm_enabled,
        "llm_provider": settings.improvement_llm_provider,
        "llm_model": settings.improvement_llm_model,
        "llm_orchestrator_model": settings.improvement_llm_orchestrator_model,
        "allow_auto_apply": settings.allow_auto_apply_improvements,
        "allow_live_trading": settings.allow_live_trading,
        "latest_cycle": store.latest_continuous_improvement_cycle(),
        "runtime": runtime_state,
        "initiatives_open": len(open_initiatives),
        "initiatives_validating": len(validating_initiatives),
        "initiatives_review": len(review_initiatives),
        "initiatives_ready_to_apply": len(ready_initiatives),
        "initiatives_monitoring": len(monitoring_initiatives),
        "committee_decisions": decision_counts,
        "backlog_buckets": backlog_buckets,
        "events_pending": len(store.continuous_improvement_events(statuses=["DISCOVERED", "PLANNED"], limit=500)),
        "tasks_pending": len(
            store.continuous_improvement_tasks(
                statuses=["DISCOVERED", "WAITING_DEPENDENCY", "ASSIGNED", "RUNNING"],
                limit=500,
            )
        ),
        "pending_proposals": len(store.continuous_improvement_proposals(status="PENDING", limit=1000)),
        "review_proposals": 0,
        "applied_changes": len([item for item in applied_changes if item.get("status") == "APPLIED"]),
        "blocked_changes": len([item for item in applied_changes if item.get("status") == "BLOCKED"]),
        "rolled_back_changes": len([item for item in applied_changes if item.get("status") == "ROLLED_BACK"]),
    }


def production_health_payload() -> dict[str, Any]:
    settings = get_settings()
    store = _store()
    report = build_production_health_report(
        settings,
        store,
        settings.data_dir / "reports",
        "api_health",
    )
    return report


def run_cycle_background() -> dict[str, Any]:
    settings = get_settings()
    store = _store()

    def _target() -> None:
        ContinuousImprovementOrchestrator(settings, store).run_cycle(mode="api")

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return {"queued": True, "mode": "run_once"}


def enqueue_event_background(*, event_type: str, domain: str, source: str, payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime()
    result = runtime.enqueue_event(
        event_type=event_type,
        source=source,
        domain=domain,
        payload=payload,
        force_unique=True,
    )
    return {"queued": True, "inserted": result.get("inserted"), "event": result.get("event")}


class ContinuousImprovementApiHandler(BaseHTTPRequestHandler):
    server_version = "ContinuousImprovementApi/2.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        store = _store()
        runtime = _runtime()
        if path in {f"{BASE_PATH}/health", f"{BASE_PATH}/production-health"}:
            self._json(200, production_health_payload())
            return
        if path == f"{BASE_PATH}/status" or path == f"{BASE_PATH}/lab/status":
            self._json(200, status_payload())
            return
        if path == f"{BASE_PATH}/agents":
            self._json(200, {"agents": runtime.describe_agents()})
            return
        if path == f"{BASE_PATH}/initiatives":
            self._json(200, {"initiatives": store.continuous_improvement_initiatives(limit=int((query.get("limit") or ["200"])[0]))})
            return
        if path.startswith(f"{BASE_PATH}/initiatives/") and path.endswith("/messages"):
            initiative_id = path.split("/")[-2]
            self._json(
                200,
                {
                    "messages": store.continuous_improvement_initiative_messages(
                        initiative_id=initiative_id,
                        limit=int((query.get("limit") or ["200"])[0]),
                    )
                },
            )
            return
        if path.startswith(f"{BASE_PATH}/initiatives/"):
            initiative_id = path.rsplit("/", 1)[-1]
            initiative = store.continuous_improvement_initiative(initiative_id)
            self._json(200 if initiative else 404, initiative or {"error": "not_found"})
            return
        if path == f"{BASE_PATH}/events":
            statuses = query.get("status")
            self._json(200, {"events": store.continuous_improvement_events(statuses=statuses, limit=int((query.get("limit") or ["100"])[0]))})
            return
        if path == f"{BASE_PATH}/tasks":
            statuses = query.get("status")
            self._json(200, {"tasks": store.continuous_improvement_tasks(statuses=statuses, limit=int((query.get("limit") or ["200"])[0]))})
            return
        if path == f"{BASE_PATH}/hypotheses":
            self._json(200, {"hypotheses": store.continuous_improvement_hypotheses(status=(query.get("status") or [None])[0], limit=int((query.get("limit") or ["200"])[0]))})
            return
        if path == f"{BASE_PATH}/cycles":
            self._json(200, {"cycles": store.continuous_improvement_cycles(limit=int((query.get("limit") or ["50"])[0]))})
            return
        if path.startswith(f"{BASE_PATH}/cycles/"):
            cycle_id = path.rsplit("/", 1)[-1]
            cycle = store.continuous_improvement_cycle(cycle_id)
            self._json(200 if cycle else 404, cycle or {"error": "not_found"})
            return
        if path == f"{BASE_PATH}/proposals":
            self._json(200, {"proposals": store.continuous_improvement_proposals(status=(query.get("status") or [None])[0], limit=int((query.get("limit") or ["200"])[0]))})
            return
        if path == f"{BASE_PATH}/decisions":
            self._json(
                200,
                {
                    "decisions": store.continuous_improvement_decisions(
                        actor=(query.get("actor") or [None])[0],
                        limit=int((query.get("limit") or ["200"])[0]),
                    )
                },
            )
            return
        if path == f"{BASE_PATH}/applied-changes":
            statuses = query.get("status")
            self._json(
                200,
                {
                    "applied_changes": store.continuous_improvement_applied_changes(
                        statuses=statuses,
                        limit=int((query.get("limit") or ["200"])[0]),
                    )
                },
            )
            return
        if path.startswith(f"{BASE_PATH}/proposals/") and path.endswith("/artifact"):
            proposal_id = path.split("/")[-2]
            artifact = store.continuous_improvement_proposal_artifact(proposal_id)
            self._json(200 if artifact else 404, artifact or {"error": "not_found"})
            return
        if path.startswith(f"{BASE_PATH}/proposals/"):
            proposal_id = path.rsplit("/", 1)[-1]
            proposal = store.continuous_improvement_proposal(proposal_id)
            self._json(200 if proposal else 404, proposal or {"error": "not_found"})
            return
        if path == f"{BASE_PATH}/reports/latest":
            cycle = store.latest_continuous_improvement_cycle()
            self._json(200 if cycle else 404, (cycle or {}).get("report") or {"error": "not_found"})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        store = _store()
        if path == f"{BASE_PATH}/cycles/run":
            self._json(202, run_cycle_background())
            return
        if path == f"{BASE_PATH}/events":
            payload = self._read_json()
            self._json(
                202,
                enqueue_event_background(
                    event_type=str(payload.get("event_type") or "manual_event"),
                    domain=str(payload.get("domain") or "software-improvement"),
                    source=str(payload.get("source") or "api"),
                    payload=payload.get("payload") or {},
                ),
            )
            return
        if path.startswith(f"{BASE_PATH}/tasks/") and path.endswith("/retry"):
            task_id = path.split("/")[-2]
            task = store.continuous_improvement_task(task_id)
            if not task:
                self._json(404, {"error": "not_found"})
                return
            store.update_continuous_improvement_task(
                task_id,
                status="DISCOVERED",
                error={},
                started_at=None,
                finished_at=None,
            )
            self._json(200, store.continuous_improvement_task(task_id))
            return
        if path.startswith(f"{BASE_PATH}/proposals/"):
            parts = path[len(f"{BASE_PATH}/proposals/") :].split("/")
            if len(parts) != 2:
                self._json(404, {"error": "not_found"})
                return
            proposal_id, action = parts
            mapping = {
                "approve": "APPROVED",
                "reject": "REJECTED",
                "apply": "READY_TO_APPLY",
                "validate": "PENDING",
            }
            if action not in mapping:
                self._json(404, {"error": "not_found"})
                return
            proposal = store.continuous_improvement_proposal(proposal_id)
            if not proposal:
                self._json(404, {"error": "not_found"})
                return
            reason = {
                "approve": "Aprobada manualmente via API.",
                "reject": "Rechazada manualmente via API.",
                "apply": "Forzada a READY_TO_APPLY via API.",
                "validate": "Revalidacion manual solicitada; vuelve al pipeline automatico.",
            }[action]
            store.update_continuous_improvement_proposal_status(
                proposal_id,
                status=mapping[action],
                actor="api",
                reason=reason,
                payload={"action": action},
            )
            self._json(200, store.continuous_improvement_proposal(proposal_id))
            return
        if path.startswith(f"{BASE_PATH}/applied-changes/") and path.endswith("/rollback"):
            applied_change_id = path.split("/")[-2]
            change = AutoApplyCodeAgent().rollback(settings=get_settings(), store=store, applied_change_id=applied_change_id, actor="api")
            self._json(200 if change else 404, change or {"error": "not_found"})
            return
        if path.startswith(f"{BASE_PATH}/initiatives/"):
            parts = path[len(f"{BASE_PATH}/initiatives/") :].split("/")
            if len(parts) != 2:
                self._json(404, {"error": "not_found"})
                return
            initiative_id, action = parts
            initiative = store.continuous_improvement_initiative(initiative_id)
            if not initiative:
                self._json(404, {"error": "not_found"})
                return
            payload = self._read_json()
            if action == "validate":
                store.update_continuous_improvement_initiative(
                    initiative_id,
                    status="VALIDATING",
                    latest_decision={
                        "decision": "VALIDATING",
                        "actor": "api",
                        "reason": str(payload.get("reason") or "Validacion solicitada via API."),
                    },
                    next_action=str(payload.get("next_action") or "Ejecutar validacion objetiva."),
                )
            elif action == "decide":
                decision = str(payload.get("decision") or "WAITING_REVIEW")
                store.update_continuous_improvement_initiative(
                    initiative_id,
                    status=decision,
                    latest_decision={
                        "decision": decision,
                        "actor": "api",
                        "reason": str(payload.get("reason") or "Decision manual via API."),
                    },
                    next_action=str(payload.get("next_action") or ""),
                )
            elif action == "close":
                store.update_continuous_improvement_initiative(
                    initiative_id,
                    status="CLOSED",
                    latest_decision={
                        "decision": "CLOSED",
                        "actor": "api",
                        "reason": str(payload.get("reason") or "Iniciativa cerrada via API."),
                    },
                    next_action="",
                )
            else:
                self._json(404, {"error": "not_found"})
                return
            self._json(200, store.continuous_improvement_initiative(initiative_id))
            return
        self._json(404, {"error": "not_found"})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_api_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), ContinuousImprovementApiHandler)
    print(f"Continuous improvement API en http://{host}:{port}{BASE_PATH}/lab/status")
    server.serve_forever()
