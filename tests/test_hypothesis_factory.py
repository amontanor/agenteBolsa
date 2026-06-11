"""Tests de la fabrica de hipotesis y backtests en lote (T3.2)."""

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.hypothesis_factory import (
    DEFAULT_PARAM_BASE,
    deflated_sharpe,
    generate_variants,
    passes_survival,
    run_batch,
    run_factory,
)


def _setup(tmp_path, **overrides):
    # Cuota de regimen a 0 por defecto: estos tests cuentan solo las variantes
    # parametricas base (la cuota de T5.7 se prueba en test_cash_regime).
    base = {"FACTORY_REGIME_QUOTA": 0.0}
    base.update(overrides)
    settings = Settings(DATA_DIR=tmp_path, **base)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


_GOOD_OOS = {"sharpe": 1.2, "trades": 40, "profit_factor": 1.5, "max_drawdown": 0.12, "expectancy_return": 0.02}
_BASELINE = {"expectancy_return": 0.01}


def test_generate_variants_are_bounded(tmp_path):
    settings, _ = _setup(tmp_path)
    variants = generate_variants(settings)
    assert len(variants) == 11  # base + 2 por cada uno de los 5 parametros
    for variant in variants:
        for key, value in variant["params"].items():
            if key == "holding_days":
                continue
            base = DEFAULT_PARAM_BASE[key]
            assert base * 0.69 <= value <= base * 1.31


def test_generate_variants_respects_cap(tmp_path):
    settings, _ = _setup(tmp_path, FACTORY_MAX_VARIANTS_PER_NIGHT=4)
    assert len(generate_variants(settings)) == 4


def test_survival_filter_accepts_strong_variant():
    ok, reasons = passes_survival(_GOOD_OOS, _BASELINE, subperiod_improvements=[0.1, 0.2, 0.05])
    assert ok
    assert reasons == []


def test_survival_filter_rejects_few_trades():
    ok, reasons = passes_survival({**_GOOD_OOS, "trades": 5}, _BASELINE, subperiod_improvements=[0.1, 0.2, 0.05])
    assert not ok
    assert any("trades" in r for r in reasons)


def test_survival_guard_rejects_unstable_subperiods():
    ok, reasons = passes_survival(_GOOD_OOS, _BASELINE, subperiod_improvements=[0.1, -0.2, -0.05])
    assert not ok
    assert "mejora_inestable_en_subperiodos" in reasons


def test_run_batch_collects_survivors(tmp_path):
    settings, _ = _setup(tmp_path)
    variants = generate_variants(settings)

    def backtester(variant):
        if variant["label"].endswith("_hi"):
            return {"oos_metrics": _GOOD_OOS, "subperiod_improvements": [0.1, 0.2, 0.05]}
        return {"oos_metrics": {"sharpe": 0.3, "trades": 5}, "subperiod_improvements": []}

    batch = run_batch(variants, backtester=backtester, baseline_metrics=_BASELINE)
    assert batch["variants_run"] == 11
    assert len(batch["survivors"]) == 5


def test_deflated_sharpe_penalizes_many_trials():
    assert deflated_sharpe(1.2, 1) == 1.2
    assert deflated_sharpe(1.2, 50) < 0  # 50 variantes elevan el umbral
    assert deflated_sharpe(3.0, 50) > 0


def test_survival_requires_positive_deflated_sharpe():
    metrics = {"sharpe": 1.2, "trades": 40, "profit_factor": 1.5, "max_drawdown": 0.1, "expectancy_return": 0.02}
    ok_one, _ = passes_survival(metrics, _BASELINE, subperiod_improvements=[0.1, 0.1, 0.1], n_trials=1)
    ok_many, reasons = passes_survival(metrics, _BASELINE, subperiod_improvements=[0.1, 0.1, 0.1], n_trials=50)
    assert ok_one
    assert not ok_many
    assert "deflated_sharpe<=0" in reasons


def test_run_factory_persists_survivors_as_hypotheses(tmp_path):
    settings, store = _setup(tmp_path)

    def backtester(variant):
        if variant["label"] == "base":
            return {"oos_metrics": _GOOD_OOS, "subperiod_improvements": [0.1, 0.2, 0.05]}
        return {"oos_metrics": {"sharpe": 0.1, "trades": 1}, "subperiod_improvements": []}

    result = run_factory(store, settings, backtester=backtester, baseline_metrics=_BASELINE)
    assert result["survivors"] == 1
    assert result["hypotheses_inserted"] == 1
    runs = store.factory_runs()
    assert len(runs) == 1
    assert runs[0]["survivors"] == 1
