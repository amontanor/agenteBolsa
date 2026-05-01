"""Multi-session chart pattern detection.

The detector is deliberately rule-based. It turns visual chart patterns into
auditable pivots, levels, status and confidence so the signal can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Pivot:
    kind: str
    position: int
    date: str
    price: float


def _round(value: float | None, precision: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), precision)


def _index_label(index: Any) -> str:
    if hasattr(index, "date"):
        return str(index.date())
    return str(index)


def _pivot_to_dict(pivot: Pivot) -> dict[str, Any]:
    return {
        "kind": pivot.kind,
        "position": pivot.position,
        "date": pivot.date,
        "price": _round(pivot.price),
    }


def _relative_gap(a: float, b: float) -> float:
    base = (abs(a) + abs(b)) / 2
    if base == 0:
        return 0
    return abs(a - b) / base


def _similar(a: float, b: float, tolerance: float) -> bool:
    return _relative_gap(a, b) <= tolerance


def _project_level(first: Pivot, second: Pivot, position: int) -> float:
    if second.position == first.position:
        return second.price
    slope = (second.price - first.price) / (second.position - first.position)
    return first.price + (slope * (position - first.position))


def _confidence(value: float) -> float:
    return round(max(0.0, min(0.95, value)), 2)


def _find_pivots(frame: pd.DataFrame, window: int = 3) -> list[Pivot]:
    raw: list[Pivot] = []
    highs = frame["High"].astype(float)
    lows = frame["Low"].astype(float)

    for position in range(window, len(frame) - window):
        high = float(highs.iloc[position])
        low = float(lows.iloc[position])
        high_slice = highs.iloc[position - window : position + window + 1]
        low_slice = lows.iloc[position - window : position + window + 1]

        if high == float(high_slice.max()) and int((high_slice == high).sum()) == 1:
            raw.append(
                Pivot(
                    kind="high",
                    position=position,
                    date=_index_label(frame.index[position]),
                    price=high,
                )
            )
        if low == float(low_slice.min()) and int((low_slice == low).sum()) == 1:
            raw.append(
                Pivot(
                    kind="low",
                    position=position,
                    date=_index_label(frame.index[position]),
                    price=low,
                )
            )

    raw.sort(key=lambda pivot: pivot.position)
    compact: list[Pivot] = []
    for pivot in raw:
        if not compact:
            compact.append(pivot)
            continue

        last = compact[-1]
        if pivot.kind != last.kind:
            compact.append(pivot)
            continue

        if pivot.kind == "high" and pivot.price > last.price:
            compact[-1] = pivot
        elif pivot.kind == "low" and pivot.price < last.price:
            compact[-1] = pivot

    return compact


def _pattern(
    *,
    pattern: str,
    label: str,
    bias: str,
    status: str,
    confidence: float,
    level_name: str,
    level: float,
    components: list[Pivot],
    reason: str,
) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "label": label,
        "bias": bias,
        "status": status,
        "confidence": _confidence(confidence),
        level_name: _round(level),
        "components": [_pivot_to_dict(pivot) for pivot in components],
        "reason": reason,
    }


def _detect_head_and_shoulders(
    pivots: list[Pivot],
    latest_close: float,
    latest_position: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    expected = ["high", "low", "high", "low", "high"]

    for start in range(len(pivots) - 4):
        sequence = pivots[start : start + 5]
        if [pivot.kind for pivot in sequence] != expected:
            continue

        left, neck_left, head, neck_right, right = sequence
        shoulder_avg = (left.price + right.price) / 2
        neckline_now = _project_level(neck_left, neck_right, latest_position)
        head_extension = (head.price - shoulder_avg) / shoulder_avg
        pattern_depth = (shoulder_avg - min(neck_left.price, neck_right.price)) / shoulder_avg

        if (
            head.price <= max(left.price, right.price)
            or head_extension < 0.03
            or pattern_depth < 0.03
            or not _similar(left.price, right.price, 0.12)
        ):
            continue

        status = "confirmed" if latest_close < neckline_now else "forming"
        patterns.append(
            _pattern(
                pattern="head_and_shoulders",
                label="hombro-cabeza-hombro",
                bias="bearish",
                status=status,
                confidence=0.54 + head_extension + pattern_depth,
                level_name="neckline",
                level=neckline_now,
                components=sequence,
                reason=(
                    "Cabeza por encima de ambos hombros y neckline definido; "
                    "sesgo bajista si pierde neckline."
                ),
            )
        )

    return patterns


def _detect_inverse_head_and_shoulders(
    pivots: list[Pivot],
    latest_close: float,
    latest_position: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    expected = ["low", "high", "low", "high", "low"]

    for start in range(len(pivots) - 4):
        sequence = pivots[start : start + 5]
        if [pivot.kind for pivot in sequence] != expected:
            continue

        left, neck_left, head, neck_right, right = sequence
        shoulder_avg = (left.price + right.price) / 2
        neckline_now = _project_level(neck_left, neck_right, latest_position)
        head_extension = (shoulder_avg - head.price) / shoulder_avg
        pattern_depth = (max(neck_left.price, neck_right.price) - shoulder_avg) / shoulder_avg

        if (
            head.price >= min(left.price, right.price)
            or head_extension < 0.03
            or pattern_depth < 0.03
            or not _similar(left.price, right.price, 0.12)
        ):
            continue

        status = "confirmed" if latest_close > neckline_now else "forming"
        patterns.append(
            _pattern(
                pattern="inverse_head_and_shoulders",
                label="hombro-cabeza-hombro invertido",
                bias="bullish",
                status=status,
                confidence=0.54 + head_extension + pattern_depth,
                level_name="neckline",
                level=neckline_now,
                components=sequence,
                reason=(
                    "Cabeza bajo ambos hombros y neckline definido; "
                    "sesgo alcista si recupera neckline."
                ),
            )
        )

    return patterns


def _detect_double_patterns(
    pivots: list[Pivot],
    latest_close: float,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []

    for start in range(len(pivots) - 2):
        first, middle, second = pivots[start : start + 3]
        kinds = [first.kind, middle.kind, second.kind]

        if kinds == ["high", "low", "high"]:
            peak_avg = (first.price + second.price) / 2
            depth = (peak_avg - middle.price) / peak_avg
            if _similar(first.price, second.price, 0.045) and depth >= 0.035:
                status = "confirmed" if latest_close < middle.price else "forming"
                patterns.append(
                    _pattern(
                        pattern="double_top",
                        label="doble techo",
                        bias="bearish",
                        status=status,
                        confidence=0.52 + depth - _relative_gap(first.price, second.price),
                        level_name="neckline",
                        level=middle.price,
                        components=[first, middle, second],
                        reason=(
                            "Dos maximos similares separados por retroceso; "
                            "sesgo bajista si pierde el minimo intermedio."
                        ),
                    )
                )

        if kinds == ["low", "high", "low"]:
            trough_avg = (first.price + second.price) / 2
            rebound = (middle.price - trough_avg) / trough_avg
            if _similar(first.price, second.price, 0.045) and rebound >= 0.035:
                status = "confirmed" if latest_close > middle.price else "forming"
                patterns.append(
                    _pattern(
                        pattern="double_bottom",
                        label="doble suelo",
                        bias="bullish",
                        status=status,
                        confidence=0.52 + rebound - _relative_gap(first.price, second.price),
                        level_name="neckline",
                        level=middle.price,
                        components=[first, middle, second],
                        reason=(
                            "Dos minimos similares separados por rebote; "
                            "sesgo alcista si supera el maximo intermedio."
                        ),
                    )
                )

    return patterns


def _last_pivots(pivots: list[Pivot], kind: str, limit: int = 5) -> list[Pivot]:
    return [pivot for pivot in pivots if pivot.kind == kind][-limit:]


def _pivot_change(pivots: list[Pivot]) -> float:
    if len(pivots) < 2 or pivots[0].price == 0:
        return 0.0
    return (pivots[-1].price - pivots[0].price) / pivots[0].price


def _pivot_flatness(pivots: list[Pivot]) -> float:
    if not pivots:
        return 1.0
    avg = sum(pivot.price for pivot in pivots) / len(pivots)
    if avg == 0:
        return 1.0
    return (max(pivot.price for pivot in pivots) - min(pivot.price for pivot in pivots)) / avg


def _detect_triangles(
    pivots: list[Pivot],
    latest_close: float,
    latest_position: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    highs = _last_pivots(pivots, "high")
    lows = _last_pivots(pivots, "low")
    if len(highs) < 3 or len(lows) < 3:
        return patterns

    high_change = _pivot_change(highs)
    low_change = _pivot_change(lows)
    high_flatness = _pivot_flatness(highs)
    low_flatness = _pivot_flatness(lows)

    if high_flatness <= 0.035 and low_change >= 0.035:
        resistance = sum(pivot.price for pivot in highs) / len(highs)
        status = "confirmed" if latest_close > resistance else "forming"
        patterns.append(
            _pattern(
                pattern="ascending_triangle",
                label="triangulo ascendente",
                bias="bullish",
                status=status,
                confidence=0.50 + low_change + (0.035 - high_flatness),
                level_name="resistance",
                level=resistance,
                components=[highs[0], highs[-1], lows[0], lows[-1]],
                reason=(
                    "Resistencia horizontal con minimos crecientes; "
                    "sesgo alcista si rompe resistencia."
                ),
            )
        )

    if low_flatness <= 0.035 and high_change <= -0.035:
        support = sum(pivot.price for pivot in lows) / len(lows)
        status = "confirmed" if latest_close < support else "forming"
        patterns.append(
            _pattern(
                pattern="descending_triangle",
                label="triangulo descendente",
                bias="bearish",
                status=status,
                confidence=0.50 + abs(high_change) + (0.035 - low_flatness),
                level_name="support",
                level=support,
                components=[highs[0], highs[-1], lows[0], lows[-1]],
                reason=(
                    "Soporte horizontal con maximos decrecientes; "
                    "sesgo bajista si pierde soporte."
                ),
            )
        )

    if high_change <= -0.035 and low_change >= 0.035:
        upper = _project_level(highs[0], highs[-1], latest_position)
        lower = _project_level(lows[0], lows[-1], latest_position)
        status = "forming"
        bias = "neutral"
        if latest_close > upper:
            status = "confirmed"
            bias = "bullish"
        elif latest_close < lower:
            status = "confirmed"
            bias = "bearish"

        patterns.append(
            _pattern(
                pattern="symmetrical_triangle",
                label="triangulo simetrico",
                bias=bias,
                status=status,
                confidence=0.50 + abs(high_change) + low_change,
                level_name="apex_zone_mid",
                level=(upper + lower) / 2,
                components=[highs[0], highs[-1], lows[0], lows[-1]],
                reason=(
                    "Maximos decrecientes y minimos crecientes; "
                    "requiere ruptura para definir direccion."
                ),
            )
        )

    return patterns


def _dedupe_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_type: dict[str, dict[str, Any]] = {}
    for item in patterns:
        key = str(item["pattern"])
        previous = best_by_type.get(key)
        if previous is None:
            best_by_type[key] = item
            continue

        previous_position = max(component["position"] for component in previous["components"])
        current_position = max(component["position"] for component in item["components"])
        previous_rank = (
            previous["status"] == "confirmed",
            previous["confidence"],
            previous_position,
        )
        current_rank = (
            item["status"] == "confirmed",
            item["confidence"],
            current_position,
        )
        if current_rank > previous_rank:
            best_by_type[key] = item

    return sorted(
        best_by_type.values(),
        key=lambda item: (
            item["status"] == "confirmed",
            item["confidence"],
            max(component["position"] for component in item["components"]),
        ),
        reverse=True,
    )


def analyze_chart_patterns(
    frame: pd.DataFrame,
    *,
    lookback: int = 180,
    pivot_window: int = 3,
    max_patterns: int = 6,
) -> list[dict[str, Any]]:
    """Detect complex chart figures from a single-symbol OHLCV frame."""

    required = {"High", "Low", "Close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")

    recent = frame.dropna(subset=["High", "Low", "Close"]).tail(lookback).copy()
    if len(recent) < 30:
        return []

    latest_close = float(recent["Close"].iloc[-1])
    latest_position = len(recent) - 1
    pivots = _find_pivots(recent, window=pivot_window)
    if len(pivots) < 3:
        return []

    patterns: list[dict[str, Any]] = []
    patterns.extend(_detect_head_and_shoulders(pivots, latest_close, latest_position))
    patterns.extend(_detect_inverse_head_and_shoulders(pivots, latest_close, latest_position))
    patterns.extend(_detect_double_patterns(pivots, latest_close))
    patterns.extend(_detect_triangles(pivots, latest_close, latest_position))
    return _dedupe_patterns(patterns)[:max_patterns]
