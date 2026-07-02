"""Persistent research agenda for falsifiable hypotheses."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.models import new_id

DEFAULT_RESEARCH_AGENDA_PATH = Path("data/research/research_agenda.json")
OPEN_STATUSES = {"pendiente", "en_curso"}
CLOSED_STATUSES = {"matada", "promovida"}
VALID_STATUSES = OPEN_STATUSES | CLOSED_STATUSES

DEFAULT_RESEARCH_AGENDA = [
    {
        "hypothesis_id": "agenda_pullback_20260706",
        "title": "pullback",
        "status": "pendiente",
        "target_date": "2026-07-06",
        "notes": "Medir edge de builtin_pullback con muestra madura y OOS.",
    },
    {
        "hypothesis_id": "agenda_exit_horizon_5_10d_p16",
        "title": "horizonte salida 5-10d",
        "status": "matada",
        "target_date": "2026-07-02",
        "notes": "P16 no cumple criterios pre-registrados: n<20 y concentracion temporal/regimen.",
    },
    {
        "hypothesis_id": "agenda_telegram_radar_20260720",
        "title": "telegram radar",
        "status": "pendiente",
        "target_date": "2026-07-20",
        "notes": "Evaluar si los posts filtrados aportan senal incremental.",
    },
    {
        "hypothesis_id": "agenda_overlay_activation_20260705",
        "title": "overlay activacion",
        "status": "en_curso",
        "target_date": "2026-07-05",
        "notes": "Activacion humana de core sleeve tras paridad limpia.",
    },
    {
        "hypothesis_id": "agenda_orcl_anomaly_p21",
        "title": "anomalia ORCL",
        "status": "pendiente",
        "target_date": "2026-07-02",
        "notes": "P21: validar si ext_sma20=-23.35% es dato real o corrupto.",
    },
]


def load_research_agenda(path: Path = DEFAULT_RESEARCH_AGENDA_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return [_with_defaults(item) for item in DEFAULT_RESEARCH_AGENDA]
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Agenda de investigacion invalida: {path}")
    items = payload.get("hypotheses") or []
    if not isinstance(items, list):
        raise ValueError(f"Agenda de investigacion invalida: {path}")
    return [_with_defaults(item) for item in items if isinstance(item, dict)]


def save_research_agenda(items: list[dict[str, Any]], path: Path = DEFAULT_RESEARCH_AGENDA_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "hypotheses": [_with_defaults(item) for item in items]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path


def add_research_hypothesis(
    *,
    path: Path = DEFAULT_RESEARCH_AGENDA_PATH,
    title: str,
    target_date: str,
    status: str = "pendiente",
    notes: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_status = _validate_status(status)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    items = load_research_agenda(path)
    item = {
        "hypothesis_id": new_id("agenda"),
        "title": title,
        "status": normalized_status,
        "target_date": target_date,
        "notes": notes,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "closed_at": now.isoformat() if normalized_status in CLOSED_STATUSES else None,
    }
    items.append(item)
    save_research_agenda(items, path)
    return item


def close_research_hypothesis(
    *,
    path: Path = DEFAULT_RESEARCH_AGENDA_PATH,
    hypothesis_id: str,
    status: str,
    notes: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_status = _validate_status(status)
    if normalized_status not in CLOSED_STATUSES:
        raise ValueError("Cerrar hipotesis exige status matada o promovida.")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    items = load_research_agenda(path)
    for item in items:
        if str(item.get("hypothesis_id")) != hypothesis_id:
            continue
        item["status"] = normalized_status
        item["updated_at"] = now.isoformat()
        item["closed_at"] = now.isoformat()
        if notes:
            item["notes"] = notes
        save_research_agenda(items, path)
        return item
    raise ValueError(f"Hipotesis no encontrada: {hypothesis_id}")


def build_research_agenda_snapshot(
    data_dir: Path,
    experiments: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    path = data_dir / "research" / "research_agenda.json"
    items = load_research_agenda(path)
    return {
        "path": str(path),
        "items": sorted(items, key=lambda item: (str(item.get("target_date") or ""), str(item.get("title") or ""))),
        "kpis": research_agenda_kpis(items, experiments, now=now),
    }


def research_agenda_kpis(
    items: list[dict[str, Any]],
    experiments: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    week_start = _week_start(now)
    return {
        "week_start": week_start.date().isoformat(),
        "estudios_ejecutados_semana": sum(1 for item in experiments if _is_since_week(item.get("created_at"), week_start)),
        "hipotesis_matadas_semana": sum(
            1
            for item in items
            if str(item.get("status") or "") == "matada" and _is_since_week(item.get("closed_at") or item.get("updated_at"), week_start)
        ),
        "hipotesis_promovidas_semana": sum(
            1
            for item in items
            if str(item.get("status") or "") == "promovida" and _is_since_week(item.get("closed_at") or item.get("updated_at"), week_start)
        ),
    }


def _with_defaults(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized.setdefault("hypothesis_id", new_id("agenda"))
    normalized.setdefault("title", "")
    normalized["status"] = _validate_status(str(normalized.get("status") or "pendiente"))
    normalized.setdefault("target_date", "")
    normalized.setdefault("notes", "")
    normalized.setdefault("created_at", None)
    normalized.setdefault("updated_at", normalized.get("created_at"))
    normalized.setdefault("closed_at", normalized.get("updated_at") if normalized["status"] in CLOSED_STATUSES else None)
    return normalized


def _validate_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in VALID_STATUSES:
        raise ValueError(f"Estado de hipotesis invalido: {status}")
    return normalized


def _week_start(now: datetime) -> datetime:
    day = now.astimezone(timezone.utc).date()
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=day.weekday())


def _is_since_week(value: Any, week_start: datetime) -> bool:
    parsed = _parse_datetime(value)
    return parsed is not None and parsed >= week_start


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
