"""Measure digest CLI parity and process memory in isolated temporary runs.

This script never points Settings at the repository data directory.  It is a
review artifact for the Oct10 digest route; it does not call broker, network,
LLM, or production services.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _run(command: list[str], *, env: dict[str, str], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, text=True, env=env)
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


def _scrub(value: Any, temp_root: str) -> Any:
    if isinstance(value, dict):
        volatile = {"generated_at", "as_of", "from", "to", "window_start", "reference_at", "path"}
        return {key: _scrub(item, temp_root) for key, item in value.items() if key not in volatile}
    if isinstance(value, list):
        return [_scrub(item, temp_root) for item in value]
    if isinstance(value, str):
        return value.replace(temp_root, "<TEMP>")
    return value


def measure(output_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="digest-cli-oct10-") as temp_text:
        temp_root = Path(temp_text)
        data_root = temp_root / "data"
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "DATA_DIR": str(data_root),
                "TRADING_MODE": "paper",
                "ALPACA_PAPER": "true",
                "ALLOW_LIVE_TRADING": "false",
                "ALLOW_AUTO_APPLY_IMPROVEMENTS": "false",
            }
        )
        import_results = {
            "digest_cli": _import_probe("agente_bolsa.digest_cli", env=env, output_dir=temp_root / "import_digest"),
            "main": _import_probe("agente_bolsa.main", env=env, output_dir=temp_root / "import_main"),
        }
        routes: dict[str, dict[str, Any]] = {}
        child = Path(__file__).with_name("digest_route_isolated_child_oct10.py")
        for name, command in {
            "new": ["--days", "1", "--out"],
            "legacy": ["continuous-improvement-lab", "digest", "--days", "1", "--out"],
        }.items():
            report = temp_root / f"{name}.md"
            module = "agente_bolsa.digest_cli" if name == "new" else "agente_bolsa.main"
            child_env = {**env, "DIGEST_ROUTE_MODULE": module, "DIGEST_ROUTE_IMPORT_ONLY": "0"}
            routes[name] = _run(
                [sys.executable, str(child), *command, str(report), "--json"],
                env=child_env,
                output_dir=temp_root / name,
            )
            routes[name]["report_bytes"] = report.stat().st_size if report.exists() else None
            routes[name]["report_exists"] = report.exists()
            output_text = routes[name].pop("stdout")
            routes[name]["payload"] = json.loads(output_text) if routes[name]["returncode"] == 0 else None

        new_payload = routes["new"]["payload"] or {}
        legacy_payload = routes["legacy"]["payload"] or {}
        new_scrubbed = _scrub(new_payload, str(temp_root))
        legacy_scrubbed = _scrub(legacy_payload, str(temp_root))
        for route in routes.values():
            payload = route.pop("payload") or {}
            digest = payload.get("digest") or {}
            safety = digest.get("safety") or {}
            route["payload_summary"] = {
                "ok": payload.get("ok"),
                "days": digest.get("days"),
                "safety_ok": safety.get("ok"),
                "safety_violations": safety.get("violations"),
                "top_level_keys": sorted(payload),
                "digest_keys": sorted(digest),
            }
        result = {
            "python": sys.executable,
            "platform": os.name,
            "data_root_is_temporary": True,
            "network_broker_llm": "not invoked by this script",
            "import_results": import_results,
            "routes": routes,
            "parity": {
                "returncodes_equal_zero": routes["new"]["returncode"] == routes["legacy"]["returncode"] == 0,
                "stable_payload_equal_after_runtime_normalization": new_scrubbed == legacy_scrubbed,
                "top_level_keys_equal": set(new_payload) == set(legacy_payload),
                "digest_keys_equal": set(new_payload.get("digest") or {}) == set(legacy_payload.get("digest") or {}),
                "normalization_keys": ["generated_at", "as_of", "from", "to", "window_start", "reference_at", "path"],
            },
            "limits": {
                "reference_memcg_bytes": 268435456,
                "windows_rss_is_not_linux_memcg": True,
                "import_probe_is_not_full_digest": True,
            },
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "parity": result["parity"], "routes": {name: {key: value for key, value in data.items() if key != "payload"} for name, data in routes.items()}}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    measure(parser.parse_args().output)


if __name__ == "__main__":
    main()
