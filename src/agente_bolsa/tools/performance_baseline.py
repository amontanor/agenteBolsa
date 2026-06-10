"""Baseline de rendimiento y metrica unica de progreso (T0.2).

Construye una serie diaria objetiva del rendimiento del sistema completo y un
score compuesto ``iq_score`` (0-100) que resume "cada dia mas listo y rentable".
Es la referencia contra la que se mide TODA mejora futura.

El nucleo de calculo usa solo la libreria estandar para ser barato y testeable
sin red ni LLM. La descarga del benchmark SPY se hace de forma perezosa y
degrada a ``None`` (alpha nulo) si falla, nunca con excepcion.
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


TRADING_DAYS_PER_YEAR = 252
HIT_RATE_WINDOW_SESSIONS = 20
SHARPE_WINDOW_SESSIONS = 60


def _is_matured(signal: dict[str, Any]) -> bool:
    verdict = str((signal.get("outcome") or {}).get("verdict", "") or "")
    return verdict not in {"", "pending"}


def _verdict(signal: dict[str, Any]) -> str:
    return str((signal.get("outcome") or {}).get("verdict", "") or "")


def _return_pct(signal: dict[str, Any]) -> float | None:
    value = (signal.get("outcome") or {}).get("return_pct")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _matured_window(
    store: "Store",
    *,
    window_sessions: int,
    lookback_limit: int = 4000,
) -> list[dict[str, Any]]:
    """Outcomes madurados de las ultimas ``window_sessions`` sesiones con senal."""

    signals = [item for item in store.signal_outcomes(limit=lookback_limit) if _is_matured(item)]
    if not signals:
        return []
    distinct_dates = sorted({item["signal_date"] for item in signals}, reverse=True)
    keep = set(distinct_dates[:window_sessions])
    return [item for item in signals if item["signal_date"] in keep]


def _hit_rate(matured: list[dict[str, Any]]) -> float | None:
    decided = [item for item in matured if _verdict(item).startswith(("winner", "loser"))]
    if not decided:
        return None
    winners = sum(1 for item in decided if _verdict(item).startswith("winner"))
    return round(winners / len(decided), 4)


def _profit_factor(matured: list[dict[str, Any]]) -> float | None:
    gross_win = 0.0
    gross_loss = 0.0
    for item in matured:
        ret = _return_pct(item)
        if ret is None:
            continue
        if ret >= 0:
            gross_win += ret
        else:
            gross_loss += abs(ret)
    if gross_loss <= 0:
        return None if gross_win <= 0 else float("inf")
    return round(gross_win / gross_loss, 4)


def _sharpe(pnl_series: list[float]) -> float | None:
    clean = [value for value in pnl_series if isinstance(value, (int, float))]
    if len(clean) < 2:
        return None
    stdev = statistics.pstdev(clean)
    if stdev == 0:
        return None
    mean = statistics.fmean(clean)
    return round((mean / stdev) * math.sqrt(TRADING_DAYS_PER_YEAR), 4)


def _max_drawdown(equity_series: list[float]) -> float | None:
    clean = [value for value in equity_series if isinstance(value, (int, float)) and value > 0]
    if len(clean) < 2:
        return None
    peak = clean[0]
    max_dd = 0.0
    for value in clean:
        peak = max(peak, value)
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, drawdown)
    return round(max_dd, 4)


def _count_signals(store: "Store", session_date: str) -> dict[str, int]:
    rows = store.signal_outcomes(limit=2000, since_date=session_date)
    same_day = [item for item in rows if item["signal_date"] == session_date]
    buys = sum(1 for item in same_day if str(item.get("decision", "")).lower() in {"buy", "long", "enter"})
    sells = sum(1 for item in same_day if str(item.get("decision", "")).lower() in {"sell", "exit", "reduce"})
    return {"signals": len(same_day), "buys": buys, "sells": sells}


def _avg_exposure(portfolio: Any, equity: float | None) -> float | None:
    if portfolio is None or not equity or equity <= 0:
        return None
    positions = getattr(portfolio, "positions", None) or []
    total = 0.0
    for position in positions:
        market_value = getattr(position, "market_value", None)
        if isinstance(market_value, (int, float)):
            total += abs(market_value)
    return round(total / equity, 4)


def build_daily_performance(
    store: "Store",
    settings: "Settings",
    session_date: str,
    *,
    equity: float | None = None,
    spy_pct: float | None = None,
    portfolio: Any = None,
) -> dict[str, Any]:
    """Serie diaria de rendimiento del sistema completo para ``session_date``."""

    if equity is None and portfolio is not None:
        portfolio_value = getattr(portfolio, "portfolio_value", None)
        if isinstance(portfolio_value, (int, float)):
            equity = float(portfolio_value)

    history = [row for row in store.performance_daily(limit=0) if row["session_date"] < session_date]
    prev_equity = None
    cumulative_pnl_pct = 0.0
    for row in history:
        if isinstance(row.get("equity"), (int, float)):
            prev_equity = row["equity"]
        if isinstance(row.get("pnl_pct"), (int, float)):
            cumulative_pnl_pct += row["pnl_pct"]

    pnl_pct: float | None = None
    if equity is not None and prev_equity:
        pnl_pct = round((equity - prev_equity) / prev_equity, 6)
        cumulative_pnl_pct += pnl_pct
    elif equity is not None and prev_equity is None:
        pnl_pct = 0.0

    counts = _count_signals(store, session_date)
    matured = _matured_window(store, window_sessions=HIT_RATE_WINDOW_SESSIONS)
    hit_rate_20 = _hit_rate(matured)
    profit_factor = _profit_factor(matured)

    pnl_history = [row["pnl_pct"] for row in history[-(SHARPE_WINDOW_SESSIONS - 1):]]
    if pnl_pct is not None:
        pnl_history = pnl_history + [pnl_pct]
    sharpe_60 = _sharpe(pnl_history)

    equity_history = [row["equity"] for row in history if isinstance(row.get("equity"), (int, float))]
    if equity is not None:
        equity_history = equity_history + [equity]
    max_dd = _max_drawdown(equity_history)

    alpha = None
    if pnl_pct is not None and isinstance(spy_pct, (int, float)):
        alpha = round(pnl_pct - spy_pct, 6)

    payload: dict[str, Any] = {
        "session_date": session_date,
        "equity": equity,
        "pnl_pct": pnl_pct,
        "cumulative_pnl_pct": round(cumulative_pnl_pct, 6),
        "signals": counts["signals"],
        "buys": counts["buys"],
        "sells": counts["sells"],
        "hit_rate_20": hit_rate_20,
        "profit_factor": profit_factor if profit_factor != float("inf") else None,
        "sharpe_60": sharpe_60,
        "max_dd": max_dd,
        "avg_exposure": _avg_exposure(portfolio, equity),
        "spy_pct": spy_pct if isinstance(spy_pct, (int, float)) else None,
        "alpha_vs_spy": alpha,
    }
    payload["iq_score"] = system_iq_score(store, window_days=20, extra_today=payload)
    return payload


def _normalize_alpha(alpha_values: list[float]) -> float:
    """Normaliza el alpha medio a [0, 1] con una saturacion suave a +-2%/dia."""

    if not alpha_values:
        return 0.5
    mean_alpha = statistics.fmean(alpha_values)
    # 0% alpha -> 0.5; +2% diario -> ~1.0; -2% -> ~0.0.
    scaled = 0.5 + (mean_alpha / 0.04)
    return max(0.0, min(1.0, scaled))


def _lab_promotion_quality(store: "Store") -> float:
    """Ratio de cambios autonomos que sobreviven (APPLIED no revertidos)."""

    try:
        changes = store.continuous_improvement_applied_changes(limit=500)
    except Exception:  # noqa: BLE001 - metrica opcional.
        return 0.5
    applied = [item for item in changes if str(item.get("status")) == "APPLIED"]
    rolled = [item for item in changes if str(item.get("status")) == "ROLLED_BACK"]
    total = len(applied) + len(rolled)
    if total == 0:
        return 0.5
    return len(applied) / total


def system_iq_score(
    store: "Store",
    *,
    window_days: int = 20,
    extra_today: dict[str, Any] | None = None,
) -> float:
    """Score compuesto 0-100 de "cada dia mas listo".

    40% alpha_vs_spy normalizado + 25% hit rate + 20% profit factor (saturado) +
    15% calidad de promociones del laboratorio. Componentes ausentes degradan a
    un valor neutro en vez de romper.
    """

    rows = store.performance_daily(limit=0)[-window_days:]
    if extra_today is not None:
        rows = rows + [extra_today]

    alpha_values = [row["alpha_vs_spy"] if "alpha_vs_spy" in row else row.get("alpha") for row in rows]
    alpha_values = [value for value in alpha_values if isinstance(value, (int, float))]
    alpha_component = _normalize_alpha(alpha_values)

    hit_values = [row.get("hit_rate_20") for row in rows if isinstance(row.get("hit_rate_20"), (int, float))]
    hit_component = statistics.fmean(hit_values) if hit_values else 0.5

    pf_values = [row.get("profit_factor") for row in rows if isinstance(row.get("profit_factor"), (int, float))]
    if pf_values:
        # profit factor 1.0 -> 0.5; 2.0 -> ~0.75; saturado en 3.0 -> 1.0.
        pf_norm = [max(0.0, min(1.0, (value - 1.0) / 2.0 + 0.5)) for value in pf_values]
        pf_component = statistics.fmean(pf_norm)
    else:
        pf_component = 0.5

    lab_component = _lab_promotion_quality(store)

    score = (
        0.40 * alpha_component
        + 0.25 * hit_component
        + 0.20 * pf_component
        + 0.15 * lab_component
    )
    return round(score * 100.0, 2)


def fetch_spy_daily_return(settings: "Settings", session_date: str) -> float | None:
    """Retorno diario de SPY para la sesion. Degrada a ``None`` si falla."""

    try:
        from datetime import date, timedelta

        from .market_data import download_daily_prices

        session = date.fromisoformat(session_date)
        start = (session - timedelta(days=10)).isoformat()
        end = (session + timedelta(days=1)).isoformat()
        frame = download_daily_prices(
            ["SPY"],
            start,
            end,
            provider=settings.market_data_provider,
            fmp_api_key=settings.fmp_api_key,
        )
        if frame is None or len(frame) < 2:
            return None
        closes = frame["Close"] if "Close" in getattr(frame, "columns", []) else None
        if closes is None:
            return None
        closes = closes.dropna()
        if len(closes) < 2:
            return None
        prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
        if prev <= 0:
            return None
        return round((last - prev) / prev, 6)
    except Exception:  # noqa: BLE001 - SPY ausente -> alpha nulo, nunca excepcion.
        return None
