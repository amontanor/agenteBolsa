# Dictamen

`partially_verified_memory_bounded`. El digest de calidad de controles comparables deja de conservar hasta 50.000 recomendaciones y 200.000 outcomes completos. Lee ambos límites mediante un stream SQLite read-only con `fetchmany(512)`, mantiene contadores y solo retiene identidades relevantes más booleanos de madurez. La paridad del handler congelado y los focales aislados pasan; no se afirma que el OOM de producción esté resuelto.

## Identidad y alcance

- Fecha: 2026-10-10; XNYS cerrado según el encargo (`09:09 UTC`, próxima sesión 2026-10-12 15:30 Europe/Madrid).
- Base exacta: `43325d7b8c6525fa3665537f5109d570f2f2f5a9`.
- Worktree: `C:\Users\utopi\.codex\worktrees\bolsa-controls-memory-oct10\agenteBolsa`.
- Rama: `codex/oct10-comparable-memory`.
- HEAD funcional y de caracterización antes del informe: `de0932ff` (`33ada1b8` versión, `756877b4` corrección funcional, `b249166b` y `de0932ff` pruebas).
- Versión: `0.4.359` (`.358` queda reservado para el lote paralelo).
- Commits separados: `22f1acf7` funcional, `9fbd169c` tests iniciales, `33ada1b8` versión, `83ec4b60` last-wins, `756877b4` precedencia/formas inválidas, `b249166b` caracterización AST y `de0932ff` aislamiento `_env_file=None`.
- El informe es el único documento creado para este lote; no se modificaron plan maestro ni relevo.

## Cambio

`Store.comparable_control_quality_record_stream()` abre conexiones SQLite URI `mode=ro`, aplica `PRAGMA busy_timeout=30000` y `PRAGMA query_only=ON`, ejecuta los límites exactos de 50.000 recomendaciones y 200.000 outcomes, usa los decoders existentes y consume cursores con `fetchmany(512)`. Cada cursor y conexión se cierra en éxito, excepción o cierre temprano. El lector existente `decision_context_quality_record_stream()` no se modificó.

`build_comparable_control_quality()` procesa cada set una vez. Conserva denominadores, estados, razones, cobertura, filtros de ventana y schema, pero sustituye payloads retenidos por contadores. Para outcomes conserva únicamente IDs que aparecen en tratamiento/control y un probe compacto de `matured_horizons["10d"]`; la forma final se evalúa solo después de conocer la última fila. La asignación se repite en el orden SQL `signal_date DESC, created_at DESC`, preservando el `last-wins` histórico y la precedencia de errores para IDs duplicados. Stores/fakes sin la API nueva conservan el fallback a `trade_recommendations()` y `signal_outcomes()`.

No se tocaron selección, gates, órdenes, aprendizaje, promoción ni el helper de comparables que usa outcomes en línea 675. No se tocaron archivos protegidos, configuración, servicios, broker, red, LLM, datos productivos, locks ni push.

## Paridad y caracterización

El handler base congelado en el commit exacto tiene:

- SHA-256 del segmento fuente: `50add4204610883ff2dffddf56988d69cc80e905eb7d5817638419c25b4ac92a`;
- SHA-256 del AST sin atributos de posición: `dc01653387ae3d47b10cfe905027edebfa6463f4bd82e912f9f7dd4814157351`;
- 89 líneas.

La caracterización ejecutó el handler base exacto contra fixtures con sets verificados/parciales, legacy, controles vacíos, ventana y filtro de estado, payloads falsy, outcomes repetidos, madurez por brazo, duplicado inválido temprano/final, controles inválidos y errores métricos. La prueba carga la función desde `git show 43325d7b...`, verifica los hashes de fuente/AST y compara salida o tipo/mensaje de excepción. La revisión detectó que una forma inválida en una fila duplicada temprana se evaluaba antes del `last-wins`; `83ec4b60` y `756877b4` lo corrigen reteniendo un probe, evaluando solo la fila final y preservando el `TypeError "'int' object is not iterable"` para `status=verified, controls=1`. La ejecución v3 pasó la caracterización contra ese AST congelado.

## Validación ejecutada

Python usado: `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`; `PYTHONPATH` apuntó exactamente a `C:\Users\utopi\.codex\worktrees\bolsa-controls-memory-oct10\agenteBolsa\src`; no se usó red, broker, LLM, proveedor externo ni SQLite productiva.

- Intentos pytest focales, antes de `83ec4b60`: sesiones `31,33,34,36,42,46,55,56`; CIM identificó wrappers PID `22444,43796,5160,35964,35168,46244,34980,33956` e hijos `42456,10168,48820,52184,34984,19576,42600,29956`. Mostraron puntos parciales, pero quedaron vivos; no hay código de salida final confiable y se clasifican como `inconclusive`, no como pass.
- Los 16 PID se detuvieron explícitamente después de verificar comando y pertenencia al lote; comprobación posterior: `owned_test_pids_remaining=0`.
- Ensayo v2 de bootstrap: PID `40616`, log `C:\Users\utopi\AppData\Local\Temp\oct10_comparable_memory_final_v2.log`, `exit=5`, `42 deselected`; se debió a pasar `-m pytest` al bootstrap que ya ejecutaba pytest. No se cuenta como QA.
- Ensayo final v3: PID `2556`, log `C:\Users\utopi\AppData\Local\Temp\oct10_comparable_memory_final_v3.log`, `exit=0`, `42 passed in 3.65s`. Intérprete `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`, `PYTHONPATH` exacto al `src` del worktree, `DATA_DIR=C:\Users\utopi\AppData\Local\Temp\oct10-comparable-final-v3-data`, `_env_file=None`, autoload de plugins desactivado y guardas locales de socket/DNS. La verificación posterior conjunta dio `GetProcessCount=0` y `CimCount=0`.
- `python -m ruff check --no-cache src/agente_bolsa/tools/comparable_controls.py src/agente_bolsa/storage.py tests/test_oct10_comparable_memory.py`: `All checks passed!` antes del ensayo v3.
- `git diff --check`: pasó antes de los commits.

Las pruebas nuevas cubren igualdad stream/fallback, ventanas y estados, legacy behavior, `last-wins`, formas inválidas y precedencia de errores contra el AST base, cierre del stream al error, conexiones/cursors cerrados, PRAGMA read-only y `fetchmany` acotado. El lote focal conjunto incluye también comparables existentes, `decision_context` streaming y la política de versión; el único resultado final acreditado es el log v3.

El intento de Ruff sin `--no-cache` fue bloqueado por permisos del sandbox al crear `.ruff_cache`; repetir con `--no-cache` pasó. Los comandos pytest anteriores imprimieron puntos parciales, pero no terminaron con estado observable antes de `83ec4b60`; no se ejecutó suite completa, smoke, build ni benchmark largo.

## Memoria y límites residuales

La mejora demostrada es de retención estructural y de lifecycle: el digest no guarda listas de recomendaciones/outcomes completos; la memoria de joins queda acotada por IDs y contadores a los límites del contrato. No se usó RSS launcher porque Windows no ofrece el mismo control memcg de Linux, y no se extrapola esta medición a un OOM productivo. Queda pendiente una medición local independiente de RSS/tracemalloc con payloads grandes si el coordinador la requiere después de que terminen las validaciones concurrentes.

La ruta todavía decodifica un registro por vez, conserva hasta 200.000 IDs booleanos potencialmente distintos y materializa el payload de una recomendación individual durante su consumo. SQLite sigue imponiendo los límites históricos; cambios en esquema, proveedor, producción o scheduler quedan fuera de este lote.

## Estado de entrega

Tras el commit documental, `git status --short --branch` debe mostrar únicamente la rama `codex/oct10-comparable-memory` sin cambios. No hubo despliegue, merge, push, reinicio, acceso SSH, broker, red ni escritura en producción.
