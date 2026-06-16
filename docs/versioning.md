# Versionado

La version visible de la aplicacion se toma de `src/agente_bolsa/__init__.py` en `__version__`.

Regla:
- usar formato semantico de tres digitos: `MAJOR.MINOR.PATCH`
- aumentar la version en cada cambio entregado
- mostrar siempre esa misma version en la web y en el empaquetado

Fuente unica:
- `src/agente_bolsa/__init__.py`

Integraciones:
- `pyproject.toml` lee la version de `agente_bolsa.__version__`
- `src/agente_bolsa/web_app.py` muestra `vX.Y.Z` en la barra lateral

Gestion de mejoras:
- El registro vivo de mejoras y tareas (terminado / pendiente) esta en
  `docs/plan_mejoras_y_tareas.md`. Cada entrega que sube version debe dejar su
  paso documentado alli y reiniciar el sistema para cargar los cambios.

Historial reciente:
- `0.2.0` (2026-06-16): plan maestro de mejoras + herramientas de salud LLM,
  mantenimiento de BD, refresco de evidencia, reconciliacion de ordenes e informe
  semanal. Ver `docs/plan_mejoras_y_tareas.md`.
- `0.3.0` (2026-06-16): resiliencia del grupo de agentes. Motor determinista de
  oportunidades (`opportunity_ranker`), watchdog de LLM degradado
  (`llm_degraded_watchdog`), runner `scripts/agents_healthcheck.py` y tests.
  Ver `docs/plan_mejoras_y_tareas.md` (seccion 3.3).
