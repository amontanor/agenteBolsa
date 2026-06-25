"""Registro de estrategias plugables (T1.2).

Descubre las estrategias disponibles: las builtin del paquete `strategies/` mas
las registradas en la tabla `strategy_versions` con estado ACTIVE/SHADOW. Valida
la firma de cualquier estrategia registrada con AST (sin imports de
broker/execution ni red) antes de activarla.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import Strategy

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from ..storage import Store


# Estrategias builtin: nombre -> factory perezosa.
def _builtin_breakout_factory() -> Strategy:
    from .builtin_breakout import get_strategy

    return get_strategy()


def _builtin_pullback_factory() -> Strategy:
    from .builtin_pullback import get_strategy

    return get_strategy()


BUILTIN_FACTORIES: dict[str, Callable[[], Strategy]] = {
    "builtin_breakout": _builtin_breakout_factory,
    "builtin_pullback": _builtin_pullback_factory,
}

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "tools.broker",
    "tools.execution",
    "requests",
    "urllib",
    "http.client",
    "socket",
    "aiohttp",
    "httpx",
)


def validate_strategy_source(source: str) -> str | None:
    """Valida el codigo fuente de una estrategia. Devuelve motivo o None."""

    try:
        tree = ast.parse(source or "")
    except SyntaxError as exc:
        return f"syntax_error: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(bad in module for bad in _FORBIDDEN_IMPORT_SUBSTRINGS):
                return f"import prohibido: {module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(bad in alias.name for bad in _FORBIDDEN_IMPORT_SUBSTRINGS):
                    return f"import prohibido: {alias.name}"
    return None


def validate_strategy_file(path: Path) -> str | None:
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return f"no se pudo leer {path}: {exc}"
    return validate_strategy_source(source)


def register(
    store: Store,
    *,
    name: str,
    version: str = "1",
    status: str = "SHADOW",
    source_path: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra/actualiza una estrategia en `strategy_versions`.

    Si trae `source_path` a un archivo, valida su firma antes de aceptarla.
    """

    if source_path:
        candidate = Path(source_path)
        if candidate.exists():
            violation = validate_strategy_file(candidate)
            if violation:
                return {"ok": False, "error": violation}
    item = {
        "name": name,
        "version": version,
        "status": status,
        "source_path": source_path,
        "metrics": metrics or {},
    }
    store.upsert_strategy_version(item)
    return {"ok": True, "name": name, "version": version, "status": status}


def _load_registered_strategy(row: dict[str, Any]) -> Strategy | None:
    name = str(row.get("name"))
    if name in BUILTIN_FACTORIES:
        strategy = BUILTIN_FACTORIES[name]()
    else:
        module_path = str(row.get("source_path") or "")
        if not module_path:
            return None
        try:
            module = importlib.import_module(module_path)
            factory = getattr(module, "get_strategy", None)
            if factory is None:
                return None
            strategy = factory()
        except Exception:  # noqa: BLE001 - una estrategia rota no debe romper el scan.
            return None
    strategy.status = str(row.get("status") or strategy.status)
    if row.get("version"):
        strategy.version = str(row["version"])
    return strategy


def discover(store: Store | None) -> list[Strategy]:
    """Lista de estrategias instanciadas (ACTIVE + SHADOW, sin RETIRED)."""

    rows_by_name: dict[str, dict[str, Any]] = {}
    if store is not None:
        try:
            for row in store.strategy_versions(limit=500):
                rows_by_name.setdefault(str(row.get("name")), row)
        except Exception:  # noqa: BLE001 - sin tabla usamos solo builtins.
            rows_by_name = {}

    strategies: list[Strategy] = []
    seen: set[str] = set()

    # Builtins primero (ACTIVE por defecto salvo que el registro diga otra cosa).
    for name, factory in BUILTIN_FACTORIES.items():
        strategy = factory()
        row = rows_by_name.get(name)
        status = str((row or {}).get("status") or strategy.status).upper()
        if status == "RETIRED":
            seen.add(name)
            continue
        strategy.status = status
        if row and row.get("version"):
            strategy.version = str(row["version"])
        strategies.append(strategy)
        seen.add(name)

    # Estrategias registradas no-builtin.
    for name, row in rows_by_name.items():
        if name in seen:
            continue
        if str(row.get("status") or "").upper() not in {"ACTIVE", "SHADOW"}:
            continue
        strategy = _load_registered_strategy(row)
        if strategy is not None:
            strategies.append(strategy)
    return strategies


def discover_active(store: Store | None) -> list[Strategy]:
    return [s for s in discover(store) if str(s.status).upper() == "ACTIVE"]


def strategy_matches_regime(strategy: Strategy, regime: str | None) -> bool:
    """True si la estrategia opera en el regimen vigente (T5.7)."""

    target = str(getattr(strategy, "target_regime", "any") or "any").lower()
    if target == "any" or not regime:
        return True
    return target == str(regime).lower()


def discover_active_for_regime(store: Store | None, regime: str | None) -> list[Strategy]:
    """Estrategias ACTIVE cuyo target_regime coincide con el regimen vigente."""

    return [s for s in discover_active(store) if strategy_matches_regime(s, regime)]
