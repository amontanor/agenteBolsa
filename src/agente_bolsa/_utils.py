"""Utilidades compartidas, ligeras y sin dependencias pesadas (solo stdlib).

Motivacion (auditoria 21-jun-2026): habia helpers reimplementados en muchos
modulos (`_float` en 9 ficheros, `parse_iso` en 3, `table_exists`, formato de
bytes, conexion sqlite de solo lectura...). Esto centraliza esas piezas para
evitar divergencias sutiles (D3) y ofrece un helper de "swallow con log" para que
los `except` dejen de tragarse errores en silencio (D2).

Importable desde cualquier capa sin arrastrar pydantic/crewai.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "to_float",
    "parse_iso",
    "utc_now",
    "human_bytes",
    "sqlite_connect_ro",
    "table_exists",
    "log_swallow",
]


def to_float(value: Any, default: float | None = None) -> float | None:
    """Coercion tolerante a float. Devuelve `default` si no es convertible.

    Reemplaza las multiples copias de `_float`/`_f` repartidas por el codigo.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    """Parsea un ISO-8601 (acepta sufijo 'Z') y normaliza a UTC. None si falla."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def human_bytes(n_bytes: float) -> str:
    """Formatea bytes en unidades legibles (B/KB/MB/GB/TB/PB)."""
    n = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def sqlite_connect_ro(db_path: str | Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Conexion sqlite de SOLO LECTURA, segura con el sistema escribiendo.

    Usa `mode=ro` (respeta el WAL del proceso vivo) en vez de `immutable=1`, que
    puede dar 'disk I/O error'/'malformed' durante escrituras concurrentes.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=timeout)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        pass
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def log_swallow(logger: logging.Logger, context: str, exc: BaseException, *, level: int = logging.WARNING) -> None:
    """Registra una excepcion que se decide ignorar, en lugar de tragarla en
    silencio. Asi un fallo recurrente (p.ej. caida de LLM) deja rastro.

    Uso:
        try:
            ...
        except Exception as exc:  # noqa: BLE001
            log_swallow(LOGGER, "persistir healthcheck", exc)
    """
    try:
        logger.log(level, "swallow [%s]: %s: %s", context, type(exc).__name__, exc)
    except Exception:  # noqa: BLE001 - el logging nunca debe romper al caller
        pass
