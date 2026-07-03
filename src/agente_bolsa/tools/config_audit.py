"""Auditoria de configuracion efectiva (P28).

Automatiza la seccion 1 del informe P26: valores efectivos vs defaults de
codigo, configs file-based de ``data/config/`` y un bloque ``safety`` con los
flags criticos. Read-only: no modifica nada.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agente_bolsa.config import Settings

AUDIT_FIELDS: tuple[str, ...] = (
    "trading_mode",
    "allow_live_trading",
    "auto_paper_trading",
    "require_human_approval",
    "allow_auto_apply_improvements",
    "improvement_dry_run",
    "continuous_improvement_enabled",
    "continuous_improvement_schedule_enabled",
    "continuous_improvement_max_proposals_per_cycle",
    "continuous_improvement_runtime_interval_seconds",
    "continuous_improvement_group_cooldown_seconds",
    "ci_max_open_initiatives",
    "ci_recurring_cooldown_hours",
    "ci_task_ttl_hours",
    "ci_validation_backlog_ttl_days",
    "ci_build_strategy_enabled",
    "ci_sandbox_enabled",
    "code_autonomy_level",
    "require_human_approval_for_code_changes",
    "require_human_approval_for_high_risk",
    "improvement_llm_enabled",
    "improvement_llm_provider",
    "improvement_llm_model",
    "improvement_llm_orchestrator_model",
    "improvement_llm_max_tokens",
    "improvement_llm_context_target_tokens",
    "llm_daily_budget_usd",
    "llm_role_deep_daily_budget_usd",
    "overnight_learning_enabled",
    "overnight_learning_use_llm",
    "overnight_learning_time_local",
    "overnight_learning_stale_llm_alert_hours",
    "trade_aggressiveness_profile",
    "max_orders_per_cycle",
    "max_daily_buy_orders",
    "min_llm_confidence_to_trade",
    "entry_quality_gate_enabled",
    "backtest_gate_enabled",
    "pre_earnings_enabled",
)

FILE_CONFIGS: dict[str, str] = {
    "core_sleeve": "config/core_sleeve.json",
    "lab_book": "config/lab_book.json",
    "ci_research_mode": "config/ci_research_mode.json",
    "codegen_nightly": "config/codegen_nightly.json",
    "cast_governance": "config/cast_governance.json",
}

# Flags criticos: (nombre, valor esperado seguro).
ENV_SAFETY_EXPECTATIONS: tuple[tuple[str, Any], ...] = (
    ("trading_mode", "paper"),
    ("allow_live_trading", False),
    ("allow_auto_apply_improvements", False),
)


def _read_file_config(data_dir: Path, relative: str) -> dict[str, Any] | None:
    path = Path(data_dir) / relative
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"_error": "no parseable"}
    return raw if isinstance(raw, dict) else {"_error": "no es objeto"}


def _field_default(field_name: str) -> Any:
    field = Settings.model_fields.get(field_name)
    if field is None:
        return None
    default = getattr(field, "default", None)
    if default is not None and default.__class__.__name__ == "PydanticUndefinedType":
        return "(requerido)"
    if default is None and getattr(field, "default_factory", None) is not None:
        return "(factory)"
    return default


def build_config_audit(settings: Settings) -> dict[str, Any]:
    """Construye la auditoria completa: campos, configs file-based y safety."""
    rows: list[dict[str, Any]] = []
    for name in AUDIT_FIELDS:
        if not hasattr(settings, name):
            continue
        effective = getattr(settings, name)
        default = _field_default(name)
        rows.append(
            {
                "field": name,
                "effective": effective,
                "default": default,
                "divergent": default not in ("(requerido)", "(factory)") and effective != default,
            }
        )

    data_dir = Path(settings.data_dir)
    file_configs: dict[str, Any] = {}
    for label, relative in FILE_CONFIGS.items():
        file_configs[label] = _read_file_config(data_dir, relative)

    checks: list[dict[str, Any]] = []
    for name, expected in ENV_SAFETY_EXPECTATIONS:
        value = getattr(settings, name, None)
        checks.append({"name": name, "value": value, "expected": expected, "ok": value == expected})
    core_sleeve = file_configs.get("core_sleeve")
    if isinstance(core_sleeve, dict) and "_error" not in core_sleeve:
        checks.append(
            {
                "name": "core_sleeve.dry_run",
                "value": core_sleeve.get("dry_run"),
                "expected": True,
                "ok": bool(core_sleeve.get("dry_run")) is True,
            }
        )
    safety = {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "violations": [check["name"] for check in checks if not check["ok"]],
    }
    return {
        "fields": rows,
        "divergent_count": sum(1 for row in rows if row["divergent"]),
        "file_configs": file_configs,
        "safety": safety,
    }


def format_config_audit_text(audit: dict[str, Any]) -> str:
    lines = ["Auditoria de configuracion efectiva", ""]
    safety = audit.get("safety") or {}
    if safety.get("ok"):
        lines.append("Safety: OK (paper, live off, auto-apply off, sleeve dry-run)")
    else:
        lines.append(f"Safety: ALERTA -> {', '.join(safety.get('violations') or ['sin datos'])}")
    lines.append("")
    lines.append("| Campo | Efectivo | Default | Divergente |")
    lines.append("|---|---|---|---|")
    for row in audit.get("fields") or []:
        marker = "SI" if row.get("divergent") else "no"
        lines.append(f"| {row['field']} | {row['effective']} | {row['default']} | {marker} |")
    lines.append("")
    lines.append("Configs file-based (data/config):")
    for label, payload in (audit.get("file_configs") or {}).items():
        if payload is None:
            lines.append(f"- {label}: (ausente)")
        elif "_error" in payload:
            lines.append(f"- {label}: ERROR {payload['_error']}")
        else:
            keys = ("enabled", "dry_run", "mode", "human_gated")
            summary = ", ".join(f"{k}={payload[k]}" for k in keys if k in payload)
            lines.append(f"- {label}: {summary or 'ok'}")
    return "\n".join(lines) + "\n"


def digest_safety_summary(settings: Settings) -> dict[str, Any] | None:
    """Bloque safety para el digest diario; nunca lanza."""
    try:
        return build_config_audit(settings)["safety"]
    except Exception:  # noqa: BLE001 - el digest no debe caer por la auditoria
        return None
