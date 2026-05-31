"""Shared memory helpers for the continuous improvement lab."""

from __future__ import annotations

from typing import Any

from agente_bolsa.storage import Store


class SharedMemory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def snapshot(self) -> dict[str, Any]:
        memories = self.store.continuous_improvement_memories()
        return {item["memory_key"]: item for item in memories}

    def domain_snapshot(self, domain: str) -> list[dict[str, Any]]:
        return self.store.continuous_improvement_memories(domain=domain)

    def remember(
        self,
        *,
        memory_key: str,
        domain: str,
        summary_text: str,
        payload: dict[str, Any],
        source_event_id: str | None = None,
    ) -> None:
        self.store.upsert_continuous_improvement_memory(
            memory_key=memory_key,
            domain=domain,
            summary_text=summary_text,
            payload=payload,
            source_event_id=source_event_id,
        )
