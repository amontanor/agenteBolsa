import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from agente_bolsa.tools.adaptive_tuning import (
    active_adaptive_overrides,
    adaptive_config_path,
    adaptive_governance_status,
)


def _settings(tmp_path, *, allow=True):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        state_dir=state_dir,
        allow_auto_apply_improvements=allow,
        market_calendar="XNYS",
        local_timezone="Europe/Madrid",
    )


def _write_parameters(settings, parameters):
    adaptive_config_path(settings).write_text(
        json.dumps({"version": 1, "parameters": parameters}),
        encoding="utf-8",
    )


def _canonical_item(*, proposed=2, session_date="2026-07-13", **extra):
    item = {
        "status": "active",
        "proposed": proposed,
        "requested_auto_apply": True,
        "authorized_auto_apply": True,
        "expires_after_sessions": 3,
        "evidence": {"session_date": session_date, "source": "authorized_test"},
    }
    item.update(extra)
    return item


def test_legacy_active_override_cannot_change_settings_when_global_false(tmp_path):
    settings = _settings(tmp_path, allow=False)
    _write_parameters(
        settings,
        {"MAX_ORDERS_PER_CYCLE": {"status": "active", "proposed": 2, "auto_apply": True}},
    )

    assert active_adaptive_overrides(settings) == {}


@pytest.mark.parametrize("global_value", [None, "true", 1, False])
def test_global_authorization_requires_literal_true(tmp_path, global_value):
    settings = _settings(tmp_path, allow=global_value)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": _canonical_item()})

    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {}


def test_legacy_auto_apply_does_not_substitute_individual_authorization(tmp_path):
    settings = _settings(tmp_path)
    _write_parameters(
        settings,
        {
            "MAX_ORDERS_PER_CYCLE": {
                "status": "active",
                "proposed": 2,
                "auto_apply": True,
                "expires_after_sessions": 3,
                "evidence": {"session_date": "2026-07-13"},
            }
        },
    )

    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_auto_apply": None, "authorized_auto_apply": True},
        {"requested_auto_apply": False, "authorized_auto_apply": True},
        {"requested_auto_apply": True, "authorized_auto_apply": False},
        {"requested_auto_apply": True, "authorized_auto_apply": False, "auto_apply": True},
        {"requested_auto_apply": "true", "authorized_auto_apply": True},
    ],
)
def test_missing_false_or_contradictory_individual_authorization_fails_closed(tmp_path, changes):
    settings = _settings(tmp_path)
    item = _canonical_item(**changes)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": item})

    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {}


def test_canonical_authorization_and_current_session_apply_only_its_field(tmp_path):
    settings = _settings(tmp_path)
    _write_parameters(
        settings,
        {
            "MAX_ORDERS_PER_CYCLE": _canonical_item(proposed=2),
            "UNKNOWN_PARAMETER": _canonical_item(proposed=2),
        },
    )

    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {
        "max_orders_per_cycle": 2
    }


def test_expired_override_is_ignored_by_xnys_session_age(tmp_path):
    settings = _settings(tmp_path)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": _canonical_item()})

    assert active_adaptive_overrides(settings, current_session_date="2026-07-16") == {}


@pytest.mark.parametrize(
    "current_session_date, item",
    [
        (None, _canonical_item()),
        ("2026-07-13", _canonical_item(evidence={})),
        ("2026-07-13", _canonical_item(expires_after_sessions="3")),
        ("not-a-date", _canonical_item()),
    ],
)
def test_non_evaluable_expiry_is_unavailable_and_ignored(tmp_path, current_session_date, item):
    settings = _settings(tmp_path)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": item})

    assert active_adaptive_overrides(settings, current_session_date=current_session_date) == {}


def test_equivalent_noop_requires_the_same_authority_contract(tmp_path):
    settings = _settings(tmp_path)
    _write_parameters(settings, {"ENTRY_QUALITY_MAX_RSI": _canonical_item(proposed=85)})

    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {
        "entry_quality_max_rsi": 85.0
    }

    settings.allow_auto_apply_improvements = False
    assert active_adaptive_overrides(settings, current_session_date="2026-07-13") == {}


def test_invalid_type_is_ignored_and_out_of_bounds_keeps_existing_safe_bound(tmp_path):
    settings = _settings(tmp_path)
    _write_parameters(
        settings,
        {
            "MAX_ORDERS_PER_CYCLE": _canonical_item(proposed=99),
            "ENTRY_QUALITY_MAX_RSI": _canonical_item(proposed="not-a-number"),
        },
    )

    overrides = active_adaptive_overrides(settings, current_session_date="2026-07-13")
    assert overrides == {"max_orders_per_cycle": 3}


def test_loader_is_read_only_and_repeatable(tmp_path):
    settings = _settings(tmp_path, allow=False)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": {"status": "active", "proposed": 2}})
    path = adaptive_config_path(settings)
    before = sha256(path.read_bytes()).hexdigest()

    first = active_adaptive_overrides(settings)
    second = active_adaptive_overrides(settings)

    assert first == second == {}
    assert sha256(path.read_bytes()).hexdigest() == before
    assert sorted(path.parent.iterdir()) == [path]


def test_max_orders_legacy_two_does_not_replace_base_four(tmp_path):
    settings = _settings(tmp_path, allow=False)
    settings.max_orders_per_cycle = 4
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": {"status": "active", "proposed": 2, "auto_apply": True}})

    overrides = active_adaptive_overrides(settings)
    effective = settings.max_orders_per_cycle if not overrides else overrides["max_orders_per_cycle"]

    assert overrides == {}
    assert effective == 4


def test_governance_inventory_still_reports_legacy_without_granting_authority(tmp_path):
    settings = _settings(tmp_path, allow=False)
    _write_parameters(settings, {"MAX_ORDERS_PER_CYCLE": {"status": "active", "proposed": 2}})

    status = adaptive_governance_status(settings)

    assert status["unauthorized_or_legacy_active_override_count"] == 1
    assert status["overrides"][0]["governance"] == "preexisting_unauthorized"
    assert active_adaptive_overrides(settings) == {}
