"""Sandbox git real para cambios autonomos (T0.3).

Cada cambio de codigo propuesto por los agentes se aplica en un git worktree
aislado, en una rama `ci/auto/<change_id>`, donde se ejecuta la suite COMPLETA
(ruff + pytest + smoke `run-once --skip-crew`). Si todo pasa, se fusiona a la
rama de trabajo con un commit revertible y un tag; si falla, el worktree se
destruye y se conservan los logs como artefactos. Asi ningun cambio autonomo
toca la rama principal sin la suite verde.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings


def git_available() -> bool:
    return shutil.which("git") is not None


def is_git_repo(path: Path) -> bool:
    return (Path(path) / ".git").exists()


def sandbox_supported(repo_root: Path) -> bool:
    """True si se puede usar el sandbox git real sobre ``repo_root``."""

    return git_available() and is_git_repo(Path(repo_root))


class GitSandboxError(RuntimeError):
    pass


class GitSandbox:
    """Worktree git aislado para validar y fusionar un cambio autonomo."""

    def __init__(self, settings: Settings, repo_root: Path | None = None) -> None:
        self.settings = settings
        self.repo_root = Path(repo_root or settings.improvement_workspace_dir).resolve()
        self.change_id: str | None = None
        self.branch: str | None = None
        self.tag: str | None = None
        self.worktree: Path | None = None

    # -- helpers -----------------------------------------------------------
    def _git(self, *args: str, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo_root),
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    def _git_or_raise(self, *args: str, cwd: Path | None = None, timeout: int = 120) -> str:
        result = self._git(*args, cwd=cwd, timeout=timeout)
        if result.returncode != 0:
            raise GitSandboxError(
                f"git {' '.join(args)} fallo (rc={result.returncode}): "
                f"{(result.stderr or result.stdout).strip()}"
            )
        return result.stdout.strip()

    def _current_branch(self) -> str:
        return self._git_or_raise("rev-parse", "--abbrev-ref", "HEAD")

    # -- ciclo de vida -----------------------------------------------------
    def open(self, change_id: str) -> Path:
        if not sandbox_supported(self.repo_root):
            raise GitSandboxError("Sandbox git no soportado: falta git o no es un repo.")
        self.change_id = change_id
        self.branch = f"ci/auto/{change_id}"
        self.tag = f"ci-auto/{change_id}"
        sandbox_root = self.repo_root / "sandboxes"
        sandbox_root.mkdir(parents=True, exist_ok=True)
        self.worktree = sandbox_root / change_id
        if self.worktree.exists():
            # Limpieza defensiva de un intento previo abortado.
            self._safe_remove_worktree()
        self._git_or_raise("worktree", "add", str(self.worktree), "-b", self.branch, "HEAD")
        return self.worktree

    def apply(self, file_edits: Any, patch_text: str) -> None:
        if self.worktree is None:
            raise GitSandboxError("Sandbox no abierto.")
        apply_payload_to_worktree(self.worktree, file_edits=file_edits, patch_text=patch_text)
        # Commit del cambio dentro de la rama aislada.
        self._git_or_raise("add", "-A", cwd=self.worktree)
        self._git_or_raise(
            "-c",
            "user.email=ci-bot@agente-bolsa.local",
            "-c",
            "user.name=ci-auto",
            "commit",
            "--no-verify",
            "-m",
            f"[ci-auto] {self.change_id}",
            cwd=self.worktree,
        )

    def validate(self, *, steps: list[tuple[str, list[str]]] | None = None) -> dict[str, Any]:
        if self.worktree is None:
            raise GitSandboxError("Sandbox no abierto.")
        steps = steps if steps is not None else self._default_validation_steps()
        return run_validation_steps(self.settings, self.worktree, steps=steps)

    def merge(self) -> dict[str, Any]:
        if self.branch is None or self.tag is None:
            raise GitSandboxError("Sandbox no abierto.")
        work_branch = self._current_branch()
        self._git_or_raise(
            "-c",
            "user.email=ci-bot@agente-bolsa.local",
            "-c",
            "user.name=ci-auto",
            "merge",
            "--no-ff",
            self.branch,
            "-m",
            f"[ci-auto] merge {self.change_id}",
        )
        commit_hash = self._git_or_raise("rev-parse", "HEAD")
        # Tag idempotente sobre el commit de merge.
        self._git("tag", "-f", self.tag)
        return {"merged_into": work_branch, "commit": commit_hash, "tag": self.tag}

    def destroy(self) -> None:
        self._safe_remove_worktree()
        if self.branch:
            self._git("branch", "-D", self.branch)

    # -- internos ----------------------------------------------------------
    def _safe_remove_worktree(self) -> None:
        if self.worktree is not None:
            self._git("worktree", "remove", "--force", str(self.worktree))
            if self.worktree.exists():
                shutil.rmtree(self.worktree, ignore_errors=True)
        self._git("worktree", "prune")

    def _default_validation_steps(self) -> list[tuple[str, list[str]]]:
        return default_validation_steps(self.settings)


def default_validation_steps(settings: Settings) -> list[tuple[str, list[str]]]:
    """Pasos de validacion: ruff + pytest (suite completa) + smoke run-once."""

    full_suite = bool(getattr(settings, "ci_sandbox_full_suite", True))
    python = sys.executable or "python"
    pytest_target = ["-m", "pytest", "tests/", "-x", "-q"] if full_suite else [
        "-m",
        "pytest",
        "tests/test_continuous_improvement.py",
        "-q",
    ]
    return [
        ("ruff", [python, "-m", "ruff", "check", "src", "tests"]),
        ("pytest", [python, *pytest_target]),
        ("smoke_run_once", [python, "-m", "agente_bolsa.main", "run-once", "--skip-crew"]),
    ]


def run_validation_steps(
    settings: Settings,
    cwd: Path,
    *,
    steps: list[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Ejecuta pasos de validacion en ``cwd`` y devuelve el resultado agregado."""

    import os

    timeout = int(getattr(settings, "ci_sandbox_validate_timeout_seconds", 900))
    steps = steps if steps is not None else default_validation_steps(settings)
    env = dict(os.environ)
    env["DATA_DIR"] = tempfile.mkdtemp(prefix="ci_sandbox_data_")
    env.setdefault("PYTHONPATH", str(Path(cwd) / "src"))
    results: list[dict[str, Any]] = []
    ok = True
    for name, command in steps:
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                text=True,
                capture_output=True,
                timeout=timeout,
                env=env,
            )
            output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            step_ok = proc.returncode == 0
            results.append(
                {"step": name, "returncode": proc.returncode, "ok": step_ok, "output": output[-6000:]}
            )
        except subprocess.TimeoutExpired:
            step_ok = False
            results.append({"step": name, "returncode": None, "ok": False, "output": f"timeout tras {timeout}s"})
        except OSError as exc:
            step_ok = False
            results.append({"step": name, "returncode": None, "ok": False, "output": f"{type(exc).__name__}: {exc}"})
        if not step_ok:
            ok = False
            break
    return {"ok": ok, "steps": results}


def _write_and_verify(path: Path, content: str) -> None:
    """Escribe un archivo y verifica su integridad (T5.8).

    Normaliza a newline final, escribe, re-lee y comprueba: (a) sin bytes nulos,
    (b) ast.parse si es .py, (c) coincide byte a byte con lo solicitado. Cualquier
    fallo lanza excepcion para que el sandbox aborte y destruya el worktree.
    """

    if not content.endswith("\n"):
        content = content + "\n"
    # Validacion PREVIA a la escritura: un contenido invalido jamas toca disco.
    if "\x00" in content:
        raise GitSandboxError(f"contenido con bytes nulos: {path.name}")
    if str(path).endswith(".py"):
        import ast

        try:
            ast.parse(content)
        except SyntaxError as exc:
            raise GitSandboxError(f"archivo .py invalido ({path.name}): {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    reread = path.read_text(encoding="utf-8")
    if reread != content:
        # Escritura corrupta: no dejar el archivo a medias en el worktree.
        try:
            path.unlink()
        except OSError:
            pass
        raise GitSandboxError(f"escritura corrupta (no coincide byte a byte): {path.name}")


def apply_payload_to_worktree(worktree: Path, *, file_edits: Any, patch_text: str) -> None:
    """Aplica file_edits/patch sobre un worktree, con verificacion de integridad.

    Soporta: lista de `{path, content}` (contenido completo) o `{path, old, new}`
    (reemplazo de bloque), o un patch unificado via `git apply`. Cada archivo
    escrito se re-lee y valida (sin nulls, ast.parse en .py, byte a byte) — T5.8.
    """

    if isinstance(file_edits, list) and file_edits:
        for item in file_edits:
            if not isinstance(item, dict) or not item.get("path"):
                raise ValueError("file_edits invalido")
            path = worktree / str(item["path"])
            if "content" in item:
                _write_and_verify(path, str(item["content"]))
                continue
            old = str(item.get("old") or "")
            new = str(item.get("new") or "")
            if not path.exists() and old == "":
                _write_and_verify(path, new)
                continue
            current = path.read_text(encoding="utf-8")
            if old not in current:
                raise ValueError(f"No se encontro bloque old en {item['path']}")
            _write_and_verify(path, current.replace(old, new, 1))
        return
    patch_text = str(patch_text or "").strip()
    if patch_text:
        if shutil.which("git") is None:
            raise RuntimeError("git no disponible para aplicar patch")
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=str(worktree),
            input=patch_text,
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git apply fallo")
        return
    raise ValueError("Falta patch o file_edits aplicable")
