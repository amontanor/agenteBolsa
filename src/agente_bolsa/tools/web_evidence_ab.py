"""Shadow A/B logging for web evidence value."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOCAL_NEWS_PROVIDERS = {"", "yahoo", "yfinance"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _web_ab_dir(data_dir: Path) -> Path:
    return data_dir / "research" / "web_ab"


def _web_ab_path(data_dir: Path) -> Path:
    return _web_ab_dir(data_dir) / "web_evidence_ab.jsonl"


def split_local_web_news(news: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    local: list[dict[str, Any]] = []
    web: list[dict[str, Any]] = []
    for item in news:
        provider = str(item.get("provider") or "").lower()
        if provider in LOCAL_NEWS_PROVIDERS:
            local.append(item)
        else:
            web.append(item)
    return local, web


def build_web_ab_observation(
    *,
    run_id: str,
    symbol: str,
    news: list[dict[str, Any]],
    combined_material_risk: dict[str, Any],
    local_material_risk: dict[str, Any],
    sentiment: dict[str, Any],
    research_gate_changed: bool | None = None,
) -> dict[str, Any] | None:
    local_news, web_news = split_local_web_news(news)
    if not web_news:
        return None
    material_changed = str(combined_material_risk.get("severity")) != str(local_material_risk.get("severity"))
    gate_changed = bool(research_gate_changed) if research_gate_changed is not None else material_changed
    return {
        "schema": "agente_bolsa.web_evidence_ab.v1",
        "created_at": _utc_now(),
        "run_id": run_id,
        "symbol": symbol.upper(),
        "local_items": len(local_news),
        "web_items": len(web_news),
        "web_titles": [str(item.get("title") or "") for item in web_news[:5]],
        "sentiment_score": sentiment.get("sentiment_score"),
        "sentiment_score_changed": None,
        "material_risk_local": local_material_risk,
        "material_risk_combined": combined_material_risk,
        "material_risk_changed": material_changed,
        "gate_changed": gate_changed,
        "outcome_forward": None,
    }


def record_web_ab_observation(data_dir: Path, observation: dict[str, Any] | None) -> None:
    if not observation:
        return
    path = _web_ab_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, ensure_ascii=True, sort_keys=True, default=str) + "\n")


def load_web_ab_observations(data_dir: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = _web_ab_path(data_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:] if limit else rows


def build_web_evidence_ab_report(data_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    rows = load_web_ab_observations(data_dir, limit=limit)
    changed = [item for item in rows if item.get("gate_changed") or item.get("material_risk_changed")]
    matured = [item for item in rows if isinstance(item.get("outcome_forward"), dict)]
    changed_matured = [item for item in matured if item.get("gate_changed") or item.get("material_risk_changed")]
    unchanged_matured = [item for item in matured if not (item.get("gate_changed") or item.get("material_risk_changed"))]
    n = len(rows)
    return {
        "as_of": _utc_now(),
        "path": str(_web_ab_path(data_dir)),
        "summary": {
            "observations": n,
            "decisions_changed": len(changed),
            "pct_decisions_changed": round(len(changed) / n, 4) if n else 0.0,
            "web_items": sum(int(item.get("web_items") or 0) for item in rows),
            "matured_outcomes": len(matured),
            "changed_matured_outcomes": len(changed_matured),
            "unchanged_matured_outcomes": len(unchanged_matured),
        },
        "recent": rows[-20:],
    }
