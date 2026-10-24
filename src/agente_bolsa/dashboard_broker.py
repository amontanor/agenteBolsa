"""Presentation-only FILL GET adapter. No order or trading authority."""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _normal_endpoint(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    endpoint = value.strip().rstrip("/")
    if endpoint.endswith("/v2"):
        return endpoint[:-3]
    return endpoint

def _decode_activity_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Accept the list payload and the paginated object shape.

    Alpaca has returned ``[activity, ...]`` for this endpoint; a paginated
    object (``activities``/``items`` plus ``next_page_token``) is accepted too so
    malformed items or unknown shapes raise instead of certifying completeness.
    """
    if isinstance(payload, list):
        if any(not isinstance(item, dict) or not item.get("id") for item in payload):
            raise ValueError("Actividad sin ID")
        return [item for item in payload if isinstance(item, dict)], None
    if isinstance(payload, dict):
        for key in ("activities", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                if any(not isinstance(item, dict) or not item.get("id") for item in value):
                    raise ValueError("Actividad sin ID")
                token = payload.get("next_page_token") or payload.get("page_token")
                text = str(token).strip() if token else ""
                return [item for item in value if isinstance(item, dict)], text or None
    raise ValueError("Respuesta de actividades no interpretable.")

def _header_token(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("X-Next-Page-Token", "X-Pagination-Next-Page-Token", "Next-Page-Token"):
        try:
            value = headers.get(name)
        except AttributeError:
            return None
        if value:
            text = str(value).strip()
            if text:
                return text
    return None

def _read_activity_page(url: str, headers: dict[str, str], timeout: float) -> tuple[Any, str | None]:
    """One HTTP read of the activities endpoint, separated for deterministic tests."""
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        token = _header_token(response)
    return json.loads(body), token

class DashboardBroker:
    def __init__(self, settings: Any, *, read_timeout: float = 5.0) -> None:
        self.settings = settings
        if not math.isfinite(read_timeout) or read_timeout <= 0:
            raise ValueError("read_timeout must be finite and positive")
        self.read_timeout = read_timeout

    def alpaca_trade_activities(
        self,
        *,
        limit: int = 100,
        timeout: float | None = None,
        page_token: str | None = None,
        after: str | None = None,
        direction: str = "desc",
        max_pages: int = 1,
    ) -> list[dict[str, Any]]:
        """Fetch trade fill activities from Alpaca paper REST API.

        Kept as the historical list-returning entry point: ``limit`` is clamped to
        the provider page size of 100 and, by default, exactly one page is read.
        Callers that need cursor metadata use
        :meth:`alpaca_trade_activities_page`.
        """

        envelope = self.alpaca_trade_activities_page(
            page_size=limit,
            timeout=timeout,
            page_token=page_token,
            after=after,
            direction=direction,
            max_pages=max_pages,
        )
        return list(envelope["items"])

    def alpaca_trade_activities_page(
        self,
        *,
        limit: int = 100,
        page_size: int | None = None,
        timeout: float | None = None,
        page_token: str | None = None,
        after: str | None = None,
        direction: str = "desc",
        max_pages: int = 1,
    ) -> dict[str, Any]:
        """Read fill activities with real cursor pagination.

        Contract
        --------
        - ``page_size`` is clamped to ``1..100``; ``limit`` is the fallback.
        - ``page_token`` is an activity ID; ``after`` is an ISO date/time.
          Bare arrays continue using the final activity ID, until an empty page.
        - At most ``max_pages`` requests are made. The loop stops on an empty
          page, an absent token, a repeated token or the page ceiling.
        - The result always carries ``pages``, ``next_page_token``, ``truncated``
          and ``stop_reason`` so a partial read can never be presented as a
          complete history. Items are validated dictionaries, deduplicated by
          activity id and kept in provider order.
        - Only presentation reads: no order, risk, execution or sizing behaviour
          depends on this method.
        """

        self.settings.assert_trading_safety()
        if direction not in {"asc", "desc"}:
            raise ValueError("direction debe ser asc o desc.")
        if after:
            datetime.fromisoformat(str(after).replace("Z", "+00:00"))
        endpoint = _normal_endpoint(self.settings.alpaca_endpoint) or "https://paper-api.alpaca.markets"
        size = max(1, min(int(page_size if page_size is not None else limit), 100))
        page_ceiling = max(1, int(max_pages))
        headers = {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key or "",
            "APCA-API-SECRET-KEY": self.settings.alpaca_secret_key or "",
            "Accept": "application/json",
        }
        effective_timeout = self.read_timeout if timeout is None else float(timeout)
        if not math.isfinite(effective_timeout) or effective_timeout <= 0:
            raise ValueError("timeout must be finite and positive")

        items: list[dict[str, Any]] = []
        seen_ids: dict[str, dict[str, Any]] = {}
        seen_tokens: set[str] = set()
        token = str(page_token).strip() if page_token else ""
        if token:
            seen_tokens.add(token)
        pages_done = 0
        next_token: str | None = token or None
        truncated = False
        stop_reason = "exhausted"

        while pages_done < page_ceiling:
            params: dict[str, str] = {"direction": direction, "page_size": str(size)}
            if after:
                params["after"] = str(after)
            if token:
                params["page_token"] = token
            url = f"{endpoint}/v2/account/activities/FILL?{urlencode(params)}"
            payload, header_token = _read_activity_page(url, headers, effective_timeout)
            page_items, body_token = _decode_activity_page(payload)
            pages_done += 1
            for item in page_items:
                activity_id = str(item.get("id") or "").strip()
                if activity_id and activity_id in seen_ids:
                    if seen_ids[activity_id] != item:
                        raise ValueError("Actividad con ID duplicado y contenido distinto")
                    continue
                if activity_id:
                    seen_ids[activity_id] = item
                items.append(item)

            next_token = body_token or header_token
            if isinstance(payload, list) and payload:
                # Alpaca returns an array, without a next-token header. Even a
                # short page is continued until explicit empty-page exhaustion.
                if any(not isinstance(item, dict) or not item.get("id") for item in payload):
                    raise ValueError("Actividad sin ID: no se puede garantizar la paginacion.")
                next_token = str(payload[-1]["id"])
            if not page_items:
                # An empty page ends the read; a token that arrives with it is
                # reported as truncation, never assumed to be exhausted data.
                truncated = bool(next_token)
                stop_reason = "empty_page"
                break
            if not next_token:
                stop_reason = "exhausted"
                break
            if next_token in seen_tokens:
                truncated = True
                stop_reason = "repeated_token"
                break
            seen_tokens.add(next_token)
            token = next_token
            if pages_done >= page_ceiling:
                truncated = True
                stop_reason = "max_pages"
                break

        return {
            "items": items,
            "pages": pages_done,
            "next_page_token": next_token,
            "truncated": truncated,
            "stop_reason": stop_reason,
            "page_size": size,
            "direction": direction,
        }
