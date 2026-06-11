"""Objective experiments and controlled config auto-apply for the CI lab."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings
from agente_bolsa.models import new_id
from agente_bolsa.storage import Store
from agente_bolsa.tools.backtest import build_symbol_backtest
from agente_bolsa.tools.counterfactual_analysis import (
    build_session_retrospective_report,
    build_walk_forward_validation_report,
)

from .sandbox import GitSandbox, GitSandboxError, sandbox_supported
from .autonomy import (
    ALWAYS_BLOCKED_EXACT,
    ALWAYS_BLOCKED_PREFIXES,
    active_autonomy_level,
    ast_import_violation,
    path_violation,
)


class ExperimentRunner:
    VALIDATION_ALIASES = {
        "backtest": "in_sample",
        "baseline_compare": "out_of_sample",
        "shadow_review": "walk_forward",
        "paper_audit": "paper_or_shadow_window",
    }

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def run_for_proposal(
        self,
        *,
        proposal: dict[str, Any],
        cycle_id: str,
        initiative_id: str | None,
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        required = {
            self.VALIDATION_ALIASES.get(str(item).lower(), str(item).lower())
            for item in payload.get("required_validations", []) or []
        }
        proposal_type = str(proposal.get("proposal_type") or payload.get("proposal_type") or "")
        reports_dir = self.settings.data_dir / "reports"
        artifacts: dict[str, Any] = {}

        if "in_sample" in required:
            artifacts["backtest"] = self._run_backtest(proposal=proposal, cycle_id=cycle_id, initiative_id=initiative_id)
        if "out_of_sample" in required:
            artifacts["session_retrospective"] = self._run_session_retrospective(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
            )
        if "walk_forward" in required or proposal_type in {"RISK_RULE_CHANGE", "STRATEGY_RULE_CHANGE"}:
            artifacts["walk_forward_validation"] = self._run_walk_forward(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
            )
        if "paper_or_shadow_window" in required:
            artifacts["paper_or_shadow_window"] = self._record_report_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="paper_or_shadow_window",
                artifact_path=str(reports_dir / "latest_operational_learning.json"),
            )
        if "risk_review" in required:
            artifacts["risk_review"] = self._record_report_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="risk_review",
                artifact_path=str(reports_dir / "latest_live_readiness.json"),
            )
        if "data_quality_review" in required:
            artifacts["data_quality_review"] = self._record_report_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="data_quality_review",
                artifact_path=str(reports_dir / "latest_market_data_quality.json"),
            )
        return artifacts

    def _proposal_symbol(self, proposal: dict[str, Any]) -> str | None:
        payload = proposal.get("payload") or {}
        candidates = [
            payload.get("symbol"),
            payload.get("target_identifier"),
            proposal.get("target_identifier"),
            proposal.get("symbol"),
        ]
        for candidate in candidates:
            text = re.sub(r"[^A-Z0-9]+", "", str(candidate or "").upper())
            if 1 <= len(text) <= 6 and text.isalpha():
                return text
        return None

    def _base_experiment(
        self,
        *,
        proposal: dict[str, Any],
        cycle_id: str,
        initiative_id: str | None,
        experiment_type: str,
        status: str,
        input_payload: dict[str, Any],
        period: dict[str, Any],
        metrics: dict[str, Any],
        result: dict[str, Any],
        artifact_path: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "experiment_id": new_id("ci_exp"),
            "initiative_id": initiative_id,
            "proposal_id": proposal.get("proposal_id"),
            "cycle_id": cycle_id,
            "experiment_type": experiment_type,
            "status": status,
            "input": input_payload,
            "period": period,
            "metrics": metrics,
            "result": result,
            "artifact_path": artifact_path,
            "error": error,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.save_continuous_improvement_experiment(item)
        return item

    def _run_backtest(self, *, proposal: dict[str, Any], cycle_id: str, initiative_id: str | None) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        symbol = self._proposal_symbol(proposal)
        period = {
            "start": str(payload.get("backtest_start") or payload.get("since_date") or "2026-04-01"),
            "end": str(payload.get("backtest_end") or payload.get("end_date") or "") or None,
        }
        if not symbol:
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="backtest",
                status="FAILED",
                input_payload={"required_symbol": True},
                period=period,
                metrics={},
                result={},
                error="No se pudo inferir un simbolo para ejecutar backtest.",
            )
        try:
            report = build_symbol_backtest(
                symbol,
                self.settings.data_dir / "reports",
                new_id("ci_bt"),
                start=str(period["start"]),
                end=period["end"],
                min_score=int(payload.get("min_score") or self.settings.entry_quality_min_score),
                setup_quality=str(payload.get("setup_quality") or "strong"),
                max_holding_days=int(payload.get("max_holding_days") or 10),
                benchmark_symbol=str(payload.get("benchmark_symbol") or self.settings.benchmark_symbol),
                provider=self.settings.market_data_provider,
                fmp_api_key=self.settings.fmp_api_key,
                gate_config={
                    "min_trades": self.settings.backtest_gate_min_trades,
                    "min_hit_rate": self.settings.backtest_gate_min_hit_rate,
                    "min_profit_factor": self.settings.backtest_gate_min_profit_factor,
                    "max_drawdown": self.settings.backtest_gate_max_drawdown,
                    "min_alpha_vs_benchmark": self.settings.backtest_gate_min_alpha_vs_benchmark,
                    "min_trade_window_alpha": self.settings.backtest_gate_min_trade_window_alpha,
                    "min_regime_trades": self.settings.backtest_gate_min_regime_trades,
                    "max_negative_regimes": self.settings.backtest_gate_max_negative_regimes,
                },
            )
            validation = report.get("validation") if isinstance(report, dict) else {}
            approved = bool((validation or {}).get("gate", {}).get("approved", False))
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="backtest",
                status="PASSED" if approved else "COMPLETED",
                input_payload={"symbol": symbol, "payload": payload},
                period=period,
                metrics=report.get("metrics", {}) if isinstance(report, dict) else {},
                result=report if isinstance(report, dict) else {},
                artifact_path=str((report or {}).get("path") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="backtest",
                status="FAILED",
                input_payload={"symbol": symbol, "payload": payload},
                period=period,
                metrics={},
                result={},
                error=str(exc),
            )

    def _run_session_retrospective(self, *, proposal: dict[str, Any], cycle_id: str, initiative_id: str | None) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        period = {"since_date": str(payload.get("since_date") or "2026-04-01"), "end_date": str(payload.get("end_date") or "") or None}
        try:
            report = build_session_retrospective_report(
                self.settings,
                self.store,
                self.settings.data_dir / "reports",
                new_id("ci_sr"),
                since_date=period["since_date"],
                end_date=period["end_date"],
                sessions=int(payload.get("sessions") or 8),
                policy=str(payload.get("policy") or "proposed"),
                full=False,
            )
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="baseline_compare",
                status="COMPLETED",
                input_payload={"payload": payload},
                period=period,
                metrics=report.get("metrics", {}) if isinstance(report, dict) else {},
                result=report if isinstance(report, dict) else {},
                artifact_path=str((report or {}).get("path") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="baseline_compare",
                status="FAILED",
                input_payload={"payload": payload},
                period=period,
                metrics={},
                result={},
                error=str(exc),
            )

    def _run_walk_forward(self, *, proposal: dict[str, Any], cycle_id: str, initiative_id: str | None) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        period = {"since_date": str(payload.get("since_date") or "2026-04-01"), "end_date": str(payload.get("end_date") or "") or None}
        try:
            report = build_walk_forward_validation_report(
                self.settings,
                self.store,
                self.settings.data_dir / "reports",
                new_id("ci_wf"),
                since_date=period["since_date"],
                end_date=period["end_date"],
                policy=str(payload.get("policy") or "proposed"),
                train_days=int(payload.get("train_days") or 5),
                test_days=int(payload.get("test_days") or 3),
                full=False,
            )
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="shadow_review",
                status="COMPLETED",
                input_payload={"payload": payload},
                period=period,
                metrics=report.get("metrics", {}) if isinstance(report, dict) else {},
                result=report if isinstance(report, dict) else {},
                artifact_path=str((report or {}).get("path") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            return self._base_experiment(
                proposal=proposal,
                cycle_id=cycle_id,
                initiative_id=initiative_id,
                experiment_type="shadow_review",
                status="FAILED",
                input_payload={"payload": payload},
                period=period,
                metrics={},
                result={},
                error=str(exc),
            )

    def _record_report_experiment(
        self,
        *,
        proposal: dict[str, Any],
        cycle_id: str,
        initiative_id: str | None,
        experiment_type: str,
        artifact_path: str,
    ) -> dict[str, Any]:
        return self._base_experiment(
            proposal=proposal,
            cycle_id=cycle_id,
            initiative_id=initiative_id,
            experiment_type=experiment_type,
            status="COMPLETED",
            input_payload={"source": artifact_path},
            period={},
            metrics={},
            result={"artifact_path": artifact_path},
            artifact_path=artifact_path,
        )


class AutoApplyConfigAgent:
    ALLOWED_TARGETS = {
        "ENTRY_QUALITY_MAX_RSI": "entry_quality_max_rsi",
        "ENTRY_QUALITY_MAX_SMA20_DISTANCE": "entry_quality_max_sma20_distance",
        "ENTRY_QUALITY_MIN_SCORE": "entry_quality_min_score",
        "CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS": "continuous_improvement_runtime_interval_seconds",
        "CONTINUOUS_IMPROVEMENT_MAX_PROPOSALS_PER_CYCLE": "continuous_improvement_max_proposals_per_cycle",
        "MARKET_DATA_PROVIDER": "market_data_provider",
        "RISK_BUDGET_DAILY_VAR_PCT": "risk_budget_daily_var_pct",
        "RISK_BUDGET_MAX_NEW_RISK_PER_DAY_PCT": "risk_budget_max_new_risk_per_day_pct",
        "RISK_BUDGET_MAX_CORRELATED_CLUSTER_PCT": "risk_budget_max_correlated_cluster_pct",
    }
    FORBIDDEN_TERMS = {"LIVE_TRADING", "BROKER", "ALPACA", "OPENAI", "API_KEY", "SECRET", "ORDER", "TRADING_MODE"}

    def try_apply(
        self,
        *,
        settings: Settings,
        store: Store,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        target_key = self._target_key(proposal)
        base = {
            "applied_change_id": new_id("ci_apply"),
            "initiative_id": (initiative or {}).get("initiative_id"),
            "proposal_id": proposal.get("proposal_id"),
            "cycle_id": proposal.get("cycle_id"),
            "change_type": "CONFIG_CHANGE",
            "target_key": target_key,
            "validation_ids": [validation.get("validation_id")] if validation.get("validation_id") else [],
            "decision": {
                "actor": "AutoApplyConfigAgent",
                "validation_status": validation.get("status"),
                "objective_status": (validation.get("payload") or {}).get("objective_status"),
            },
        }
        blocked_reason = self._blocked_reason(settings=settings, initiative=initiative, proposal=proposal, target_key=target_key)
        if blocked_reason:
            item = {
                **base,
                "status": "BLOCKED",
                "before": {},
                "after": {},
                "rollback": {},
                "error": blocked_reason,
            }
            store.save_continuous_improvement_applied_change(item)
            return item

        attr = self.ALLOWED_TARGETS[target_key]
        before_value = getattr(settings, attr, None)
        proposed_value = payload.get("proposed_value")
        item = {
            **base,
            "status": "APPLIED",
            "before": {"setting": attr, "value": before_value},
            "after": {"setting": attr, "value": proposed_value},
            "rollback": {"restore": {"setting": attr, "value": before_value}},
            "error": None,
        }
        store.save_continuous_improvement_applied_change(item)
        return item

    def _target_key(self, proposal: dict[str, Any]) -> str:
        payload = proposal.get("payload", {}) or {}
        raw = str(payload.get("target_identifier") or proposal.get("target_identifier") or payload.get("target_component") or "")
        normalized = re.sub(r"[^A-Z0-9]+", "_", raw.upper()).strip("_")
        return normalized

    def _blocked_reason(
        self,
        *,
        settings: Settings,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        target_key: str,
    ) -> str | None:
        payload = proposal.get("payload", {}) or {}
        if getattr(settings, "system_freeze_mode", False):
            return "system_freeze"
        if not settings.allow_auto_apply_improvements:
            return "ALLOW_AUTO_APPLY_IMPROVEMENTS=false"
        if settings.allow_live_trading:
            return "ALLOW_LIVE_TRADING=true bloquea autoapply"
        if proposal.get("proposal_type") == "CODE_CHANGE":
            return "CODE_CHANGE requiere revision humana"
        if str(proposal.get("risk_level") or payload.get("risk_level") or "").upper() != "LOW":
            return "Solo se autoaplican cambios LOW"
        if (initiative or {}).get("status") != "READY_TO_APPLY":
            return "La iniciativa no esta READY_TO_APPLY"
        if not str(payload.get("rollback_plan") or "").strip():
            return "Falta rollback_plan"
        if target_key not in self.ALLOWED_TARGETS:
            return f"{target_key or 'target'} no esta en allowlist"
        if any(term in target_key for term in self.FORBIDDEN_TERMS):
            return f"{target_key} contiene termino prohibido"
        return None


class AutoApplyCodeAgent:
    """Applies small, reversible code changes after deterministic gates pass.

    El allowlist ya no es fijo: depende del nivel de autonomia vigente (T1.1),
    resuelto por ``continuous_improvement/autonomy.py``. ``BLOCKED_PREFIXES`` se
    mantiene como las rutas bloqueadas SIEMPRE (compatibilidad y kernel test).
    """

    # Compatibilidad: rutas bloqueadas en todos los niveles.
    BLOCKED_PREFIXES = ALWAYS_BLOCKED_PREFIXES
    BLOCKED_EXACT = ALWAYS_BLOCKED_EXACT

    def try_apply(
        self,
        *,
        settings: Settings,
        store: Store,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica un cambio autonomo.

        Si el sandbox git real esta habilitado y el workspace es un repo git,
        usa `GitSandbox` (rama aislada + suite completa + merge revertible).
        En cualquier otro caso (p. ej. tests con workspace no-git) cae al
        camino legacy de snapshot/restore.
        """

        workspace = settings.improvement_workspace_dir
        if getattr(settings, "ci_sandbox_enabled", True) and sandbox_supported(workspace):
            return self._sandbox_apply(
                settings=settings,
                store=store,
                initiative=initiative,
                proposal=proposal,
                validation=validation,
            )
        return self._legacy_apply(
            settings=settings,
            store=store,
            initiative=initiative,
            proposal=proposal,
            validation=validation,
        )

    def _apply_base(
        self,
        *,
        settings: Settings,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        workspace = settings.improvement_workspace_dir
        target_key = str(proposal.get("target_component") or payload.get("target_component") or "code")
        return {
            "applied_change_id": new_id("ci_apply"),
            "initiative_id": (initiative or {}).get("initiative_id"),
            "proposal_id": proposal.get("proposal_id"),
            "cycle_id": proposal.get("cycle_id"),
            "change_type": "CODE_CHANGE",
            "target_key": target_key,
            "validation_ids": [validation.get("validation_id")] if validation.get("validation_id") else [],
            "decision": {
                "actor": "AutoApplyCodeAgent",
                "validation_status": validation.get("status"),
                "workspace": str(workspace),
            },
        }

    def _sandbox_apply(
        self,
        *,
        settings: Settings,
        store: Store,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        workspace = settings.improvement_workspace_dir
        base = self._apply_base(settings=settings, initiative=initiative, proposal=proposal, validation=validation)

        blocked_reason = self._blocked_reason(settings=settings, proposal=proposal, validation=validation)
        if blocked_reason:
            return self._save(store, base, status="BLOCKED", error=blocked_reason)

        file_edits = payload.get("file_edits") or payload.get("files")
        patch_text = str(payload.get("patch") or "").strip()

        # Validacion de rutas ANTES de crear el worktree: un cambio a una ruta
        # bloqueada (p. ej. kernel.py) se rechaza sin abrir sandbox.
        level = active_autonomy_level(store, settings)
        base["decision"]["autonomy_level"] = level
        targets = self._target_paths(workspace, file_edits=file_edits, patch_text=patch_text)
        path_error = self._validate_paths(workspace, targets, level)
        if path_error:
            return self._save(store, base, status="BLOCKED", error=path_error)
        ast_error = self._ast_import_violation(workspace, file_edits)
        if ast_error:
            return self._save(store, base, status="BLOCKED", error=ast_error)

        sandbox = GitSandbox(settings, repo_root=workspace)
        change_id = str(base["applied_change_id"])
        try:
            sandbox.open(change_id)
            sandbox.apply(file_edits, patch_text)
            validation_result = sandbox.validate()
        except (GitSandboxError, ValueError, RuntimeError) as exc:
            sandbox.destroy()
            return self._save(store, base, status="FAILED", error=f"{type(exc).__name__}: {exc}")

        if not validation_result.get("ok"):
            self._persist_sandbox_artifacts(store, proposal, validation_result)
            sandbox.destroy()
            return self._save(
                store,
                base,
                status="REJECTED_BY_TESTS",
                rollback={"reason": "sandbox_validation_failed"},
                decision={**base["decision"], "sandbox": validation_result},
                error=self._summarize_validation_failure(validation_result),
            )

        try:
            merge_result = sandbox.merge()
        except GitSandboxError as exc:
            sandbox.destroy()
            return self._save(store, base, status="FAILED", error=f"merge fallo: {exc}")
        sandbox.destroy()
        return self._save(
            store,
            base,
            status="APPLIED",
            after={"git": merge_result},
            rollback={"git": merge_result},
            decision={**base["decision"], "sandbox": validation_result, "git": merge_result},
        )

    def _persist_sandbox_artifacts(
        self,
        store: Store,
        proposal: dict[str, Any],
        validation_result: dict[str, Any],
    ) -> None:
        proposal_id = proposal.get("proposal_id")
        if not proposal_id:
            return
        for step in validation_result.get("steps", []):
            try:
                store.save_continuous_improvement_proposal_artifact(
                    {
                        "artifact_id": new_id("ci_artifact"),
                        "proposal_id": proposal_id,
                        "artifact_type": f"sandbox_{step.get('step', 'step')}_log",
                        "content_text": str(step.get("output") or "")[-6000:],
                        "payload": {"returncode": step.get("returncode"), "ok": step.get("ok")},
                    }
                )
            except Exception:  # noqa: BLE001 - los artefactos no deben tumbar el flujo.
                continue

    @staticmethod
    def _summarize_validation_failure(validation_result: dict[str, Any]) -> str:
        failed = [item for item in validation_result.get("steps", []) if not item.get("ok")]
        if not failed:
            return "Validacion del sandbox fallida."
        last = failed[-1]
        return f"sandbox:{last.get('step')} rc={last.get('returncode')}: {str(last.get('output') or '')[-2000:]}"

    def _legacy_apply(
        self,
        *,
        settings: Settings,
        store: Store,
        initiative: dict[str, Any] | None,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        payload = proposal.get("payload", {}) or {}
        workspace = settings.improvement_workspace_dir
        target_key = str(proposal.get("target_component") or payload.get("target_component") or "code")
        base = {
            "applied_change_id": new_id("ci_apply"),
            "initiative_id": (initiative or {}).get("initiative_id"),
            "proposal_id": proposal.get("proposal_id"),
            "cycle_id": proposal.get("cycle_id"),
            "change_type": "CODE_CHANGE",
            "target_key": target_key,
            "validation_ids": [validation.get("validation_id")] if validation.get("validation_id") else [],
            "decision": {
                "actor": "AutoApplyCodeAgent",
                "validation_status": validation.get("status"),
                "workspace": str(workspace),
            },
        }
        blocked_reason = self._blocked_reason(settings=settings, proposal=proposal, validation=validation)
        if blocked_reason:
            return self._save(store, base, status="BLOCKED", error=blocked_reason)

        level = active_autonomy_level(store, settings)
        base["decision"]["autonomy_level"] = level
        file_edits = payload.get("file_edits") or payload.get("files")
        patch_text = str(payload.get("patch") or "").strip()
        test_commands = [str(item) for item in payload.get("test_commands", []) or [] if str(item).strip()]
        if not test_commands:
            test_commands = ["python -m pytest tests/test_continuous_improvement.py"]

        try:
            targets = self._target_paths(workspace, file_edits=file_edits, patch_text=patch_text)
            path_error = self._validate_paths(workspace, targets, level)
            if path_error:
                return self._save(store, base, status="BLOCKED", error=path_error)
            ast_error = self._ast_import_violation(workspace, file_edits)
            if ast_error:
                return self._save(store, base, status="BLOCKED", error=ast_error)
            dirty_error = self._dirty_targets(workspace, targets)
            if dirty_error:
                return self._save(store, base, status="BLOCKED", error=dirty_error)

            before = self._snapshot(workspace, targets)
            self._apply_payload(workspace, file_edits=file_edits, patch_text=patch_text)
            after = self._snapshot(workspace, targets)
            test_result = self._run_tests(workspace, test_commands)
            if test_result["returncode"] != 0:
                self._restore_snapshot(workspace, before)
                return self._save(
                    store,
                    base,
                    status="ROLLED_BACK",
                    before=before,
                    after=after,
                    rollback={"restore": before, "reason": "tests_failed"},
                    error=test_result["output"],
                    decision={**base["decision"], "tests": test_result},
                )
            return self._save(
                store,
                base,
                status="APPLIED",
                before=before,
                after=after,
                rollback={"restore": before},
                decision={**base["decision"], "tests": test_result},
            )
        except Exception as exc:  # noqa: BLE001
            return self._save(store, base, status="FAILED", error=f"{type(exc).__name__}: {exc}")

    def rollback(
        self,
        *,
        settings: Settings,
        store: Store,
        applied_change_id: str,
        actor: str = "api",
    ) -> dict[str, Any] | None:
        change = next(
            (
                item
                for item in store.continuous_improvement_applied_changes(limit=10000)
                if item["applied_change_id"] == applied_change_id
            ),
            None,
        )
        if not change:
            return None
        if change.get("change_type") != "CODE_CHANGE":
            return store.rollback_continuous_improvement_applied_change(applied_change_id, actor=actor)
        git_info = (change.get("rollback") or {}).get("git")
        if isinstance(git_info, dict) and git_info.get("commit"):
            return self._git_revert(settings=settings, store=store, change=change, git_info=git_info, actor=actor)
        restore = (change.get("rollback") or {}).get("restore")
        if not isinstance(restore, dict):
            change["status"] = "ROLLBACK_FAILED"
            change["error"] = "No hay snapshot de rollback para restaurar."
            store.save_continuous_improvement_applied_change(change)
            return change
        workspace = settings.improvement_workspace_dir
        targets = [(workspace / rel).resolve() for rel in (restore.get("files") or {}).keys()]
        # Restaurar un snapshot ya aplicado: validar al nivel maximo (no es una
        # escalada de privilegios, solo se revierten archivos ya permitidos).
        path_error = self._validate_paths(workspace, targets, 3)
        if path_error:
            change["status"] = "ROLLBACK_FAILED"
            change["error"] = path_error
            store.save_continuous_improvement_applied_change(change)
            return change
        self._restore_snapshot(workspace, restore)
        change["status"] = "ROLLED_BACK"
        change["after"] = restore
        change["decision"] = {
            **(change.get("decision") or {}),
            "rollback_actor": actor,
            "rollback_at": datetime.now(timezone.utc).isoformat(),
        }
        store.save_continuous_improvement_applied_change(change)
        return change

    def _git_revert(
        self,
        *,
        settings: Settings,
        store: Store,
        change: dict[str, Any],
        git_info: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """Revierte un cambio fusionado (T0.3) con `git revert` + re-suite."""

        workspace = settings.improvement_workspace_dir
        commit = str(git_info.get("commit"))
        sandbox = GitSandbox(settings, repo_root=workspace)
        # Un commit de merge requiere -m 1 (mainline). Si no es merge, git lo
        # ignora y revierte normal; probamos primero con -m 1 y caemos a simple.
        revert_ok = False
        revert_error = ""
        for args in (["revert", "--no-edit", "-m", "1", commit], ["revert", "--no-edit", commit]):
            result = sandbox._git(
                "-c", "user.email=ci-bot@agente-bolsa.local", "-c", "user.name=ci-auto", *args
            )
            if result.returncode == 0:
                revert_ok = True
                break
            revert_error = (result.stderr or result.stdout).strip()
            sandbox._git("revert", "--abort")
        if not revert_ok:
            change["status"] = "ROLLBACK_FAILED"
            change["error"] = f"git revert fallo: {revert_error}"
            store.save_continuous_improvement_applied_change(change)
            return change

        revert_commit = sandbox._git("rev-parse", "HEAD").stdout.strip()
        # Re-ejecutar la suite tras el revert para confirmar arbol verde.
        from .sandbox import run_validation_steps

        suite = run_validation_steps(settings, workspace)
        change["status"] = "ROLLED_BACK"
        change["decision"] = {
            **(change.get("decision") or {}),
            "rollback_actor": actor,
            "rollback_at": datetime.now(timezone.utc).isoformat(),
            "rollback_strategy": "git_revert",
            "revert_commit": revert_commit,
            "rollback_suite_ok": suite.get("ok"),
        }
        store.save_continuous_improvement_applied_change(change)
        return change

    def _save(
        self,
        store: Store,
        base: dict[str, Any],
        *,
        status: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
        decision: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        item = {
            **base,
            "status": status,
            "before": before or {},
            "after": after or {},
            "rollback": rollback or {},
            "decision": decision or base.get("decision", {}),
            "error": error,
        }
        store.save_continuous_improvement_applied_change(item)
        return item

    def _blocked_reason(self, *, settings: Settings, proposal: dict[str, Any], validation: dict[str, Any]) -> str | None:
        if getattr(settings, "system_freeze_mode", False):
            return "system_freeze"
        if not settings.allow_auto_apply_improvements:
            return "ALLOW_AUTO_APPLY_IMPROVEMENTS=false"
        if settings.improvement_dry_run:
            return "IMPROVEMENT_DRY_RUN=true"
        if settings.allow_live_trading:
            return "ALLOW_LIVE_TRADING=true bloquea autoapply"
        if settings.require_human_approval_for_code_changes:
            return "REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true"
        if proposal.get("proposal_type") != "CODE_CHANGE":
            return "Solo aplica CODE_CHANGE"
        if str(proposal.get("risk_level") or "").upper() == "HIGH":
            return "CODE_CHANGE HIGH requiere revision humana"
        if validation.get("status") != "READY_TO_APPLY":
            return "La validacion no esta READY_TO_APPLY"
        payload = proposal.get("payload", {}) or {}
        if not str(payload.get("rollback_plan") or "").strip():
            return "Falta rollback_plan"
        if not (payload.get("file_edits") or payload.get("files") or str(payload.get("patch") or "").strip()):
            return "Falta patch o file_edits aplicable"
        return None

    def _target_paths(self, workspace: Path, *, file_edits: Any, patch_text: str) -> list[Path]:
        targets: list[Path] = []
        if isinstance(file_edits, list):
            for item in file_edits:
                if isinstance(item, dict) and item.get("path"):
                    targets.append((workspace / str(item["path"])).resolve())
        for match in re.finditer(r"^\+\+\+\s+b/(.+)$", patch_text, flags=re.MULTILINE):
            targets.append((workspace / match.group(1).strip()).resolve())
        return sorted(set(targets))

    def _validate_paths(self, workspace: Path, targets: list[Path], level: int = 1) -> str | None:
        if not targets:
            return "No hay archivos objetivo"
        workspace = workspace.resolve()
        for path in targets:
            try:
                rel = path.resolve().relative_to(workspace).as_posix()
            except ValueError:
                return f"{path} queda fuera del workspace"
            violation = path_violation(rel, level)
            if violation:
                return violation
        return None

    def _ast_import_violation(self, workspace: Path, file_edits: Any) -> str | None:
        """Rechaza ediciones que introducen imports de broker/execution nuevos."""

        if not isinstance(file_edits, list):
            return None
        workspace = workspace.resolve()
        for item in file_edits:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            rel = str(item["path"])
            if not rel.endswith(".py") or "content" not in item:
                continue
            existing = workspace / rel
            before_text = existing.read_text(encoding="utf-8") if existing.exists() else ""
            violation = ast_import_violation(before_text, str(item.get("content") or ""))
            if violation:
                return f"{rel}: {violation}"
        return None

    def _dirty_targets(self, workspace: Path, targets: list[Path]) -> str | None:
        if not (workspace / ".git").exists() or shutil.which("git") is None:
            return None
        rels = [path.resolve().relative_to(workspace.resolve()).as_posix() for path in targets if path.exists()]
        if not rels:
            return None
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *rels],
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return f"No se pudo comprobar git status: {result.stderr.strip()}"
        if result.stdout.strip():
            return "Working tree sucio en archivos objetivo"
        return None

    def _snapshot(self, workspace: Path, targets: list[Path]) -> dict[str, Any]:
        files: dict[str, Any] = {}
        for path in targets:
            rel = path.resolve().relative_to(workspace.resolve()).as_posix()
            files[rel] = {
                "exists": path.exists(),
                "content": path.read_text(encoding="utf-8") if path.exists() else None,
            }
        return {"files": files}

    def _restore_snapshot(self, workspace: Path, snapshot: dict[str, Any]) -> None:
        for rel, item in (snapshot.get("files") or {}).items():
            path = workspace / rel
            if item.get("exists"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(item.get("content") or ""), encoding="utf-8")
            elif path.exists():
                path.unlink()

    def _apply_payload(self, workspace: Path, *, file_edits: Any, patch_text: str) -> None:
        # T5.8: el camino legacy JAMAS escribe sobre el repo principal. Esa via
        # es solo para entornos sin git (tests con workspace temporal); en
        # produccion la unica via de escritura es el worktree del GitSandbox.
        if Path(workspace).resolve() == Path(__file__).resolve().parents[3]:
            raise RuntimeError(
                "Escritura directa sobre el repo principal prohibida (T5.8): usa el GitSandbox."
            )
        if isinstance(file_edits, list) and file_edits:
            for item in file_edits:
                if not isinstance(item, dict) or not item.get("path"):
                    raise ValueError("file_edits invalido")
                path = workspace / str(item["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                if "content" in item:
                    path.write_text(str(item["content"]), encoding="utf-8")
                    continue
                old = str(item.get("old") or "")
                new = str(item.get("new") or "")
                current = path.read_text(encoding="utf-8")
                if old not in current:
                    raise ValueError(f"No se encontro bloque old en {item['path']}")
                path.write_text(current.replace(old, new, 1), encoding="utf-8")
            return
        if patch_text:
            if shutil.which("git") is None:
                raise RuntimeError("git no disponible para aplicar patch")
            result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=workspace,
                input=patch_text,
                text=True,
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git apply fallo")
            return
        raise ValueError("Falta patch o file_edits aplicable")

    def _run_tests(self, workspace: Path, commands: list[str]) -> dict[str, Any]:
        outputs: list[dict[str, Any]] = []
        for command in commands:
            result = subprocess.run(
                command,
                cwd=workspace,
                shell=True,
                text=True,
                capture_output=True,
                timeout=300,
            )
            output = (result.stdout + "\n" + result.stderr).strip()
            outputs.append({"command": command, "returncode": result.returncode, "output": output[-4000:]})
            if result.returncode != 0:
                return {"returncode": result.returncode, "commands": outputs, "output": output[-4000:]}
        return {"returncode": 0, "commands": outputs, "output": "\n".join(item["output"] for item in outputs)[-4000:]}
