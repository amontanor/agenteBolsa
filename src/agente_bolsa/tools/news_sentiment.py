"""News download and LLM sentiment validation for technical candidates."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.llm_router import chat_for_role
from agente_bolsa.llm_usage import record_llm_response

from .reporting import write_json_report
from .web_evidence_ab import (
    build_web_ab_observation,
    record_web_ab_observation,
    split_local_web_news,
)
from .web_research import dedupe_news_items, search_company_news
from .web_research_budget import env_bool, freshness_hours

ProgressCallback = Callable[[int, int, str], None]


MATERIAL_NEGATIVE_TERMS = (
    "amazon logistics",
    "competitor",
    "competition",
    "rival",
    "downgrade",
    "guidance cut",
    "profit warning",
    "earnings miss",
    "lawsuit",
    "investigation",
    "regulatory",
    "sec investigation",
    "fraud",
    "bankruptcy",
    "halted",
    "recall",
    "data breach",
    "antitrust",
    "margin pressure",
    "cuts outlook",
    "slumps",
    "slides",
    "plunges",
    "sinks",
)


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _published_at(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    return _clean_text(value) or None


def _normalize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    return {
        "title": _clean_text(item.get("title") or content.get("title")),
        "publisher": _clean_text(
            item.get("publisher") or provider.get("displayName") or provider.get("name")
        ),
        "published_at": _published_at(
            item.get("providerPublishTime")
            or item.get("pubDate")
            or content.get("pubDate")
            or content.get("displayTime")
        ),
        "summary": _clean_text(item.get("summary") or content.get("summary")),
        "link": _clean_text(item.get("link") or item.get("clickThroughUrl") or content.get("canonicalUrl")),
    }


def fetch_symbol_news(symbol: str, max_items: int = 5) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Instala yfinance con `pip install -r requirements.txt`.") from exc

    raw_items = yf.Ticker(symbol).news or []
    normalized = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized_item = _normalize_news_item(item)
        if normalized_item["title"]:
            normalized.append(normalized_item)
        if len(normalized) >= max_items:
            break
    return normalized


def _has_fresh_local_news(settings: Settings, news: list[dict[str, Any]]) -> bool:
    max_age_hours = float(getattr(settings, "research_evidence_max_age_hours", 48.0))
    for item in news:
        if str(item.get("provider") or "").lower() not in {"", "yfinance", "yahoo"}:
            continue
        age = freshness_hours(item.get("published_at"))
        if age is not None and age <= max_age_hours:
            return True
    return False


def fetch_combined_symbol_news(
    settings: Settings,
    symbol: str,
    max_items: int = 5,
    *,
    force_web: bool = False,
) -> list[dict[str, Any]]:
    news: list[dict[str, Any]] = []
    try:
        news.extend(fetch_symbol_news(symbol, max_items=max_items))
    except Exception:
        if not getattr(settings, "web_search_enabled", False):
            raise
    should_call_web = force_web or not _has_fresh_local_news(settings, news)
    if getattr(settings, "web_search_enabled", False) and should_call_web:
        web_result = search_company_news(settings, symbol, max_items=max_items)
        news.extend(list(web_result.get("items") or []))
    return dedupe_news_items(news, limit=max_items)


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {
        "sentiment": "unknown",
        "sentiment_score": 0,
        "supports_technical_setup": False,
        "confidence": 0,
        "summary": text[:1000],
        "risk_flags": ["respuesta_llm_no_json"],
    }


def _llm_sentiment(settings: Settings, symbol: str, candidate: dict[str, Any], news: list[dict[str, Any]]) -> dict[str, Any]:
    if not news:
        return {
            "sentiment": "no_news",
            "sentiment_score": 0,
            "supports_technical_setup": False,
            "confidence": 0,
            "summary": "No se encontraron noticias recientes en la fuente configurada.",
            "risk_flags": ["sin_noticias"],
        }

    prompt = {
        "symbol": symbol,
        "technical_direction": candidate.get("direction"),
        "technical_score": candidate.get("score"),
        "technical_reasons": candidate.get("reasons", []),
        "technical_state": candidate.get("technical_state", {}),
        "news": news,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un analista de sentimiento financiero. Usa solo las noticias recibidas. "
                "No recomiendes comprar ni vender. Devuelve solo JSON valido con estas claves: "
                "sentiment (positive|neutral|negative|mixed|no_news), sentiment_score (-2 a 2), "
                "supports_technical_setup (boolean), confidence (0 a 1), summary, risk_flags."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(prompt, ensure_ascii=True),
        },
    ]
    response, _endpoint, _attempts = chat_for_role(
        "sentiment",
        settings=settings,
        messages=messages,
    )
    record_llm_response(settings, "news_sentiment", response, prompt=messages, role="sentiment")
    content = response.choices[0].message.content or "{}"
    result = _extract_json_object(content)
    required = {"sentiment", "sentiment_score", "confidence", "risk_flags"}
    if not required.issubset(result):
        missing = ", ".join(sorted(required - set(result)))
        raise ValueError(f"Respuesta de sentimiento incompleta; faltan: {missing}")
    result["raw_response_preview"] = content[:1000]
    return result


def assess_material_news_risk(
    symbol: str,
    news: list[dict[str, Any]],
    sentiment: dict[str, Any] | None = None,
    *,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Flag material news risk without relying on the LLM path."""

    sentiment = sentiment or {}
    symbol_text = symbol.upper().strip()
    company_text = _clean_text(company_name).lower()

    def _term_matches(*, require_subject: bool) -> tuple[list[str], list[str]]:
        matched_terms: list[str] = []
        matched_titles: list[str] = []
        for item in news:
            text = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("publisher") or ""),
                ]
            ).lower()
            item_terms = [term for term in MATERIAL_NEGATIVE_TERMS if term in text]
            if require_subject:
                subject_present = symbol_text.lower() in text or (bool(company_text) and company_text in text)
                item_terms = [
                    term
                    for term in item_terms
                    if subject_present and term not in {"competitor", "rival"}
                ]
            if item_terms:
                matched_terms.extend(item_terms)
                title = _clean_text(item.get("title"))
                if title:
                    matched_titles.append(title)
        return sorted(set(matched_terms)), matched_titles[:5]

    matched_terms, matched_titles = _term_matches(require_subject=False)
    v2_terms, v2_titles = _term_matches(require_subject=True)
    material_risk_v2 = env_bool("MATERIAL_RISK_V2", False)
    active_terms = v2_terms if material_risk_v2 else matched_terms
    active_titles = v2_titles if material_risk_v2 else matched_titles

    risk_flags = [str(flag) for flag in sentiment.get("risk_flags", [])]
    sentiment_score = sentiment.get("sentiment_score")
    confidence = sentiment.get("confidence") or 0
    negative_sentiment = (
        isinstance(sentiment_score, (int, float))
        and float(confidence) >= 0.5
        and float(sentiment_score) <= -0.5
    )
    failed = "sentiment_failed" in risk_flags

    severity = "none"
    if active_terms or negative_sentiment:
        severity = "material"
    elif failed:
        severity = "unknown"
    elif not news:
        severity = "no_news"

    return {
        "symbol": symbol.upper(),
        "severity": severity,
        "material": severity == "material",
        "unknown": severity == "unknown",
        "matched_terms": active_terms,
        "matched_titles": active_titles,
        "sentiment_failed": failed,
        "sentiment_score": sentiment_score,
        "sentiment_confidence": confidence,
        "risk_flags": risk_flags,
        "material_risk_v2_shadow": {
            "enabled": material_risk_v2,
            "old_severity": "material" if matched_terms or negative_sentiment else ("unknown" if failed else "no_news" if not news else "none"),
            "v2_severity": "material" if v2_terms or negative_sentiment else ("unknown" if failed else "no_news" if not news else "none"),
            "old_terms": matched_terms,
            "v2_terms": v2_terms,
            "material_to_none": bool(matched_terms) and not v2_terms and not negative_sentiment,
        },
    }


def analyze_news_sentiment_for_candidates(
    settings: Settings,
    candidates: list[dict[str, Any]],
    output_dir: Path,
    run_id: str,
    *,
    max_news_items: int = 5,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    results = []
    warnings = []
    total = len(candidates)
    for index, candidate in enumerate(candidates, start=1):
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol:
            continue
        news: list[dict[str, Any]] = []
        try:
            news = fetch_combined_symbol_news(settings, symbol, max_items=max_news_items)
        except Exception as exc:  # noqa: BLE001 - one symbol must not block the study.
            warnings.append(f"{symbol}: news fetch failed: {exc}")
            sentiment = {
                "sentiment": "unknown",
                "sentiment_score": 0,
                "supports_technical_setup": False,
                "confidence": 0,
                "summary": f"No se pudieron descargar noticias: {exc}",
                "risk_flags": ["news_fetch_failed", "sentiment_failed"],
            }
        else:
            try:
                sentiment = _llm_sentiment(settings, symbol, candidate, news)
            except Exception as exc:  # noqa: BLE001 - keep fetched news for deterministic guards.
                warnings.append(f"{symbol}: sentiment failed: {exc}")
                sentiment = {
                    "sentiment": "unknown",
                    "sentiment_score": 0,
                    "supports_technical_setup": False,
                    "confidence": 0,
                    "summary": f"No se pudo validar sentimiento: {exc}",
                    "risk_flags": ["sentiment_failed"],
                }
        try:
            material_risk = assess_material_news_risk(symbol, news, sentiment)
            local_news, web_news = split_local_web_news(news)
            if web_news and getattr(settings, "web_search_enabled", False):
                local_material_risk = assess_material_news_risk(symbol, local_news, sentiment)
                record_web_ab_observation(
                    settings.data_dir,
                    build_web_ab_observation(
                        run_id=run_id,
                        symbol=symbol,
                        news=news,
                        combined_material_risk=material_risk,
                        local_material_risk=local_material_risk,
                        sentiment=sentiment,
                    ),
                )
            results.append(
                {
                    "symbol": symbol,
                    "technical_direction": candidate.get("direction"),
                    "technical_score": candidate.get("score"),
                    "news_count": len(news),
                    "news": news,
                    "sentiment": sentiment,
                    "material_risk": material_risk,
                }
            )
        except Exception as exc:  # noqa: BLE001 - one symbol must not block the study.
            warnings.append(f"{symbol}: {exc}")
            results.append(
                {
                    "symbol": symbol,
                    "technical_direction": candidate.get("direction"),
                    "technical_score": candidate.get("score"),
                    "news_count": 0,
                    "news": [],
                    "sentiment": {
                        "sentiment": "unknown",
                        "sentiment_score": 0,
                        "supports_technical_setup": False,
                        "confidence": 0,
                        "summary": f"No se pudo validar sentimiento: {exc}",
                        "risk_flags": ["sentiment_failed"],
                    },
                    "material_risk": {
                        "symbol": symbol,
                        "severity": "unknown",
                        "material": False,
                        "unknown": True,
                        "matched_terms": [],
                        "matched_titles": [],
                        "sentiment_failed": True,
                        "risk_flags": ["sentiment_failed"],
                    },
                }
            )
        if progress_callback:
            progress_callback(index, total, symbol)

    report = {
        "run_id": run_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbols_analyzed": len(results),
        "candidate_symbols": [item.get("symbol") for item in candidates if item.get("symbol")],
        "results": results,
        "warnings": warnings[:100],
    }
    return write_json_report(
        report,
        output_dir,
        "news_sentiment",
        run_id,
        latest_filename="latest_news_sentiment.json",
    )
