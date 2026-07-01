"""JSONL storage for Telegram radar research data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TelegramRadarStore:
    """Small append-only JSONL store under data/research/telegram."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.posts_path = self.root / "posts.jsonl"
        self.extractions_path = self.root / "extractions.jsonl"
        self.cache_dir = self.root / "cache"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_posts(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.posts_path)

    def load_extractions(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.extractions_path)

    def upsert_posts(self, posts: list[dict[str, Any]]) -> dict[str, Any]:
        self.ensure_dirs()
        existing = {int(item["message_id"]): item for item in self.load_posts()}
        inserted = 0
        updated = 0
        for post in posts:
            message_id = int(post["message_id"])
            if message_id in existing:
                if existing[message_id] != post:
                    updated += 1
                existing[message_id] = post
            else:
                inserted += 1
                existing[message_id] = post
        _write_jsonl_atomic(self.posts_path, [existing[key] for key in sorted(existing)])
        return {"inserted": inserted, "updated": updated, "total": len(existing)}

    def upsert_extractions(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        self.ensure_dirs()
        existing = {int(item["message_id"]): item for item in self.load_extractions()}
        inserted = 0
        updated = 0
        for row in rows:
            message_id = int(row["message_id"])
            if message_id in existing:
                if existing[message_id] != row:
                    updated += 1
                existing[message_id] = row
            else:
                inserted += 1
                existing[message_id] = row
        _write_jsonl_atomic(self.extractions_path, [existing[key] for key in sorted(existing)])
        return {"inserted": inserted, "updated": updated, "total": len(existing)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)
