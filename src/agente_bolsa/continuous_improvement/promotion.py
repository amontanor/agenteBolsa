"""Champion/challenger con promocion automatica por metricas (T1.3).

Una estrategia validada entra en SHADOW; de SHADOW pasa a ACTIVE por metricas,
sin humano (en paper). Una ventana se resuelve cuando acumula suficientes
sesiones y senales shadow madurada. Criterio de promocion: hit rate shadow >=
champion - margen, expectancy shadow > champion y max drawdown shadow <= factor x
champion. El humano conserva un freno (veto configurable), no un gate.

Nucleo stdlib para ser testeable con outcomes sinteticos.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

from ..models import new_id

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


def _strategy_of(signal: dict[str, Any]) -> str | None:
    features = signal.get("features") or {}
    return features.get("strategy_name") or signal.get("strategy_name")


def _is_shadow(signal: dict[str, Any]) -> bool:
    features = signal.get("features") or {}
    outcome = signal.get("outcome") or {}
    return bool(features.get("shadow")) or bool(outcome.get("shadow"))


def _is_matured(signal: dict[str, Any]) -> bool:
    verdict = str((signal.get("outcome") or {}).get("verdict", "") or "")
    return verdict not in {"", "pending"}


def _return_pct(signal: dict[str, Any]) -> float | None:
    value = (signal.get("outcome") or {}).get("return_pct")
    return float(value) if isinstance(value, (int, float)) else None


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return round(max_dd, 4)


def compute_strategy_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    matured = [item for item in outcomes if _is_matured(item)]
    decided = [item for item in matured if str((item.get("outcome") or {}).get("verdict", "")).startswith(("winner", "loser"))]
    returns = [r for r in (_return_pct(item) for item in matured) if r is not None]
    sessions = len({item.get("signal_date") for item in matured})
    winners = sum(1 for item in decided if str((item.get("outcome") or {}).get("verdict", "")).startswith("winner"))
    hit_rate = (winners / len(decided)) if decided else None
    expectancy = statistics.fmean(returns) if returns else None
    return {
        "sessions": sessions,
        "signals": len(matured),
        "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "expectancy": round(expectancy, 6) if expectancy is not None else None,
        "max_dd": _max_drawdown(returns),
    }


class PromotionManager:
    def __init__(self, store: "Store", settings: "Settings") -> None:
        self.store = store
        self.settings = settings
        self.min_sessions = int(getattr(settings, "promotion_min_sessions", 10))
        self.min_signals = int(getattr(settings, "promotion_min_signals", 20))
        self.max_sessions = int(getattr(settings, "promotion_max_sessions", 25))
        self.hit_margin = float(getattr(settings, "promotion_hit_rate_margin", 0.02))
        self.dd_factor = float(getattr(settings, "promotion_max_dd_factor", 1.2))

    # -- apertura ----------------------------------------------------------
    def start_shadow(self, strategy_name: str, version: str = "1", *, slot: str | None = None) -> dict[str, Any]:
        try:
            self.store.set_strategy_status(strategy_name, "SHADOW")
        except Exception:  # noqa: BLE001 - la estrategia puede no estar aun en el registro.
            pass
        window = {
            "window_id": new_id("promwin"),
            "strategy": strategy_name,
            "version": version,
            "slot": slot or strategy_name,
            "min_sessions": self.min_sessions,
            "min_signals": self.min_signals,
            "status": "OPEN",
            "result": {},
        }
        self.store.upsert_promotion_window(window)
        return window

    # -- evaluacion --------------------------------------------------------
    def _champion_name(self, exclude: str) -> str | None:
        try:
            actives = [row for row in self.store.strategy_versions(status="ACTIVE") if row["name"] != exclude]
        except Exception:  # noqa: BLE001
            actives = []
        if actives:
            return str(actives[0]["name"])
        return "builtin_breakout" if exclude != "builtin_breakout" else None

    def _outcomes(self, strategy: str, *, shadow: bool, since_date: str | None) -> list[dict[str, Any]]:
        rows = self.store.signal_outcomes(limit=5000, since_date=since_date)
        return [
            item
            for item in rows
            if _strategy_of(item) == strategy and _is_shadow(item) == shadow
        ]

    def _decide(self, shadow_m: dict[str, Any], champ_m: dict[str, Any]) -> tuple[bool, str]:
        champion_has_baseline = (champ_m.get("signals") or 0) >= self.min_signals
        expectancy_ok = (shadow_m.get("expectancy") or 0.0) > 0 and (
            not champion_has_baseline or (shadow_m["expectancy"] > (champ_m.get("expectancy") or 0.0))
        )
        if not champion_has_baseline:
            # Sin incumbente real: basta expectancy positiva y hit rate decente.
            hit_ok = (shadow_m.get("hit_rate") or 0.0) >= 0.40
            if expectancy_ok and hit_ok:
                return True, "promovida (sin champion incumbente)"
            return False, "expectancy/hit insuficientes sin incumbente"
        hit_ok = (shadow_m.get("hit_rate") or 0.0) >= (champ_m.get("hit_rate") or 0.0) - self.hit_margin
        dd_ok = (shadow_m.get("max_dd") or 0.0) <= self.dd_factor * (champ_m.get("max_dd") or 0.0) or (champ_m.get("max_dd") or 0.0) == 0.0
        if expectancy_ok and hit_ok and dd_ok:
            return True, "supera al champion en expectancy/hit/dd"
        return False, "no supera al champion"

    def evaluate_windows(self, *, session_date: str | None = None) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        for window in self.store.promotion_windows(status="OPEN", limit=200):
            strategy = window["strategy"]
            since = str(window.get("started_at") or "")[:10] or None
            shadow_outcomes = self._outcomes(strategy, shadow=True, since_date=since)
            shadow_m = compute_strategy_metrics(shadow_outcomes)

            champion = self._champion_name(strategy)
            champ_outcomes = self._outcomes(champion, shadow=False, since_date=since) if champion else []
            champ_m = compute_strategy_metrics(champ_outcomes)

            base = {"window_id": window["window_id"], "strategy": strategy, "shadow_metrics": shadow_m, "champion": champion, "champion_metrics": champ_m}

            if shadow_m["sessions"] < self.min_sessions or shadow_m["signals"] < self.min_signals:
                if shadow_m["sessions"] >= self.max_sessions:
                    self._resolve(window, "REJECTED_SHADOW", base | {"reason": "ventana vencida sin evidencia"})
                    decisions.append({**base, "verdict": "REJECTED_SHADOW", "reason": "max_sessions"})
                else:
                    decisions.append({**base, "verdict": "EXTEND"})
                continue

            promote, reason = self._decide(shadow_m, champ_m)
            if promote:
                self._promote(strategy, champion, window, base | {"reason": reason})
                decisions.append({**base, "verdict": "PROMOTED", "reason": reason})
            else:
                self._resolve(window, "REJECTED_SHADOW", base | {"reason": reason})
                try:
                    self.store.set_strategy_status(strategy, "RETIRED")
                except Exception:  # noqa: BLE001
                    pass
                decisions.append({**base, "verdict": "REJECTED_SHADOW", "reason": reason})
        return decisions

    def _promote(self, strategy: str, champion: str | None, window: dict[str, Any], result: dict[str, Any]) -> None:
        try:
            self.store.set_strategy_status(strategy, "ACTIVE")
            if champion and champion != strategy:
                # Degradacion reversible del champion reemplazado.
                self.store.set_strategy_status(champion, "SHADOW")
        except Exception:  # noqa: BLE001
            pass
        self._resolve(window, "PROMOTED", result)

    def _resolve(self, window: dict[str, Any], status: str, result: dict[str, Any]) -> None:
        updated = {**window, "status": status, "result": result}
        self.store.upsert_promotion_window(updated)
