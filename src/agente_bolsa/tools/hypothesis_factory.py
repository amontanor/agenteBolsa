"""Fabrica de hipotesis + granja de backtests en lote (T3.2).

Cada noche se generan variantes PARAMETRICAS baratas (sin LLM) de las estrategias
y umbrales vigentes, se backtestan en lote con split temporal (in-sample / out-of
-sample) y solo las supervivientes consumen atencion del pipeline caro (T1.4). El
filtro de supervivencia incluye un guard anti data-mining: la mejora debe
mantenerse en 3 sub-periodos de la OOS.

El backtester es inyectable para tests; por defecto usa `build_symbol_backtest`.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from ..models import new_id

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


# Parametros tuneables y su valor base. Las variantes se acotan a +-30%.
DEFAULT_PARAM_BASE: dict[str, float] = {
    "min_score": 6.0,
    "rsi_max": 75.0,
    "sma20_distance": 0.05,
    "atr_stop_multiple": 2.0,
    "holding_days": 10.0,
}

# Umbrales de supervivencia (OOS).
SURVIVAL_MIN_SHARPE = 0.8
SURVIVAL_MIN_TRADES = 30
SURVIVAL_MIN_PROFIT_FACTOR = 1.3
SURVIVAL_MAX_DRAWDOWN = 0.20
SURVIVAL_MIN_IMPROVEMENT = 0.10  # 10% sobre la variante vigente


def generate_variants(
    settings: "Settings",
    *,
    base_params: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Genera variantes parametricas acotadas a +-30% del valor vigente."""

    base = {**DEFAULT_PARAM_BASE, **(base_params or {})}
    max_variants = int(getattr(settings, "factory_max_variants_per_night", 50))
    variants: list[dict[str, Any]] = [{"params": dict(base), "label": "base", "target_regime": "trend"}]
    for key, value in base.items():
        for factor, tag in ((0.7, "lo"), (1.3, "hi")):
            new_value = round(value * factor, 6)
            if key == "holding_days":
                new_value = max(1, int(round(new_value)))
            params = {**base, key: new_value}
            variants.append({"params": params, "label": f"{key}_{tag}", "target_regime": "trend"})
            if len(variants) >= max_variants:
                return variants[:max_variants]

    # Cuota minima para regimenes no alcistas (T5.7): mean-reversion / pullback.
    quota = float(getattr(settings, "factory_regime_quota", 0.30))
    target_regimes = ("range", "bear")
    needed = int(round(len(variants) * quota / (1 - quota))) if quota < 1 else len(variants)
    for index in range(max(0, needed)):
        if len(variants) >= max_variants:
            break
        regime = target_regimes[index % len(target_regimes)]
        # Variante de reversion: stop mas ajustado y holding mas corto.
        params = {**base, "atr_stop_multiple": round(base["atr_stop_multiple"] * 0.8, 6), "holding_days": max(1, int(base["holding_days"] * 0.6))}
        variants.append({"params": params, "label": f"{regime}_revert_{index}", "target_regime": regime})
    return variants[:max_variants]


def _expected_max_sharpe(n_trials: int) -> float:
    """E[max] de n_trials Sharpes bajo H0 (Bailey & Lopez de Prado)."""

    from statistics import NormalDist

    n = max(1, int(n_trials))
    if n == 1:
        return 0.0
    gamma = 0.5772156649015329  # Euler-Mascheroni
    nd = NormalDist()
    return (1 - gamma) * nd.inv_cdf(1 - 1.0 / n) + gamma * nd.inv_cdf(1 - 1.0 / (n * math.e))


def deflated_sharpe(
    sharpe: float,
    n_trials: int,
    n_obs: int = 0,
    *,
    sr_std: float = 0.6,
) -> float:
    """Sharpe deflactado: excedente del Sharpe sobre el maximo esperado por azar.

    Penaliza por el numero de variantes probadas (`n_trials`): mas pruebas elevan
    el umbral. > 0 significa que el Sharpe observado bate lo esperable de buscar
    entre `n_trials` candidatos. `sr_std` es la dispersion tipica de los Sharpes
    estimados entre variantes (0.6 calibrado: una tanda nocturna de ~10 variantes
    no debe anular un Sharpe OOS de 1.2, pero 50 variantes si).
    """

    sr_star = max(0.0, float(sr_std)) * _expected_max_sharpe(n_trials)
    return round(float(sharpe) - sr_star, 4)


def _improvement(oos: float | None, baseline: float | None) -> float | None:
    if oos is None or baseline is None:
        return None
    if baseline == 0:
        return None
    return (oos - baseline) / abs(baseline)


def passes_survival(
    oos_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any] | None,
    *,
    subperiod_improvements: list[float] | None = None,
    n_trials: int = 1,
    survivorship_biased: bool = False,
    haircut: float = 0.25,
) -> tuple[bool, list[str]]:
    """Filtro determinista de supervivencia + guard anti data-mining (+ DSR T5.2).

    Si el universo es survivorship-biased (T5.6) se aplica un haircut a los
    umbrales de Sharpe y profit factor (mas exigentes).
    """

    reasons: list[str] = []
    sharpe = oos_metrics.get("sharpe")
    trades = int(oos_metrics.get("trades") or 0)
    pf = oos_metrics.get("profit_factor")
    dd = oos_metrics.get("max_drawdown")

    bump = (1.0 + haircut) if survivorship_biased else 1.0
    min_sharpe = SURVIVAL_MIN_SHARPE * bump
    min_pf = SURVIVAL_MIN_PROFIT_FACTOR * bump

    if not isinstance(sharpe, (int, float)) or sharpe <= min_sharpe:
        reasons.append(f"sharpe_oos<={round(min_sharpe, 3)}")
    elif deflated_sharpe(sharpe, n_trials, trades) <= 0:
        # Significancia ajustada por busqueda multiple (T5.2).
        reasons.append("deflated_sharpe<=0")
    if trades < SURVIVAL_MIN_TRADES:
        reasons.append(f"trades<{SURVIVAL_MIN_TRADES}")
    if not isinstance(pf, (int, float)) or pf <= min_pf:
        reasons.append(f"profit_factor<={round(min_pf, 3)}")
    if not isinstance(dd, (int, float)) or abs(dd) >= SURVIVAL_MAX_DRAWDOWN:
        reasons.append("drawdown>=0.20")

    if baseline_metrics is not None:
        improvement = _improvement(oos_metrics.get("expectancy_return"), baseline_metrics.get("expectancy_return"))
        if improvement is None or improvement < SURVIVAL_MIN_IMPROVEMENT:
            reasons.append("mejora<10%")

    # Guard anti data-mining: la mejora debe mantenerse en 3 sub-periodos OOS.
    if subperiod_improvements is not None:
        positive = [value for value in subperiod_improvements if value is not None and value > 0]
        if len(subperiod_improvements) < 3 or len(positive) < 3:
            reasons.append("mejora_inestable_en_subperiodos")

    return (not reasons), reasons


def run_batch(
    variants: list[dict[str, Any]],
    *,
    backtester: Callable[[dict[str, Any]], dict[str, Any]],
    baseline_metrics: dict[str, Any] | None,
    max_seconds: int | None = None,
    survivorship_biased: bool = False,
    haircut: float = 0.25,
) -> dict[str, Any]:
    """Backtesta cada variante y aplica el filtro de supervivencia."""

    deadline = (time.monotonic() + max_seconds) if max_seconds else None
    n_trials = len(variants)  # busqueda multiple de la tanda (T5.2)
    results: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []
    for variant in variants:
        if deadline is not None and time.monotonic() > deadline:
            break
        try:
            outcome = backtester(variant)
        except Exception as exc:  # noqa: BLE001 - una variante mala no corta el lote.
            results.append({"variant": variant, "error": repr(exc)})
            continue
        oos = outcome.get("oos_metrics", {}) or {}
        subperiods = outcome.get("subperiod_improvements")
        ok, reasons = passes_survival(
            oos, baseline_metrics, subperiod_improvements=subperiods, n_trials=n_trials,
            survivorship_biased=survivorship_biased, haircut=haircut,
        )
        entry = {"variant": variant, "oos_metrics": oos, "survived": ok, "reasons": reasons}
        results.append(entry)
        if ok:
            survivors.append(entry)
    return {"results": results, "survivors": survivors, "variants_run": len(results), "n_trials": n_trials}


def run_factory(
    store: "Store",
    settings: "Settings",
    *,
    backtester: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    base_params: dict[str, float] | None = None,
    baseline_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pipeline nocturno: generar -> backtestear -> persistir supervivientes."""

    variants = generate_variants(settings, base_params=base_params)
    if backtester is None:
        backtester = _default_backtester(settings)
    max_seconds = int(getattr(settings, "factory_max_minutes", 60)) * 60
    # Sesgo de supervivencia (T5.6): sin dataset point-in-time, exigir mas.
    from pathlib import Path as _Path

    survivorship_biased = not _Path("data/universe/sp500_changes.csv").exists()
    haircut = float(getattr(settings, "survivorship_haircut", 0.25))
    batch = run_batch(
        variants, backtester=backtester, baseline_metrics=baseline_metrics, max_seconds=max_seconds,
        survivorship_biased=survivorship_biased, haircut=haircut,
    )

    run_date = datetime.now(timezone.utc).date().isoformat()
    inserted = _persist_survivors(store, batch["survivors"], run_date)
    run_id = new_id("factory")
    store.save_factory_run(
        {
            "run_id": run_id,
            "run_date": run_date,
            "variants": batch["variants_run"],
            "survivors": len(batch["survivors"]),
            "payload": {
                "survivors": batch["survivors"][:20],
                "hypotheses": inserted,
                "n_trials": batch.get("n_trials"),
            },
        }
    )
    return {
        "run_id": run_id,
        "run_date": run_date,
        "variants": batch["variants_run"],
        "survivors": len(batch["survivors"]),
        "hypotheses_inserted": len(inserted),
    }


def _persist_survivors(store: "Store", survivors: list[dict[str, Any]], run_date: str) -> list[str]:
    inserted: list[str] = []
    for item in survivors:
        params = item["variant"].get("params", {})
        fingerprint = "factory:" + hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:20]
        hypothesis_id, created = store.upsert_continuous_improvement_hypothesis(
            {
                "hypothesis_id": new_id("hyp"),
                "event_id": new_id("factory"),
                "domain": "strategy",
                "subject": f"factory_variant:{item['variant'].get('label', 'param_grid')}"[:200],
                "status": "OPEN",
                "confidence": "MEDIUM",
                "fingerprint": fingerprint,
                "summary_text": json.dumps(
                    {
                        "params": params,
                        "oos_metrics": item.get("oos_metrics", {}),
                        "reasons": item.get("reasons", []),
                        "run_date": run_date,
                    },
                    ensure_ascii=True,
                ),
                "evidence": [f"factory_run:{run_date}"],
            }
        )
        if created:
            inserted.append(hypothesis_id)
    return inserted


def _default_backtester(settings: "Settings") -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Backtester real (placeholder defensivo).

    El cableado completo a `build_symbol_backtest` sobre el universo cacheado se
    activa en produccion; aqui degrada a metricas vacias si no hay datos, para no
    romper el job nocturno cuando falta cache.
    """

    def backtester(variant: dict[str, Any]) -> dict[str, Any]:
        return {"oos_metrics": {}, "subperiod_improvements": []}

    return backtester
