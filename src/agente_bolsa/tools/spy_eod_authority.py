"""Par de cierres SPY con autoridad EOD por sesion XNYS (P-L121).

Observacional y read-only salvo la escritura del recibo por el job
post-sesion. Reutiliza la autoridad EOD de P-L71
(`load_cached_spy_observation`): nunca interpola, nunca reescribe historico
y nunca inventa una sesion ausente. Sin par real de cierres de sesiones
XNYS estrictamente consecutivas, el recibo queda `unavailable` con razones
explicitas; los cierres ausentes son `None`, jamas cero.

P-L155: el lector elige por reloj de captura y no por nombre de fichero. El
sufijo del nombre es `content_hash[:8]`, no tiempo, asi que el orden alfabetico
no puede decidir y un `unavailable` no puede tapar un `comparable`. El
productor toma el reloj de captura despues de la descarga para que la cache
recien escrita no nazca con `cache_created_at_future`.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .performance_benchmark import (
    load_cached_spy_observation,
    previous_xnys_session,
    session_status,
    xnys_sessions_between,
)

SPY_EOD_RECEIPT_SCHEMA = "p-l121.spy-eod-close.v1"
RECEIPT_PREFIX = "spy_eod_close_"
_FAR_PAST = datetime.min.replace(tzinfo=timezone.utc)


def _cache_root(settings: Any) -> Path:
    return Path(settings.data_dir) / "cache" / "market_data"


def _parse_utc(value: Any) -> datetime | None:
    """Normaliza un instante a UTC; `None` si no es un ISO-8601 parseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in {"Z", "z"}:
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_hash(payload: dict[str, Any]) -> str:
    stable = deepcopy(payload)
    stable.pop("captured_at", None)
    stable.pop("content_hash", None)
    stable.pop("receipt_path", None)
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _unavailable(
    session_date: str, previous: str | None, reasons: list[str], *, captured_at: str
) -> dict[str, Any]:
    receipt = {
        "schema_version": SPY_EOD_RECEIPT_SCHEMA,
        "session_date": session_date,
        "previous_session": previous,
        "previous_close": None,
        "close": None,
        "daily_return": None,
        "price_basis": None,
        "interval": "1d",
        "source": None,
        "bars_as_of": None,
        "cache_created_at": None,
        "eod_authority": None,
        "comparison_status": "unavailable",
        "reason_codes": sorted(set(reasons)),
        "captured_at": captured_at,
    }
    receipt["content_hash"] = _stable_hash(receipt)
    return receipt


def build_spy_eod_receipt(settings: Any, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Construye el recibo del par de cierres sin escribir nada."""
    captured = _now(now)
    captured_at = captured.isoformat()
    try:
        previous = previous_xnys_session(session_date)
    except (TypeError, ValueError):
        return _unavailable(session_date, None, ["invalid_session_date"], captured_at=captured_at)
    if previous is None:
        return _unavailable(session_date, None, ["missing_previous_xnys_session"], captured_at=captured_at)
    status, status_warnings = session_status(session_date, now=captured)
    if status != "closed":
        return _unavailable(session_date, previous, list(status_warnings), captured_at=captured_at)
    observation = load_cached_spy_observation(settings, session_date, now=captured)
    if str(observation.get("status")) != "available" or observation.get("daily_return") is None:
        reasons = list(observation.get("warnings") or ["spy_close_pair_unavailable"])
        return _unavailable(session_date, previous, reasons, captured_at=captured_at)
    receipt = {
        "schema_version": SPY_EOD_RECEIPT_SCHEMA,
        "session_date": session_date,
        "previous_session": previous,
        "previous_close": observation.get("previous_close"),
        "close": observation.get("close"),
        "daily_return": observation.get("daily_return"),
        "price_basis": observation.get("price_basis"),
        "interval": observation.get("interval") or "1d",
        "source": observation.get("source"),
        "bars_as_of": observation.get("as_of"),
        "cache_created_at": observation.get("cache_created_at"),
        "eod_authority": observation.get("eod_authority"),
        "comparison_status": "comparable",
        "reason_codes": [],
        "captured_at": captured_at,
    }
    receipt["content_hash"] = _stable_hash(receipt)
    return receipt


def capture_spy_eod_receipt(settings: Any, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Construye y persiste el recibo. Fail-open: nunca lanza por I/O."""
    receipt = build_spy_eod_receipt(settings, session_date, now=now)
    root = _cache_root(settings)
    stem = f"{RECEIPT_PREFIX}{session_date.replace('-', '')}_{receipt['content_hash'][:8]}"
    path = root / f"{stem}.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"persisted": False, "reason": f"receipt_write_failed:{type(exc).__name__}", "receipt": receipt, "path": None}
    return {"persisted": True, "receipt": receipt, "path": str(path)}


def _receipt_precedence(receipt: dict[str, Any]) -> tuple[Any, ...]:
    """Precedencia de un recibo valido de la misma sesion (P-L155).

    Orden de mayor a menor:

    1. `comparison_status == "comparable"`: un `unavailable` nunca enmascara
       un `comparable` de la misma sesion, sea cual sea su reloj.
    2. `captured_at` mas reciente en UTC. El nombre del fichero NO entra: su
       sufijo es `content_hash[:8]`, un identificador de contenido truncado,
       no un reloj.
    3. Desempate determinista y explicito, sin reloj del sistema: gana el
       `content_hash` completo mayor, que es identidad canonica del contenido
       del recibo; si tambien empata, gana el `receipt_path` mayor. Un
       `captured_at` ausente o no parseable ordena por debajo de cualquier
       `captured_at` presente, pero sigue desempataado por el mismo par
       (`content_hash`, `receipt_path`), nunca por el hash truncado del
       nombre.
    """
    comparable = str(receipt.get("comparison_status") or "") == "comparable"
    captured = _parse_utc(receipt.get("captured_at"))
    return (
        1 if comparable else 0,
        1 if captured is not None else 0,
        captured or _FAR_PAST,
        str(receipt.get("content_hash") or ""),
        str(receipt.get("receipt_path") or ""),
    )


def load_spy_eod_receipt(settings: Any, session_date: str) -> dict[str, Any] | None:
    """Lee el recibo valido mas autoritativo de la sesion; `None` si no hay.

    La validacion de `schema_version`, `session_date` y `content_hash` se
    mantiene: un recibo invalido se ignora como hoy. Entre los validos gana el
    `comparable` mas reciente por `captured_at`; un `unavailable` solo se
    devuelve si no existe ningun `comparable` de la sesion. El desempate
    determinista esta declarado en `_receipt_precedence`. La funcion es
    estrictamente de lectura: no reescribe, no borra y no renombra ficheros.
    """
    root = _cache_root(settings)
    stem = f"{RECEIPT_PREFIX}{session_date.replace('-', '')}_"
    candidates = sorted(root.glob(f"{stem}*.json")) if root.exists() else []
    valid: list[dict[str, Any]] = []
    for path in candidates:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        if receipt.get("schema_version") != SPY_EOD_RECEIPT_SCHEMA:
            continue
        if str(receipt.get("session_date") or "") != session_date:
            continue
        if receipt.get("content_hash") != _stable_hash(receipt):
            continue
        receipt["receipt_path"] = str(path)
        valid.append(receipt)
    if not valid:
        return None
    return max(valid, key=_receipt_precedence)


def spy_eod_coverage(settings: Any, start: str, end: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Cobertura de recibos comparables sobre sesiones XNYS (solo ficheros)."""
    del now
    sessions = xnys_sessions_between(start, end)
    by_session: list[dict[str, Any]] = []
    comparable = 0
    for session_date in sessions:
        receipt = load_spy_eod_receipt(settings, session_date)
        ok = receipt is not None and receipt.get("comparison_status") == "comparable"
        comparable += 1 if ok else 0
        by_session.append(
            {
                "session_date": session_date,
                "comparison_status": receipt.get("comparison_status") if receipt else "unavailable",
                "eod_authority": receipt.get("eod_authority") if receipt else None,
                "reason_codes": list(receipt.get("reason_codes") or []) if receipt else ["receipt_missing"],
            }
        )
    total = len(sessions)
    return {
        "start": start,
        "end": end,
        "denominator": "xnys_sessions",
        "sessions_total": total,
        "sessions_comparable": comparable,
        "sessions_unavailable": total - comparable,
        "provisional": comparable < total,
        "by_session": by_session,
    }

def receipt_as_observation(receipt: dict[str, Any]) -> dict[str, Any]:
    """Expone un recibo comparable con la forma de `load_cached_spy_observation`."""
    return {
        "status": "available",
        "previous_close": receipt.get("previous_close"),
        "close": receipt.get("close"),
        "daily_return": receipt.get("daily_return"),
        "price_basis": receipt.get("price_basis"),
        "source": receipt.get("source"),
        "instrument_label": "SPY (ETF S&P 500)",
        "as_of": receipt.get("bars_as_of"),
        "cache_created_at": receipt.get("cache_created_at"),
        "eod_authority": receipt.get("eod_authority"),
        "interval": receipt.get("interval") or "1d",
        "data_quality": "available",
        "warnings": [],
    }


def _capture_clock(entry: datetime, meta: Any) -> datetime:
    """Reloj de captura posterior a la descarga (P-L155).

    `entry` es el reloj con el que se entro a la funcion. El reloj de captura
    se vuelve a leer DESPUES de la descarga y, si la propia descarga declara un
    `created_at` posterior, se avanza hasta ese instante: la cache recien
    escrita no puede quedar por delante del reloj del recibo y producir
    `cache_created_at_future`. Con `now` explicito sigue siendo determinista
    (maximo de la entrada y del `created_at` declarado); con `now=None` el reloj
    real se lee aqui, ya descargada la cache.
    """
    captured = _now(entry)
    downloaded = _parse_utc(meta.get("created_at")) if isinstance(meta, dict) else None
    if downloaded is not None and downloaded > captured:
        return downloaded
    return captured


def refresh_and_capture_spy_eod(settings: Any, session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Descarga la ventana exacta [previa, sesion] y persiste el recibo (P-L127).

    Fail-open total: cualquier fallo de red, validacion o I/O devuelve un
    resumen no persistado sin lanzar. Nunca inventa cierres. La sesion se
    evalua cerrada ANTES de descargar; el reloj del recibo se toma despues
    (P-L155).
    """
    from .market_data import download_daily_prices_with_metadata

    entry = _now(now)  # reloj de entrada; el de captura se toma tras la descarga.
    try:
        previous = previous_xnys_session(session_date)
    except (TypeError, ValueError):
        return {"persisted": False, "reason": "invalid_session_date", "receipt": None}
    if previous is None:
        return {"persisted": False, "reason": "missing_previous_xnys_session", "receipt": None}
    status, _ = session_status(session_date, now=entry)
    if status != "closed":
        return {"persisted": False, "reason": "session_not_closed", "receipt": None}
    symbol = str(getattr(settings, "benchmark_symbol", "SPY") or "SPY").upper()
    try:
        end = (date.fromisoformat(session_date) + timedelta(days=1)).isoformat()
        _frame, download_meta = download_daily_prices_with_metadata(
            [symbol],
            previous,
            end,
            cache_dir=_cache_root(settings),
            provider=getattr(settings, "market_data_provider", "auto") or "auto",
        )
    except Exception as exc:  # noqa: BLE001 - red caida no tumba reconciliacion.
        return {"persisted": False, "reason": f"fetch_failed_open:{type(exc).__name__}", "receipt": None}
    captured_result = capture_spy_eod_receipt(
        settings, session_date, now=_capture_clock(entry, download_meta)
    )
    receipt = captured_result.get("receipt") or {}
    if not captured_result.get("persisted") or receipt.get("comparison_status") != "comparable":
        return {
            "persisted": bool(captured_result.get("persisted")),
            "reason": ",".join(receipt.get("reason_codes") or ["receipt_unavailable"]),
            "receipt": receipt or None,
        }
    return {**captured_result, "reason": None}


def backfill_spy_eod_receipts(settings: Any, start: str, end: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Genera recibos desde caches existentes, sin descargas (P-L127)."""
    sessions = xnys_sessions_between(start, end)
    built: list[str] = []
    skipped: list[str] = []
    unavailable: dict[str, list[str]] = {}
    for session_date in sessions:
        existing = load_spy_eod_receipt(settings, session_date)
        if existing is not None and existing.get("comparison_status") == "comparable":
            skipped.append(session_date)
            continue
        captured = capture_spy_eod_receipt(settings, session_date, now=now)
        receipt = captured.get("receipt") or {}
        if captured.get("persisted") and receipt.get("comparison_status") == "comparable":
            built.append(session_date)
        else:
            unavailable[session_date] = list(receipt.get("reason_codes") or ["receipt_unavailable"])
    return {"built": built, "skipped": skipped, "unavailable": unavailable}
