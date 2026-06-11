"""Tests de sesgo de supervivencia (T5.6)."""

from agente_bolsa.tools.hypothesis_factory import passes_survival
from agente_bolsa.tools.universe import universe_as_of


def _write_changes(path):
    path.write_text(
        "date,added,removed\n"
        "# comentario que debe ignorarse\n"
        "2024-06-01,CCC,DDD\n",
        encoding="utf-8",
    )


def test_universe_as_of_reconstructs_membership(tmp_path):
    changes = tmp_path / "sp500_changes.csv"
    _write_changes(changes)
    # Universo actual: AAA, BBB, CCC. En 2024-06-01 entro CCC y salio DDD.
    result = universe_as_of("2024-01-01", changes_path=changes, current_universe=["AAA", "BBB", "CCC"])
    assert result["survivorship_biased"] is False
    assert set(result["symbols"]) == {"AAA", "BBB", "DDD"}  # CCC fuera, DDD dentro


def test_universe_as_of_after_change_is_current(tmp_path):
    changes = tmp_path / "sp500_changes.csv"
    _write_changes(changes)
    result = universe_as_of("2025-01-01", changes_path=changes, current_universe=["AAA", "BBB", "CCC"])
    assert set(result["symbols"]) == {"AAA", "BBB", "CCC"}


def test_universe_as_of_fallback_flags_bias(tmp_path):
    missing = tmp_path / "nope.csv"
    result = universe_as_of("2024-01-01", changes_path=missing, current_universe=["AAA", "BBB"])
    assert result["survivorship_biased"] is True
    assert set(result["symbols"]) == {"AAA", "BBB"}


def test_haircut_raises_thresholds_when_biased():
    metrics = {"sharpe": 0.95, "trades": 40, "profit_factor": 1.4, "max_drawdown": 0.1, "expectancy_return": 0.02}
    baseline = {"expectancy_return": 0.01}
    ok_unbiased, _ = passes_survival(metrics, baseline, subperiod_improvements=[0.1, 0.1, 0.1], n_trials=1)
    ok_biased, reasons = passes_survival(
        metrics, baseline, subperiod_improvements=[0.1, 0.1, 0.1], n_trials=1, survivorship_biased=True, haircut=0.25
    )
    assert ok_unbiased  # 0.95 > 0.8 y pf 1.4 > 1.3
    assert not ok_biased  # con haircut: sharpe<=1.0 y pf<=1.625
