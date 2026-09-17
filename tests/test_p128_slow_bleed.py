"""P-L128: la sangria lenta a 10d tambien retira (solo degrada a shadow)."""
from __future__ import annotations

from datetime import date, timedelta

from agente_bolsa.continuous_improvement.promotion_readiness import _candidate_decision


def _rows(n, ret10, ret5, start="2026-06-01"):
    base = date.fromisoformat(start)
    rows = []
    for i in range(n):
        d = (base + timedelta(days=i)).isoformat()
        rows.append({
            "signal_date": d,
            "outcome": {"return_10d": ret10, "return_5d": ret5},
            "features": {},
        })
    return rows


def _bench(rows, spy10=0.005, spy5=0.002):
    bench = {}
    for r in rows:
        bench[(r["signal_date"], 10)] = spy10
        bench[(r["signal_date"], 5)] = spy5
    return bench


def test_slow_bleed_10d_retires_actionable_setup():
    rows = _rows(25, -0.03, -0.004)
    out = _candidate_decision(kind="setup", key="confirmed_pattern", rows=rows, benchmark=_bench(rows))
    assert out["slow_bleed_10d"] is True
    assert out["verdict"] == "RETIRE_CANDIDATE"
    assert out["action"] == "propose_active_to_shadow"


def test_healthy_setup_stays_hold():
    rows = _rows(25, 0.02, 0.01)
    out = _candidate_decision(kind="setup", key="confirmed_pattern", rows=rows, benchmark=_bench(rows))
    assert out["slow_bleed_10d"] is False
    assert out["verdict"] == "HOLD"


def test_non_actionable_key_never_slow_bleeds():
    rows = _rows(25, -0.05, -0.004)
    out = _candidate_decision(kind="setup", key="invented_setup", rows=rows, benchmark=_bench(rows))
    assert out["slow_bleed_10d"] is False
    assert out["verdict"] == "HOLD"


def test_small_sample_never_slow_bleeds():
    rows = _rows(10, -0.05, -0.004)
    out = _candidate_decision(kind="setup", key="confirmed_pattern", rows=rows, benchmark=_bench(rows))
    assert out["slow_bleed_10d"] is False
    assert out["verdict"] == "HOLD"
