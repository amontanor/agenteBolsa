# P-L41R — ensayo secuencial P-L37B → P-L40B

Fecha del ensayo: 14-jul-2026
Base productiva: `6640ed91ed4d83f598950517e4997a82a2043e9`
Worktree: `codex/nightly-integration-rehearsal`

## Orden e historial

1. Merge `codex/pl37b-tests` (`0e975cb0`) mediante `39a308fa`.
2. Merge `codex/pl40b-tests` (`498bafb9`) mediante `0fe1dea8`.
3. El único conflicto apareció en `storage.py`, entre `_merge_json_dicts` de P-L37B y `_json_safe` de P-L40B. Se conservaron ambas funciones.

## Garantías verificadas

- P-L37B conserva capturas append-only, merges recursivos, identidad literal y compatibilidad legacy.
- P-L40B conserva benchmark local, una captura de cartera compartida, SPY sin red, hash estable y conflictos sin overwrite.
- La persistencia de señal y la de performance permanecen separadas.
- El digest se ejecuta después de `performance_daily`.
- No se modifican señales, ranking, gates, planes, cantidades, stops, takes ni órdenes.

## Pruebas

- Focales P-L37B: `15 passed`.
- Focales P-L40B: `51 passed`.
- Focales relacionadas P-L30–P-L38: `137 passed`.
- Ensayo combinado P-L41R: se ejecuta únicamente en este worktree con Store temporal y sin red, broker, LLM ni servicios.
- Suite completa, smoke y despliegue quedan pendientes fuera de mercado.

## Estado

El ensayo no modifica producción ni los worktrees originales. No se sube versión ni se hace push. La integración queda pendiente de postmarket terminal y suite completa.
