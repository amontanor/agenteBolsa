"""Budget, TTL cache and freshness helpers for web search providers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class BudgetedSearchResult:
    items: list[Any]
    cache_hit: bool
    calls_used: int
    warnings: list[str]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def web_search_monthly_budget() -> int:
    return max(0, env_int("WEB_SEARCH_MONTHLY_BUDGET", 1000))


def web_search_freshness_v2_enabled() -> bool:
    return env_bool("WEB_SEARCH_FRESHNESS_V2", False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _month_key(now: datetime | None = None) -> str:
    now = now or _utc_now()
    return now.strftime("%Y-%m")


def _state_dir(settings: Any) -> Path:
    return Path(getattr(settings, "data_dir", "data")) / "state"


def _reports_dir(settings: Any) -> Path:
    return Path(getattr(settings, "data_dir", "data")) / "reports"


def _cache_dir(settings: Any) -> Path:
    return Path(getattr(settings, "data_dir", "data")) / "cache" / "web_search"


def _usage_path(settings: Any, month_key: str | None = None) -> Path:
    return _state_dir(settings) / f"web_search_usage_{month_key or _month_key()}.json"


def _budget_report_path(settings: Any) -> Path:
    return _reports_dir(settings) / "latest_web_search_budget.json"


def _normalize_query(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _cache_key(provider: str, query: str, max_items: int, scope: str) -> str:
    raw = json.dumps(
        {
            "provider": provider,
            "query": _normalize_query(query),
            "max_items": max_items,
            "scope": scope,
            "freshness_v2": web_search_freshness_v2_enabled(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _ttl_hours(scope: str) -> float:
    if scope == "macro":
        return max(0.0, env_float("WEB_SEARCH_CACHE_TTL_MACRO_HOURS", 3.0))
    return max(0.0, env_float("WEB_SEARCH_CACHE_TTL_SYMBOL_HOURS", 12.0))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")


def _serialize_item(item: Any) -> Any:
    if hasattr(item, "__dataclass_fields__"):
        return {"__dataclass__": type(item).__name__, "payload": asdict(item)}
    if isinstance(item, dict):
        return item
    return item


def _deserialize_items(raw_items: list[Any], item_factory: Callable[[dict[str, Any]], T] | None) -> list[Any]:
    items: list[Any] = []
    for item in raw_items:
        if isinstance(item, dict) and item.get("__dataclass__") and isinstance(item.get("payload"), dict):
            items.append(item_factory(item["payload"]) if item_factory else item["payload"])
        else:
            items.append(item)
    return items


def _read_cache(
    settings: Any,
    *,
    provider: str,
    query: str,
    max_items: int,
    scope: str,
    item_factory: Callable[[dict[str, Any]], T] | None,
) -> list[Any] | None:
    key = _cache_key(provider, query, max_items, scope)
    path = _cache_dir(settings) / f"{key}.json"
    payload = _load_json(path)
    created_at = parse_published_at(payload.get("created_at"))
    if created_at is None:
        return None
    age_hours = (_utc_now() - created_at).total_seconds() / 3600.0
    if age_hours > _ttl_hours(scope):
        return None
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return _deserialize_items(raw_items, item_factory)


def _write_cache(
    settings: Any,
    *,
    provider: str,
    query: str,
    max_items: int,
    scope: str,
    items: list[Any],
) -> None:
    key = _cache_key(provider, query, max_items, scope)
    _write_json(
        _cache_dir(settings) / f"{key}.json",
        {
            "created_at": _utc_now().isoformat(),
            "provider": provider,
            "query": _normalize_query(query),
            "max_items": max_items,
            "scope": scope,
            "items": [_serialize_item(item) for item in items],
        },
    )


def _load_usage(settings: Any) -> dict[str, Any]:
    month = _month_key()
    payload = _load_json(_usage_path(settings, month))
    if not payload:
        payload = {
            "month": month,
            "calls_used": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "budget_exhaustions": 0,
            "providers": {},
            "updated_at": None,
        }
    return payload


def _save_usage(settings: Any, payload: dict[str, Any]) -> None:
    payload["updated_at"] = _utc_now().isoformat()
    _write_json(_usage_path(settings, str(payload.get("month") or _month_key())), payload)


def _provider_usage(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = payload.setdefault("providers", {})
    provider_payload = providers.setdefault(provider, {"calls": 0, "cache_hits": 0, "degradations": 0})
    if not isinstance(provider_payload, dict):
        provider_payload = {"calls": 0, "cache_hits": 0, "degradations": 0}
        providers[provider] = provider_payload
    return provider_payload


def _write_budget_report(settings: Any, usage: dict[str, Any], *, last_warning: str | None = None) -> None:
    calls_used = int(usage.get("calls_used") or 0)
    cache_hits = int(usage.get("cache_hits") or 0)
    cache_misses = int(usage.get("cache_misses") or 0)
    total_cache_lookups = cache_hits + cache_misses
    budget = web_search_monthly_budget()
    now = _utc_now()
    projected_monthly = round(calls_used / max(now.day, 1) * 31, 2)
    report = {
        "as_of": now.isoformat(),
        "month": usage.get("month") or _month_key(now),
        "monthly_budget": budget,
        "calls_used": calls_used,
        "calls_remaining": max(budget - calls_used, 0),
        "projected_monthly_calls": projected_monthly,
        "within_budget_projection": projected_monthly <= budget if budget > 0 else calls_used == 0,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate": round(cache_hits / total_cache_lookups, 4) if total_cache_lookups else 0.0,
        "budget_exhaustions": int(usage.get("budget_exhaustions") or 0),
        "providers": usage.get("providers") or {},
        "degraded": int(usage.get("budget_exhaustions") or 0) > 0,
        "last_warning": last_warning,
    }
    _write_json(_budget_report_path(settings), report)


def budgeted_provider_search(
    settings: Any,
    *,
    provider: str,
    query: str,
    max_items: int,
    scope: str,
    fetcher: Callable[[], list[T]],
    item_factory: Callable[[dict[str, Any]], T] | None = None,
) -> BudgetedSearchResult:
    usage = _load_usage(settings)
    cached = _read_cache(
        settings,
        provider=provider,
        query=query,
        max_items=max_items,
        scope=scope,
        item_factory=item_factory,
    )
    if cached is not None:
        usage["cache_hits"] = int(usage.get("cache_hits") or 0) + 1
        _provider_usage(usage, provider)["cache_hits"] += 1
        _save_usage(settings, usage)
        _write_budget_report(settings, usage)
        return BudgetedSearchResult(items=list(cached), cache_hit=True, calls_used=0, warnings=[])

    usage["cache_misses"] = int(usage.get("cache_misses") or 0) + 1
    budget = web_search_monthly_budget()
    calls_used = int(usage.get("calls_used") or 0)
    if calls_used >= budget:
        warning = "web_search_budget_exhausted"
        usage["budget_exhaustions"] = int(usage.get("budget_exhaustions") or 0) + 1
        _provider_usage(usage, provider)["degradations"] += 1
        _save_usage(settings, usage)
        _write_budget_report(settings, usage, last_warning=warning)
        return BudgetedSearchResult(items=[], cache_hit=False, calls_used=0, warnings=[warning])

    usage["calls_used"] = calls_used + 1
    _provider_usage(usage, provider)["calls"] += 1
    _save_usage(settings, usage)
    try:
        items = list(fetcher())
    except Exception:
        _write_budget_report(settings, usage)
        raise
    _write_cache(settings, provider=provider, query=query, max_items=max_items, scope=scope, items=items)
    _write_budget_report(settings, usage)
    return BudgetedSearchResult(items=items, cache_hit=False, calls_used=1, warnings=[])


def parse_published_at(value: Any, *, now: datetime | None = None) -> datetime | None:
    if value is None:
        return None
    now = now or _utc_now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"today", "just now"}:
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)
    match = re.search(r"(\d+)\s*(minute|minutes|min|hour|hours|hr|hrs|day|days|week|weeks)\s+ago", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("minute") or unit == "min":
            return now - timedelta(minutes=amount)
        if unit.startswith("hour") or unit in {"hr", "hrs"}:
            return now - timedelta(hours=amount)
        if unit.startswith("day"):
            return now - timedelta(days=amount)
        if unit.startswith("week"):
            return now - timedelta(weeks=amount)
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            parsed_naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed_naive.replace(tzinfo=timezone.utc)
    return None


def freshness_hours(value: Any, *, fetched_at: datetime | None = None) -> float | None:
    fetched_at = fetched_at or _utc_now()
    published = parse_published_at(value, now=fetched_at)
    if published is None:
        return None
    return round(max((fetched_at - published).total_seconds(), 0.0) / 3600.0, 3)
