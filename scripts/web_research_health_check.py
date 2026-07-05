#!/usr/bin/env python3
"""Chequeo real del flujo de web research del grupo de agentes.

Prueba el camino operativo que usan los agentes:

1. `web_research_agent` -> `build_web_research_report`
2. `macro_news_researcher` -> `analyze_news_sentiment_for_candidates`
3. `source_reliability_agent` / `trade_decision` -> `build_research_evidence_report`

Uso:

    python scripts/web_research_health_check.py
    python scripts/web_research_health_check.py --symbol NVDA --json
    python scripts/web_research_health_check.py --skip-sentiment

Codigos de salida:
    0 -> web research y evidencia OK
    1 -> fallo critico en web research o evidencia
    2 -> error importando el proyecto
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Chequeo real de web research del grupo de agentes.")
    parser.add_argument("--symbol", default="AAPL", help="Ticker a probar.")
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    parser.add_argument("--skip-sentiment", action="store_true", help="Omite la validacion LLM de sentimiento.")
    args = parser.parse_args()

    try:
        from agente_bolsa.config import get_settings
        from agente_bolsa.models import new_id
        from agente_bolsa.storage import Store
        from agente_bolsa.tools.news_sentiment import analyze_news_sentiment_for_candidates
        from agente_bolsa.tools.research_evidence import build_research_evidence_report
        from agente_bolsa.tools.web_research import build_web_research_report
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importando modulos del proyecto: {exc}", file=sys.stderr)
        return 2

    settings = get_settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    reports_dir = settings.data_dir / "reports"
    run_id = new_id("webhc")
    symbol = str(args.symbol or "AAPL").upper().strip()

    web_report = build_web_research_report(
        settings,
        reports_dir,
        run_id,
        symbol=symbol,
        max_items=min(5, int(getattr(settings, "web_search_max_items_per_symbol", 5) or 5)),
    )
    web_summary = dict(web_report.get("summary") or {})
    web_ok = str(web_summary.get("quality") or "").lower() == "ok" and int(web_summary.get("items") or 0) > 0

    sentiment_report: dict[str, object] | None = None
    sentiment_ok: bool | None = None
    if not args.skip_sentiment:
        candidate = {
            "symbol": symbol,
            "direction": "long",
            "score": 50,
            "reasons": ["healthcheck"],
            "technical_state": {},
        }
        sentiment_report = analyze_news_sentiment_for_candidates(
            settings,
            [candidate],
            reports_dir,
            f"{run_id}_{symbol.lower()}",
            max_news_items=min(5, int(getattr(settings, "news_items_per_symbol", 5) or 5)),
        )
        results = list(sentiment_report.get("results") or [])
        first = results[0] if results else {}
        sentiment = dict(first.get("sentiment") or {}) if isinstance(first, dict) else {}
        sentiment_ok = bool(results) and str(sentiment.get("sentiment") or "").lower() not in {"unknown", ""}

    evidence_report = build_research_evidence_report(
        store,
        settings,
        reports_dir,
        f"{run_id}_{symbol.lower()}",
        symbols=[symbol],
        market_state={},
        sentiment_context=sentiment_report or {},
    )
    evidence_summary = dict(evidence_report.get("summary") or {})
    evidence_ok = int(evidence_summary.get("rows_persisted") or 0) > 0

    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "web_research": {
            "ok": web_ok,
            "quality": web_summary.get("quality"),
            "provider": web_summary.get("provider"),
            "items": web_summary.get("items"),
            "path": web_report.get("path"),
        },
        "sentiment": {
            "enabled": not args.skip_sentiment,
            "ok": sentiment_ok,
            "path": (sentiment_report or {}).get("path") if isinstance(sentiment_report, dict) else None,
        },
        "research_evidence": {
            "ok": evidence_ok,
            "decision_ready": evidence_summary.get("decision_ready"),
            "rows_persisted": evidence_summary.get("rows_persisted"),
            "path": evidence_report.get("path"),
        },
    }
    overall_ok = web_ok and evidence_ok and (True if args.skip_sentiment else bool(sentiment_ok))

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print("=== Web research health check ===")
        print(
            f"[{'OK' if web_ok else 'XX'}] web_research_agent    "
            f"{payload['web_research']['provider']} | "
            f"quality={payload['web_research']['quality']} | "
            f"items={payload['web_research']['items']}"
        )
        if not args.skip_sentiment:
            print(
                f"[{'OK' if sentiment_ok else 'XX'}] macro_news_researcher "
                f"sentiment_path={payload['sentiment']['path'] or '-'}"
            )
        print(
            f"[{'OK' if evidence_ok else 'XX'}] research_evidence     "
            f"rows={payload['research_evidence']['rows_persisted']} | "
            f"decision_ready={payload['research_evidence']['decision_ready']}"
        )
        print()
        if overall_ok:
            print("RESULTADO: el flujo de agentes para busqueda web esta funcionando.")
        else:
            print("RESULTADO: fallo en alguna etapa del flujo de agentes de web research.")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
