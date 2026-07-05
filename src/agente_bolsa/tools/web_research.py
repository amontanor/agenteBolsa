"""Traceable web search adapters for market and company research."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .reporting import write_json_report
from .web_research_budget import (
    BudgetedSearchResult,
    budgeted_provider_search,
    parse_published_at,
    web_search_freshness_v2_enabled,
)

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from pathlib import Path

    from ..config import Settings


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    summary: str
    published_at: str | None
    source_name: str
    provider: str
    query: str
    payload: dict[str, Any]


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _published_at(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if web_search_freshness_v2_enabled():
        parsed = parse_published_at(text)
        if parsed is not None:
            return parsed.isoformat()
    return text


def _normalize_tavily_result(item: dict[str, Any], *, query: str) -> WebSearchResult | None:
    title = _clean_text(item.get("title"))
    url = _clean_text(item.get("url"))
    if not title or not url:
        return None
    return WebSearchResult(
        title=title,
        url=url,
        summary=_clean_text(item.get("content") or item.get("raw_content") or item.get("snippet")),
        published_at=_published_at(item.get("published_date") or item.get("published_at") or item.get("date")),
        source_name=_clean_text(item.get("source") or item.get("site_name") or "tavily"),
        provider="tavily",
        query=query,
        payload=item,
    )


def _normalize_brave_result(item: dict[str, Any], *, query: str) -> WebSearchResult | None:
    title = _clean_text(item.get("title"))
    url = _clean_text(item.get("url"))
    if not title or not url:
        return None
    profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
    return WebSearchResult(
        title=title,
        url=url,
        summary=_clean_text(item.get("description") or item.get("snippet")),
        published_at=_published_at(item.get("age") or item.get("page_age") or item.get("published_at")),
        source_name=_clean_text(profile.get("name") or item.get("source") or "brave"),
        provider="brave",
        query=query,
        payload=item,
    )


def dedupe_news_items(items: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        title = _clean_text(item.get("title")).lower()
        url = _clean_text(item.get("link") or item.get("url")).lower()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _request_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> dict[str, Any]:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured provider URLs.
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _tavily_search(settings: Settings, query: str, *, max_items: int) -> list[WebSearchResult]:
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY no configurada")
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "basic",
        "topic": "news",
        "max_results": max_items,
        "include_answer": False,
    }
    if web_search_freshness_v2_enabled():
        payload["days"] = 7
    data = _tavily_post(settings, payload)
    results = data.get("results") if isinstance(data.get("results"), list) else []
    return [
        normalized
        for item in results
        if isinstance(item, dict)
        for normalized in [_normalize_tavily_result(item, query=query)]
        if normalized is not None
    ]


def _tavily_post(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8")
    request = Request(
        settings.tavily_base_url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=settings.web_search_timeout_seconds) as response:  # noqa: S310
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _brave_search(settings: Settings, query: str, *, max_items: int) -> list[WebSearchResult]:
    if not settings.brave_api_key:
        raise RuntimeError("BRAVE_API_KEY no configurada")
    freshness = "pw" if web_search_freshness_v2_enabled() else "pm"
    url = settings.brave_base_url + "?" + urlencode({"q": query, "count": max_items, "freshness": freshness})
    data = _request_json(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_api_key,
        },
        timeout=settings.web_search_timeout_seconds,
    )
    web = data.get("web") if isinstance(data.get("web"), dict) else {}
    results = web.get("results") if isinstance(web.get("results"), list) else []
    return [
        normalized
        for item in results
        if isinstance(item, dict)
        for normalized in [_normalize_brave_result(item, query=query)]
        if normalized is not None
    ]


def _provider_order(settings: Settings) -> list[str]:
    if not settings.web_search_enabled or settings.web_search_provider == "off":
        return []
    if settings.web_search_provider in {"tavily", "brave"}:
        return [settings.web_search_provider]
    ordered = []
    if settings.tavily_api_key:
        ordered.append("tavily")
    if settings.brave_api_key:
        ordered.append("brave")
    return ordered


def _search_provider(settings: Settings, provider: str, query: str, *, max_items: int) -> list[WebSearchResult]:
    if provider == "tavily":
        return _tavily_search(settings, query, max_items=max_items)
    if provider == "brave":
        return _brave_search(settings, query, max_items=max_items)
    raise ValueError(f"Proveedor web no soportado: {provider}")


def _web_search_result_factory(payload: dict[str, Any]) -> WebSearchResult:
    return WebSearchResult(**payload)


def _budgeted_search_provider(
    settings: Settings,
    provider: str,
    query: str,
    *,
    max_items: int,
    scope: str,
) -> BudgetedSearchResult:
    return budgeted_provider_search(
        settings,
        provider=provider,
        query=query,
        max_items=max_items,
        scope=scope,
        fetcher=lambda: _search_provider(settings, provider, query, max_items=max_items),
        item_factory=_web_search_result_factory,
    )


def _to_news_item(result: WebSearchResult) -> dict[str, Any]:
    return {
        "title": result.title,
        "publisher": result.source_name,
        "published_at": result.published_at,
        "summary": result.summary,
        "link": result.url,
        "provider": result.provider,
        "query": result.query,
        "payload": result.payload,
    }


def search_company_news(
    settings: Settings,
    symbol: str,
    *,
    company_name: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    max_items = max_items or settings.web_search_max_items_per_symbol
    subject = f"{symbol} {company_name}".strip() if company_name else symbol
    queries = [
        f"{subject} stock news",
        f"{subject} earnings guidance lawsuit downgrade catalyst",
    ]
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    attempted: list[str] = []
    cache_hits = 0
    provider_calls = 0
    for provider in _provider_order(settings):
        attempted.append(provider)
        for query in queries:
            try:
                search_result = _budgeted_search_provider(
                    settings,
                    provider,
                    query,
                    max_items=max_items,
                    scope="symbol",
                )
                cache_hits += int(search_result.cache_hit)
                provider_calls += int(search_result.calls_used)
                warnings.extend(search_result.warnings)
                items.extend(_to_news_item(result) for result in search_result.items)
            except Exception as exc:  # noqa: BLE001 - best effort evidence.
                warnings.append(f"{provider}:{query}:{type(exc).__name__}")
        items = dedupe_news_items(items, limit=max_items)
        if items:
            break
    quality = "ok" if items else ("no_provider" if not attempted else "empty")
    return {
        "symbol": symbol,
        "provider": attempted[0] if attempted else "none",
        "providers_attempted": attempted,
        "quality": quality,
        "items": items,
        "warnings": warnings,
        "cache_hits": cache_hits,
        "provider_calls": provider_calls,
    }


def search_general_market_news(settings: Settings, *, max_items: int | None = None) -> dict[str, Any]:
    max_items = max_items or settings.web_search_market_max_items
    query = "US stock market macro news earnings Federal Reserve inflation catalysts"
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    attempted: list[str] = []
    cache_hits = 0
    provider_calls = 0
    for provider in _provider_order(settings):
        attempted.append(provider)
        try:
            search_result = _budgeted_search_provider(
                settings,
                provider,
                query,
                max_items=max_items,
                scope="macro",
            )
            cache_hits += int(search_result.cache_hit)
            provider_calls += int(search_result.calls_used)
            warnings.extend(search_result.warnings)
            items.extend(_to_news_item(result) for result in search_result.items)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{provider}:{type(exc).__name__}")
        items = dedupe_news_items(items, limit=max_items)
        if items:
            break
    quality = "ok" if items else ("no_provider" if not attempted else "empty")
    return {
        "provider": attempted[0] if attempted else "none",
        "providers_attempted": attempted,
        "quality": quality,
        "items": items,
        "warnings": warnings,
        "cache_hits": cache_hits,
        "provider_calls": provider_calls,
    }


def build_web_research_report(
    settings: Settings,
    output_dir: Path,
    run_id: str,
    *,
    symbol: str | None = None,
    market: bool = False,
    max_items: int | None = None,
) -> dict[str, Any]:
    if symbol:
        result = search_company_news(settings, symbol, max_items=max_items)
        scope = "symbol"
    elif market:
        result = search_general_market_news(settings, max_items=max_items)
        scope = "market"
    else:
        raise ValueError("Indica un simbolo o --market.")
    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "symbol": symbol.upper() if symbol else None,
        "result": result,
        "summary": {
            "quality": result.get("quality"),
            "provider": result.get("provider"),
            "items": len(list(result.get("items") or [])),
            "warnings": list(result.get("warnings") or [])[:20],
        },
    }
    return write_json_report(
        report,
        output_dir,
        "web_research",
        run_id,
        latest_filename="latest_web_research.json",
        manifest={"symbol": symbol, "market": market, "max_items": max_items},
    )
