from __future__ import annotations

from agente_bolsa.web_app import _spy_alpha_summary


def _row(session: str, system_pct, spy_pct, *, status="final", comparison="comparable"):
    return {
        "session_date": session,
        "system_pct": system_pct,
        "spy_pct": spy_pct,
        "status": status,
        "comparison_status": comparison,
    }


def test_empty_rows_have_no_alpha() -> None:
    summary = _spy_alpha_summary([])

    assert summary == {"n": 0, "system_cum": None, "spy_cum": None, "alpha": None}


def test_only_final_comparable_rows_compound() -> None:
    rows = [
        _row("2026-09-14", 0.01, 0.005),
        _row("2026-09-15", 0.02, 0.01),
        _row("2026-09-16", 0.05, 0.05, status="in_progress"),
        _row("2026-09-13", 0.10, 0.10, comparison="unavailable"),
    ]
    summary = _spy_alpha_summary(rows)

    assert summary["n"] == 2
    assert summary["system_cum"] == round(1.01 * 1.02 - 1.0, 6)
    assert summary["spy_cum"] == round(1.005 * 1.01 - 1.0, 6)
    assert summary["alpha"] == round(summary["system_cum"] - summary["spy_cum"], 6)


def test_single_session_alpha() -> None:
    summary = _spy_alpha_summary([_row("2026-09-15", 0.02, 0.01)])

    assert summary["n"] == 1
    assert summary["alpha"] == 0.01


def test_leaderboard_block_renders_without_gain_headless() -> None:
    from streamlit.testing.v1 import AppTest

    def _script() -> None:
        from types import SimpleNamespace

        from agente_bolsa import web_app as _web_app

        store = SimpleNamespace(latest_events=lambda limit: [], record_agent_event=lambda event: None)
        _web_app._render_leaderboard_controls(store, None)

    app = AppTest.from_function(_script)
    app.run()

    assert not app.exception
    assert any("Leaderboard" in str(item.value) for item in app.markdown)
    assert app.button(key="leaderboard_submit_gain").disabled is True


def test_leaderboard_block_enables_submit_with_gain_headless() -> None:
    from streamlit.testing.v1 import AppTest

    def _script() -> None:
        from types import SimpleNamespace

        from agente_bolsa import web_app as _web_app

        store = SimpleNamespace(latest_events=lambda limit: [], record_agent_event=lambda event: None)
        _web_app._render_leaderboard_controls(store, 0.0123)

    app = AppTest.from_function(_script)
    app.run()

    assert not app.exception
    assert app.button(key="leaderboard_submit_gain").disabled is False
