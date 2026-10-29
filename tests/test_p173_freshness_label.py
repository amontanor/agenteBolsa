"""P-L173: la etiqueta de frescura debe coincidir con la edad mostrada."""

from __future__ import annotations

from agente_bolsa.web_app import _freshness_label


def test_recent_age_is_fresh_even_if_snapshot_says_stale() -> None:
    assert _freshness_label(3.0, "stale") == "fresh"


def test_old_age_is_stale_even_if_snapshot_says_fresh() -> None:
    assert _freshness_label(600.0, "fresh") == "stale"


def test_unknown_age_keeps_the_recorded_state() -> None:
    assert _freshness_label(None, "stale") == "stale"
    assert _freshness_label(None, "fresh") == "fresh"
