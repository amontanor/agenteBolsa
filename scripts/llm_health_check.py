#!/usr/bin/env python3
"""Chequeo de salud de los proveedores LLM configurados.

Diagnostica los roles reales del sistema con probes cercanas a su uso real para
evitar falsos positivos/negativos por prompts triviales o `max_tokens` ridiculos.
Captura por rol el estado HTTP, `finish_reason`, chars de `content` y de
`reasoning_content`, ademas del estado del gate de presupuesto interno.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
SRC_PATH = ROOT / "src"


@dataclass(frozen=True)
class ProbeSpec:
    role: str
    provider: str
    base_url: str
    api_key: str
    model: str
    messages: list[dict[str, str]]
    max_tokens: int
    response_format: dict[str, str] | None = None
    expected_text: str | None = None
    required_json_keys: tuple[str, ...] = ()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    return values


def cfg(env: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key) or env.get(key, default)


def mask(value: str) -> str:
    if not value:
        return "(vacio)"
    if len(value) <= 6:
        return value[:2] + "***"
    return value[:4] + "***" + value[-2:]


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_probe_content(spec: ProbeSpec, content: str, finish_reason: str | None) -> tuple[bool, str | None]:
    text = str(content or "").strip()
    if finish_reason == "length":
        return False, "finish_reason=length"
    if not text:
        return False, "content_vacio"
    if spec.expected_text is not None and text != spec.expected_text:
        return False, f"texto_inesperado:{text[:80]}"
    if spec.required_json_keys:
        parsed = _try_parse_json_object(text)
        if parsed is None:
            return False, "json_invalido"
        missing = [key for key in spec.required_json_keys if key not in parsed]
        if missing:
            return False, "json_incompleto:" + ",".join(missing)
    return True, None


def build_probe_specs(env: dict[str, str]) -> list[ProbeSpec]:
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
    deep_base = cfg(env, "LLM_ROLE_DEEP_BASE_URL") or cfg(env, "IMPROVEMENT_LLM_BASE_URL") or prim_base
    deep_key = cfg(env, "LLM_ROLE_DEEP_API_KEY") or cfg(env, "IMPROVEMENT_LLM_API_KEY") or prim_key
    deep_model = cfg(env, "LLM_ROLE_DEEP_MODEL") or cfg(env, "IMPROVEMENT_LLM_MODEL") or prim_model
    improvement_base = cfg(env, "IMPROVEMENT_LLM_BASE_URL")
    improvement_key = cfg(env, "IMPROVEMENT_LLM_API_KEY") or prim_key
    improvement_model = cfg(env, "IMPROVEMENT_LLM_MODEL")
    codegen_base = cfg(env, "IMPROVEMENT_LLM_CODEGEN_BASE_URL") or improvement_base
    codegen_key = cfg(env, "IMPROVEMENT_LLM_CODEGEN_API_KEY") or improvement_key
    codegen_model = cfg(env, "IMPROVEMENT_LLM_CODEGEN_MODEL")
    if not codegen_model and improvement_model.lower().startswith("glm-"):
        codegen_model = cfg(env, "IMPROVEMENT_LLM_ORCHESTRATOR_MODEL") or prim_model
    codegen_model = codegen_model or improvement_model

    sentiment_messages = [
        {
            "role": "system",
            "content": (
                "Eres un analista de sentimiento financiero. Devuelve solo JSON valido con: "
                "sentiment, sentiment_score, supports_technical_setup, confidence, summary y risk_flags."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "symbol": "TEST",
                    "technical_direction": "long",
                    "technical_score": 17.5,
                    "technical_reasons": ["earnings beat", "price above sma20"],
                    "technical_state": {"rsi_14": 61, "volume_zscore_20": 0.8},
                    "news": [{"title": "Test earnings beat", "summary": "positive results"}],
                },
                ensure_ascii=True,
            ),
        },
    ]

    return [
        ProbeSpec(
            role="decision",
            provider=f"decision [{selector}]",
            base_url=decision_base,
            api_key=decision_key,
            model=decision_model,
            messages=[
                {"role": "system", "content": "Responde solo con texto plano."},
                {"role": "user", "content": "Responde solo: OK-DECISION"},
            ],
            max_tokens=512,
            expected_text="OK-DECISION",
        ),
        ProbeSpec(
            role="sentiment",
            provider=f"sentiment [{selector}]",
            base_url=sentiment_base,
            api_key=sentiment_key,
            model=sentiment_model,
            messages=sentiment_messages,
            max_tokens=2048,
            required_json_keys=(
                "sentiment",
                "sentiment_score",
                "supports_technical_setup",
                "confidence",
                "summary",
                "risk_flags",
            ),
        ),
        ProbeSpec(
            role="deep",
            provider="deep [improvement stack]",
            base_url=deep_base,
            api_key=deep_key,
            model=deep_model,
            messages=[
                {"role": "system", "content": "Devuelve solo JSON valido."},
                {"role": "user", "content": '{"ok": true, "role": "deep"}'},
            ],
            max_tokens=512,
            response_format={"type": "json_object"},
        ),
        ProbeSpec(
            role="improvement",
            provider="continuous improvement",
            base_url=improvement_base,
            api_key=improvement_key,
            model=improvement_model,
            messages=[
                {"role": "system", "content": "Devuelve solo JSON valido."},
                {"role": "user", "content": '{"ok": true, "role": "improvement"}'},
            ],
            max_tokens=1024,
            response_format={"type": "json_object"},
            required_json_keys=("ok", "role"),
        ),
        ProbeSpec(
            role="codegen",
            provider="codegen [continuous improvement]",
            base_url=codegen_base,
            api_key=codegen_key,
            model=codegen_model,
            messages=[
                {"role": "system", "content": "Devuelve solo JSON valido."},
                {"role": "user", "content": '{"ok": true, "role": "codegen"}'},
            ],
            max_tokens=2048,
            response_format={"type": "json_object"},
        ),
    ]


def ping_provider(spec: ProbeSpec, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "provider": spec.provider,
        "role": spec.role,
        "base_url": spec.base_url,
        "model": spec.model,
        "api_key": mask(spec.api_key),
        "ok": False,
        "latency_ms": None,
        "status": None,
        "finish_reason": None,
        "content_chars": 0,
        "reasoning_chars": 0,
        "detail": None,
        "error": None,
    }
    if not spec.base_url or not spec.model:
        result["detail"] = "configuracion incompleta (base_url o model vacios)"
        return result

    body: dict[str, Any] = {
        "model": spec.model,
        "messages": spec.messages,
        "max_tokens": spec.max_tokens,
        "temperature": 0,
    }
    if spec.response_format:
        body["response_format"] = spec.response_format
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(spec.base_url.rstrip("/") + "/chat/completions", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "agente-bolsa-healthcheck/2.0 (+openai-compatible)")
    if spec.api_key:
        req.add_header("Authorization", f"Bearer {spec.api_key}")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8", "replace")
            result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            result["status"] = resp.status
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError:
                result["error"] = "respuesta_no_json"
                result["detail"] = raw_body[:160]
                return result

            choice = (data.get("choices") or [{}])[0] or {}
            message = choice.get("message") or {}
            content = _extract_text(message.get("content"))
            reasoning = _extract_text(message.get("reasoning_content") or message.get("reasoning"))
            finish_reason = choice.get("finish_reason")
            ok, error = _validate_probe_content(spec, content, finish_reason)

            result["finish_reason"] = finish_reason
            result["content_chars"] = len(content)
            result["reasoning_chars"] = len(reasoning)
            result["detail"] = content[:160] if content else "(respuesta vacia)"
            result["reasoning_preview"] = reasoning[:160] if reasoning else ""
            result["error"] = error
            result["ok"] = resp.status == 200 and ok
            return result
    except urllib.error.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        result["status"] = exc.code
        result["error"] = f"HTTP {exc.code}: {exc.reason}"
        result["detail"] = exc.read().decode("utf-8", "replace")[:300]
    except urllib.error.URLError as exc:
        result["error"] = f"sin conexion: {exc.reason}"
        if spec.base_url.rstrip("/").startswith("http://127.0.0.1:8080"):
            result["detail"] = (
                "fallback local no disponible en 127.0.0.1:8080 "
                "(esperado si el servidor local no esta arrancado)"
            )
    except Exception as exc:  # noqa: BLE001 - diagnostico no debe romper.
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def run_pip_check() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "output": output.splitlines(),
    }


def read_budget_status() -> dict[str, Any]:
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))
    try:
        from agente_bolsa.config import Settings
        from agente_bolsa.llm_usage import today_llm_spend
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"import_error: {exc}"}

    settings = Settings(DATA_DIR=ROOT / "data")
    total_budget = float(getattr(settings, "llm_daily_budget_usd", 0.0) or 0.0)
    deep_budget = float(getattr(settings, "llm_role_deep_daily_budget_usd", 0.0) or 0.0)
    total_spend = today_llm_spend(settings)
    deep_spend = today_llm_spend(settings, role="deep")
    return {
        "available": True,
        "total_budget_usd": total_budget,
        "total_spend_usd_today": total_spend,
        "total_remaining_usd_today": round(max(total_budget - total_spend, 0.0), 6) if total_budget > 0 else None,
        "total_exhausted": total_budget > 0 and total_spend >= total_budget,
        "deep_budget_usd": deep_budget,
        "deep_spend_usd_today": deep_spend,
        "deep_remaining_usd_today": round(max(deep_budget - deep_spend, 0.0), 6) if deep_budget > 0 else None,
        "deep_exhausted": deep_budget > 0 and deep_spend >= deep_budget,
    }


def build_report(timeout: float) -> dict[str, Any]:
    env = load_env(ENV_PATH)
    probes = build_probe_specs(env)
    providers = [ping_provider(spec, timeout) for spec in probes]
    ok_by_role = {item["role"]: bool(item.get("ok")) for item in providers}
    budget = read_budget_status()
    dependencies = run_pip_check()
    return {
        "overall_ok": all(ok_by_role.get(role, False) for role in ("decision", "sentiment", "deep", "improvement", "codegen")),
        "decision_ok": ok_by_role.get("decision", False),
        "sentiment_ok": ok_by_role.get("sentiment", False),
        "deep_ok": ok_by_role.get("deep", False),
        "improvement_ok": ok_by_role.get("improvement", False),
        "codegen_ok": ok_by_role.get("codegen", False),
        "budget": budget,
        "dependencies": dependencies,
        "providers": providers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Chequeo de salud de proveedores LLM.")
    parser.add_argument("--json", action="store_true", help="Salida en JSON.")
    parser.add_argument("--timeout", type=float, default=40.0, help="Timeout por proveedor (s).")
    args = parser.parse_args()

    report = build_report(args.timeout)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("=== Chequeo de salud LLM ===")
        for item in report["providers"]:
            flag = "[OK]" if item.get("ok") else "[XX]"
            latency = f"{item['latency_ms']}ms" if item.get("latency_ms") else "-"
            print(
                f"{flag} {item['role']:<11} {item['model']:<18} {latency:>8} "
                f"HTTP={item.get('status')} finish={item.get('finish_reason') or '-'} "
                f"content={item.get('content_chars', 0)} reasoning={item.get('reasoning_chars', 0)} "
                f"err={item.get('error') or '-'}"
            )
        budget = report.get("budget") or {}
        if budget.get("available"):
            print(
                "Budget:"
                f" total={budget.get('total_spend_usd_today')}/{budget.get('total_budget_usd')} USD"
                f" deep={budget.get('deep_spend_usd_today')}/{budget.get('deep_budget_usd')} USD"
            )
        deps = report.get("dependencies") or {}
        print(f"pip check: {'OK' if deps.get('ok') else 'ROTO'}")
        if not deps.get("ok"):
            for line in (deps.get("output") or [])[:5]:
                print(f"  - {line}")
        print()
        if report["overall_ok"]:
            print("RESULTADO: todos los roles LLM tienen respuesta valida.")
        else:
            print("RESULTADO: hay roles LLM sin respuesta valida o con diagnostico roto.")
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
