import json

from types import SimpleNamespace

from agente_bolsa.tools.adaptive_tuning import active_adaptive_overrides, adaptive_config_path


def test_legacy_active_override_cannot_change_settings_when_global_false(tmp_path):
    settings = SimpleNamespace(
        state_dir=tmp_path / "state",
        allow_auto_apply_improvements=False,
    )
    settings.state_dir.mkdir()
    adaptive_config_path(settings).write_text(
        json.dumps(
            {
                "version": 1,
                "parameters": {
                    "MAX_ORDERS_PER_CYCLE": {
                        "status": "active",
                        "proposed": 2,
                        "auto_apply": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert active_adaptive_overrides(settings) == {}
