"""Opportunity extraction for Telegram radar posts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from agente_bolsa.config import Settings, get_settings
from agente_bolsa.llm_router import chat_for_role
from agente_bolsa.tools.universe import universe_as_of

from .models import TelegramExtraction

NAME_TO_TICKER = {
    "palantir": "PLTR",
    "reddit": "RDDT",
    "ferrari": "RACE",
    "mercadolibre": "MELI",
    "mercado libre": "MELI",
    "meli": "MELI",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "meta": "META",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "oracle": "ORCL",
    "micron": "MU",
    "micrón": "MU",
    "sandisk": "SNDK",
}

TICKER_RE = re.compile(r"(?<![A-Z0-9])\$?([A-Z][A-Z0-9.-]{1,5})(?![A-Z0-9])")
TICKER_STOPWORDS = {"AYER", "HOY", "MAS", "USA", "VIP"}


def normalize_mentions(text: str) -> tuple[list[str], list[str]]:
    found: list[str] = []
    unresolved: list[str] = []
    for match in TICKER_RE.finditer(text):
        token = match.group(1).replace(".", "-").strip("-")
        if token in TICKER_STOPWORDS:
            continue
        if 1 < len(token) <= 5:
            found.append(token)
    lower_text = text.lower()
    for name, ticker in NAME_TO_TICKER.items():
        if name in lower_text:
            found.append(ticker)
    result = sorted(dict.fromkeys(found))
    for word in re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text):
        lower = word.lower()
        if lower not in NAME_TO_TICKER and word.upper() not in result:
            unresolved.append(word)
    return result, sorted(dict.fromkeys(unresolved))


def map_tickers_to_universe(
    tickers: list[str],
    *,
    posted_at: str | None,
    current_universe: list[str] | None = None,
) -> list[dict[str, Any]]:
    as_of = str(posted_at or "")[:10] or "2026-01-01"
    state = universe_as_of(as_of, current_universe=current_universe)
    members = {str(symbol).upper() for symbol in state.get("symbols", [])}
    rows: list[dict[str, Any]] = []
    for ticker in sorted(dict.fromkeys(str(item).upper() for item in tickers if str(item).strip())):
        in_universe = ticker in members
        rows.append(
            {
                "ticker": ticker,
                "as_of": state.get("as_of", as_of),
                "in_universe": in_universe,
                "out_of_coverage": not in_universe,
                "survivorship_biased": bool(state.get("survivorship_biased")),
            }
        )
    return rows


def extract_opportunity(
    post: dict[str, Any],
    *,
    settings: Settings | None = None,
    llm: Callable[[list[dict[str, Any]]], str] | None = None,
    use_llm: bool = True,
    current_universe: list[str] | None = None,
) -> TelegramExtraction:
    text = str(post.get("text") or "")
    heuristic_tickers, heuristic_unresolved = normalize_mentions(text)
    raw: dict[str, Any] = {}
    llm_error: str | None = None
    llm_model: str | None = None
    status = "heuristic_only"
    if use_llm:
        messages = _messages_for_post(text)
        try:
            content = _call_extraction_llm(messages, settings=settings, llm=llm)
            raw = _parse_json_object(content)
            status = "llm_ok"
        except json.JSONDecodeError as exc:
            try:
                content = _call_extraction_llm(_messages_for_post(text, retry=True), settings=settings, llm=llm)
                raw = _parse_json_object(content)
                status = "llm_ok"
            except Exception as retry_exc:
                llm_error = f"{exc}; retry: {retry_exc}"
                status = "llm_unavailable_heuristic_fallback"
        except ValueError as exc:
            try:
                content = _call_extraction_llm(_messages_for_post(text, retry=True), settings=settings, llm=llm)
                raw = _parse_json_object(content)
                status = "llm_ok"
            except Exception as retry_exc:
                llm_error = f"{exc}; retry: {retry_exc}"
                status = "llm_unavailable_heuristic_fallback"
        except Exception as exc:
            llm_error = str(exc)
            status = "llm_unavailable_heuristic_fallback"

    raw_tickers = [str(item).upper().replace("$", "").replace(".", "-") for item in raw.get("tickers", []) if str(item).strip()]
    tickers = sorted(dict.fromkeys([*heuristic_tickers, *raw_tickers]))
    direction = _normalize_direction(str(raw.get("direction") or _heuristic_direction(text)))
    is_opportunity = bool(raw.get("is_opportunity", bool(tickers and direction in {"buy", "sell", "watch"})))
    thesis = str(raw.get("thesis") or _heuristic_thesis(text, tickers))
    timeframe = raw.get("timeframe")
    confidence = _clamp_float(raw.get("confidence"), default=0.45 if status.startswith("llm_") else 0.35)
    unresolved = sorted(dict.fromkeys([*heuristic_unresolved, *[str(x) for x in raw.get("unresolved_mentions", []) if str(x).strip()]]))
    coverage = map_tickers_to_universe(tickers, posted_at=post.get("posted_at"), current_universe=current_universe)
    return TelegramExtraction(
        message_id=int(post["message_id"]),
        extraction_status=status,
        is_opportunity=is_opportunity,
        tickers=tickers,
        direction=direction,
        thesis=thesis[:500],
        timeframe=str(timeframe) if timeframe else None,
        confidence=confidence,
        unresolved_mentions=unresolved,
        ticker_coverage=coverage,
        llm_error=llm_error,
        llm_model=llm_model,
    )


def _call_extraction_llm(
    messages: list[dict[str, Any]],
    *,
    settings: Settings | None,
    llm: Callable[[list[dict[str, Any]]], str] | None,
) -> str:
    return llm(messages) if llm else _call_llm(messages, settings or get_settings())


def _messages_for_post(text: str, *, retry: bool = False) -> list[dict[str, Any]]:
    retry_prefix = (
        "REINTENTO: la respuesta anterior no fue JSON parseable. "
        "Responde SOLO con el objeto JSON, sin texto, sin markdown y sin fences. "
        if retry
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                f"{retry_prefix}"
                "Extrae oportunidades de bolsa de posts de Telegram en espanol. "
                "Tu respuesta completa debe ser un unico objeto JSON valido: debe empezar con { y acabar con }. "
                "No incluyas explicaciones, razonamiento, texto antes/despues, markdown ni fences ```json. "
                "Usa exactamente estas claves: "
                "is_opportunity (boolean), tickers (array de strings), "
                "direction (uno de buy, sell, watch, none), thesis (string breve), "
                "timeframe (string o null), confidence (numero 0-1), unresolved_mentions (array de strings). "
                "Normaliza $RH a RH y nombres comunes: Palantir=PLTR, Reddit=RDDT, Ferrari=RACE, "
                "MercadoLibre/MELI=MELI, Google=GOOGL, Oracle=ORCL, Micron=MU. "
                "Si no hay ticker concreto, usa tickers=[] y direction=none."
            ),
        },
        {"role": "user", "content": text},
    ]


def _call_llm(messages: list[dict[str, Any]], settings: Settings) -> str:
    response, _endpoint, _attempts = chat_for_role(
        "deep",
        settings=settings,
        messages=messages,
        temperature=0.0,
        max_tokens=900,
    )
    choice = response.choices[0]
    return _response_message_text(getattr(choice, "message", None))


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _extract_first_json_object(content)
    value = json.loads(text)
    return value if isinstance(value, dict) else {}


def _response_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if str(content or "").strip():
        return str(content)
    reasoning_content = getattr(message, "reasoning_content", None)
    if reasoning_content is None and isinstance(message, dict):
        reasoning_content = message.get("reasoning_content")
    return str(reasoning_content or "")


def _extract_first_json_object(content: str) -> str:
    text = _strip_outer_fence(str(content or "").strip())
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("no_json_object_found")


def _strip_outer_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    first_line_end = stripped.find("\n")
    if first_line_end == -1:
        return stripped
    closing = stripped.rfind("```")
    if closing <= first_line_end:
        return stripped
    return stripped[first_line_end + 1 : closing].strip()


def _normalize_direction(value: str) -> str:
    token = value.strip().lower()
    if token in {"buy", "compra", "comprar", "long"}:
        return "buy"
    if token in {"sell", "venta", "vender", "short"}:
        return "sell"
    if token in {"watch", "vigilar", "seguimiento", "mirar"}:
        return "watch"
    return "none"


def _heuristic_direction(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("compramos", "comprar", "compra", "me gusta", "entramos")):
        return "buy"
    if any(word in lower for word in ("vendemos", "vender", "venta", "salimos")):
        return "sell"
    if any(word in lower for word in ("vigilar", "watch", "radar", "seguimiento", "oportunidad")):
        return "watch"
    return "none"


def _heuristic_thesis(text: str, tickers: list[str]) -> str:
    if not tickers:
        return ""
    return f"Mencion explicita en radar Telegram: {', '.join(tickers)}."


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, round(number, 4)))
