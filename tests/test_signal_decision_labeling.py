"""Regresion: el etiquetado de decisiones no debe ocultar rechazos de entry-quality.

Bug detectado el 20-jun-2026: senales rechazadas por entry-quality quedaban
etiquetadas como `approved_buy_micro` cuando la recomendacion arrastraba
`micro_experiment=True` desde el soft-override de backtest. El bloqueo de
entry-quality debe prevalecer salvo que la propia entry-quality conceda micro.
"""
from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa.tools.signal_learning import update_signal_decisions


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def update_signal_decision(self, *, source_run_id, symbol, decision, gate):  # noqa: ANN001
        self.calls.append({"symbol": symbol, "decision": decision, "gate": gate})


def _run(rec, entry_quality_gate, backtest_gate):
    store = _FakeStore()
    n = update_signal_decisions(
        store,
        source_run_id="run-test",
        recommendations=[rec],
        entry_quality_gate=entry_quality_gate,
        backtest_gate=backtest_gate,
        settings=SimpleNamespace(),
    )
    assert n == 1
    return store.calls[0]["decision"]


def test_entry_quality_rejection_not_mislabeled_as_micro():
    # La recomendacion arrastra micro_experiment del soft-override de backtest,
    # pero entry-quality la RECHAZA y no concede micro propio -> bloqueo debe ganar.
    rec = SimpleNamespace(symbol="APH", action="buy", micro_experiment=True,
                          confidence=0.6, reason="x")
    eqg = [{"symbol": "APH", "approved": False, "reason": "calidad insuficiente",
            "checks": {"entry_score_v2": {"micro_experiment": False}}}]
    assert _run(rec, eqg, []) == "blocked_entry_quality"


def test_entry_quality_own_micro_still_allows_micro_label():
    # Si entry-quality SI concede micro, se mantiene el camino micro (no se bloquea).
    rec = SimpleNamespace(symbol="ZZZ", action="buy", micro_experiment=False,
                          confidence=0.6, reason="x")
    eqg = [{"symbol": "ZZZ", "approved": False, "reason": "micro permitido",
            "checks": {"entry_score_v2": {"micro_experiment": True}}}]
    assert _run(rec, eqg, []) == "approved_buy_micro"
