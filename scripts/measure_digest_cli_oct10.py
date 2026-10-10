"""Measure the isolated digest route, parity, and effective Windows RSS.

This is a local review harness. It uses temporary DATA_DIR roots, blocks
network/DNS in each child, forces Settings(_env_file=None), and never invokes
broker, LLM, production data, or a service. The pre-refactor path is kept as
an AST/hash provenance anchor from cb3; no second copy of production business
logic is executed or maintained here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

BASE_COMMIT = "cb3d8805a9890fab0357b0ba3a3f7afaa8577586"


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    output_dir: Path,
    cwd: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".env").write_text("DATA_DIR=hostile-env-path\n", encoding="utf-8")
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
            cwd=str(cwd or output_dir),
        )
        returncode = process.wait()
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    phases = []
    other_stderr = []
    for line in stderr_text.splitlines():
        if line.startswith("DIGEST_PHASE "):
            phases.append(json.loads(line.removeprefix("DIGEST_PHASE ")))
        elif line:
            other_stderr.append(line)
    return {
        "returncode": returncode,
        "stdout_bytes": len(stdout_text.encode("utf-8")),
        "stderr_tail": "\n".join(other_stderr)[-500:],
        "rss_phases": phases,
        "stdout": stdout_text,
    }


def _import_probe(module: str, *, env: dict[str, str], output_dir: Path) -> dict[str, Any]:
    child = Path(__file__).with_name("digest_route_isolated_child_oct10.py")
    child_env = {**env, "DIGEST_ROUTE_MODULE": module, "DIGEST_ROUTE_IMPORT_ONLY": "1"}
    result = _run([sys.executable, str(child)], env=child_env, output_dir=output_dir)
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    result["probe"] = json.loads(lines[-1]) if lines else None
    result.pop("stdout", None)
    return result


def _normalize_artifact_paths(value: Any, temp_root: str) -> Any:
    """Normalize only the temporary artifact root; preserve business windows."""

    if isinstance(value, dict):
        return {key: _normalize_artifact_paths(item, temp_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_artifact_paths(item, temp_root) for item in value]
    if isinstance(value, str):
        return value.replace(temp_root, "<TEMP_ROOT>")
    return value


def _payload_from(result: dict[str, Any]) -> dict[str, Any] | None:
    if result["returncode"] != 0:
        return None
    stdout = result["stdout"].strip()
    return json.loads(stdout) if stdout else None


def _route_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    digest = payload.get("digest") or {}
    safety = digest.get("safety") or {}
    summary = {
        "ok": payload.get("ok"),
        "days": digest.get("days"),
        "safety_ok": safety.get("ok"),
        "safety_violations": safety.get("violations"),
        "top_level_keys": sorted(payload),
        "digest_keys": sorted(digest),
    }
    for key in ("from", "to", "window_start", "reference_at", "as_of"):
        if key in digest:
            summary[key] = digest[key]
    return summary


def _base_fingerprint(repo_root: Path) -> dict[str, Any]:
    """Record cb3's old digest branch without copying or executing it."""

    old_main = subprocess.check_output(
        ["git", "show", f"{BASE_COMMIT}:src/agente_bolsa/main.py"],
        cwd=repo_root,
        text=True,
    )
    old_tree = ast.parse(old_main)
    related = [
        node
        for node in ast.walk(old_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and any(token in node.name.lower() for token in ("digest", "continuous_improvement_lab"))
    ]
    related_dump = "\n".join(ast.dump(node, include_attributes=False) for node in related)
    current_text = (repo_root / "src/agente_bolsa/digest_cli.py").read_text(encoding="utf-8")
    current_tree = ast.parse(current_text)
    execute_nodes = [
        node
        for node in current_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_digest_command"
    ]
    current_dump = "\n".join(ast.dump(node, include_attributes=False) for node in execute_nodes)
    return {
        "base_commit": BASE_COMMIT,
        "base_main_sha256": hashlib.sha256(old_main.encode("utf-8")).hexdigest(),
        "base_digest_related_ast_sha256": hashlib.sha256(related_dump.encode("utf-8")).hexdigest(),
        "base_digest_related_nodes": [node.name for node in related],
        "current_shared_execute_ast_sha256": hashlib.sha256(current_dump.encode("utf-8")).hexdigest(),
        "comparison_mode": "pre-refactor provenance hash only; no duplicated business implementation executed",
    }


def _run_case(case_root: Path, *, env: dict[str, str], fixture: bool) -> dict[str, Any]:
    data_root = case_root / "data"
    report = case_root / "report.md"
    child = Path(__file__).with_name("digest_route_isolated_child_oct10.py")
    routes: dict[str, dict[str, Any]] = {}
    for name, command in {
        "new": ["--days", "1", "--out", str(report)],
        "legacy": ["continuous-improvement-lab", "digest", "--days", "1", "--out", str(report)],
    }.items():
        module = "agente_bolsa.digest_cli" if name == "new" else "agente_bolsa.main"
        child_env = {
            **env,
            "DATA_DIR": str(data_root),
            "DIGEST_ROUTE_MODULE": module,
            "DIGEST_ROUTE_IMPORT_ONLY": "0",
            "DIGEST_ROUTE_FIXTURE": "1" if fixture else "0",
        }
        result = _run(
            [sys.executable, str(child), *command, "--json"],
            env=child_env,
            output_dir=case_root / name,
            cwd=case_root,
        )
        payload = _payload_from(result)
        result.pop("stdout")
        result["report_bytes"] = report.stat().st_size if report.exists() else None
        result["report_exists"] = report.exists()
        result["payload_summary"] = _route_summary(payload)
        result["payload"] = _normalize_artifact_paths(payload, str(case_root)) if payload is not None else None
        routes[name] = result

    new_payload = routes["new"]["payload"]
    legacy_payload = routes["legacy"]["payload"]
    return {
        "fixture": fixture,
        "routes": routes,
        "parity": {
            "returncodes_equal_zero": routes["new"]["returncode"] == routes["legacy"]["returncode"] == 0,
            "payload_equal_after_artifact_root_normalization": new_payload == legacy_payload,
            "top_level_keys_equal": set(new_payload or {}) == set(legacy_payload or {}),
            "digest_keys_equal": set((new_payload or {}).get("digest") or {}) == set((legacy_payload or {}).get("digest") or {}),
            "normalization": {"only": "temporary artifact root string", "removed_business_fields": []},
        },
    }


def measure(output_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="digest-cli-oct10-") as temp_text:
        temp_root = Path(temp_text)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(repo_root / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "TRADING_MODE": "paper",
                "ALPACA_PAPER": "true",
                "ALLOW_LIVE_TRADING": "false",
                "ALLOW_AUTO_APPLY_IMPROVEMENTS": "false",
            }
        )
        import_results = _normalize_artifact_paths({
            "digest_cli": _import_probe(
                "agente_bolsa.digest_cli",
                env={**env, "DATA_DIR": str(temp_root / "import-data")},
                output_dir=temp_root / "import_digest",
            ),
            "main": _import_probe(
                "agente_bolsa.main",
                env={**env, "DATA_DIR": str(temp_root / "import-data")},
                output_dir=temp_root / "import_main",
            ),
        }, str(temp_root))
        cases = {
            "empty": _run_case(temp_root / "empty", env=env, fixture=False),
            "fixture": _run_case(temp_root / "fixture", env=env, fixture=True),
        }
        result = {
            "python": sys.executable,
            "sys_prefix": sys.prefix,
            "platform": os.name,
            "data_root_is_temporary": True,
            "network_broker_llm": "blocked/not invoked by this script",
            "import_results": import_results,
            "cases": cases,
            "legacy_pre_refactor": _base_fingerprint(repo_root),
            "limits": {
                "reference_memcg_bytes": 268435456,
                "windows_rss_is_not_linux_memcg": True,
                "import_probe_is_not_full_digest": True,
                "fixture_is_synthetic": True,
                "pre_refactor_route_not_executed": True,
            },
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "cases": {name: data["parity"] for name, data in cases.items()},
                "routes": {
                    case: {
                        name: {key: value for key, value in route.items() if key != "payload"}
                        for name, route in data["routes"].items()
                    }
                    for case, data in cases.items()
                },
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    measure(parser.parse_args().output)


if __name__ == "__main__":
    main()
