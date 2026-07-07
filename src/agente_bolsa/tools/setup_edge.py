"""Helpers for setup-level edge bias.

This module stays light on purpose. It exposes:
1. A stable setup key used by studies and ranking.
2. A bounded score bias derived from measured setup edge.
3. A read-only loader that builds the setup edge table from `signal_outcomes`
   using a train window, so callers can keep walk-forward discipline.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agente_bolsa._utils import sqlite_connect_ro, table_exists, to_float


def setup_quality_key(features: dict[str, Any] | None) -> str:
    """Build a stable setup key from signal features, en el espacio `{base}|{quality}`.

    `base` = confirmed_pattern / sin_patron segun si hay patron alcista confirmado.
    NO se usa `setup_name` como clave: el estudio de edge y la `edge_table` viven en
    este espacio `{base}|{quality}`, y los candidatos en vivo SI traen `setup_name`
    mientras que las features historicas NO. Usar setup_name dejaba la clave en vivo
    como p.ej. "confirmed_pattern" (sin calidad) y nunca casaba con
    "confirmed_pattern|strong" de la tabla -> el sesgo quedaba SIEMPRE en 0 (inerte).
    Mantener ambos lados en el mismo espacio garantiza el match (medido por el shadow
    por ciclo: keys_without_edge_match).
    """
    feats = features or {}
    patterns = feats.get("chart_patterns") or {}
    if isinstance(patterns, list):
        confirmed = float(
            sum(
                1
                for item in patterns
                if isinstance(item, dict)
                and str(item.get("bias") or "").lower() == "bullish"
                and str(item.get("status") or "").lower() == "confirmed"
            )
        )
    else:
        confirmed = to_float(patterns.get("bullish_confirmed_count")) or 0.0
    quality = str(feats.get("setup_quality") or "n/d")
    base = "confirmed_pattern" if confirmed >= 1 else "sin_patron"
    return f"{base}|{quality}"


def setup_edge_bias(
    key: str,
    edge_table: dict[str, float] | None = None,
    *,
    scale: float = 1000.0,
    cap: float = 15.0,
) -> float:
    """Convert measured mean return into a bounded score bias."""
    if not edge_table:
        return 0.0
    mean_ret = edge_table.get(key)
    if mean_ret is None:
        return 0.0
    biased = float(mean_ret) * scale
    return max(-cap, min(cap, biased))


def _loads_dict(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _coerce_as_of(value: str | date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if "T" in text:
            text = text.split("T", 1)[0]
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def compute_setup_edge_table_from_connection(
    connection: sqlite3.Connection,
    *,
    as_of: str | date | datetime | None = None,
    train_window_days: int = 120,
    min_samples: int = 20,
    horizon: str = "return_5d",
) -> dict[str, float]:
    """Compute `{setup_key: mean(return_Xd)}` from mature signal outcomes."""
    if train_window_days <= 0 or min_samples <= 0:
        return {}
    if not table_exists(connection, "signal_outcomes"):
        return {}

    end_date = _coerce_as_of(as_of)
    start_date = end_date - timedelta(days=max(1, int(train_window_days)))
    columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(signal_outcomes)").fetchall()}
    source_filter = "AND coalesce(source, '') NOT IN ('lab_book', 'learning_experiment')" if "source" in columns else ""
    rows = connection.execute(
        f"""
        SELECT signal_date, features_json, outcome_json
        FROM signal_outcomes
        WHERE signal_date >= ? AND signal_date < ?
          {source_filter}
        """,
        (start_date.isoformat(), end_date.isoformat()),
    ).fetchall()

    grouped: dict[str, list[float]] = {}
    for row in rows:
        if isinstance(row, sqlite3.Row):
            features_raw = row["features_json"]
            outcome_raw = row["outcome_json"]
        else:
            features_raw = row[1]
            outcome_raw = row[2]
        features = _loads_dict(features_raw)
        outcome = _loads_dict(outcome_raw)
        forward_return = to_float(outcome.get(horizon))
        if forward_return is None:
            continue
        key = setup_quality_key(features)
        grouped.setdefault(key, []).append(float(forward_return))

    return {
        key: round(sum(values) / len(values), 6)
        for key, values in grouped.items()
        if len(values) >= int(min_samples)
    }


def load_setup_edge_table(
    db_path: str | Path,
    *,
    as_of: str | date | datetime | None = None,
    train_window_days: int = 120,
    min_samples: int = 20,
    horizon: str = "return_5d",
) -> dict[str, float]:
    """Open the live DB in read-only mode and compute the setup edge table."""
    connection = sqlite_connect_ro(db_path, timeout=30.0)
    try:
        return compute_setup_edge_table_from_connection(
            connection,
            as_of=as_of,
            train_window_days=train_window_days,
            min_samples=min_samples,
            horizon=horizon,
        )
    finally:
        connection.close()
