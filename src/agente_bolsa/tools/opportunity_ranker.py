"""Motor determinista de ranking de oportunidades (largos).

Motivacion (16-jun-2026): cuando el LLM de decision esta caido, el sistema cae a
un fallback que en la practica solo evaluaba un unico candidato y lo perdia todo
en un dia alcista. Este modulo proporciona un ranking determinista, explicable y
sin dependencias pesadas (solo stdlib) de las mejores oportunidades de compra a
partir de un snapshot de mercado. Sirve para:

  - dar al sistema un slate de candidatos de calidad aunque el LLM falle,
  - hacer visible "que deberiamos estar mirando" en el dashboard,
  - alimentar/contrastar el fallback determinista existente.

No ejecuta ordenes ni toca el broker: solo puntua y ordena. El score es una
combinacion explicable de fuerza relativa vs benchmark, alineacion de tendencia,
momentum, extension respecto a la SMA20 y confirmacion de volumen.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agente_bolsa._utils import to_float
from agente_bolsa.tools.setup_edge import setup_edge_bias, setup_quality_key

# ETFs de indice/sector que normalmente no queremos como "oportunidad" individual.
DEFAULT_EXCLUDE = {
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",
    "XLK", "XLV", "XLF", "XLE", "XLP", "XLC", "XLY", "XLI", "XLU", "XLB", "XLRE",
}


@dataclass
class OpportunityConfig:
    """Pesos y umbrales del scoring (todos ajustables)."""
    w_relative_strength: float = 40.0
    w_momentum: float = 20.0
    w_trend: float = 25.0
    w_volume: float = 10.0
    extension_penalty: float = 35.0
    max_sma20_distance: float = 0.12
    min_volume_z: float = -2.0
    require_above_sma20: bool = True
    require_uptrend_200: bool = False
    atr_stop_multiple: float = 2.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class ScoredOpportunity:
    symbol: str
    score: float
    components: dict[str, float]
    metrics: dict[str, Any]
    suggested_stop: float | None
    suggested_stop_pct: float | None
    reason: str
    eligible: bool
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_symbol(
    symbol: str,
    metrics: dict[str, Any],
    benchmark_return_20d: float,
    config: OpportunityConfig | None = None,
) -> ScoredOpportunity:
    """Puntua un simbolo. Score mayor = mejor oportunidad de largo."""
    cfg = config or OpportunityConfig()
    close = to_float(metrics.get("close"))
    ret20 = to_float(metrics.get("return_20d"))
    sma20 = to_float(metrics.get("sma_20"))
    sma50 = to_float(metrics.get("sma_50"))
    sma200 = to_float(metrics.get("sma_200"))
    vol_z = to_float(metrics.get("volume_zscore_20"))
    atr = to_float(metrics.get("atr_14"))
    trend_positive = bool(metrics.get("trend_positive"))
    above_long = bool(metrics.get("above_long_trend"))

    exclusion = None
    if ret20 is None or close is None:
        exclusion = "datos_insuficientes"
    elif cfg.require_above_sma20 and not trend_positive:
        exclusion = "bajo_sma20"
    elif cfg.require_uptrend_200 and not above_long:
        exclusion = "bajo_sma200"
    elif vol_z is not None and vol_z < cfg.min_volume_z:
        exclusion = "volumen_muy_flojo"

    rel = (ret20 - benchmark_return_20d) if ret20 is not None else 0.0

    c_rel = cfg.w_relative_strength * _clamp(rel / 0.10, -1.0, 1.5)
    c_mom = cfg.w_momentum * _clamp((ret20 or 0.0) / 0.10, -1.0, 1.5)
    trend_pts = 0.0
    if close is not None:
        if sma20 and close > sma20:
            trend_pts += 0.4
        if sma50 and close > sma50:
            trend_pts += 0.3
        if sma200 and close > sma200:
            trend_pts += 0.3
    c_trend = cfg.w_trend * trend_pts
    c_vol = cfg.w_volume * _clamp(((vol_z or 0.0) + 1.0) / 2.0, -1.0, 1.0)

    ext_pen = 0.0
    sma20_dist = None
    if close is not None and sma20:
        sma20_dist = (close - sma20) / sma20
        if sma20_dist > cfg.max_sma20_distance:
            over = (sma20_dist - cfg.max_sma20_distance) / cfg.max_sma20_distance
            ext_pen = cfg.extension_penalty * _clamp(over, 0.0, 1.0)

    raw = c_rel + c_mom + c_trend + c_vol - ext_pen
    score = round(raw, 2)

    suggested_stop = None
    suggested_stop_pct = None
    if close is not None and atr:
        suggested_stop = round(close - cfg.atr_stop_multiple * atr, 4)
        if close:
            suggested_stop_pct = round((close - suggested_stop) / close, 4)

    reason = (
        f"RS vs {('+' if rel >= 0 else '')}{rel * 100:.1f}% benchmark, "
        f"ret20d={ (ret20 or 0.0) * 100:.1f}%, "
        f"tendencia={trend_pts:.1f}/1.0, volZ={vol_z if vol_z is not None else 'n/d'}"
    )
    if ext_pen > 0 and sma20_dist is not None:
        reason += f", sobre-extension {sma20_dist * 100:.1f}% sobre SMA20 (penalizada)"

    return ScoredOpportunity(
        symbol=symbol.upper(),
        score=score,
        components={
            "relative_strength": round(c_rel, 2),
            "momentum": round(c_mom, 2),
            "trend": round(c_trend, 2),
            "volume": round(c_vol, 2),
            "extension_penalty": round(-ext_pen, 2),
        },
        metrics={
            "close": close,
            "return_20d": ret20,
            "relative_return_20d": round(rel, 4) if ret20 is not None else None,
            "sma20_distance": round(sma20_dist, 4) if sma20_dist is not None else None,
            "volume_zscore_20": vol_z,
            "atr_14": atr,
            "trend_positive": trend_positive,
            "above_long_trend": above_long,
        },
        suggested_stop=suggested_stop,
        suggested_stop_pct=suggested_stop_pct,
        reason=reason,
        eligible=exclusion is None,
        exclusion_reason=exclusion,
    )


def rank_opportunities(
    snapshot: dict[str, Any],
    *,
    top_n: int = 10,
    exclude: set[str] | None = None,
    include_ineligible: bool = False,
    config: OpportunityConfig | None = None,
    benchmark_return_20d: float | None = None,
) -> dict[str, Any]:
    """Ordena las mejores oportunidades de largo de un snapshot de mercado.

    Si `benchmark_return_20d` se pasa explicitamente, se usa como referencia de
    fuerza relativa (util cuando el benchmark no esta entre los `symbols`).
    """
    cfg = config or OpportunityConfig()
    excl = {s.upper() for s in (exclude if exclude is not None else DEFAULT_EXCLUDE)}
    symbols = dict(snapshot.get("symbols") or {})
    benchmark = str(snapshot.get("benchmark") or "SPY").upper()

    if benchmark_return_20d is not None:
        bench_ret = float(benchmark_return_20d)
    else:
        bench_ret = to_float(snapshot.get("benchmark_return_20d"))
        if bench_ret is None:
            bench_metrics = symbols.get(benchmark) or {}
            bench_ret = to_float(bench_metrics.get("return_20d")) or 0.0

    scored: list[ScoredOpportunity] = []
    for symbol, metrics in symbols.items():
        if symbol.upper() in excl:
            continue
        if not isinstance(metrics, dict):
            continue
        scored.append(score_symbol(symbol, metrics, bench_ret, cfg))

    eligible = [s for s in scored if s.eligible]
    eligible.sort(key=lambda s: s.score, reverse=True)
    pool = eligible if not include_ineligible else sorted(scored, key=lambda s: s.score, reverse=True)
    top = pool[: max(0, top_n)]

    return {
        "as_of": snapshot.get("as_of"),
        "benchmark": benchmark,
        "benchmark_return_20d": round(bench_ret, 4),
        "evaluated": len(scored),
        "eligible": len(eligible),
        "config": asdict(cfg),
        "opportunities": [s.to_dict() for s in top],
    }


def _derive_trend_flags(metrics: dict[str, Any]) -> dict[str, Any]:
    """Deriva trend_positive / above_long_trend si vienen vacios (close vs SMA)."""
    out = dict(metrics)
    close = to_float(metrics.get("close"))
    sma20 = to_float(metrics.get("sma_20"))
    sma200 = to_float(metrics.get("sma_200"))
    if out.get("trend_positive") is None and close is not None and sma20:
        out["trend_positive"] = close > sma20
    if out.get("above_long_trend") is None and close is not None and sma200:
        out["above_long_trend"] = close > sma200
    return out


def snapshot_from_technical_study(study: dict[str, Any]) -> dict[str, Any]:
    """Convierte un `closed_market_technical_study` (universo amplio) al formato
    de snapshot que entiende `rank_opportunities`.
    """
    symbols: dict[str, Any] = {}
    candidates = list(study.get("all_candidates") or study.get("top_longs") or [])
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        if str(cand.get("direction") or "long").lower() != "long":
            continue
        symbol = str(cand.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        ts = dict(cand.get("technical_state") or {})
        ts = _derive_trend_flags(ts)
        symbols[symbol] = ts
    return {
        "as_of": study.get("as_of"),
        "benchmark": str(study.get("benchmark_symbol") or "SPY").upper(),
        "benchmark_return_20d": to_float(study.get("benchmark_return_20d")),
        "symbols": symbols,
    }


def snapshot_from_breakout_scan(scan: dict[str, Any]) -> dict[str, Any]:
    """Convierte un `breakout_scan` al formato de snapshot. Reconstruye SMA20
    desde la distancia para poder puntuar tendencia y extension.
    """
    symbols: dict[str, Any] = {}
    rows = list(scan.get("alerts") or []) + list(scan.get("confirmed") or []) + list(scan.get("watch") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol or symbol in symbols:
            continue
        close = to_float(row.get("close"))
        dist = to_float(row.get("sma20_distance"))
        sma20 = None
        if close is not None and dist is not None and (1.0 + dist) != 0:
            sma20 = close / (1.0 + dist)
        symbols[symbol] = {
            "close": close,
            "return_20d": to_float(row.get("return_20d")),
            "sma_20": sma20,
            "volume_zscore_20": to_float(row.get("volume_zscore_20")),
            "atr_14": to_float(row.get("atr_14")),
            "trend_positive": (close > sma20) if (close is not None and sma20) else None,
        }
    return {
        "as_of": scan.get("as_of"),
        "benchmark": "SPY",
        "symbols": symbols,
    }


def prioritize_candidates(
    candidates: list[dict[str, Any]],
    *,
    benchmark_return_20d: float = 0.0,
    config: OpportunityConfig | None = None,
    edge_table: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Reordena una lista de candidatos (con `technical_state`) por score de
    oportunidad determinista, de mejor a peor.

    Usado por el fallback determinista (T2b) para elegir primero el mejor lider
    por fuerza relativa / momentum / tendencia en lugar de un orden arbitrario.
    No filtra ni cambia elegibilidad: solo reordena. Cada item conserva todos
    sus campos originales y gana `opportunity_score`.

    Si se pasa `edge_table` (mapa setup->retorno medio medido, ver
    `tools/setup_edge.py` y `scripts/shadow_setup_edge_reweight.py`), se aplica un
    sesgo acotado por edge de setup al orden: prioriza setups con edge positivo
    (p.ej. sin_patron|strong) y posterga los de edge negativo (confirmed_pattern).
    Sin tabla, el comportamiento es idéntico al previo (retrocompatible).
    """
    cfg = config or OpportunityConfig()
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        ts = dict(item.get("technical_state") or {})
        ts = _derive_trend_flags(ts)
        symbol = str(item.get("symbol") or "").upper()
        s = score_symbol(symbol, ts, benchmark_return_20d, cfg)
        enriched = dict(item)
        enriched["opportunity_score"] = s.score
        # Sesgo por edge de setup (neutral si no hay tabla o faltan campos).
        bias = 0.0
        if edge_table:
            key = setup_quality_key({**ts, **item})
            bias = setup_edge_bias(key, edge_table)
            enriched["setup_edge_key"] = key
            enriched["setup_edge_bias"] = bias
        final_score = s.score + bias
        enriched["opportunity_score_adjusted"] = round(final_score, 2)
        scored.append((final_score, enriched))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]
