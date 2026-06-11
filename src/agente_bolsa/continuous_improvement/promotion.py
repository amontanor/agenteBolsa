"""Champion/challenger con promocion automatica por metricas (T1.3).

Una estrategia validada entra en SHADOW; de SHADOW pasa a ACTIVE por metricas,
sin humano (en paper). Una ventana se resuelve cuando acumula suficientes
sesiones y senales shadow madurada. Criterio de promocion: hit rate shadow >=
champion - margen, expectancy shadow > champion y max drawdown shadow <= factor x
champion. El humano conserva un freno (veto configurable), no un gate.

Nucleo stdlib para ser testeable con outcomes sinteticos.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone
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
        "winners": winners,
        "decided": len(decided),
    }


def _two_proportion_p(wins_a: int, n_a: int, wins_b: int, n_b: int) -> float:
    """p-value unilateral (z, aprox. normal) de que la tasa A supere a la B."""

    if n_a <= 0 or n_b <= 0:
        return 1.0
    p_a = wins_a / n_a
    p_b = wins_b / n_b
    p_pool = (wins_a + wins_b) / (n_a + n_b)
    se = math.sqrt(max(1e-12, p_pool * (1 - p_pool) * (1.0 / n_a + 1.0 / n_b)))
    if se == 0:
        return 1.0
    z = (p_a - p_b) / se
    from statistics import NormalDist

    return round(1.0 - NormalDist().cdf(z), 4)  # cola superior: A > B


class PromotionManager:
    def __init__(self, store: "Store", settings: "Settings") -> None:
        self.store = store
        self.settings = settings
        self.min_sessions = int(getattr(settings, "promotion_min_sessions", 10))
        self.min_signals = int(getattr(settings, "promotion_min_signals", 20))
        self.max_sessions = int(getattr(settings, "promotion_max_sessions", 25))
        self.hit_margin = float(getattr(settings, "promotion_hit_rate_margin", 0.02))
        self.dd_factor = float(getattr(settings, "promotion_max_dd_factor", 1.2))
        self.binomial_max_p = float(getattr(settings, "promotion_binomial_max_p", 0.10))
        self.max_concurrent = int(getattr(settings, "max_concurrent_promotions", 2))
        self.max_per_week = int(getattr(settings, "max_promotions_per_week", 1))

    # -- apertura ----------------------------------------------------------
    def start_shadow(self, strategy_name: str, version: str = "1", *, slot: str | None = None) -> dict[str, Any]:
        if getattr(self.settings, "system_freeze_mode", False):
            return {"status": "BLOCKED", "reason": "system_freeze"}
        try:
            updated = self.store.set_strategy_status(strategy_name, "SHADOW")
            if not updated:
                # La estrategia aun no esta en el registro (p. ej. recien construida
                # por el StrategyBuilder): darla de alta directamente en SHADOW.
                self.store.upsert_strategy_version({"name": strategy_name, "version": version, "status": "SHADOW"})
        except Exception:  # noqa: BLE001 - el registro no debe bloquear la ventana.
            pass
        # Change budget (T5.2): si ya hay demasiadas ventanas abiertas, encolar.
        open_windows = len(self.store.promotion_windows(status="OPEN", limit=500))
        status = "QUEUED" if open_windows >= self.max_concurrent else "OPEN"
        window = {
            "window_id": new_id("promwin"),
            "strategy": strategy_name,
            "version": version,
            "slot": slot or strategy_name,
            "min_sessions": self.min_sessions,
            "min_signals": self.min_signals,
            "status": status,
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
        # Significancia del hit rate challenger vs champion (T5.2).
        p_value = _two_proportion_p(
            int(shadow_m.get("winners") or 0), int(shadow_m.get("decided") or 0),
            int(champ_m.get("winners") or 0), int(champ_m.get("decided") or 0),
        )
        binomial_ok = p_value < self.binomial_max_p
        if expectancy_ok and hit_ok and dd_ok and binomial_ok:
            return True, "supera al champion en expectancy/hit/dd (significativo)"
        if not binomial_ok:
            return False, f"ventaja no significativa (p={p_value})"
        return False, "no supera al champion"

    def _promotions_this_week(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return sum(
            1
            for w in self.store.promotion_windows(status="PROMOTED", limit=200)
            if str(w.get("updated_at") or "") >= cutoff
        )

    def _activate_queued(self) -> None:
        """Promueve ventanas QUEUED a OPEN si hay capacidad concurrente (T5.2)."""

        open_n = len(self.store.promotion_windows(status="OPEN", limit=500))
        for window in self.store.promotion_windows(status="QUEUED", limit=500):
            if open_n >= self.max_concurrent:
                break
            self._resolve(window, "OPEN", window.get("result") or {})
            open_n += 1

    def evaluate_windows(self, *, session_date: str | None = None) -> list[dict[str, Any]]:
        if getattr(self.settings, "system_freeze_mode", False):
            return []
        self._activate_queued()
        promotions_left = max(0, self.max_per_week - self._promotions_this_week())
        decisions: list[dict[str, Any]] = []
        for window in self.store.promotion_windows(status="OPEN", limit=500):
            strategy = str(window["strategy"])
            started = str(window.get("started_at") or window.get("created_at") or "")[:10] or None
            elapsed_days = 0
            if started:
                try:
                    elapsed_days = (datetime.now(timezone.utc).date() - date.fromisoformat(started)).days
                except ValueError:
                    elapsed_days = 0

            shadow_matured = [s for s in self._outcomes(strategy, shadow=True, since_date=started) if _is_matured(s)]
            shadow_m = compute_strategy_metrics(shadow_matured)
            signals = int(shadow_m.get("signals") or 0)
            sessions = int(shadow_m.get("sessions") or 0)

            if sessions < int(window.get("min_sessions") or self.min_sessions) or signals < int(
                window.get("min_signals") or self.min_signals
            ):
                # Gracia de calendario: una estrategia muerta (sin señales) no
                # puede mantener la ventana abierta para siempre.
                if elapsed_days > self.max_sessions * 3:
                    result = {"reason": "ventana vencida sin evidencia suficiente", "signals": signals, "sessions": sessions, "elapsed_days": elapsed_days}
                    self._resolve(window, "REJECTED_SHADOW", result)
                    try:
                        self.store.set_strategy_status(strategy, "RETIRED")
                    except Exception:  # noqa: BLE001
                        pass
                    decisions.append({"window_id": window["window_id"], "strategy": strategy, "verdict": "REJECTED_SHADOW", **result})
                else:
                    decisions.append(
                        {
                            "window_id": window["window_id"],
                            "strategy": strategy,
                            "verdict": "EXTEND",
                            "signals": signals,
                            "sessions": sessions,
                            "elapsed_days": elapsed_days,
                        }
                    )
                continue

            champion = self._champion_name(exclude=strategy)
            champ_matured = (
                [s for s in self._outcomes(champion, shadow=False, since_date=started) if _is_matured(s)]
                if champion
                else []
            )
            champ_m = compute_strategy_metrics(champ_matured)

            ok, reason = self._decide(shadow_m, champ_m)
            result = {
                "reason": reason,
                "shadow_metrics": shadow_m,
                "champion": champion,
                "champion_metrics": champ_m,
                "elapsed_days": elapsed_days,
            }
            if ok:
                if promotions_left <= 0:
                    # Cupo semanal agotado (T5.2): la ventana queda abierta y espera turno.
                    decisions.append({"window_id": window["window_id"], "strategy": strategy, "verdict": "WAITING_WEEKLY_BUDGET", "reason": reason})
                    continue
                promotions_left -= 1
                try:
                    self.store.set_strategy_status(strategy, "ACTIVE")
                    if champion and champion != strategy:
                        # Degradacion reversible del champion reemplazado (T1.3).
                        self.store.set_strategy_status(champion, "SHADOW")
                except Exception:  # noqa: BLE001
                    pass
                self._resolve(window, "PROMOTED", result)
                decisions.append({"window_id": window["window_id"], "strategy": strategy, "verdict": "PROMOTED", **result})
            else:
                self._resolve(window, "REJECTED_SHADOW", result)
                try:
                    self.store.set_strategy_status(strategy, "RETIRED")
                except Exception:  # noqa: BLE001
                    pass
                decisions.append({"window_id": window["window_id"], "strategy": strategy, "verdict": "REJECTED_SHADOW", **result})
        return decisions

    def _resolve(self, window: dict[str, Any], status: str, result: dict[str, Any]) -> None:
        updated = dict(window)
        updated["status"] = status
        updated["result"] = result
        self.store.upsert_promotion_window(updated)
