from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = "src/agente_bolsa/__init__.py"
WATCHED_PREFIXES = ("src/agente_bolsa/", "tests/")
WATCHED_FILES = {"pyproject.toml"}


def _git_paths(*args: str) -> set[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return set()
    return {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip()
    }


def test_version_must_change_when_product_files_change():
    tracked = _git_paths("diff", "--name-only", "HEAD", "--", "src/agente_bolsa", "tests", "pyproject.toml")
    untracked = _git_paths("ls-files", "--others", "--exclude-standard", "--", "src/agente_bolsa", "tests", "pyproject.toml")
    changed = tracked | untracked
    if not changed:
        return

    relevant = {
        path
        for path in changed
        if path == VERSION_FILE or path in WATCHED_FILES or path.startswith(WATCHED_PREFIXES)
    }
    if not relevant:
        return

    assert VERSION_FILE in relevant, (
        "Cualquier cambio funcional o de producto debe incrementar "
        "src/agente_bolsa/__init__.py::__version__."
    )
