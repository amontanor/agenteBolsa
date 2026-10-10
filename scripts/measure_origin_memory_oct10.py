"""Measure the origin-artifact projection against the unchanged full reader.

The parent process creates a temporary SQLite database and starts one effective
Python child per mode. Each child reports its own tracemalloc peak, PID and
interpreter identity. No Settings, network, broker or LLM provider is loaded.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
from pathlib import Path
from typing import Any

BASE_COMMIT = "1a3333a49db77898cecf1670813b4e23d445ac00"
CONTENT_BYTES = 256 * 1024
ARTIFACT_COUNT = 16


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _create_fixture(database_path: Path, *, count: int = ARTIFACT_COUNT) -> int:
    from agente_bolsa.storage import Store

    store = Store(database_path, database_path.parent / "agent_logs")
    store.ensure_schema()
    content = "X" * CONTENT_BYTES
    with store.connect() as conn:
        for index in range(count):
            timestamp = f"2026-10-10T00:00:{index:02d}+00:00"
            conn.execute(
                """
                INSERT INTO continuous_improvement_proposal_artifacts
                    (artifact_id, proposal_id, artifact_type, content_text, payload_json, created_at, updated_at)
                VALUES (?, ?, 'code_diff_preview', ?, ?, ?, ?)
                """,
                (
                    f"artifact-{index}",
                    f"proposal-{index}",
                    content,
                    json.dumps({"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True}),
                    timestamp,
                    timestamp,
                ),
            )
    del store
    gc.collect()
    return count * len(content.encode("utf-8"))


def _child_measure(mode: str, database_path: Path) -> dict[str, Any]:
    from agente_bolsa.storage import Store

    gc.collect()
    tracemalloc.start()
    if mode == "legacy":
        result = Store(database_path, database_path.parent / "agent_logs").continuous_improvement_proposal_artifacts(
            limit=50000
        )
    elif mode == "projection":
        store = Store(database_path, database_path.parent / "agent_logs")
        result = list(store.iter_continuous_improvement_proposal_artifact_summaries(limit=50000, batch_size=4))
    else:
        raise ValueError(f"unsupported mode: {mode}")
    current, peak = tracemalloc.get_traced_memory()
    payload = {
        "mode": mode,
        "pid": os.getpid(),
        "python_executable": sys.executable,
        "sys_prefix": sys.prefix,
        "current_tracemalloc_bytes": current,
        "peak_tracemalloc_bytes": peak,
        "rows": len(result),
        "retained_content_bytes": sum(len(item.get("content_text", "").encode("utf-8")) for item in result),
    }
    tracemalloc.stop()
    return payload


def _install_offline_guards() -> list[str]:
    """Block socket/DNS calls before importing project modules in each child."""
    import socket

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network disabled for isolated origin-memory measurement")

    original_socket = socket.socket

    class GuardedSocket(original_socket):
        connect = blocked
        connect_ex = blocked
        sendto = blocked
        sendmsg = blocked

    socket.socket = GuardedSocket  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    socket.getaddrinfo = blocked  # type: ignore[assignment]
    socket.gethostbyname = blocked  # type: ignore[assignment]
    return ["socket.socket", "socket.create_connection", "socket.getaddrinfo", "socket.gethostbyname"]


def _raw_git_blob(repo: Path, revision: str, relative_path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{revision}:{relative_path}"], cwd=repo)


def _ast_hash(source: bytes, *, function_name: str) -> str:
    module = ast.parse(source.decode("utf-8"))
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            normalized = ast.dump(node, annotate_fields=True, include_attributes=False).encode("utf-8")
            return hashlib.sha256(normalized).hexdigest()
    raise RuntimeError(f"function not found: {function_name}")


def _run_parent(output_path: Path) -> int:
    repo = _repo_root()
    storage_path = Path("src/agente_bolsa/storage.py")
    digest_path = Path("src/agente_bolsa/continuous_improvement/digest.py")
    current_source = (repo / storage_path).read_bytes()
    base_source = _raw_git_blob(repo, BASE_COMMIT, str(storage_path).replace("\\", "/"))
    current_digest_source = (repo / digest_path).read_bytes()
    base_digest_source = _raw_git_blob(repo, BASE_COMMIT, str(digest_path).replace("\\", "/"))
    fingerprint = {
        "base_commit": BASE_COMMIT,
        "base_storage_blob_sha256": hashlib.sha256(base_source).hexdigest(),
        "current_storage_blob_sha256": hashlib.sha256(current_source).hexdigest(),
        "base_legacy_reader_ast_sha256": _ast_hash(
            base_source, function_name="continuous_improvement_proposal_artifacts"
        ),
        "current_legacy_reader_ast_sha256": _ast_hash(
            current_source, function_name="continuous_improvement_proposal_artifacts"
        ),
        "current_projection_ast_sha256": _ast_hash(
            current_source, function_name="iter_continuous_improvement_proposal_artifact_summaries"
        ),
        "base_origin_metrics_ast_sha256": _ast_hash(
            base_digest_source, function_name="build_origin_utility_metrics"
        ),
        "current_origin_metrics_ast_sha256": _ast_hash(
            current_digest_source, function_name="build_origin_utility_metrics"
        ),
        "comparison": "projection fields compared with unchanged full-reader fields on the same temporary rows",
        "hash_scope": "raw git-show/file bytes for blob hashes; AST dump without source locations for function hashes",
    }
    temp = Path(tempfile.mkdtemp(prefix="oct10-origin-memory-"))
    try:
        database_path = temp / "origin.sqlite3"
        content_bytes = _create_fixture(database_path)
        child_env = os.environ.copy()
        child_env["PYTHONPATH"] = str(repo / "src")
        child_env["DATA_DIR"] = str(temp / "data")
        child_env["PYTHONNOUSERSITE"] = "1"
        modes: list[dict[str, Any]] = []
        for mode in ("legacy", "projection"):
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--child", mode, "--db", str(database_path)],
                cwd=repo,
                env=child_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            record: dict[str, Any] = {
                "mode": mode,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            if completed.returncode == 0:
                record["measurement"] = json.loads(completed.stdout.strip())
            modes.append(record)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    payload = {
        "status": "passed" if all(item["returncode"] == 0 for item in modes) else "failed",
        "database": "temporary SQLite fixture, best-effort removed after child runs",
        "artifact_count": ARTIFACT_COUNT,
        "content_bytes": CONTENT_BYTES,
        "fixture_content_bytes": content_bytes,
        "offline_guards": [
            "socket.socket",
            "socket.create_connection",
            "socket.getaddrinfo",
            "socket.gethostbyname",
        ],
        "settings": "Settings was not constructed; no _env_file was consulted",
        "modes": modes,
        "fingerprint": fingerprint,
        "limits": [
            "tracemalloc is Python allocation tracing, not Windows RSS or cgroup memory",
            "small synthetic fixture only; this does not prove or disprove the production OOM",
            "projection still decodes each payload JSON and retains its small output list in this measurement",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=("legacy", "projection"))
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/artifacts/oct10_origin_memory_measurement.json"),
    )
    args = parser.parse_args()
    offline_guards = _install_offline_guards()
    if args.child:
        if args.db is None:
            parser.error("--db is required with --child")
        result = _child_measure(args.child, args.db)
        result["offline_guards"] = offline_guards
        print(json.dumps(result, sort_keys=True))
        return 0
    return _run_parent(args.output if args.output.is_absolute() else _repo_root() / args.output)


if __name__ == "__main__":
    raise SystemExit(main())
