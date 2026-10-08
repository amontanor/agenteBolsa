# Outcomes: reutilización local de marcos por símbolo (8-oct-2026)

Dictamen: `partially_verified_outcome_memory_candidate`. La caché de capturas H retenía una copia de DataFrame por `signal_id`, aunque `_symbol_frame` depende exclusivamente de los datos de la llamada y del símbolo. El candidato reutiliza una copia por símbolo exacto. No se ha medido RAM productiva ni demostrado causalidad sobre incidencias operativas. No es una release ni está desplegado.

## Alcance y precondiciones

Lote N2 aislado, autorizado por dirección técnica bajo la petición del operador «Resuelve todo lo que puedas... Busca también errores y optimización de código». Modelo/esfuerzo del encargo: `gpt-6.1-sol` / `low`. Worktree exclusivo `C:/Users/utopi/.codex/worktrees/bolsa-outcome-memory-oct08/agenteBolsa`, rama `codex/oct08-outcome-memory`.

Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`, versión `0.4.321`, inicialmente limpia. Bump y reserva de versión diferidos al coordinador; candidato no apto para release mientras permanezcan pendientes.

Estado operativo comunicado por coordinador a las 08:33 Europe/Madrid: XNYS cerrado, siguiente apertura 15:30; lease postmarket activo en `outcome_update` desde 05:32. Esta tarea no consultó producción. Validación completa y despliegue: `precondition_not_met`. PID/lock, heartbeat, HTTP, kernel, configuración sensible y estado productivo posterior: `unavailable` en este lote.

## Cambio y garantías

Único archivo funcional: `src/agente_bolsa/tools/signal_learning.py`, +10/-5 líneas. `_persist_signal_outcome_captures` usa clave de símbolo exacta sin normalizar. IDs, linaje, validación y persistencia se mantienen. El marco se añade sólo después de lookup correcto; las excepciones siguen reintentándose por fila. No se cambian atomicidad, chunks SQL, esquema, límites de lectura ni histórico.

`build_outcome_capture` y `_close_by_session` sólo leen el marco. `_outcome_for_signal` copia el subconjunto futuro antes de calcular. Tests comprueban no mutación de datos, marcos compartidos, señales y predicciones, además de aislamiento entre llamadas con precios distintos.

El loop legacy de `update_signal_outcomes` también reutiliza marcos por símbolo, conservando el orden lookup, marco vacío, features y caché de outcome. Esto evita copias incluso cuando `outcome_cache` ya contiene el resultado. Tradeoff explícito: antes retenía sólo el marco actual de esa subfase; ahora retiene uno por símbolo y puede aumentar su memoria retenida. La gran reducción potencial está en capturas H, de una copia por señal a una por símbolo. No hay benchmark de RSS ni afirmación de mejora de RAM total del proceso.

## Evidencia reproducible

Python `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`, `PYTHONPATH` exacto al `src` de este worktree. Fixtures con `Settings(_env_file=None, data_dir=tmp_path)`, reloj fijo `2026-10-07T22:00:00Z`, datos temporales, sin red, broker, LLM, servicios ni SQLite productiva.

Referencia congelada `tests/outcome_memory_legacy.txt`: ambas funciones extraídas del objeto Git base, comparadas por igualdad textual después de normalizar finales de línea mediante lectura de texto. SHA256 de cada función normalizada:

- `_persist_signal_outcome_captures`: `cc051e6621709fd9c844e6d5f388b262dda2cea503a24c0ca84a78cbe038bcde`.
- `update_signal_outcomes`: `fa60a3d39ba180921c16a5bab10bbfa1e9a684e6e0a57c33b27f8a5bfde389b9`.
- Snapshot completo, bytes del archivo local: `3752f7e5cb81a32e276204fc78a0da7beb0dc874371c89641dcdf9fb8dc06bf8`.

Caracterización inicial base: 4 passed en 1.13 s. QA final: **12 passed en 1.22 s**, nueve pruebas nuevas y tres regresiones puras existentes. No sumar estas baterías solapadas como casos únicos adicionales.

Comando final: `python -m pytest tests/test_oct08_outcome_memory.py tests/test_signal_learning.py::test_outcome_for_signal_includes_exit_policy_v2_partial_and_trailing tests/test_signal_learning.py::test_outcome_for_signal_marks_matured_when_future_bars_exist tests/test_signal_learning.py::test_outcome_for_signal_keeps_pending_when_history_is_short -q --tb=short`.

Paridad completa de payloads H, IDs y hashes con 120 señales y dos símbolos: 120 lookups legacy frente a 2 candidatos; 120 payloads idénticos. Lookup fallido persistente de BBB: 40 errores por fila, 80 payloads idénticos, 41 lookups candidatos frente a 120 legacy. Fallo de persistencia en signal-2: 119 payloads idénticos y retorno fail-open conservado. Linaje inválido y señal ambigua excluidos idénticamente. Todos los payloads aceptados pasan el validador H real.

Loop legacy: 30 señales, dos símbolos, resultados completos y diccionario guardado idénticos con reloj fijo. Cubre datos correctos, símbolo ausente, marco vacío y features inválidas. Lookups: 30 legacy frente a 2 candidatos; con símbolo ausente, 11 candidatos, preservando sus 10 errores por fila. No se compara sólo contadores.

Ruff focal: `All checks passed!`. `scripts/check_no_nulls.py`: `OK (538 archivos)`. `git diff --check`: verde. Fallos durante creación de fixtures corregidos antes de fijar caracterización; no son regresiones del producto.

## Commits y límites

- `5b1e9402`: caracterización inicial.
- `91ddfe6c`: referencia legacy del loop y paridad completa.
- `192a58b3`: implementación mínima.
- `1ad9c32959737628149540a959d42deb2bb50ef3`: QA; tree `e60e79ed960b1f510ab46b589e8b79a59c804f07`.

Suite completa, regresión extensa, benchmark de 33.336 observaciones, Ruff completo, smoke, validate-agent-config y kernel-status: omitidos y no aprobados por alcance acotado y lease activo. No se tocaron protegidos/configuración/política/trading, producción, servicios, leases ni otros worktrees. Sin despliegue, reinicio, merge o push.

Siguiente paso: revisión del coordinador, reserva/bump y ensayo en ventana cerrada con postmarket terminal, sin leases ni jobs activos. Repetir gates proporcionales afectados antes de considerar integración. El commit documental y limpieza final se registran en entrega del coordinador.
