#!/usr/bin/env python3
"""Chequeo de salud de los proveedores LLM configurados.

Motivacion (16-jun-2026): el sistema dejo de operar porque el LLM de decision
y el de sentimiento no producian respuestas desde ~6-jun. El sistema cayo en
fallback determinista de forma silenciosa. Este script comprueba de forma
explicita si cada proveedor LLM configurado responde, para detectar el modo
degradado antes de que paralice la operativa.

Uso (no requiere dependencias del proyecto, solo stdlib):

    python scripts/llm_health_check.py
    python scripts/llm_health_check.py --json
    python scripts/llm_health_check.py --timeout 20

Codigos de salida:
    0  -> decision, sentimiento y codegen tienen proveedor disponible
    1  -> algun rol critico no tiene proveedor disponible

Lee la configuracion de .env (no sobrescribe variables ya presentes en el
entorno). Nunca imprime claves completas.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    """Carga simple de .env sin dependencias externas."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        values.setdefault(key, val)
    return values


def cfg(env: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key) or env.get(key, default)


def mask(value: str) -> str:
    if not value:
        return "(vacio)"
    if len(value) <= 6:
        return value[:2] + "***"
    return value[:4] + "***" + value[-2:]


def ping_provider(
    name: str,
    base: str,
    key: str,
    model: str,
    timeout: float,
    *,
    role: str = "",
    json_probe: bool = False,
) -> dict:
    """Lanza una completion minima y mide latencia/estado."""
    result = {
        "provider": name,
        "base_url": base,
        "model": model,
        "api_key": mask(key),
        "role": role,
        "ok": False,
        "latency_ms": None,
        "status": None,
        "detail": None,
    }
    if not base or not model:
        result["detail"] = "configuracion incompleta (base_url o model vacios)"
        return result

    url = base.rstrip("/") + "/chat/completions"
    if json_probe:
        messages = [
            {"role": "system", "content": "Devuelve solo JSON valido."},
            {"role": "user", "content": 'Devuelve exactamente {"ok": true}.'},
        ]
        max_tokens = 64
    else:
        messages = [{"role": "user", "content": "Responde solo: OK"}]
        max_tokens = 8
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if json_probe:
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    # User-Agent normal: algunos proveedores estan tras Cloudflare y bloquean
    # con 403 el UA por defecto de urllib (Python-urllib/x.y).
    req.add_header("User-Agent", "agente-bolsa-healthcheck/1.0 (+openai-compatible)")
    if key:
        req.add_header("Authorization", f"Bearer {key}")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            result["status"] = resp.status
            try:
                data = json.loads(body)
                content = (
                    data.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                result["detail"] = (content or "").strip()[:80] or "(respuesta vacia)"
                if json_probe:
                    try:
                        result["ok"] = resp.status == 200 and bool(json.loads(content or "{}").get("ok"))
                    except (TypeError, json.JSONDecodeError):
                        result["ok"] = False
                else:
                    result["ok"] = resp.status == 200 and bool(data.get("choices"))
            except json.JSONDecodeError:
                result["detail"] = body[:80]
                result["ok"] = resp.status == 200
    except urllib.error.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        result["status"] = exc.code
        result["detail"] = f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        local_8080 = base.rstrip("/").startswith("http://127.0.0.1:8080")
        if local_8080:
            result["detail"] = (
                "fallback local no disponible en 127.0.0.1:8080 "
                "(esperado si el servidor local no esta arrancado)"
            )
        else:
            result["detail"] = f"sin conexion: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - diagnostico no debe romper.
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Chequeo de salud de proveedores LLM.")
    parser.add_argument("--json", action="store_true", help="Salida en JSON.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout por proveedor (s).")
    args = parser.parse_args()

    env = load_env(ENV_PATH)

    # El proveedor primario depende de LLM_MODEL_SELECTOR (igual que llm_router.py):
    # con opencode/opencode-go se usa el bloque OPENCODE_*, no OPENAI_* (que puede
    # quedar obsoleto apuntando a otro proveedor).
    selector = (cfg(env, "LLM_MODEL_SELECTOR", "custom") or "custom").strip().lower()
    if selector in ("opencode", "opencode-go"):
        prim_base = cfg(env, "OPENCODE_API_BASE", "https://opencode.ai/zen/go/v1")
        prim_key = cfg(env, "OPENCODE_API_KEY")
        prim_model = cfg(env, "OPENCODE_MODEL", "kimi-k2.6")
    else:
        prim_base = cfg(env, "OPENAI_API_BASE")
        prim_key = cfg(env, "OPENAI_API_KEY")
        prim_model = cfg(env, "OPENAI_MODEL_NAME")

    decision_base = cfg(env, "LLM_ROLE_DECISION_BASE_URL") or prim_base
    decision_key = cfg(env, "LLM_ROLE_DECISION_API_KEY") or prim_key
    decision_model = cfg(env, "LLM_ROLE_DECISION_MODEL") or prim_model
    sentiment_base = cfg(env, "LLM_ROLE_SENTIMENT_BASE_URL") or prim_base
    sentiment_key = cfg(env, "LLM_ROLE_SENTIMENT_API_KEY") or prim_key
    sentiment_model = cfg(env, "LLM_ROLE_SENTIMENT_MODEL") or prim_model
    codegen_base = cfg(env, "IMPROVEMENT_LLM_CODEGEN_BASE_URL") or cfg(env, "IMPROVEMENT_LLM_BASE_URL")
    codegen_key = (
        cfg(env, "IMPROVEMENT_LLM_CODEGEN_API_KEY")
        or cfg(env, "IMPROVEMENT_LLM_API_KEY")
        or cfg(env, "OPENCODE_API_KEY")
    )
    improvement_model = cfg(env, "IMPROVEMENT_LLM_MODEL")
    codegen_model = cfg(env, "IMPROVEMENT_LLM_CODEGEN_MODEL")
    if not codegen_model and improvement_model.lower().startswith("glm-"):
        codegen_model = cfg(env, "IMPROVEMENT_LLM_ORCHESTRATOR_MODEL") or cfg(env, "OPENCODE_MODEL")
    codegen_model = codegen_model or improvement_model

    providers = [
        {
            "name": f"decision [{selector}]",
            "role": "decision",
            "base": decision_base,
            "key": decision_key,
            "model": decision_model,
        },
        {
            "name": f"sentiment [{selector}]",
            "role": "sentiment",
            "base": sentiment_base,
            "key": sentiment_key,
            "model": sentiment_model,
        },
        {
            "name": "local fallback",
            "role": "fallback",
            "base": cfg(env, "LLM_LOCAL_FALLBACK_API_BASE"),
            "key": cfg(env, "LLM_LOCAL_FALLBACK_API_KEY"),
            "model": cfg(env, "LLM_LOCAL_FALLBACK_MODEL"),
            "enabled": cfg(env, "LLM_LOCAL_FALLBACK_ENABLED", "true").lower() == "true",
        },
        {
            "name": "continuous improvement",
            "role": "improvement",
            "base": cfg(env, "IMPROVEMENT_LLM_BASE_URL"),
            "key": cfg(env, "IMPROVEMENT_LLM_API_KEY") or cfg(env, "OPENCODE_API_KEY"),
            "model": cfg(env, "IMPROVEMENT_LLM_MODEL"),
            "enabled": cfg(env, "IMPROVEMENT_LLM_ENABLED", "true").lower() == "true",
        },
        {
            "name": "codegen [continuous improvement]",
            "role": "codegen",
            "base": codegen_base,
            "key": codegen_key,
            "model": codegen_model,
            "enabled": cfg(env, "IMPROVEMENT_LLM_ENABLED", "true").lower() == "true",
            "json_probe": True,
        },
    ]

    results = []
    for p in providers:
        if p.get("enabled") is False:
            results.append(
                {
                    "provider": p["name"],
                    "role": p["role"],
                    "ok": None,
                    "detail": "deshabilitado por configuracion",
                    "base_url": p["base"],
                    "model": p["model"],
                }
            )
            continue
        res = ping_provider(
            p["name"],
            p["base"],
            p["key"],
            p["model"],
            args.timeout,
            role=p["role"],
            json_probe=bool(p.get("json_probe")),
        )
        res["role"] = p["role"]
        results.append(res)

    fallback_ok = any(r.get("ok") for r in results if r.get("role") == "fallback")
    decision_ok = fallback_ok or any(r.get("ok") for r in results if r.get("role") == "decision")
    sentiment_ok = fallback_ok or any(r.get("ok") for r in results if r.get("role") == "sentiment")
    codegen_ok = any(r.get("ok") for r in results if r.get("role") == "codegen")
    overall_ok = decision_ok and sentiment_ok and codegen_ok

    if args.json:
        print(
            json.dumps(
                {
                    "decision_ok": decision_ok,
                    "sentiment_ok": sentiment_ok,
                    "codegen_ok": codegen_ok,
                    "providers": results,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print("=== Chequeo de salud LLM ===")
        for r in results:
            if r.get("ok") is None:
                flag = "[--]"
            elif r.get("ok"):
                flag = "[OK]"
            else:
                flag = "[XX]"
            lat = f"{r['latency_ms']}ms" if r.get("latency_ms") else "-"
            print(f"{flag} {r['provider']:<28} {r['model']:<18} {lat:>8}  {r.get('detail')}")
        print()
        if overall_ok:
            print("RESULTADO: decision, sentimiento y codegen tienen LLM disponible. Operativa normal.")
        else:
            print("RESULTADO: algun rol critico no tiene LLM disponible -> modo degradado.")
            print("           El sistema puede operar en")
            print("           fallback determinista (slate de candidatos muy reducido,")
            print("           sin sentimiento). Revisar proveedor primario y/o arrancar")
            print("           el servidor LLM local antes de esperar operativa normal.")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
