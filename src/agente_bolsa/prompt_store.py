"""Prompts como datos versionados (T2.1).

Los prompts dejan de estar hardcodeados: se guardan en `prompt_versions` con
estado ACTIVE/CANDIDATE/RETIRED. `get_prompt` devuelve el ACTIVE (con cache) y
cae al valor por defecto (YAML/hardcode) si la tabla esta vacia, garantizando que
el arranque nunca dependa de la base. Los agentes pueden `propose` versiones
CANDIDATE y `promote` la mejor tras medir su efecto (replay, T2.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .storage import Store

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones.
    from .config import Settings


# Cache simple por (db_path, key). Se invalida al proponer/promover/importar.
_CACHE: dict[tuple[str, str], str] = {}


def _store(settings: "Settings") -> Store:
    return Store(settings.database_path, settings.agent_logs_dir)


def _invalidate(settings: "Settings", key: str) -> None:
    _CACHE.pop((str(settings.database_path), key), None)


def get_prompt(settings: "Settings", key: str, default: str = "") -> str:
    """Devuelve el template ACTIVE de ``key`` o ``default`` si no hay ninguno."""

    cache_key = (str(settings.database_path), key)
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    template = default
    try:
        row = _store(settings).active_prompt(key)
        if row and str(row.get("template") or "").strip():
            template = str(row["template"])
    except Exception:  # noqa: BLE001 - sin tabla usamos el default.
        template = default
    _CACHE[cache_key] = template
    return template


def propose(
    settings: "Settings",
    key: str,
    template: str,
    *,
    created_by: str = "lab",
    parent_version: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> int:
    """Crea una nueva version CANDIDATE y devuelve su numero de version."""

    store = _store(settings)
    version = store.next_prompt_version(key)
    store.upsert_prompt_version(
        {
            "prompt_key": key,
            "version": version,
            "template": template,
            "status": "CANDIDATE",
            "parent_version": parent_version,
            "created_by": created_by,
            "metrics": metrics or {},
        }
    )
    _invalidate(settings, key)
    return version


def promote(settings: "Settings", key: str, version: int) -> None:
    """Promueve una version a ACTIVE (retira la ACTIVE previa)."""

    _store(settings).set_prompt_status(key, version, "ACTIVE")
    _invalidate(settings, key)


def import_prompts(settings: "Settings", prompts: dict[str, str], *, created_by: str = "import") -> dict[str, Any]:
    """Carga prompts actuales como version 1 ACTIVE (idempotente)."""

    store = _store(settings)
    imported: list[str] = []
    skipped: list[str] = []
    for key, template in prompts.items():
        existing = store.prompt_versions(prompt_key=key, limit=1)
        if existing:
            skipped.append(key)
            continue
        store.upsert_prompt_version(
            {
                "prompt_key": key,
                "version": 1,
                "template": template,
                "status": "ACTIVE",
                "parent_version": None,
                "created_by": created_by,
                "metrics": {},
            }
        )
        imported.append(key)
        _invalidate(settings, key)
    return {"imported": imported, "skipped": skipped}


def list_prompts(settings: "Settings") -> list[dict[str, Any]]:
    return _store(settings).prompt_versions(limit=500)


def default_prompt_catalog() -> dict[str, str]:
    """Catalogo de prompts editables por el laboratorio con su texto por defecto.

    Recolecta los defaults de los modulos consumidores (T2.3/T2.4) de forma
    perezosa para que `prompts-import` los cargue como version 1 ACTIVE.
    """

    catalog: dict[str, str] = {}
    try:
        from .tools.nightly_retrospective import DEFAULT_RETROSPECTIVE_PROMPT

        catalog["nightly_retrospective"] = DEFAULT_RETROSPECTIVE_PROMPT
    except Exception:  # noqa: BLE001
        pass
    try:
        from .continuous_improvement.lesson_distiller import DEFAULT_DISTILLER_PROMPT

        catalog["lesson_distiller"] = DEFAULT_DISTILLER_PROMPT
    except Exception:  # noqa: BLE001
        pass
    return catalog
