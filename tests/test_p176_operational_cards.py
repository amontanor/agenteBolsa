"""P-L176: las tarjetas operativas nombran el informe ausente y su comando."""

from __future__ import annotations

from agente_bolsa.web_app import _operational_report_detail


def test_missing_report_names_responsible_command():
    detail = _operational_report_detail(
        False, "n/d", True, "sin proveedor", command="market-data-quality"
    )
    assert detail == "sin informe · ejecuta market-data-quality"
    assert "rancio" not in detail


def test_available_fresh_report_keeps_age_and_detail():
    detail = _operational_report_detail(
        True, "hace 2 min", False, "yfinance", command="live-readiness"
    )
    assert detail == "hace 2 min · yfinance"


def test_available_stale_report_marks_stale():
    detail = _operational_report_detail(
        True, "hace 9 d", True, "18 blocks", command="weekly-review"
    )
    assert detail == "hace 9 d · rancio · 18 blocks"


def test_available_report_without_age_uses_detail_only():
    detail = _operational_report_detail(
        True, "", False, "SPY", command="weekly-review"
    )
    assert detail == "SPY"


def test_each_card_uses_its_own_command():
    for command in ("market-data-quality", "live-readiness", "weekly-review"):
        detail = _operational_report_detail(False, "", True, "", command=command)
        assert command in detail
