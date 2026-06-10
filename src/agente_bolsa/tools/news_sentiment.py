"""News download and LLM sentiment validation for technical candidates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agente_bolsa.config import Settings
from agente_bolsa.llm_router import chat_for_role
from agente_bolsa.llm_usage import record_llm_response
from .reporting import write_json_report


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
        "fast",
        settings=settings,
        messages=messages,
    )
    record_llm_response(settings, "news_sentiment", response, prompt=messages, role="fast")
    content = response.choices[0].message.content or "{}"
    result = _extract_json_object(content)
    result["raw_response_preview"] = content[:1000]
    return result


def assess_material_news_risk(
    symbol: str,
    news: list[dict[str, Any]],
    sentiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flag material news risk without relying on the LLM path."""

    sentiment = sentiment or {}
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
        if item_terms:
            matched_terms.extend(item_terms)
            title = _clean_text(item.get("title"))
            if title:
                matched_titles.append(title)

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
    if matched_terms or negative_sentiment:
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
        "matched_terms": sorted(set(matched_terms)),
        "matched_titles": matched_titles[:5],
        "sentiment_failed": failed,
        "sentiment_score": sentiment_score,
        "sentiment_confidence": confidence,
        "risk_flags": risk_flags,
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
            news = fetch_symbol_news(symbol, max_items=max_news_items)
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
