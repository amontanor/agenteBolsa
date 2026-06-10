"""Niveles de autonomia de codigo y promocion por historial (T1.1).

Sustituye el allowlist fijo de `AutoApplyCodeAgent` por niveles progresivos. El
sistema gana permisos solo, en funcion de su propio historial de fiabilidad
(cambios aplicados sin rollbacks y `iq_score` estable o creciente), y los pierde
si acumula rollbacks. El kernel (T0.1) sigue siendo el suelo absoluto: subir de
nivel jamas habilita tocar `kernel.py`, `broker.py`, `execution.py`, etc.

Nucleo stdlib (incluye `ast`) para ser testeable sin red ni LLM.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..config import Settings
    from ..storage import Store


RUNTIME_LEVEL_KEY = "code_autonomy_level"
MIN_LEVEL = 1
MAX_LEVEL = 3

# Bloqueado SIEMPRE, en todos los niveles. El kernel es el suelo absoluto.
ALWAYS_BLOCKED_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    "data/",
    "logs/",
    ".github/",
    "sandboxes/",
    "src/agente_bolsa/kernel.py",
    "src/agente_bolsa/tools/broker.py",
    "src/agente_bolsa/tools/execution.py",
    "src/agente_bolsa/tools/risk.py",
    "src/agente_bolsa/config.py",
)
ALWAYS_BLOCKED_EXACT: frozenset[str] = frozenset({".env"})

# Allowlist del nivel 1 (el comportamiento actual).
_LEVEL1_ALLOWED: tuple[str, ...] = (
    "src/agente_bolsa/continuous_improvement/",
    "src/agente_bolsa/tools/operational_",
    "src/agente_bolsa/tools/reporting.py",
    "src/agente_bolsa/tools/retention.py",
    "tests/",
    "docs/",
    ".env.example",
)

# Archivos del nucleo de decision: solo editables en nivel 3.
_LEVEL3_ONLY: frozenset[str] = frozenset(
    {
        "src/agente_bolsa/tools/trade_decision.py",
        "src/agente_bolsa/tools/position_sizing.py",
        "src/agente_bolsa/tools/portfolio_optimizer.py",
        "src/agente_bolsa/scheduler.py",
    }
)

_FULL_BLOCKED_TERMS = {
    "API_KEY",
    "SECRET",
    "TOKEN",
    "LIVE_TRADING",
    "TRADING_MODE",
    "ALPACA",
    "BROKER",
    "ORDER",
    "EXECUTION",
}
# En nivel >=2 dejan de ser terminos prohibidos (impedian trabajo legitimo).
_RELAXED_BLOCKED_TERMS = _FULL_BLOCKED_TERMS - {"ORDER", "EXECUTION"}

AUTONOMY_TIERS: dict[int, dict[str, Any]] = {
    1: {"allowed_prefixes": _LEVEL1_ALLOWED, "blocked_terms": frozenset(_FULL_BLOCKED_TERMS)},
    2: {
        "allowed_prefixes": _LEVEL1_ALLOWED
        + ("src/agente_bolsa/tools/", "src/agente_bolsa/strategies/"),
        "blocked_terms": frozenset(_RELAXED_BLOCKED_TERMS),
    },
    3: {
        "allowed_prefixes": _LEVEL1_ALLOWED
        + (
            "src/agente_bolsa/tools/",
            "src/agente_bolsa/strategies/",
            "src/agente_bolsa/config/",  # prompts (tasks.yaml/agents.yaml)
        )
        + tuple(sorted(_LEVEL3_ONLY)),
        "blocked_terms": frozenset(_RELAXED_BLOCKED_TERMS),
    },
}


def clamp_level(level: int) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, int(level)))


def active_autonomy_level(store: "Store", settings: "Settings") -> int:
    override = None
    try:
        override = store.get_runtime_value(RUNTIME_LEVEL_KEY)
    except Exception:  # noqa: BLE001 - sin runtime_state usamos el setting.
        override = None
    if isinstance(override, dict):
        override = override.get("level")
    if isinstance(override, (int, float)):
        return clamp_level(int(override))
    return clamp_level(int(getattr(settings, "code_autonomy_level", 1)))


def path_violation(rel: str, level: int) -> str | None:
    """Devuelve el motivo de bloqueo de una ruta para un nivel, o None si pasa."""

    rel = rel.replace("\\", "/")
    if rel in ALWAYS_BLOCKED_EXACT or any(rel.startswith(prefix) for prefix in ALWAYS_BLOCKED_PREFIXES):
        return f"{rel} esta bloqueado (siempre)"
    if level < 3 and rel in _LEVEL3_ONLY:
        return f"{rel} requiere nivel de autonomia 3 (actual {level})"
    tier = AUTONOMY_TIERS.get(clamp_level(level), AUTONOMY_TIERS[1])
    allowed = tier["allowed_prefixes"]
    if not any(rel == prefix or rel.startswith(prefix) for prefix in allowed):
        return f"{rel} no esta en allowlist del nivel {level}"
    upper = rel.upper()
    for term in tier["blocked_terms"]:
        if term in upper:
            return f"{rel} contiene termino protegido ({term})"
    return None


def _imports_broker_or_execution(source: str) -> set[str]:
    """Modulos sensibles importados (tools.broker / tools.execution)."""

    found: set[str] = set()
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return found
    sensitive = ("tools.broker", "tools.execution", "agente_bolsa.tools.broker", "agente_bolsa.tools.execution")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module.endswith(s) or module == s for s in ("tools.broker", "tools.execution")) or any(
                module.endswith(s) for s in sensitive
            ):
                found.add(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.endswith(s) for s in ("tools.broker", "tools.execution")):
                    found.add(alias.name)
    return found


def ast_import_violation(before_text: str, after_text: str) -> str | None:
    """Rechaza diffs que introducen imports de broker/execution no presentes antes."""

    before = _imports_broker_or_execution(before_text or "")
    after = _imports_broker_or_execution(after_text or "")
    new_imports = after - before
    if new_imports:
        return f"introduce imports sensibles no presentes antes: {sorted(new_imports)}"
    return None


def _recent_watchdog_rollbacks(store: "Store", sessions: int) -> int:
    """Cuenta rollbacks recientes ejecutados por el watchdog (T0.5).

    ``continuous_improvement_applied_changes`` ya viene ordenada por
    ``updated_at`` descendente, asi que limitamos a las ``sessions`` mas
    recientes como aproximacion conservadora de la ventana.
    """

    try:
        changes = store.continuous_improvement_applied_changes(statuses=["ROLLED_BACK"], limit=max(1, sessions) * 4)
    except Exception:  # noqa: BLE001
        return 0
    count = 0
    for change in changes[: max(1, sessions) * 4]:
        actor = str(((change.get("decision") or {}).get("rollback_actor")) or "")
        if actor == "change_watchdog":
            count += 1
    return count


def _iq_trend_ok(store: "Store") -> bool:
    """iq_score medio de las ultimas 10 sesiones >= al de las 10 previas."""

    try:
        rows = store.performance_daily(limit=0)
    except Exception:  # noqa: BLE001
        return False
    iqs = [row.get("iq_score") for row in rows if isinstance(row.get("iq_score"), (int, float))]
    if len(iqs) < 20:
        return False
    recent = iqs[-10:]
    previous = iqs[-20:-10]
    return (sum(recent) / 10.0) >= (sum(previous) / 10.0)


def _applied_in_level(store: "Store", level: int) -> int:
    try:
        changes = store.continuous_improvement_applied_changes(statuses=["APPLIED"], limit=1000)
    except Exception:  # noqa: BLE001
        return 0
    return sum(
        1
        for change in changes
        if int(((change.get("decision") or {}).get("autonomy_level")) or 1) == level
    )


def autonomy_promotion_check(store: "Store", settings: "Settings", *, persist: bool = True) -> dict[str, Any]:
    """Sube o baja el nivel de autonomia automaticamente segun el historial.

    Sube si: >= AUTONOMY_PROMOTION_MIN_APPLIED cambios APPLIED en el nivel actual,
    0 rollbacks del watchdog en AUTONOMY_PROMOTION_CLEAN_SESSIONS sesiones y la
    tendencia de iq_score no decrece. Baja si hay >= AUTONOMY_DEMOTE_ROLLBACKS
    rollbacks en AUTONOMY_DEMOTE_SESSIONS sesiones.
    """

    current = active_autonomy_level(store, settings)
    min_applied = int(getattr(settings, "autonomy_promotion_min_applied", 10))
    clean_sessions = int(getattr(settings, "autonomy_promotion_clean_sessions", 15))
    demote_rollbacks = int(getattr(settings, "autonomy_demote_rollbacks", 2))
    demote_sessions = int(getattr(settings, "autonomy_demote_sessions", 10))

    applied = _applied_in_level(store, current)
    rollbacks_clean = _recent_watchdog_rollbacks(store, clean_sessions)
    rollbacks_demote = _recent_watchdog_rollbacks(store, demote_sessions)
    iq_ok = _iq_trend_ok(store)

    new_level = current
    reason = "sin cambios"
    if current > MIN_LEVEL and rollbacks_demote >= demote_rollbacks:
        new_level = clamp_level(current - 1)
        reason = f"degradacion: {rollbacks_demote} rollbacks recientes"
    elif (
        current < MAX_LEVEL
        and applied >= min_applied
        and rollbacks_clean == 0
        and iq_ok
    ):
        new_level = clamp_level(current + 1)
        reason = f"promocion: {applied} APPLIED, 0 rollbacks, iq estable"

    progress = {
        "current_level": current,
        "new_level": new_level,
        "applied_in_level": applied,
        "min_applied": min_applied,
        "recent_rollbacks": rollbacks_clean,
        "iq_trend_ok": iq_ok,
        "reason": reason,
        "changed": new_level != current,
    }
    if new_level != current and persist:
        store.set_runtime_value(RUNTIME_LEVEL_KEY, {"level": new_level, "reason": reason})
    return progress
