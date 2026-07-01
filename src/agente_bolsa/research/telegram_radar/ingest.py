"""Read-only ingestion of public Telegram channel pages."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from lxml import html

from .models import TelegramPost
from .storage import TelegramRadarStore

LOGGER = logging.getLogger(__name__)

DEFAULT_CHANNEL_URL = "https://t.me/s/bolsazonefreezone"
USER_AGENT = "agente-bolsa-telegram-radar/0.1 (+research read-only)"


def parse_telegram_posts(page_html: str) -> list[TelegramPost]:
    tree = html.fromstring(page_html)
    posts: list[TelegramPost] = []
    for node in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " tgme_widget_message ")]'):
        data_post = str(node.get("data-post") or "")
        if "/" not in data_post:
            continue
        message_token = data_post.rsplit("/", 1)[-1]
        try:
            message_id = int(message_token)
        except ValueError:
            continue
        text_parts = node.xpath(
            './/*[contains(concat(" ", normalize-space(@class), " "), " tgme_widget_message_text ")]//text()'
        )
        text = " ".join(part.strip() for part in text_parts if part and part.strip())
        time_values = node.xpath(".//time/@datetime")
        author_values = node.xpath(
            './/*[contains(concat(" ", normalize-space(@class), " "), " tgme_widget_message_author_name ")]//text()'
        )
        links = [
            str(link)
            for link in node.xpath(".//a/@href")
            if str(link).strip() and not str(link).startswith("#")
        ]
        raw_html = html.tostring(node, encoding="unicode")
        posts.append(
            TelegramPost(
                message_id=message_id,
                posted_at=str(time_values[0]) if time_values else None,
                author=" ".join(item.strip() for item in author_values if item.strip()) or None,
                text=text,
                links=links,
                raw_html_hash=hashlib.sha256(raw_html.encode()).hexdigest(),
            )
        )
    return sorted(posts, key=lambda item: item.message_id)


def fetch_telegram_page(
    *,
    channel_url: str = DEFAULT_CHANNEL_URL,
    before: int | None = None,
    cache_dir: Path | None = None,
    timeout_seconds: float = 15.0,
    force: bool = False,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    params = {"before": before} if before is not None else {}
    url = channel_url if not params else f"{channel_url}?{urlencode(params)}"
    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_path = cache_dir / f"{digest}.html"
        if cache_path.exists() and not force:
            return {"ok": True, "url": url, "from_cache": True, "html": cache_path.read_text(encoding="utf-8")}
    client = session or requests.Session()
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("telegram_radar_fetch_failed url=%s error=%s", url, exc)
        return {"ok": False, "url": url, "from_cache": False, "html": "", "error": str(exc)}
    text = response.text
    if cache_path is not None:
        cache_path.write_text(text, encoding="utf-8")
    return {"ok": True, "url": url, "from_cache": False, "html": text}


def ingest_channel(
    store: TelegramRadarStore,
    *,
    channel_url: str = DEFAULT_CHANNEL_URL,
    backfill_pages: int = 1,
    timeout_seconds: float = 15.0,
    force: bool = False,
    session: requests.Session | None = None,
    polite_sleep_seconds: float = 1.0,
) -> dict[str, Any]:
    store.ensure_dirs()
    pages: list[dict[str, Any]] = []
    posts_by_id: dict[int, TelegramPost] = {}
    before: int | None = None
    warnings: list[str] = []
    for page_index in range(max(1, int(backfill_pages))):
        if page_index > 0 and polite_sleep_seconds > 0:
            time.sleep(polite_sleep_seconds)
        fetched = fetch_telegram_page(
            channel_url=channel_url,
            before=before,
            cache_dir=store.cache_dir,
            timeout_seconds=timeout_seconds,
            force=force,
            session=session,
        )
        page_summary = {
            "url": fetched["url"],
            "ok": fetched["ok"],
            "from_cache": fetched.get("from_cache", False),
            "posts": 0,
        }
        if not fetched["ok"]:
            warnings.append(str(fetched.get("error") or "telegram_fetch_failed"))
            pages.append(page_summary)
            break
        posts = parse_telegram_posts(str(fetched.get("html") or ""))
        for post in posts:
            posts_by_id[post.message_id] = post
        page_summary["posts"] = len(posts)
        pages.append(page_summary)
        if not posts:
            break
        before = min(post.message_id for post in posts)
    upsert = store.upsert_posts([post.to_dict() for post in posts_by_id.values()])
    return {
        "ok": not warnings,
        "channel_url": channel_url,
        "pages": pages,
        "posts_parsed": len(posts_by_id),
        "storage": upsert,
        "warnings": warnings,
    }
