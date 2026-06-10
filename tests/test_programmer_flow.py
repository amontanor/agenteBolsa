"""Tests del ProgrammerAgent end-to-end / build de estrategias (T1.4)."""

import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.strategy_builder import (
    StrategyBuilder,
    build_strategy_from_spec,
)
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    return Settings(DATA_DIR=tmp_path, **overrides)


def _store(settings):
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


_GOOD_RESPONSE = json.dumps(
    {
        "file_edits": [
            {"path": "src/agente_bolsa/strategies/foo.py", "content": "# strategy\n"},
            {"path": "tests/test_foo.py", "content": "def test_x():\n    assert True\n"},
        ],
        "test_commands": ["python -m pytest tests/test_foo.py -q"],
        "strategy_name": "foo",
        "strategy_version": "1",
        "rationale": "breakout mas estricto",
        "expected_metric_impact": "+hit rate",
    }
)

_NO_TEST_RESPONSE = json.dumps(
    {
        "file_edits": [{"path": "src/agente_bolsa/strategies/foo.py", "content": "# strategy\n"}],
        "strategy_name": "foo",
    }
)


class _AppliedApplier:
    def try_apply(self, **kwargs):
        return {"status": "APPLIED", "applied_change_id": "ac1"}


class _RejectApplier:
    def __init__(self):
        self.calls = 0

    def try_apply(self, **kwargs):
        self.calls += 1
        return {"status": "REJECTED_BY_TESTS", "error": "pytest failed at line 3"}


class _RepairApplier:
    def __init__(self):
        self.calls = 0

    def try_apply(self, **kwargs):
        self.calls += 1
        if self.calls >= 2:
            return {"status": "APPLIED", "applied_change_id": "ac2"}
        return {"status": "REJECTED_BY_TESTS", "error": "boom"}


def test_valid_response_applies_and_opens_shadow_window(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    builder = StrategyBuilder(store, settings, applier=_AppliedApplier(), llm=lambda messages: _GOOD_RESPONSE)

    result = builder.build({"hypothesis": "breakout mas estricto"})

    assert result["ok"] is True
    assert result["status"] == "APPLIED"
    assert result["promotion_window"]
    status = {row["name"]: row["status"] for row in store.strategy_versions()}
    assert status.get("foo") == "SHADOW"


def test_repair_loop_succeeds_on_second_attempt(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    applier = _RepairApplier()
    builder = StrategyBuilder(store, settings, applier=applier, llm=lambda messages: _GOOD_RESPONSE)

    result = builder.build({})

    assert result["ok"] is True
    assert applier.calls == 2


def test_repeated_test_failure_archives_failed_build(tmp_path):
    settings = _settings(tmp_path, PROGRAMMER_MAX_REPAIR_ATTEMPTS=2)
    store = _store(settings)
    applier = _RejectApplier()
    builder = StrategyBuilder(store, settings, applier=applier, llm=lambda messages: _GOOD_RESPONSE)

    result = builder.build({"proposal_id": "ci_prop_fail"})

    assert result["ok"] is False
    assert result["status"] == "FAILED_BUILD"
    assert applier.calls == 3  # 1 + 2 reintentos
    artifact = store.continuous_improvement_proposal_artifact("ci_prop_fail")
    assert artifact is not None
    assert artifact["artifact_type"] == "failed_build"


def test_missing_test_file_never_applies(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)

    calls = {"n": 0}

    class _CountApplier:
        def try_apply(self, **kwargs):
            calls["n"] += 1
            return {"status": "APPLIED"}

    builder = StrategyBuilder(store, settings, applier=_CountApplier(), llm=lambda messages: _NO_TEST_RESPONSE)
    result = builder.build({})

    assert result["ok"] is False
    assert result["status"] == "FAILED_BUILD"
    assert calls["n"] == 0


def test_build_disabled_by_setting(tmp_path):
    settings = _settings(tmp_path, CI_BUILD_STRATEGY_ENABLED=False)
    store = _store(settings)
    result = build_strategy_from_spec(store, settings, {"hypothesis": "x"}, applier=_AppliedApplier(), llm=lambda m: _GOOD_RESPONSE)
    assert result["status"] == "DISABLED"
