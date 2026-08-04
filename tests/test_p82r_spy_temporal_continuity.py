from datetime import datetime, timezone

import pytest

from agente_bolsa import web_app
from agente_bolsa.tools.opening_performance import build_open_to_open_rows


UTC = timezone.utc


def _opening_row(start: str, end: str, system: float, spy: float) -> dict:
    return {
        "session_date": start,
        "end_session_date": end,
        "status": "final",
        "system_pct": system,
        "spy_pct": spy,
        "system_start_at": f"{start}T13:30:00+00:00",
        "system_end_at": f"{end}T13:30:00+00:00",
        "spy_start_at": f"{start}T13:30:00+00:00",
        "spy_end_at": f"{end}T13:30:00+00:00",
    }


def _line_dataset_lengths(chart) -> list[int]:
    spec = chart.to_dict()
    datasets = spec.get("datasets") or {}
    return [
        len(datasets[layer["data"]["name"]])
        for layer in spec.get("layer", [])
        if layer.get("mark", {}).get("type") == "line"
    ]


def test_chart_does_not_connect_final_rows_across_omitted_interval():
    rows = [
        _opening_row("2026-07-24", "2026-07-25", 0.01, 0.02),
        _opening_row("2026-07-31", "2026-08-03", 0.03, 0.01),
    ]

    chart = web_app._daily_vs_spy_chart(rows)

    assert _line_dataset_lengths(chart) == [1, 1]


def test_chart_keeps_contiguous_final_rows_in_one_segment():
    rows = [
        _opening_row("2026-07-24", "2026-07-25", 0.01, 0.02),
        _opening_row("2026-07-25", "2026-07-28", 0.03, 0.01),
    ]

    chart = web_app._daily_vs_spy_chart(rows)

    assert _line_dataset_lengths(chart) == [2]


def _current_fixture(*, spy_at: str, system_at: str) -> tuple[list[dict], dict]:
    account_at = "2026-08-03T13:30:00+00:00"
    account = [{"session_date": "2026-08-03", "equity": 100.0, "observed_at": account_at}]
    spy = {
        "opens": [
            {
                "session_date": "2026-08-03",
                "price": 100.0,
                "price_basis": "adjusted_ohlc",
                "observed_at": account_at,
            }
        ],
        "current": {
            "price": 101.0,
            "price_basis": "adjusted_ohlc",
            "observed_at": spy_at,
            "source": "fixture",
        },
    }
    return account, spy


def test_current_spy_requires_explicitly_aligned_as_of():
    account, spy = _current_fixture(
        spy_at="2026-08-03T20:12:55+00:00",
        system_at="2026-08-04T08:11:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime.fromisoformat("2026-08-04T08:11:00+00:00"),
    )

    current = rows[-1]
    assert current["status"] == "in_progress"
    assert current["comparison_status"] == "unavailable"
    assert current["comparison_reason"] == "current_observation_not_aligned"
    assert current["spy_pct"] is None
    assert current["system_pct"] == pytest.approx(0.02)


def test_current_spy_exact_as_of_is_comparable():
    account, spy = _current_fixture(
        spy_at="2026-08-04T08:11:00+00:00",
        system_at="2026-08-04T08:11:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime.fromisoformat("2026-08-04T08:11:00+00:00"),
    )

    current = rows[-1]
    assert current["comparison_status"] == "comparable"
    assert current["comparison_reason"] is None
    assert current["spy_pct"] == pytest.approx(0.01)


def test_future_spy_as_of_is_not_comparable():
    account, spy = _current_fixture(
        spy_at="2026-08-04T08:12:00+00:00",
        system_at="2026-08-04T08:11:00+00:00",
    )

    rows = build_open_to_open_rows(
        account,
        spy,
        current_equity=102.0,
        current_equity_at=datetime.fromisoformat("2026-08-04T08:11:00+00:00"),
    )

    assert rows[-1]["comparison_reason"] == "current_observation_future"


def test_unavailable_current_observation_is_excluded_from_winner_counts():
    rows = [
        {
            **_opening_row("2026-08-01", "2026-08-03", 0.01, 0.02),
            "comparison_status": "comparable",
        },
        {
            "session_date": "2026-08-03",
            "end_session_date": None,
            "status": "in_progress",
            "system_pct": 0.50,
            "spy_pct": None,
            "comparison_status": "unavailable",
            "comparison_reason": "current_observation_not_aligned",
        },
    ]

    summary = web_app._daily_vs_spy_summary(rows)

    assert summary["visible_total"] == 2
    assert summary["final"] == 1
    assert summary["in_progress"] == 1
    assert summary["system_wins"] == 0
    assert summary["spy_wins"] == 1
    assert summary["ties"] == 0
