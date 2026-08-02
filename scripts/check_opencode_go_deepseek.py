#!/usr/bin/env python3
"""Comprobador seguro de una sola llamada OpenCode Go / DeepSeek V4 Flash.

El script es deliberadamente independiente del runtime operativo: no importa
el scheduler, el broker, SQLite ni ninguna ruta de decisiones. Solo resuelve
la configuracion LLM ya existente, envia una peticion OpenAI-compatible y
devuelve un diagnostico sanitizado.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_PROVIDER = "opencode-go"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_ENDPOINT = f"{DEFAULT_BASE_URL}/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 20.0
USER_AGENT = "agente-bolsa-opencode-health/1.0"
SYSTEM_PROMPT = 'Devuelve exclusivamente JSON valido con la clave "ok" booleana.'
USER_PROMPT = 'Responde exactamente con {"ok":true}.'

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


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes


class HealthTransport(Protocol):
    def post(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse: ...


class UrllibHealthTransport:
    """Transporte real sin reintentos ni dependencias adicionales."""

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
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - endpoint configurado
                return TransportResponse(status=int(response.status), body=response.read())
        except HTTPError as exc:
            # HTTPError es tambien una respuesta HTTP. No se imprime su cuerpo:
            # puede contener identificadores o detalles sensibles del proveedor.
            return TransportResponse(status=int(exc.code), body=exc.read(2048))


def _endpoint_from_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        base = DEFAULT_BASE_URL
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _endpoint_parts(endpoint: str) -> tuple[str | None, str | None]:
    parsed = urlsplit(endpoint)
    return parsed.hostname, parsed.path or "/"


def _safe_finish_reason(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value[:64]
    return None


def _content_is_non_empty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(
            isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
            for item in value
        )
    return False


def _json_result(
    *,
    config: ProbeConfig,
    status: str,
    http_status: int | None,
    latency_seconds: float | None,
    finish_reason: str | None,
    error_type: str | None,
    error_message: str | None,
    requests_made: int,
) -> dict[str, Any]:
    host, path = _endpoint_parts(config.endpoint)
    return {
        "ok": status == "ok",
        "provider": config.provider,
        "model": config.model,
        "endpoint_host": host,
        "endpoint_path": path,
        "status": status,
        "http_status": http_status,
        "latency_seconds": latency_seconds,
        "finish_reason": finish_reason,
        "fallback_used": False,
        "requests_made": requests_made,
        "error_type": error_type,
        "error_message": error_message,
    }


def _http_error(status: int, body: bytes) -> tuple[str, str]:
    lowered = body[:2048].lower()
    if status == 401:
        return "unauthorized", "OpenCode Go rechazo la autenticacion"
    if status == 403:
        if b"region" in lowered or b"china" in lowered:
            return "region_forbidden", "OpenCode Go rechazo el acceso regional del modelo"
        return "forbidden", "OpenCode Go rechazo la solicitud"
    if status == 404:
        return "not_found", "OpenCode Go no encontro el endpoint o modelo"
    if status == 429:
        return "rate_limited", "OpenCode Go limito la solicitud"
    if 500 <= status <= 599:
        return "provider_error", "OpenCode Go devolvio un error del proveedor"
    return "http_error", f"OpenCode Go devolvio HTTP {status}"


def _invalid_response_error(body: bytes) -> tuple[str, str]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "malformed_json", "La respuesta no es JSON valido"
    if not isinstance(payload, dict):
        return "response_invalid", "La respuesta JSON no es un objeto"
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "choices_missing", "La respuesta no contiene choices validos"
    message = choices[0].get("message")
    if not isinstance(message, dict) or not _content_is_non_empty(message.get("content")):
        return "response_invalid", "La respuesta no contiene contenido valido"
    return "response_invalid", "La respuesta no cumple el contrato esperado"


def run_probe(config: ProbeConfig, transport: HealthTransport | None = None) -> dict[str, Any]:
    """Ejecuta exactamente cero o una peticion, nunca reintenta ni hace fallback."""

    common = {
        "status": "failed",
        "http_status": None,
        "latency_seconds": None,
        "finish_reason": None,
        "error_type": None,
        "error_message": None,
        "requests_made": 0,
    }
    if not config.provider.strip() or config.provider.lower() not in {"opencode", "opencode-go"}:
        common.update(
            error_type="configuration_mismatch",
            error_message="El selector no es OpenCode Go",
        )
        return _json_result(config=config, **common)
    if not config.model.strip() or config.model != DEFAULT_MODEL:
        common.update(
            error_type="configuration_mismatch",
            error_message="El modelo efectivo no es deepseek-v4-flash",
        )
        return _json_result(config=config, **common)
    if not config.endpoint.startswith("https://"):
        common.update(
            error_type="configuration_mismatch",
            error_message="El endpoint debe usar HTTPS",
        )
        return _json_result(config=config, **common)
    if not config.api_key.strip():
        common.update(
            error_type="missing_api_key",
            error_message="No hay credencial OpenCode Go configurada",
        )
        return _json_result(config=config, **common)
    if config.timeout_seconds <= 0:
        common.update(
            error_type="configuration_invalid",
            error_message="El timeout debe ser positivo",
        )
        return _json_result(config=config, **common)

    payload = json.dumps(
        {
            "model": config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT},
            ],
            "temperature": 0,
            "max_tokens": 16,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    active_transport = transport or UrllibHealthTransport()
    started = time.perf_counter()
    try:
        response = active_transport.post(
            endpoint=config.endpoint,
            headers=headers,
            body=payload,
            timeout_seconds=config.timeout_seconds,
        )
    except TimeoutError:
        common.update(
            latency_seconds=round(time.perf_counter() - started, 3),
            error_type="timeout",
            error_message="La solicitud supero el timeout configurado",
            requests_made=1,
        )
        return _json_result(config=config, **common)
    except URLError:
        common.update(
            latency_seconds=round(time.perf_counter() - started, 3),
            error_type="transport_error",
            error_message="No se pudo completar la conexion con OpenCode Go",
            requests_made=1,
        )
        return _json_result(config=config, **common)
    except Exception as exc:  # noqa: BLE001 - healthcheck devuelve diagnostico acotado
        common.update(
            latency_seconds=round(time.perf_counter() - started, 3),
            error_type="transport_error",
            error_message=f"Fallo de transporte: {type(exc).__name__}"[:160],
            requests_made=1,
        )
        return _json_result(config=config, **common)

    latency = round(time.perf_counter() - started, 3)
    common.update(http_status=response.status, latency_seconds=latency, requests_made=1)
    if response.status < 200 or response.status >= 300:
        error_type, error_message = _http_error(response.status, response.body)
        common.update(error_type=error_type, error_message=error_message)
        return _json_result(config=config, **common)

    try:
        payload_obj = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        error_type, error_message = _invalid_response_error(response.body)
        common.update(error_type=error_type, error_message=error_message)
        return _json_result(config=config, **common)

    choices = payload_obj.get("choices") if isinstance(payload_obj, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    finish_reason = _safe_finish_reason(choice.get("finish_reason") if choice else None)
    if choice is None or not isinstance(choice.get("message"), dict):
        error_type, error_message = _invalid_response_error(response.body)
        common.update(finish_reason=finish_reason, error_type=error_type, error_message=error_message)
        return _json_result(config=config, **common)
    if not _content_is_non_empty(choice["message"].get("content")):
        error_type, error_message = _invalid_response_error(response.body)
        common.update(finish_reason=finish_reason, error_type=error_type, error_message=error_message)
        return _json_result(config=config, **common)

    common.update(status="ok", finish_reason=finish_reason)
    return _json_result(config=config, **common)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_settings(repo_root: Path, env_file: Path | None):
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from agente_bolsa.config import Settings

    return Settings(DATA_DIR=repo_root / "data", _env_file=env_file)


def config_from_settings(settings: Any, *, endpoint_override: str | None = None, model_override: str | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> ProbeConfig:
    provider = str(getattr(settings, "llm_model_selector", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).strip().lower()
    base_url = str(getattr(settings, "opencode_api_base", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip()
    endpoint = endpoint_override or _endpoint_from_base(base_url)
    model = model_override or str(getattr(settings, "opencode_model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
    api_key = str(getattr(settings, "opencode_api_key", None) or "").strip()
    return ProbeConfig(
        provider=provider,
        model=model,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Healthcheck de una sola llamada OpenCode Go / DeepSeek V4 Flash.")
    parser.add_argument("--json", action="store_true", help="Emitir un objeto JSON estable.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Timeout de la unica llamada (s).")
    parser.add_argument("--env-file", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--endpoint", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--model", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    root = _repo_root()
    env_file = args.env_file if args.env_file is not None else root / ".env"
    try:
        settings = _load_settings(root, env_file if env_file.exists() else None)
        config = config_from_settings(
            settings,
            endpoint_override=args.endpoint,
            model_override=args.model,
            timeout_seconds=args.timeout,
        )
        result = run_probe(config)
    except Exception as exc:  # noqa: BLE001 - CLI never imprime valores de configuracion
        config = ProbeConfig(
            provider=DEFAULT_PROVIDER,
            model=DEFAULT_MODEL,
            endpoint=DEFAULT_ENDPOINT,
            api_key="",
            timeout_seconds=args.timeout,
        )
        result = _json_result(
            config=config,
            status="failed",
            http_status=None,
            latency_seconds=None,
            finish_reason=None,
            error_type="configuration_error",
            error_message=f"No se pudo resolver la configuracion: {type(exc).__name__}"[:160],
            requests_made=0,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        state = "OK" if result["ok"] else "FALLO"
        print(
            f"{state}: provider={result['provider']} model={result['model']} "
            f"status={result['status']} http={result['http_status']} "
            f"latency={result['latency_seconds']}s finish={result['finish_reason'] or '-'} "
            f"error={result['error_type'] or '-'}"
        )
    if result["ok"]:
        return EXIT_OK
    if result["error_type"] in {"configuration_error", "configuration_invalid", "configuration_mismatch", "missing_api_key"}:
        return EXIT_CONFIGURATION
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
