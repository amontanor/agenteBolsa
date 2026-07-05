"""Research evidence layer for market, macro and symbol context."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agente_bolsa.models import new_id

from .macro_context import fetch_macro_events
from .news_sentiment import fetch_combined_symbol_news
from .reporting import write_json_report
from .web_research import search_general_market_news
from .web_research_budget import freshness_hours as parsed_freshness_hours
from .web_research_budget import web_search_freshness_v2_enabled

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from ..config import Settings
    from ..storage import Store


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_to_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_hours(published_at: Any, fetched_at: datetime) -> float | None:
    if web_search_freshness_v2_enabled():
        return parsed_freshness_hours(published_at, fetched_at=fetched_at)
    published_dt = _iso_to_dt(published_at)
    if published_dt is None:
        return None
    delta = fetched_at - published_dt
    return round(max(delta.total_seconds(), 0.0) / 3600.0, 3)


def _freshness_shadow_status(published_at: Any, fetched_at: datetime, *, max_age_hours: float) -> dict[str, Any]:
    old_freshness = _iso_to_dt(published_at)
    old_status = "unknown" if old_freshness is None else _staleness_status(_freshness_hours(published_at, fetched_at), max_age_hours=max_age_hours)
    parsed = parsed_freshness_hours(published_at, fetched_at=fetched_at)
    parsed_status = _staleness_status(parsed, max_age_hours=max_age_hours)
    return {
        "old_status": old_status,
        "v2_status": parsed_status,
        "v2_freshness_hours": parsed,
        "unknown_to_fresh": old_status == "unknown" and parsed_status == "fresh",
    }


def _staleness_status(freshness_hours: float | None, *, max_age_hours: float) -> str:
    if freshness_hours is None:
        return "unknown"
    if freshness_hours <= max_age_hours:
        return "fresh"
    if freshness_hours <= max_age_hours * 2:
        return "aging"
    return "stale"


def _hash_payload(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _source_score(source_name: str, provider: str, *, source_type: str) -> float:
    text = f"{source_name} {provider}".lower()
    if source_type == "macro_thesis":
        return 0.7
    if any(term in text for term in ("sec", "edgar", "nasdaq", "nyse", "federal reserve", "bce", "bea", "bls")):
        return 0.95
    if any(term in text for term in ("reuters", "bloomberg", "wsj", "financial times", "marketwatch", "cnbc")):
        return 0.85
    if any(term in text for term in ("yahoo", "yfinance", "fmp", "financialmodelingprep")):
        return 0.65
    return 0.55


def _evidence_row(
    *,
    scope: str,
    source_type: str,
    source_name: str,
    provider: str,
    fetched_at: datetime,
    max_age_hours: float,
    symbol: str | None = None,
    topic: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    url: str | None = None,
    published_at: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    freshness = _freshness_hours(published_at, fetched_at)
    evidence_id = payload.get("evidence_id") or new_id("ev")
    reliability = _source_score(source_name, provider, source_type=source_type)
    quality_status = "available" if title or summary or payload else "empty"
    return {
        "evidence_id": evidence_id,
        "symbol": symbol.upper() if symbol else None,
        "scope": scope,
        "topic": topic,
        "source_type": source_type,
        "source_name": source_name,
        "provider": provider,
        "url": url,
        "title": title,
        "summary": summary,
        "published_at": published_at,
        "fetched_at": fetched_at.isoformat(),
        "reliability_score": round(reliability, 3),
        "freshness_hours": freshness,
        "staleness_status": _staleness_status(freshness, max_age_hours=max_age_hours),
        "quality_status": quality_status,
        "content_hash": _hash_payload(
            {
                "symbol": symbol,
                "scope": scope,
                "topic": topic,
                "source_type": source_type,
                "source_name": source_name,
                "provider": provider,
                "url": url,
                "title": title,
                "summary": summary,
                "published_at": published_at,
                "payload": payload,
            }
        ),
        "payload": payload,
    }


def build_research_evidence_report(
    store: Store,
    settings: Settings,
    reports_dir: Path,
    run_id: str,
    *,
    symbols: list[str] | None = None,
    market_state: dict[str, Any] | None = None,
    sentiment_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fetched_at = _utc_now()
    reports_dir.mkdir(parents=True, exist_ok=True)
    max_age_hours = float(getattr(settings, "research_evidence_max_age_hours", 48.0))
    min_reliability = float(getattr(settings, "research_evidence_min_reliability", 0.45))
    symbols = [str(item).upper() for item in list(symbols or []) if str(item or "").strip()]
    symbol_set = list(dict.fromkeys(symbols))
    sentiment_lookup = {
        str(item.get("symbol") or "").upper(): item
        for item in list((sentiment_context or {}).get("results", []) or [])
        if isinstance(item, dict) and str(item.get("symbol") or "").strip()
    }

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    thesis = store.latest_market_thesis()
    if thesis:
        payload = dict(thesis.get("payload") or {})
        row = _evidence_row(
            scope="market",
            source_type="macro_thesis",
            source_name="market_thesis",
            provider="internal",
            fetched_at=fetched_at,
            max_age_hours=max_age_hours,
            topic=payload.get("stance"),
            title=f"Tesis {payload.get('stance') or thesis.get('stance') or 'neutral'}",
            summary=payload.get("changes_vs_previous") or "; ".join(list(payload.get("key_risks") or [])[:2]),
            published_at=thesis.get("created_at"),
            payload=payload,
        )
        store.upsert_research_evidence(row)
        rows.append(row)

    macro_events = fetch_macro_events(settings)
    macro_quality = str(macro_events.get("quality") or "unknown")
    for item in list(macro_events.get("general_news") or [])[:10]:
        if not isinstance(item, dict):
            continue
        row = _evidence_row(
            scope="macro",
            source_type="macro_news",
            source_name=str(item.get("site") or "macro_news"),
            provider="fmp",
            fetched_at=fetched_at,
            max_age_hours=max_age_hours,
            topic="macro",
            title=str(item.get("title") or ""),
            summary=str(item.get("site") or ""),
            payload=item,
        )
        store.upsert_research_evidence(row)
        rows.append(row)
    web_macro = {"quality": "disabled", "items": [], "warnings": []}
    if getattr(settings, "web_search_enabled", False):
        try:
            web_macro = search_general_market_news(settings, max_items=settings.web_search_market_max_items)
        except Exception as exc:  # noqa: BLE001 - external search is best effort.
            warnings.append(f"web_macro: web_search_failed:{type(exc).__name__}")
            web_macro = {"quality": "error", "items": [], "warnings": [type(exc).__name__]}
        for item in list(web_macro.get("items") or [])[: settings.web_search_market_max_items]:
            if not isinstance(item, dict):
                continue
            row = _evidence_row(
                scope="macro",
                source_type="web_macro_news",
                source_name=str(item.get("publisher") or "web_macro_news"),
                provider=str(item.get("provider") or web_macro.get("provider") or "web"),
                fetched_at=fetched_at,
                max_age_hours=max_age_hours,
                topic="macro",
                title=str(item.get("title") or ""),
                summary=str(item.get("summary") or ""),
                url=str(item.get("link") or "") or None,
                published_at=str(item.get("published_at") or "") or None,
                payload=item,
            )
            store.upsert_research_evidence(row)
            rows.append(row)

    symbols_summary: list[dict[str, Any]] = []
    freshness_shadow: list[dict[str, Any]] = []
    for symbol in symbol_set:
        sentiment_row = sentiment_lookup.get(symbol) or {}
        news_rows = list(sentiment_row.get("news") or [])
        if not news_rows:
            try:
                news_rows = fetch_combined_symbol_news(
                    settings,
                    symbol,
                    max_items=max(5, int(getattr(settings, "web_search_max_items_per_symbol", 5))),
                )
            except Exception as exc:  # noqa: BLE001 - degrade and continue.
                warnings.append(f"{symbol}: news_fetch_failed:{type(exc).__name__}")
                news_rows = []
        evidence_ids: list[str] = []
        fresh_count = 0
        stale_count = 0
        best_score = 0.0
        shadow_unknown_to_fresh = 0
        for item in news_rows[:5]:
            if not isinstance(item, dict):
                continue
            shadow_freshness = _freshness_shadow_status(
                item.get("published_at"),
                fetched_at,
                max_age_hours=max_age_hours,
            )
            row = _evidence_row(
                symbol=symbol,
                scope="symbol",
                topic="news",
                source_type="symbol_news",
                source_name=str(item.get("publisher") or "symbol_news"),
                provider=str(item.get("provider") or "yfinance"),
                fetched_at=fetched_at,
                max_age_hours=max_age_hours,
                title=str(item.get("title") or ""),
                summary=str(item.get("summary") or ""),
                url=str(item.get("link") or "") or None,
                published_at=str(item.get("published_at") or "") or None,
                payload=item,
            )
            if float(row["reliability_score"]) >= min_reliability:
                evidence_ids.append(str(row["evidence_id"]))
            if row["staleness_status"] == "fresh":
                fresh_count += 1
            elif row["staleness_status"] == "stale":
                stale_count += 1
            if shadow_freshness["unknown_to_fresh"]:
                shadow_unknown_to_fresh += 1
            best_score = max(best_score, float(row["reliability_score"]))
            store.upsert_research_evidence(row)
            rows.append(row)
        latest_titles = [str(item.get("title") or "") for item in news_rows[:3] if str(item.get("title") or "").strip()]
        symbols_summary.append(
            {
                "symbol": symbol,
                "evidence_ids": evidence_ids[:5],
                "news_items": len(news_rows),
                "fresh_items": fresh_count,
                "stale_items": stale_count,
                "max_reliability": round(best_score, 3),
                "latest_titles": latest_titles,
                "sentiment_summary": ((sentiment_row.get("sentiment") or {}).get("summary") if sentiment_row else None),
                "sentiment_score": ((sentiment_row.get("sentiment") or {}).get("sentiment_score") if sentiment_row else None),
            }
        )
        if shadow_unknown_to_fresh:
            freshness_shadow.append(
                {
                    "symbol": symbol,
                    "unknown_to_fresh_items": shadow_unknown_to_fresh,
                    "live_fresh_items": fresh_count,
                    "would_have_fresh_evidence": fresh_count > 0 or shadow_unknown_to_fresh > 0,
                }
            )

    symbols_missing_fresh = [
        item["symbol"]
        for item in symbols_summary
        if item["news_items"] == 0 or item["fresh_items"] == 0
    ]
    symbols_with_fresh = [item["symbol"] for item in symbols_summary if item["fresh_items"] > 0]
    shadow_symbols_with_fresh = {
        str(item.get("symbol") or "").upper()
        for item in freshness_shadow
        if item.get("would_have_fresh_evidence")
    }
    shadow_missing_fresh = [symbol for symbol in symbols_missing_fresh if symbol not in shadow_symbols_with_fresh]
    low_quality = [
        item["symbol"]
        for item in symbols_summary
        if item["news_items"] > 0 and float(item["max_reliability"] or 0.0) < min_reliability
    ]
    providers = {
        "macro": {
            "quality": macro_quality,
            "provider": "fmp" if getattr(settings, "fmp_api_key", None) else "none",
            "web_quality": web_macro.get("quality"),
            "web_provider": web_macro.get("provider"),
        },
        "news": {
            "quality": "ok" if symbols_with_fresh else ("partial" if symbols_summary else "unknown"),
            "provider": "combined" if getattr(settings, "web_search_enabled", False) else "yfinance",
        },
    }
    required = bool(getattr(settings, "research_evidence_fail_closed_for_buys", False))
    decision_ready = not required or (
        macro_quality in {"ok", "no_provider"}
        and not symbols_missing_fresh
        and not low_quality
    )
    summary = {
        "symbols_requested": len(symbol_set),
        "symbols_with_fresh_evidence": len(symbols_with_fresh),
        "symbols_missing_fresh_evidence": symbols_missing_fresh,
        "symbols_low_reliability": low_quality,
        "providers": providers,
        "required": required,
        "decision_ready": decision_ready,
        "rows_persisted": len(rows),
        "freshness_v2_shadow": {
            "enabled": web_search_freshness_v2_enabled(),
            "symbols_unknown_to_fresh": [item["symbol"] for item in freshness_shadow],
            "symbols_missing_fresh_if_enabled": shadow_missing_fresh,
            "would_unblock_gate": required
            and not decision_ready
            and macro_quality in {"ok", "no_provider"}
            and not shadow_missing_fresh
            and not low_quality,
            "items": freshness_shadow,
        },
    }
    report = {
        "as_of": fetched_at.isoformat(),
        "summary": summary,
        "market_state": market_state or {},
        "macro": {
            "quality": macro_quality,
            "economic_events": len(list(macro_events.get("economic_calendar") or [])),
            "earnings_events": len(list(macro_events.get("earnings_calendar") or [])),
        },
        "symbols": symbols_summary,
        "freshness_v2_shadow": summary["freshness_v2_shadow"],
        "warnings": warnings,
    }
    return write_json_report(
        report,
        reports_dir,
        "research_evidence",
        run_id,
        latest_filename="latest_research_evidence.json",
        manifest={"symbols": symbol_set},
    )


def load_research_evidence_context(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "reports" / "latest_research_evidence.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def compact_research_context_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("summary") or {}
    symbols = []
    for item in list(context.get("symbols") or [])[:8]:
        if not isinstance(item, dict):
            continue
        symbols.append(
            {
                "symbol": item.get("symbol"),
                "evidence_ids": list(item.get("evidence_ids") or [])[:3],
                "fresh_items": item.get("fresh_items"),
                "news_items": item.get("news_items"),
                "latest_titles": list(item.get("latest_titles") or [])[:2],
                "sentiment_score": item.get("sentiment_score"),
            }
        )
    return {
        "as_of": context.get("as_of"),
        "decision_ready": summary.get("decision_ready"),
        "required": summary.get("required"),
        "providers": summary.get("providers") or {},
        "symbols_missing_fresh_evidence": list(summary.get("symbols_missing_fresh_evidence") or [])[:8],
        "symbols_low_reliability": list(summary.get("symbols_low_reliability") or [])[:8],
        "symbols": symbols,
    }


def research_block_reason(
    context: dict[str, Any] | None,
    *,
    symbol: str | None = None,
) -> str | None:
    if not context:
        return None
    summary = context.get("summary") or {}
    if not summary.get("required"):
        return None
    if not summary.get("decision_ready", True):
        if symbol:
            missing = {str(item).upper() for item in list(summary.get("symbols_missing_fresh_evidence") or [])}
            if symbol.upper() in missing:
                return "research_evidence_missing_or_stale"
            low_quality = {str(item).upper() for item in list(summary.get("symbols_low_reliability") or [])}
            if symbol.upper() in low_quality:
                return "research_evidence_low_reliability"
        return "research_evidence_not_ready"
    return None
