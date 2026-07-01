"""CLI helpers for Telegram radar research commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.tools.universe import resolve_study_universe

from .extract import extract_opportunity
from .ingest import DEFAULT_CHANNEL_URL, ingest_channel
from .storage import TelegramRadarStore


def default_store(settings: Settings) -> TelegramRadarStore:
    return TelegramRadarStore(Path(settings.data_dir) / "research" / "telegram")


def run_ingest(
    *,
    settings: Settings,
    backfill: int,
    channel_url: str = DEFAULT_CHANNEL_URL,
    force: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    store = default_store(settings)
    ingest = ingest_channel(
        store,
        channel_url=channel_url,
        backfill_pages=backfill,
        force=force,
    )
    posts = store.load_posts()
    extracted_ids = {int(item["message_id"]) for item in store.load_extractions()}
    new_posts = [post for post in posts if int(post["message_id"]) not in extracted_ids]
    current_universe = resolve_study_universe("sp500", settings.universe, 0, settings.data_dir / "cache")
    extractions = [
        extract_opportunity(
            post,
            settings=settings,
            use_llm=use_llm,
            current_universe=current_universe,
        ).to_dict()
        for post in new_posts
    ]
    extraction_storage = store.upsert_extractions(extractions) if extractions else {"inserted": 0, "updated": 0, "total": len(extracted_ids)}
    return {
        "ok": bool(ingest.get("ok", False)),
        "mode": "research_read_only",
        "ingest": ingest,
        "extractions_created": len(extractions),
        "extraction_storage": extraction_storage,
        "paths": {
            "root": str(store.root),
            "posts": str(store.posts_path),
            "extractions": str(store.extractions_path),
        },
    }


def list_records(
    *,
    settings: Settings,
    days: int,
    only_opportunities: bool = False,
) -> dict[str, Any]:
    store = default_store(settings)
    posts = store.load_posts()
    extraction_by_id = {int(item["message_id"]): item for item in store.load_extractions()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    rows: list[dict[str, Any]] = []
    for post in sorted(posts, key=lambda item: int(item["message_id"]), reverse=True):
        posted_at = _parse_dt(post.get("posted_at"))
        if posted_at is not None and posted_at < cutoff:
            continue
        extraction = extraction_by_id.get(int(post["message_id"]), {})
        if only_opportunities and not extraction.get("is_opportunity"):
            continue
        rows.append(
            {
                "message_id": post["message_id"],
                "posted_at": post.get("posted_at"),
                "text": post.get("text"),
                "links": post.get("links", []),
                "extraction": extraction,
            }
        )
    return {
        "ok": True,
        "mode": "research_read_only",
        "rows": rows,
        "summary": {
            "posts": len(posts),
            "extractions": len(extraction_by_id),
            "returned": len(rows),
            "only_opportunities": only_opportunities,
        },
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
