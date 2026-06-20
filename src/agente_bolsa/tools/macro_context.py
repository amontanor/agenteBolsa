"""Contexto macro continuo y tesis de mercado viva (T3.1).

El sistema lee el mercado como un gestor: calendario economico, earnings de la
semana y titulares amplios, y produce una tesis diaria (stance risk_on/neutral/
risk_off) que modula la agresividad de compras. La descarga de datos es
best-effort (degrada a vacio con flag de calidad) y la llamada al modelo es
inyectable para tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


DEFAULT_THESIS_PROMPT = (
    "Eres un estratega de mercado. A partir de los eventos macro proximos, el estado "
    "de mercado, el rendimiento reciente del sistema y la tesis anterior, produce la "
    "tesis del dia. Devuelve SOLO JSON con: stance (risk_on|neutral|risk_off), "
    "key_risks (lista), key_catalysts (lista), sector_bias (objeto), confidence (0-1), "
    "changes_vs_previous (texto breve)."
)

_VALID_STANCES = {"risk_on", "neutral", "risk_off"}


def fetch_macro_events(settings: Settings) -> dict[str, Any]:
    """Calendario economico, earnings de la semana y titulares generales.

    Best-effort: si no hay FMP configurado o falla la red, devuelve listas vacias
    con un flag de calidad en vez de propagar la excepcion.
    """

    fmp_key = getattr(settings, "fmp_api_key", None)
    if not fmp_key:
        return {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": "no_provider"}
    try:
        from datetime import timedelta

        today = datetime.now(timezone.utc).date()
        horizon = (today + timedelta(days=5)).isoformat()
        economic = _fmp_get(fmp_key, "economic_calendar", {"from": today.isoformat(), "to": horizon})
        earnings = _fmp_get(fmp_key, "earning_calendar", {"from": today.isoformat(), "to": horizon})
        news = _fmp_get(fmp_key, "stock_news", {"limit": 40})
        return {
            "economic_calendar": economic[:50],
            "earnings_calendar": earnings[:100],
            "general_news": [{"title": item.get("title"), "site": item.get("site")} for item in news[:25]],
            "quality": "ok",
        }
    except Exception as exc:  # noqa: BLE001 - degradacion controlada.
        return {"economic_calendar": [], "earnings_calendar": [], "general_news": [], "quality": f"error:{type(exc).__name__}"}


def build_market_thesis(
    store: Store,
    settings: Settings,
    *,
    macro_events: dict[str, Any] | None = None,
    market_state: dict[str, Any] | None = None,
    recent_performance: dict[str, Any] | None = None,
    llm: Callable[[list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    """Construye y persiste la tesis del dia."""

    macro_events = macro_events if macro_events is not None else fetch_macro_events(settings)
    previous = store.latest_market_thesis()
    from ..prompt_store import get_prompt

    system = get_prompt(settings, "market_thesis", DEFAULT_THESIS_PROMPT)
    user = {
        "macro_events": macro_events,
        "market_state": market_state or {},
        "recent_performance": recent_performance or {},
        "previous_thesis": (previous or {}).get("payload", {}),
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=True, default=str)},
    ]
    raw = llm(messages) if llm is not None else _default_llm(settings, messages)
    payload = _extract_obj(raw)

    stance = str(payload.get("stance") or "neutral").lower()
    if stance not in _VALID_STANCES:
        stance = "neutral"
    confidence = payload.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    confidence = max(0.0, min(1.0, confidence))
    payload["stance"] = stance
    payload["confidence"] = confidence
    payload["macro_quality"] = macro_events.get("quality")

    thesis_date = datetime.now(timezone.utc).date().isoformat()
    store.upsert_market_thesis({"thesis_date": thesis_date, "payload": payload, "stance": stance, "confidence": confidence})
    return {"thesis_date": thesis_date, "stance": stance, "confidence": confidence, "payload": payload}


def risk_off_buy_factor(settings: Settings, thesis: dict[str, Any] | None) -> float:
    """Factor multiplicativo del limite de compras segun la tesis (T3.1)."""

    if not thesis:
        return 1.0
    stance = str(thesis.get("stance") or "").lower()
    confidence = thesis.get("confidence")
    threshold = float(getattr(settings, "risk_off_confidence_threshold", 0.7))
    if stance == "risk_off" and isinstance(confidence, (int, float)) and float(confidence) > threshold:
        return float(getattr(settings, "risk_off_buy_factor", 0.5))
    return 1.0


def load_latest_thesis(settings: Settings) -> dict[str, Any] | None:
    try:
        from ..storage import Store

        store = Store(settings.database_path, settings.agent_logs_dir)
        return store.latest_market_thesis()
    except Exception:  # noqa: BLE001
        return None


def _fmp_get(api_key: str, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from urllib.parse import urlencode
    from urllib.request import urlopen

    query = urlencode({**params, "apikey": api_key})
    url = f"https://financialmodelingprep.com/api/v3/{endpoint}?{query}"
    with urlopen(url, timeout=20) as response:  # noqa: S310 - endpoint fijo de FMP.
        data = json.loads(response.read().decode("utf-8"))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _extract_obj(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    text = str(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _default_llm(settings: Settings, messages: list[dict[str, str]]) -> str:
    try:
        from ..llm_router import chat_for_role

        response, _endpoint, _attempts = chat_for_role("deep", settings=settings, messages=messages)
        return response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        return ""
