"""CLI helpers for Telegram radar research commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.tools.universe import resolve_study_universe

from .analysis import build_gate_verdicts
from .extract import extract_opportunity
from .ingest import DEFAULT_CHANNEL_URL, ingest_channel
from .scorecard import build_scorecard
from .storage import TelegramRadarStore


def default_store(settings: Settings) -> TelegramRadarStore:
    return TelegramRadarStore(Path(settings.data_dir) / "research" / "telegram")


def run_ingest(
    *,
    settings: Settings,
    backfill: int,
    channel_url: str = DEFAULT_CHANNEL_URL,
    force: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    store = default_store(settings)
    ingest = ingest_channel(
        store,
        channel_url=channel_url,
        backfill_pages=backfill,
        force=force,
    )
    posts = store.load_posts()
    extracted_ids = {int(item["message_id"]) for item in store.load_extractions()}
    new_posts = [post for post in posts if int(post["message_id"]) not in extracted_ids]
    current_universe = resolve_study_universe("sp500", settings.universe, 0, settings.data_dir / "cache")
    extractions = [
        extract_opportunity(
            post,
            settings=settings,
            use_llm=use_llm,
            current_universe=current_universe,
        ).to_dict()
        for post in new_posts
    ]
    extraction_storage = store.upsert_extractions(extractions) if extractions else {"inserted": 0, "updated": 0, "total": len(extracted_ids)}
    return {
        "ok": bool(ingest.get("ok", False)),
        "mode": "research_read_only",
        "ingest": ingest,
        "extractions_created": len(extractions),
        "extraction_storage": extraction_storage,
        "paths": {
            "root": str(store.root),
            "posts": str(store.posts_path),
            "extractions": str(store.extractions_path),
        },
    }


def list_records(
    *,
    settings: Settings,
    days: int,
    only_opportunities: bool = False,
) -> dict[str, Any]:
    store = default_store(settings)
    posts = store.load_posts()
    extraction_by_id = {int(item["message_id"]): item for item in store.load_extractions()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    rows: list[dict[str, Any]] = []
    for post in sorted(posts, key=lambda item: int(item["message_id"]), reverse=True):
        posted_at = _parse_dt(post.get("posted_at"))
        if posted_at is not None and posted_at < cutoff:
            continue
        extraction = extraction_by_id.get(int(post["message_id"]), {})
        if only_opportunities and not extraction.get("is_opportunity"):
            continue
        rows.append(
            {
                "message_id": post["message_id"],
                "posted_at": post.get("posted_at"),
                "text": post.get("text"),
                "links": post.get("links", []),
                "extraction": extraction,
            }
        )
    return {
        "ok": True,
        "mode": "research_read_only",
        "rows": rows,
        "summary": {
            "posts": len(posts),
            "extractions": len(extraction_by_id),
            "returned": len(rows),
            "only_opportunities": only_opportunities,
        },
    }


def build_report(
    *,
    settings: Settings,
    days: int,
) -> dict[str, Any]:
    store = default_store(settings)
    posts = store.load_posts()
    extractions = store.load_extractions()
    recent_post_ids = {
        int(post["message_id"])
        for post in posts
        if _is_within_days(post.get("posted_at"), days)
    }
    recent_posts = [post for post in posts if int(post["message_id"]) in recent_post_ids]
    recent_extractions = [row for row in extractions if int(row["message_id"]) in recent_post_ids]
    gate_verdicts = build_gate_verdicts(
        recent_posts,
        recent_extractions,
        settings=settings,
    )
    gate_storage = store.upsert_gate_verdicts(gate_verdicts) if gate_verdicts else {"inserted": 0, "updated": 0, "total": len(store.load_gate_verdicts())}
    scorecard = build_scorecard(
        posts,
        extractions,
        settings=settings,
    )
    score_storage = store.upsert_scorecard(scorecard["rows"]) if scorecard["rows"] else {"inserted": 0, "updated": 0, "total": len(store.load_scorecard())}
    payload = {
        "ok": True,
        "mode": "research_read_only",
        "days": days,
        "new_opportunities": _opportunity_rows(recent_posts, recent_extractions),
        "gate_verdicts": gate_verdicts,
        "scorecard": scorecard,
        "storage": {
            "gate_verdicts": gate_storage,
            "scorecard": score_storage,
        },
    }
    payload["markdown"] = render_report_markdown(payload)
    return payload


def render_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Telegram radar - Fase B",
        "",
        "Modo: research read-only. No genera ordenes ni cambia estado operativo.",
        "",
        "## Oportunidades recientes",
    ]
    opportunities = list(report.get("new_opportunities") or [])
    if not opportunities:
        lines.append("- Sin oportunidades recientes guardadas en la ventana.")
    for item in opportunities[:30]:
        tickers = ", ".join(item.get("tickers") or []) or "-"
        lines.append(
            f"- {item.get('message_id')} | {item.get('posted_at') or '-'} | "
            f"{item.get('direction') or '-'} | {tickers}"
        )

    lines.extend(["", "## Nuestro veredicto"])
    verdicts = list(report.get("gate_verdicts") or [])
    if not verdicts:
        lines.append("- Sin tickers in-universe con veredicto en la ventana.")
    for item in verdicts[:50]:
        metrics = item.get("metrics") or {}
        reasons = ", ".join(item.get("reasons") or ["ok"])
        lines.append(
            f"- {item.get('ticker')} post={item.get('message_id')} gate={item.get('our_gate')} "
            f"ext_sma20={_fmt_pct(metrics.get('sma20_extension'))} "
            f"rsi={_fmt_num(metrics.get('rsi_14'))} rr={_fmt_num(metrics.get('reward_risk'))} "
            f"spy_bull={bool(metrics.get('spy_regime_bull'))} reasons={reasons}"
        )

    lines.extend(["", "## Marcador acumulado"])
    groups = ((report.get("scorecard") or {}).get("summary") or {}).get("groups") or []
    if not groups:
        lines.append("- Sin menciones puntuables todavia.")
    else:
        lines.append("| Cobertura | Horizonte | Coste bps | n | scored | hit-rate | retorno neto medio | excess medio |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for row in groups:
            lines.append(
                "| "
                f"{row.get('coverage')} | {row.get('horizon_days')} | {row.get('cost_bps')} | "
                f"{row.get('n_mentions')} | {row.get('n_scored')} | {_fmt_pct(row.get('hit_rate'))} | "
                f"{_fmt_pct(row.get('avg_signal_return_net'))} | {_fmt_pct(row.get('avg_excess_vs_spy'))} |"
            )

    lines.extend(
        [
            "",
            "## Caveats",
            "- El canal puede hacer cherry-picking de ideas y borrar mensajes: la fuente publica ya llega sesgada.",
            "- Solo se observa el canal gratuito, no el historico completo ni precios/tamanos reales de ejecucion.",
            "- Una mencion no equivale a una orden con entrada, stop, salida y tamano definidos.",
            "- Los out-of-coverage se registran; si no hay precios, aparecen como sin datos.",
        ]
    )
    return "\n".join(lines)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None


def _is_within_days(value: Any, days: int) -> bool:
    parsed = _parse_dt(value)
    if parsed is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    return parsed >= cutoff


def _opportunity_rows(posts: list[dict[str, Any]], extractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    post_by_id = {int(post["message_id"]): post for post in posts}
    rows = []
    for extraction in sorted(extractions, key=lambda item: int(item["message_id"]), reverse=True):
        if not extraction.get("is_opportunity"):
            continue
        post = post_by_id.get(int(extraction["message_id"]), {})
        rows.append(
            {
                "message_id": extraction.get("message_id"),
                "posted_at": post.get("posted_at"),
                "direction": extraction.get("direction"),
                "tickers": extraction.get("tickers", []),
                "text": post.get("text"),
            }
        )
    return rows


def _fmt_num(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
