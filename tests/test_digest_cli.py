from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date

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


def test_continuous_improvement_package_keeps_orchestrator_public_but_lazy():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import agente_bolsa.continuous_improvement as ci; "
                "print('runtime' in sys.modules, 'agente_bolsa.continuous_improvement.runtime' in sys.modules); "
                "print(ci.ContinuousImprovementOrchestrator.__name__)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.splitlines() == ["False False", "ContinuousImprovementOrchestrator"]


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
