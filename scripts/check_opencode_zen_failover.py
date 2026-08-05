#!/usr/bin/env python3
"""Single-attempt OpenCode Zen probe with an explicit one-shot Go fallback.

This module is intentionally independent from the trading runtime.  A caller
must opt into ``run_failover``; ``run_probe`` never retries and never calls a
second provider.  Responses and headers are reduced to safe operational
metadata before they are returned.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_PROVIDER = "opencode-zen"
DEFAULT_MODEL = "deepseek-v4-flash-free"
DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_ENDPOINT = f"{DEFAULT_BASE_URL}/chat/completions"
GO_PROVIDER = "opencode-go"
GO_MODEL = "deepseek-v4-flash"
GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TOKENS = 512
USER_AGENT = "agente-bolsa-opencode-zen-health/1.0"
VALID_FINISH_REASONS = frozenset({"stop", "tool_calls", "function_call"})

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIGURATION = 2


@dataclass(frozen=True)
class ProbeConfig:
    provider: str
    model: str
    endpoint: str
    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    mode: str = "health"
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class ProbeTransport(Protocol):
    def post(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse: ...


class UrllibProbeTransport:
    """Real transport: one POST, no retry and no redirect logic of our own."""

    def post(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse:
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit user-selected endpoint
                return TransportResponse(
                    status=int(response.status),
                    body=response.read(),
                    headers={str(k): str(v) for k, v in response.headers.items()},
                )
        except HTTPError as exc:
            return TransportResponse(
                status=int(exc.code),
                body=exc.read(2048),
                headers={str(k): str(v) for k, v in exc.headers.items()},
            )


def endpoint_from_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        base = DEFAULT_BASE_URL
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def endpoint_parts(endpoint: str) -> tuple[str | None, str | None]:
    parsed = urlsplit(endpoint)
    return parsed.hostname, parsed.path or "/"


def _safe_finish_reason(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    return None


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(
            str(item.get("text"))
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ).strip()
    return ""


def _safe_text_presence(value: Any) -> tuple[bool, int]:
    text = _content_text(value)
    return bool(text), len(text)


def _mode_payload(mode: str) -> dict[str, Any]:
    if mode == "structured":
        return {
            "messages": [
                {"role": "system", "content": 'Return only JSON with boolean key "ok".'},
                {"role": "user", "content": 'Return exactly {"ok":true}.'},
            ],
            "response_format": {"type": "json_object"},
        }
    if mode == "multiturn":
        return {
            "messages": [
                {"role": "system", "content": "Answer benign synthetic checks concisely."},
                {"role": "user", "content": "Remember the token: amber."},
                {"role": "assistant", "content": "amber"},
                {"role": "user", "content": "Return the remembered token only."},
            ],
        }
    if mode == "combined":
        return {
            "messages": [
                {"role": "system", "content": 'Return only JSON with boolean key "ok".'},
                {"role": "user", "content": "Remember the token: amber."},
                {"role": "assistant", "content": "amber"},
                {"role": "user", "content": 'Return {"ok":true} and no other text.'},
            ],
            "response_format": {"type": "json_object"},
        }
    return {
        "messages": [
            {"role": "system", "content": "Return a short benign health response."},
            {"role": "user", "content": "Reply with the word ready."},
        ],
    }


def _safe_usage(payload: Any) -> dict[str, int] | None:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            result[key] = value
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        value = details.get("reasoning_tokens")
        if isinstance(value, int) and value >= 0:
            result["reasoning_tokens"] = value
    return result or None


def _header_metadata(headers: Mapping[str, str]) -> dict[str, Any]:
    lower = {str(key).lower(): str(value) for key, value in headers.items()}
    rate_headers = sorted(key for key in lower if key.startswith("x-ratelimit-"))
    retry_after = "retry-after" in lower
    request_id = any(key in lower for key in ("x-request-id", "request-id", "openai-request-id"))
    return {
        "request_id_present": request_id,
        "retry_after_present": retry_after,
        "rate_limit_headers_present": bool(rate_headers),
        "rate_limit_header_names": rate_headers,
    }


def _error_class(status: int | None, *, transport: str | None = None, body: bytes = b"") -> tuple[str, str]:
    if transport == "timeout":
        return "timeout", "La solicitud supero el timeout configurado"
    if transport == "connection":
        return "connection_error", "No se pudo completar la conexion con el proveedor"
    if status == 401:
        return "unauthorized", "El proveedor rechazo la autenticacion"
    if status == 403:
        if b"region" in body[:2048].lower() or b"china" in body[:2048].lower():
            return "region_forbidden", "El proveedor rechazo el acceso regional"
        return "forbidden", "El proveedor rechazo la solicitud"
    if status == 404:
        return "not_found", "No se encontro el endpoint o modelo"
    if status == 408:
        return "request_timeout", "El proveedor devolvio HTTP 408"
    if status == 409:
        return "conflict", "El proveedor devolvio HTTP 409"
    if status == 429:
        return "rate_limited", "El proveedor limito la solicitud"
    if status is not None and 500 <= status <= 599:
        return "provider_error", "El proveedor devolvio un error 5xx"
    if status is not None:
        return "http_error", f"El proveedor devolvio HTTP {status}"
    return "probe_error", "La prueba no pudo clasificarse"


def _result(
    *,
    config: ProbeConfig,
    ok: bool,
    status: str,
    http_status: int | None,
    latency_seconds: float | None,
    finish_reason: str | None,
    error_type: str | None,
    error_message: str | None,
    requests_made: int,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    primary_error_class: str | None = None,
    usage: dict[str, int] | None = None,
    headers: Mapping[str, str] | None = None,
    content_present: bool = False,
    content_length: int = 0,
    reasoning_content_present: bool = False,
    reasoning_content_length: int = 0,
) -> dict[str, Any]:
    host, path = endpoint_parts(config.endpoint)
    metadata = _header_metadata(headers or {})
    return {
        "ok": ok,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider": config.provider,
        "model": config.model,
        "endpoint_host": host,
        "endpoint_path": path,
        "status": status,
        "http_status": http_status,
        "latency_seconds": latency_seconds,
        "finish_reason": finish_reason,
        "content_present": content_present,
        "content_length": content_length,
        "reasoning_content_present": reasoning_content_present,
        "reasoning_content_length": reasoning_content_length,
        "usage": usage,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "primary_error_class": primary_error_class,
        "requests_made": requests_made,
        "error_type": error_type,
        "error_message": error_message,
        "request_id_present": metadata["request_id_present"],
        "retry_after_present": metadata["retry_after_present"],
        "rate_limit_headers_present": metadata["rate_limit_headers_present"],
        "rate_limit_header_names": metadata["rate_limit_header_names"],
    }


def run_probe(config: ProbeConfig, transport: ProbeTransport | None = None) -> dict[str, Any]:
    """Execute exactly one request or zero when local configuration is invalid."""

    if not config.provider.strip() or not config.model.strip() or not config.endpoint.startswith("https://"):
        return _result(
            config=config,
            ok=False,
            status="configuration_error",
            http_status=None,
            latency_seconds=None,
            finish_reason=None,
            error_type="configuration_invalid",
            error_message="provider, model y endpoint HTTPS son obligatorios",
            requests_made=0,
        )
    if not config.api_key.strip():
        return _result(
            config=config,
            ok=False,
            status="configuration_error",
            http_status=None,
            latency_seconds=None,
            finish_reason=None,
            error_type="missing_api_key",
            error_message="No hay credencial OpenCode configurada",
            requests_made=0,
        )
    if config.timeout_seconds <= 0:
        return _result(
            config=config,
            ok=False,
            status="configuration_error",
            http_status=None,
            latency_seconds=None,
            finish_reason=None,
            error_type="configuration_invalid",
            error_message="El timeout debe ser positivo",
            requests_made=0,
        )

    body_obj = {
        "model": config.model,
        **_mode_payload(config.mode),
        "temperature": 0,
        "max_tokens": config.max_tokens,
    }
    if config.mode in {"multiturn", "combined"}:
        body_obj["reasoning_effort"] = "low"
    body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    active_transport = transport or UrllibProbeTransport()
    started = time.perf_counter()
    try:
        response = active_transport.post(
            endpoint=config.endpoint,
            headers=headers,
            body=body,
            timeout_seconds=config.timeout_seconds,
        )
    except TimeoutError:
        latency = round(time.perf_counter() - started, 3)
        error_type, message = _error_class(None, transport="timeout")
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=None,
            latency_seconds=latency,
            finish_reason=None,
            error_type=error_type,
            error_message=message,
            requests_made=1,
        )
    except URLError:
        latency = round(time.perf_counter() - started, 3)
        error_type, message = _error_class(None, transport="connection")
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=None,
            latency_seconds=latency,
            finish_reason=None,
            error_type=error_type,
            error_message=message,
            requests_made=1,
        )
    except Exception as exc:  # noqa: BLE001 - health probe returns a bounded class only
        latency = round(time.perf_counter() - started, 3)
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=None,
            latency_seconds=latency,
            finish_reason=None,
            error_type="transport_error",
            error_message=f"Fallo de transporte: {type(exc).__name__}"[:160],
            requests_made=1,
        )

    latency = round(time.perf_counter() - started, 3)
    if response.status < 200 or response.status >= 300:
        error_type, message = _error_class(response.status, body=response.body)
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=response.status,
            latency_seconds=latency,
            finish_reason=None,
            error_type=error_type,
            error_message=message,
            requests_made=1,
            headers=response.headers,
        )
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=response.status,
            latency_seconds=latency,
            finish_reason=None,
            error_type="malformed_response",
            error_message="La respuesta no es JSON valido",
            requests_made=1,
            headers=response.headers,
        )
    choices = payload.get("choices") if isinstance(payload, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    message = choice.get("message") if choice else None
    finish_reason = _safe_finish_reason(choice.get("finish_reason") if choice else None)
    content_value = message.get("content") if isinstance(message, dict) else None
    reasoning_value = message.get("reasoning_content") if isinstance(message, dict) else None
    content_present, content_length = _safe_text_presence(content_value)
    reasoning_present, reasoning_length = _safe_text_presence(reasoning_value)
    if choice is None or not isinstance(message, dict) or not content_present:
        error_type, message_text = "response_invalid", "La respuesta no contiene contenido valido"
    elif finish_reason not in VALID_FINISH_REASONS:
        error_type, message_text = "finish_reason_invalid", "finish_reason no util para el contrato"
    elif config.mode == "structured":
        try:
            structured = json.loads(_content_text(content_value))
        except json.JSONDecodeError:
            structured = None
        if not isinstance(structured, dict) or structured.get("ok") is not True:
            error_type, message_text = "structured_response_invalid", "La respuesta estructurada no cumple el contrato"
        else:
            error_type = message_text = None
    else:
        error_type = message_text = None
    if error_type:
        return _result(
            config=config,
            ok=False,
            status="failed",
            http_status=response.status,
            latency_seconds=latency,
            finish_reason=finish_reason,
            error_type=error_type,
            error_message=message_text,
            requests_made=1,
            usage=_safe_usage(payload),
            headers=response.headers,
            content_present=content_present,
            content_length=content_length,
            reasoning_content_present=reasoning_present,
            reasoning_content_length=reasoning_length,
        )
    return _result(
        config=config,
        ok=True,
        status="ok",
        http_status=response.status,
        latency_seconds=latency,
        finish_reason=finish_reason,
        error_type=None,
        error_message=None,
        requests_made=1,
        usage=_safe_usage(payload),
        headers=response.headers,
        content_present=content_present,
        content_length=content_length,
        reasoning_content_present=reasoning_present,
        reasoning_content_length=reasoning_length,
    )


def run_failover(
    primary: ProbeConfig,
    fallback: ProbeConfig,
    *,
    transport: ProbeTransport,
) -> dict[str, Any]:
    """Try primary once, then Go once only when primary fails."""

    first = run_probe(primary, transport=transport)
    if first["ok"]:
        return first
    second = run_probe(fallback, transport=transport)
    combined = dict(second if second["ok"] else first)
    combined.update(
        {
            "fallback_used": bool(second["ok"]),
            "fallback_reason": first.get("error_type"),
            "primary_error_class": first.get("error_type"),
            "requests_made": int(first.get("requests_made") or 0) + int(second.get("requests_made") or 0),
        }
    )
    return combined


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_env_file(repo_root: Path) -> Path | None:
    candidates = (
        repo_root / ".env",
        repo_root.parent / "agenteBolsa" / ".env",
        repo_root.parent.parent / "agenteBolsa" / ".env",
    )
    return next((path for path in candidates if path.is_file()), None)


def _load_api_key(repo_root: Path, env_file: Path | None) -> str:
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from agente_bolsa.config import Settings

    settings = Settings(DATA_DIR=repo_root / "data", _env_file=env_file)
    return str(settings.opencode_api_key or "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe de una llamada OpenCode Zen con fallback Go opcional de una tentativa.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--mode", choices=("health", "structured", "multiturn", "combined"), default="health")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help=argparse.SUPPRESS)
    parser.add_argument("--with-go-fallback", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--env-file", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = _repo_root()
    env_file = args.env_file if args.env_file is not None else _default_env_file(root)
    api_key = _load_api_key(root, env_file if env_file and env_file.exists() else None)
    primary = ProbeConfig(
        provider=args.provider,
        model=args.model,
        endpoint=endpoint_from_base(args.base_url),
        api_key=api_key,
        timeout_seconds=args.timeout,
        mode=args.mode,
        max_tokens=args.max_tokens,
    )
    if args.with_go_fallback:
        fallback = ProbeConfig(
            provider=GO_PROVIDER,
            model=GO_MODEL,
            endpoint=endpoint_from_base(GO_BASE_URL),
            api_key=api_key,
            timeout_seconds=args.timeout,
            mode="health",
        )
        result = run_failover(primary, fallback, transport=UrllibProbeTransport())
    else:
        result = run_probe(primary)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if result["ok"] else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
