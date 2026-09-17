from __future__ import annotations

from pathlib import Path

from agente_bolsa.storage import Store
from agente_bolsa.tools.learning_mode import LEARNING_EXPERIMENT_SOURCE
from agente_bolsa.tools.llm_uplift import build_llm_uplift_report


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state" / "test.sqlite3", tmp_path / "logs" / "agents")
    store.ensure_schema()
    return store


def _seed(store: Store, tag: str, *, llm: bool | None, returns: list[float], embedded: bool) -> None:
    for index, value in enumerate(returns):
        signal_id = f"sig-{tag}-{index}"
        symbol = f"S{tag}{index}"
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id="run-1",
            source="test",
            symbol=symbol,
            signal_date="2026-09-01",
            decision="approved_buy",
            features={},
            gate={},
            outcome={"return_5d": value, "matured_horizons": {"5d": True}},
        )
        features: dict = {}
        if embedded and llm is not None:
            features = {"decision_context_snapshot": {"llm_selected": llm, "content_hash": "h"}}
        elif llm is not None:
            store.attach_decision_context_snapshot(
                signal_id, {"llm_selected": llm, "content_hash": f"h-{tag}-{index}"}
            )
        store.upsert_learning_observation(
            {
                "observation_id": f"2026-09-01:{symbol}:exec",
                "signal_date": "2026-09-01",
                "symbol": symbol,
                "source_family": LEARNING_EXPERIMENT_SOURCE,
                "source_run_ids": ["cycle-a"],
                "best_signal_id": signal_id,
                "best_score": 15.0,
                "decision": "executed_buy",
                "executed_buy": True,
                "features": features,
                "gate": {},
                "outcome": {"return_5d": value, "matured_horizons": {"5d": True}},
                "execution": {},
            }
        )


def _report(store: Store, tmp_path: Path) -> dict:
    return build_llm_uplift_report(
        store, tmp_path / "reports", "uplift",
        since_date="2026-09-01", end_date="2026-09-30",
    )


def test_sufficient_sample_measures_uplift_from_causal_flag(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "llm", llm=True, returns=[0.02] * 20, embedded=False)
    _seed(store, "det", llm=False, returns=[0.01] * 20, embedded=False)

    report = _report(store, tmp_path)

    assert report["verdict"] == "sufficient_sample"
    assert report["llm"]["n"] == 20
    assert report["deterministic"]["n"] == 20
    assert report["llm"]["expectancy_net"] == 0.019
    assert report["deterministic"]["expectancy_net"] == 0.009
    assert report["uplift_net"] == 0.01
    assert report["snapshot_coverage"] == 1.0


def test_embedded_snapshot_needs_no_join(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "llm", llm=True, returns=[0.02] * 20, embedded=True)
    _seed(store, "det", llm=False, returns=[0.01] * 20, embedded=True)

    report = _report(store, tmp_path)

    assert report["verdict"] == "sufficient_sample"
    assert report["uplift_net"] == 0.01


def test_small_sample_is_insufficient(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed(store, "llm", llm=True, returns=[0.02] * 3, embedded=False)
    _seed(store, "det", llm=False, returns=[0.01] * 2, embedded=False)

    report = _report(store, tmp_path)

    assert report["verdict"] == "insufficient_sample"
    assert any("mature_executed" in reason for reason in report["verdict_reasons"])


def test_source_text_is_never_used_as_proxy(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(35):
        signal_id = f"sig-proxy-{index}"
        store.save_signal_outcome(
            signal_id=signal_id,
            source_run_id="run-1",
            source="test",
            symbol=f"P{index}",
            signal_date="2026-09-01",
            decision="approved_buy",
            features={"recommendation_source": "llm"},
            gate={},
            outcome={"return_5d": 0.02, "matured_horizons": {"5d": True}},
        )
        store.upsert_learning_observation(
            {
                "observation_id": f"2026-09-01:P{index}:exec",
                "signal_date": "2026-09-01",
                "symbol": f"P{index}",
                "source_family": LEARNING_EXPERIMENT_SOURCE,
                "source_run_ids": ["cycle-a"],
                "best_signal_id": signal_id,
                "best_score": 15.0,
                "decision": "executed_buy",
                "executed_buy": True,
                "features": {"recommendation_source": "llm"},
                "gate": {},
                "outcome": {"return_5d": 0.02, "matured_horizons": {"5d": True}},
                "execution": {},
            }
        )

    report = _report(store, tmp_path)

    assert report["llm"]["n"] == 0
    assert report["unattached"] == 35
    assert report["verdict"] == "insufficient_sample"
