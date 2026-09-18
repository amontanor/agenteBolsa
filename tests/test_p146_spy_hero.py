"""P-L146: one-glance daily verdict reuses canonical denominators."""

from agente_bolsa.web_app import _spy_hero_verdict


def _live_context(system_pct, spy_pct, comparison_status="comparable", reason=None):
    return {
        "account_current": {
            "system_delta": 3.54,
            "system_pct": system_pct,
            "system_start_at": "2026-09-17T15:30:00+00:00",
            "system_end_at": "2026-09-18T10:00:00+00:00",
        },
        "current": {
            "instrument_label": "SPY (ETF S&P 500)",
            "benchmark_symbol": "SPY",
            "comparison_status": comparison_status,
            "spy_pct": spy_pct,
            "comparison_reason": reason,
            "spy_end_at": "2026-09-18T09:55:00+00:00",
        },
        "rows": [],
    }


def test_live_session_system_wins():
    verdict = _spy_hero_verdict(_live_context(0.0001, -0.0079))

    assert verdict["state"] == "comparable"
    assert verdict["headline"] == "Hoy ganas a SPY"
    assert verdict["tone"] == "good"
    assert verdict["system_pct"] == 0.0001
    assert verdict["spy_pct"] == -0.0079


def test_live_session_spy_wins():
    verdict = _spy_hero_verdict(_live_context(-0.0019, 0.0054))

    assert verdict["state"] == "comparable"
    assert verdict["headline"] == "Hoy SPY te gana"
    assert verdict["tone"] == "bad"


def test_live_session_tie_within_epsilon():
    verdict = _spy_hero_verdict(_live_context(0.001, 0.00102))

    assert verdict["headline"] == "Empate hoy con SPY"
    assert verdict["tone"] == "neutral"


def test_live_session_without_spy_keeps_exact_reason():
    verdict = _spy_hero_verdict(
        _live_context(0.0001, None, comparison_status="unavailable", reason="spy_open_conflict")
    )

    assert verdict["state"] == "unavailable"
    assert verdict["headline"] == "Hoy sin dato SPY"
    assert verdict["reason"] == "spy_open_conflict"
    assert verdict["spy_pct"] is None
    assert verdict["system_pct"] == 0.0001


def test_falls_back_to_last_final_session():
    context = {
        "account_current": {},
        "current": {},
        "rows": [
            {
                "session_date": "2026-09-08",
                "status": "final",
                "comparison_status": "comparable",
                "system_pct": -0.0007,
                "system_delta": -51.95,
                "spy_pct": -0.0065,
                "spy_end_at": "2026-09-09T13:30:00+00:00",
            }
        ],
    }

    verdict = _spy_hero_verdict(context)

    assert verdict["state"] == "comparable"
    assert verdict["headline"] == "Ganaste a SPY"
    assert verdict["session_label"] == "Sesión 2026-09-08"


def test_empty_without_sessions_is_honest():
    verdict = _spy_hero_verdict({"rows": []})

    assert verdict["state"] == "empty"
    assert verdict["spy_pct"] is None
    assert verdict["reason"] == "no_final_sessions"
