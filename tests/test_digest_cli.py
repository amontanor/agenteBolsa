from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from agente_bolsa import digest_cli, docker_supervisor


class _TrackedStore:
    def __init__(self) -> None:
        self.closed = 0

    def close_read_connection(self) -> None:
        self.closed += 1


def test_execute_digest_command_preserves_json_out_and_closes_store(tmp_path):
    store = _TrackedStore()
    settings = object()
    args = argparse.Namespace(days=3, out=str(tmp_path / "nested" / "digest.md"), json=True)
    seen: dict[str, object] = {}
    emitted: list[dict] = []

    def build_digest(received_store, *, days, safety):
        seen.update(store=received_store, days=days, safety=safety)
        return {"days": days, "marker": "same-handler"}

    digest_cli.execute_digest_command(
        args,
        settings=settings,
        store=store,
        build_digest=build_digest,
        format_digest=lambda payload: json.dumps(payload) + "\n",
        safety_summary=lambda received_settings: {"settings_is_same": received_settings is settings},
        emit_json=emitted.append,
    )

    assert seen == {
        "store": store,
        "days": 3,
        "safety": {"settings_is_same": True},
    }
    assert emitted == [{"ok": True, "path": str(tmp_path / "nested" / "digest.md"), "digest": {"days": 3, "marker": "same-handler"}}]
    assert (tmp_path / "nested" / "digest.md").read_text(encoding="utf-8") == '{"days": 3, "marker": "same-handler"}\n'
    assert store.closed == 1


def test_execute_digest_command_closes_store_when_digest_fails():
    store = _TrackedStore()
    args = argparse.Namespace(days=1, out=None, json=False)

    def failing_digest(*_args, **_kwargs):
        raise RuntimeError("synthetic_digest_failure")

    try:
        digest_cli.execute_digest_command(
            args,
            settings=object(),
            store=store,
            build_digest=failing_digest,
            format_digest=lambda payload: str(payload),
            safety_summary=lambda settings: {},
        )
    except RuntimeError as exc:
        assert str(exc) == "synthetic_digest_failure"
    else:
        raise AssertionError("expected synthetic digest failure")

    assert store.closed == 1


def test_execute_digest_command_closes_store_when_handler_import_fails(monkeypatch):
    store = _TrackedStore()
    args = argparse.Namespace(days=1, out=None, json=False)
    monkeypatch.setitem(sys.modules, "agente_bolsa.continuous_improvement.digest", None)

    with pytest.raises(ModuleNotFoundError):
        digest_cli.execute_digest_command(
            args,
            settings=object(),
            store=store,
            safety_summary=lambda _settings: {},
        )

    assert store.closed == 1


def test_execute_digest_command_closes_store_when_output_io_fails(tmp_path):
    store = _TrackedStore()
    blocked_parent = tmp_path / "already-a-file"
    blocked_parent.write_text("occupied", encoding="utf-8")
    args = argparse.Namespace(days=1, out=str(blocked_parent / "digest.md"), json=False)

    with pytest.raises(FileExistsError):
        digest_cli.execute_digest_command(
            args,
            settings=object(),
            store=store,
            build_digest=lambda *_args, **_kwargs: {"ok": True},
            format_digest=lambda payload: json.dumps(payload),
            safety_summary=lambda _settings: {},
        )

    assert store.closed == 1


def test_execute_digest_command_preserves_safety_input_and_text_without_output(capsys):
    store = _TrackedStore()
    args = argparse.Namespace(days=2, out=None, json=False)
    safety = {"ok": False, "violations": ["synthetic_safety_failure"]}
    seen: dict[str, object] = {}

    def build_digest(_store, *, days, safety):
        seen.update(days=days, safety=safety)
        return {"days": days, "safety_seen": safety}

    digest_cli.execute_digest_command(
        args,
        settings=object(),
        store=store,
        build_digest=build_digest,
        format_digest=lambda payload: f"TEXT:{payload['days']}",
        safety_summary=lambda _settings: safety,
    )

    assert seen == {"days": 2, "safety": safety}
    assert capsys.readouterr().out == "TEXT:2\n"
    assert store.closed == 1


def test_execute_digest_command_supports_json_without_output(capsys):
    store = _TrackedStore()
    args = argparse.Namespace(days=1, out=None, json=True)

    digest_cli.execute_digest_command(
        args,
        settings=object(),
        store=store,
        build_digest=lambda *_args, **_kwargs: {"marker": "no-output"},
        format_digest=lambda payload: str(payload),
        safety_summary=lambda _settings: {"ok": True},
    )

    assert json.loads(capsys.readouterr().out) == {"ok": True, "digest": {"marker": "no-output"}}
    assert store.closed == 1


def test_execute_digest_command_closes_store_when_safety_fails():
    store = _TrackedStore()
    args = argparse.Namespace(days=1, out=None, json=False)

    with pytest.raises(RuntimeError, match="synthetic_safety_failure"):
        digest_cli.execute_digest_command(
            args,
            settings=object(),
            store=store,
            build_digest=lambda *_args, **_kwargs: {},
            format_digest=lambda payload: str(payload),
            safety_summary=lambda _settings: (_ for _ in ()).throw(RuntimeError("synthetic_safety_failure")),
        )

    assert store.closed == 1


def test_run_digest_command_closes_store_when_ensure_schema_fails(monkeypatch):
    import agente_bolsa.config as config
    import agente_bolsa.logging_utils as logging_utils
    import agente_bolsa.storage as storage

    class Settings:
        logs_dir = "logs"
        log_level = "INFO"
        database_path = "database.sqlite"
        agent_logs_dir = "agent-logs"

    class FailingStore:
        instances: list[FailingStore] = []

        def __init__(self, *_args):
            self.closed = 0
            self.instances.append(self)

        def ensure_schema(self):
            raise RuntimeError("synthetic_schema_failure")

        def close_read_connection(self):
            self.closed += 1

    monkeypatch.setattr(config, "get_settings", lambda: Settings())
    monkeypatch.setattr(logging_utils, "configure_logging", lambda *_args: None)
    monkeypatch.setattr(storage, "Store", FailingStore)

    with pytest.raises(RuntimeError, match="synthetic_schema_failure"):
        digest_cli.run_digest_command(argparse.Namespace(days=1, out=None, json=False))

    assert len(FailingStore.instances) == 1
    assert FailingStore.instances[0].closed == 1


def test_continuous_improvement_package_keeps_orchestrator_public_but_lazy(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    child = repo_root / "scripts" / "digest_route_isolated_child_oct10.py"
    data_root = tmp_path / "data"
    (tmp_path / ".env").write_text("DATA_DIR=hostile-env-path\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "DATA_DIR": str(data_root),
        "DIGEST_ROUTE_MODULE": "agente_bolsa.continuous_improvement",
        "DIGEST_ROUTE_IMPORT_ONLY": "1",
    }
    probe = subprocess.run(
        [sys.executable, str(child)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(probe.stdout)
    assert report["main_loaded"] is False
    assert report["scheduler_loaded"] is False
    assert report["runtime_loaded"] is False
    assert report["guards"] == {"data_dir": str(data_root), "dns_blocked": True, "env_file": None}


def test_docker_supervisor_uses_lightweight_digest_entrypoint(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run_json_command(data_root, service, command):
        calls.append(command)
        return {"ok": True, "digest": {}}

    monkeypatch.setattr(docker_supervisor, "_run_json_command", fake_run_json_command)

    result = docker_supervisor.run_service_once(tmp_path, "ci_digest", date(2026, 10, 10))

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][1:4] == ["-m", "agente_bolsa.digest_cli", "--days"]
    assert calls[0][-1] == "--json"
    assert "agente_bolsa.main" not in calls[0]
