"""Manual human review and apply flow for validated code diffs."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agente_bolsa.models import new_id
from agente_bolsa.tools.ops_reports import backup_database

from .sandbox import run_validation_steps

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store


HUMAN_APPLY_ALLOWED_PREFIXES: tuple[str, ...] = (
    "src/agente_bolsa/continuous_improvement/",
    "src/agente_bolsa/tools/operational_",
    "tests/",
    "docs/",
)
HUMAN_APPLY_BLOCKED_PREFIXES: tuple[str, ...] = (
    "src/agente_bolsa/kernel.py",
    "src/agente_bolsa/tools/broker.py",
    "src/agente_bolsa/tools/execution.py",
    "src/agente_bolsa/tools/risk.py",
    "src/agente_bolsa/config.py",
)
HUMAN_APPLY_BLOCKED_EXACT: frozenset[str] = frozenset({".env"})


def review_code_diff_artifacts(
    store: Store,
    *,
    proposal_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    artifacts = _diff_artifacts(store, proposal_id=proposal_id, limit=limit)
    return {"ok": True, "count": len(artifacts), "artifacts": artifacts}


def approve_and_apply_code_diff(
    *,
    settings: Settings,
    store: Store,
    proposal_id: str,
    actor: str = "cli",
    validation_steps: list[tuple[str, list[str]]] | None = None,
    backup: bool = True,
) -> dict[str, Any]:
    repo = settings.improvement_workspace_dir.resolve()
    proposal = store.continuous_improvement_proposal(proposal_id)
    if proposal is None:
        return _abort(store, proposal_id, "NOT_FOUND", f"Propuesta no encontrada: {proposal_id}", actor=actor)
    artifact = _latest_ready_diff_artifact(store, proposal_id)
    if artifact is None:
        return _abort(store, proposal_id, "BLOCKED", "No hay diff validado READY_FOR_HUMAN_REVIEW.", actor=actor)
    diff_text = str(artifact.get("content_text") or "")
    payload = artifact.get("payload") or {}
    if payload.get("tests_ok") is not True or payload.get("status") != "READY_FOR_HUMAN_REVIEW":
        return _abort(store, proposal_id, "BLOCKED", "El artefacto no tiene tests_ok=true.", actor=actor)
    live_error = _live_guard(settings)
    if live_error:
        return _abort(store, proposal_id, "BLOCKED", live_error, actor=actor)
    targets = diff_target_paths(diff_text)
    scope_error = _scope_error(targets)
    if scope_error:
        return _abort(store, proposal_id, "BLOCKED", scope_error, actor=actor)
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if dirty:
        return _abort(store, proposal_id, "BLOCKED", "Working tree no esta limpio; aborta apply humano.", actor=actor)

    backup_report = None
    if backup:
        backup_report = backup_database(settings, settings.data_dir / "reports", new_id("db_backup_human_apply"))

    apply_result = _apply_diff_with_fallback(repo, diff_text)
    if not apply_result["ok"]:
        error = apply_result["error"]
        return _reject_tests(store, proposal, artifact, actor, error, validation={"ok": False, "steps": []})
    applied_diff_text = str(apply_result["diff_text"])

    validation = run_validation_steps(
        settings,
        repo,
        steps=validation_steps if validation_steps is not None else _full_validation_steps(),
    )
    if not validation.get("ok"):
        _reverse_patch(repo, applied_diff_text)
        _restore_targets(repo, targets)
        return _reject_tests(store, proposal, artifact, actor, "Suite fallida tras apply humano.", validation=validation)

    _git_or_raise(repo, "add", "-A", "--", *targets)
    commit_message = f"[ci-human] apply {proposal_id}"
    _git_or_raise(
        repo,
        "-c",
        "user.email=ci-human@agente-bolsa.local",
        "-c",
        "user.name=ci-human",
        "commit",
        "--no-verify",
        "-m",
        commit_message,
    )
    commit_hash = _git_or_raise(repo, "rev-parse", "HEAD")
    approval_artifact = _save_artifact(
        store,
        proposal_id=proposal_id,
        artifact_type="code_diff_human_approval",
        content_text=f"Aprobado y aplicado por {actor} en commit {commit_hash}.",
        payload={
            "status": "APPLIED",
            "actor": actor,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "diff_artifact_id": artifact.get("artifact_id"),
            "commit": commit_hash,
            "backup": backup_report,
            "validation": validation,
            "apply_strategy": apply_result["strategy"],
            "target_paths": targets,
        },
    )
    applied_change_id = new_id("ci_applied")
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": applied_change_id,
            "initiative_id": None,
            "proposal_id": proposal_id,
            "cycle_id": proposal.get("cycle_id"),
            "status": "APPLIED",
            "change_type": "CODE_CHANGE",
            "target_key": ",".join(targets),
            "before": {"diff_artifact_id": artifact.get("artifact_id")},
            "after": {"commit": commit_hash, "target_paths": targets},
            "rollback": {"git": {"command": f"git revert {commit_hash}", "commit": commit_hash}},
            "decision": {
                "actor": actor,
                "manual_approval": True,
                "approval_artifact_id": approval_artifact["artifact_id"],
                "apply_strategy": apply_result["strategy"],
                "backup": backup_report,
            },
            "validation_ids": [payload.get("validation_id")] if payload.get("validation_id") else [],
        }
    )
    store.update_continuous_improvement_proposal_status(
        proposal_id,
        status="APPLIED",
        actor="HumanApplyCLI",
        reason=f"Aprobacion humana aplicada en commit {commit_hash}.",
        payload={"applied_change_id": applied_change_id, "commit": commit_hash},
    )
    return {
        "ok": True,
        "status": "APPLIED",
        "proposal_id": proposal_id,
        "applied_change_id": applied_change_id,
        "commit": commit_hash,
        "artifact": approval_artifact,
        "backup": backup_report,
        "validation": validation,
        "target_paths": targets,
    }


def diff_target_paths(diff_text: str) -> list[str]:
    targets: list[str] = []
    for line in str(diff_text or "").splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            rel = line[6:].strip()
            if rel != "/dev/null":
                targets.append(rel.replace("\\", "/"))
    return list(dict.fromkeys(targets))


def _full_validation_steps() -> list[tuple[str, list[str]]]:
    return [
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
        ("pytest", [sys.executable, "-m", "pytest", "tests/", "-x", "-q"]),
    ]


def _live_guard(settings: Settings) -> str | None:
    if bool(getattr(settings, "allow_live_trading", False)):
        return "ALLOW_LIVE_TRADING=true bloquea apply humano."
    if str(getattr(settings, "trading_mode", "paper")).lower() != "paper":
        return "TRADING_MODE debe permanecer en paper para apply humano."
    return None


def _scope_error(targets: list[str]) -> str | None:
    if not targets:
        return "El diff no declara archivos objetivo."
    for rel in targets:
        norm = rel.replace("\\", "/").lstrip("/")
        if norm in HUMAN_APPLY_BLOCKED_EXACT or any(norm.startswith(prefix) for prefix in HUMAN_APPLY_BLOCKED_PREFIXES):
            return f"{norm} esta bloqueado por suelo de kernel."
        if ".." in norm.split("/"):
            return f"{norm} contiene traversal no permitido."
        if not any(norm.startswith(prefix) for prefix in HUMAN_APPLY_ALLOWED_PREFIXES):
            return f"{norm} fuera del allowlist de apply humano."
    return None


def _latest_ready_diff_artifact(store: Store, proposal_id: str) -> dict[str, Any] | None:
    artifacts = _diff_artifacts(store, proposal_id=proposal_id, limit=1)
    return artifacts[0] if artifacts else None


def _diff_artifacts(store: Store, *, proposal_id: str | None, limit: int) -> list[dict[str, Any]]:
    query = """
        SELECT artifact_id, proposal_id, artifact_type, content_text, payload_json,
               created_at, updated_at
        FROM continuous_improvement_proposal_artifacts
        WHERE artifact_type = 'code_diff_preview'
    """
    params: list[Any] = []
    if proposal_id:
        query += " AND proposal_id = ?"
        params.append(proposal_id)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with store.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    artifacts: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        if payload.get("status") != "READY_FOR_HUMAN_REVIEW" or payload.get("tests_ok") is not True:
            continue
        artifacts.append(
            {
                "artifact_id": row["artifact_id"],
                "proposal_id": row["proposal_id"],
                "artifact_type": row["artifact_type"],
                "content_text": row["content_text"],
                "payload": payload,
                "target_paths": diff_target_paths(row["content_text"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return artifacts


def _abort(store: Store, proposal_id: str, status: str, error: str, *, actor: str) -> dict[str, Any]:
    artifact = _save_artifact(
        store,
        proposal_id=proposal_id,
        artifact_type="code_diff_human_approval_blocked",
        content_text=error,
        payload={"status": status, "error": error, "actor": actor, "applied": False},
    )
    return {"ok": False, "status": status, "proposal_id": proposal_id, "error": error, "artifact": artifact}


def _reject_tests(
    store: Store,
    proposal: dict[str, Any],
    diff_artifact: dict[str, Any],
    actor: str,
    error: str,
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    proposal_id = proposal["proposal_id"]
    artifact = _save_artifact(
        store,
        proposal_id=proposal_id,
        artifact_type="code_diff_human_approval_rejected",
        content_text=error,
        payload={
            "status": "REJECTED_BY_TESTS",
            "error": error,
            "actor": actor,
            "diff_artifact_id": diff_artifact.get("artifact_id"),
            "validation": validation,
            "applied": False,
        },
    )
    store.update_continuous_improvement_proposal_status(
        proposal_id,
        status="REJECTED_BY_TESTS",
        actor="HumanApplyCLI",
        reason=error,
        payload={"artifact": artifact},
    )
    return {
        "ok": False,
        "status": "REJECTED_BY_TESTS",
        "proposal_id": proposal_id,
        "error": error,
        "artifact": artifact,
        "validation": validation,
    }


def _save_artifact(
    store: Store,
    *,
    proposal_id: str,
    artifact_type: str,
    content_text: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    artifact = {
        "artifact_id": new_id("ci_artifact"),
        "proposal_id": proposal_id,
        "artifact_type": artifact_type,
        "content_text": content_text,
        "payload": payload,
    }
    store.save_continuous_improvement_proposal_artifact(artifact)
    return artifact


def _git(repo: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=300,
    )


def _apply_diff_with_fallback(repo: Path, diff_text: str) -> dict[str, Any]:
    attempts = [
        ("3way", diff_text, ("apply", "--index", "--3way", "--whitespace=nowarn", "-")),
        (
            "ignore_whitespace",
            diff_text,
            ("apply", "--index", "--ignore-whitespace", "--whitespace=nowarn", "-"),
        ),
    ]
    repaired = _repair_cp1252_mojibake(diff_text)
    if repaired != diff_text:
        attempts.append(
            (
                "repair_cp1252_mojibake",
                repaired,
                ("apply", "--index", "--3way", "--whitespace=nowarn", "-"),
            )
        )
        attempts.append(
            (
                "repair_cp1252_mojibake_ignore_whitespace",
                repaired,
                ("apply", "--index", "--ignore-whitespace", "--whitespace=nowarn", "-"),
            )
        )
    errors: list[str] = []
    for strategy, candidate, command in attempts:
        result = _git(repo, *command, input_text=candidate)
        if result.returncode == 0:
            return {"ok": True, "strategy": strategy, "diff_text": candidate}
        errors.append(f"{strategy}: {(result.stderr or result.stdout or 'git apply fallo').strip()}")
    return {"ok": False, "strategy": None, "diff_text": diff_text, "error": " | ".join(errors)}


def _repair_cp1252_mojibake(text: str) -> str:
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text
    return repaired if repaired != text else text


def _git_or_raise(repo: Path, *args: str) -> str:
    result = _git(repo, *args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"git {' '.join(args)} fallo").strip())
    return result.stdout.strip()


def _reverse_patch(repo: Path, diff_text: str) -> None:
    _git(repo, "apply", "-R", "--index", "--whitespace=nowarn", "-", input_text=diff_text)


def _restore_targets(repo: Path, targets: list[str]) -> None:
    if targets:
        _git(repo, "restore", "--staged", "--worktree", "--", *targets)
