"""Compatibility facade over the resident continuous improvement lab runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store

from .runtime import ContinuousImprovementLabRuntime


class ContinuousImprovementOrchestrator:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.runtime = ContinuousImprovementLabRuntime(settings, store)

    def run_cycle(
        self,
        *,
        mode: str = "manual",
        dedupe_key: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        self.store.ensure_schema()
        if not self.settings.continuous_improvement_enabled:
            return {"ok": False, "status": "DISABLED", "reason": "CONTINUOUS_IMPROVEMENT_ENABLED=false"}
        if dedupe_key and not force:
            existing = self.store.continuous_improvement_cycle_by_dedupe_key(dedupe_key)
            if existing:
                return {"ok": True, "deduped": True, **existing}

        report = self.runtime.run_once(
            mode=mode,
            trigger_event_type="manual_trigger" if mode == "manual" else f"{mode}_trigger",
            trigger_payload={"dedupe_key": dedupe_key, "requested_at": datetime.now(timezone.utc).isoformat()},
        )
        if dedupe_key and report.get("cycle_id"):
            self.store.update_continuous_improvement_cycle(report["cycle_id"], dedupe_key=dedupe_key)
            report = self.store.continuous_improvement_cycle(report["cycle_id"]) or report
        report["deduped"] = False
        return report


def scheduled_dedupe_key(settings: Settings) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return f"continuous-improvement:scheduled:{today}:{settings.continuous_improvement_time_local}"
