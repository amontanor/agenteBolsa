# Ensayo conjunto de siete mejoras — 8-oct-2026

Dictamen: `partially_verified_integration_candidate`. Las siete mejoras conviven sin conflictos funcionales y pasan 87 casos focales distintos. No es una release ni un despliegue. La validación operativa conserva `precondition_not_met`: el último preflight real, a las 08:33 Europe/Madrid, encontraba un lease postmarket activo en outcome_update. No se reparan ni detienen servicios para eliminar ese bloqueo.

## Identidad y alcance

Worktree `C:/Users/utopi/.codex/worktrees/bolsa-oct08-integration/agenteBolsa`, rama `codex/oct08-integration-rehearsal`. Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`. HEAD probado `5f2f530d2eab5b72c171a3fc0bd1afc1f9ddf5c4`, tree probado `9507084faf3e8e32ee1b4ad259501f70322e9f79`, checkout limpio antes de este cierre documental. Versión base 0.4.321: reserva y bump pendientes antes de release; no resuelven por sí solos la divergencia histórica .321/.340.

Se integran copias aisladas de los siguientes commits, conservando los informes de cada lote:

| Lote | HEAD de entrada |
| --- | --- |
| Guardia de portfolio ausente en postmarket | `071b4b5765ec33cacb140f4993095879b7db90db` |
| Auditoría EXIT separada de rechazos BUY | `a5ee9ce36dfe0fff977e2679884172dd700c3421` |
| Cobertura canónica de símbolos, legacy conservado | `73c3d683c9b7b64cf4e313cf16fbd795aff9f8fb` |
| Observación stop/take sin autoridad del broker | `f63464ee2c60401e89438defe068bec93274cf5e` |
| Reutilización de marcos por símbolo en outcomes | `9bd9b2eadfdb81a0528d4e0c901628df91b7e814` |
| Cierre explícito del lector SQLite de eventos | `1fda7d8d636e5197f05620f33cf10c6b00a852d5` |
| Exclusión local de estudios concurrentes duplicados | `2122fca31617bccaadc7ef2d1ba23d765b665350` |

Sólo hubo conflictos documentales en plan y relevo: se conservaron las notas de ambos lados. Los siete archivos funcionales modificados son storage.py, scheduler.py, cycle_runner.py y tools/{signal_learning,post_market_review,trade_decision,technical_study}. Los objetos Git de kernel.py, tools/broker.py, tools/execution.py, tools/risk.py, config.py y .env permanecen idénticos a la base. Los checkouts de entrada y los cambios ajenos no se modifican.

## Resultado y límites

Los tres lotes nuevos corrigen reutilización repetida de DataFrames, conexiones/cursor sin cierre físico explícito y concurrencia duplicada de estudios en el mismo Store/proceso. Las caracterizaciones de sus informes reproducen los defectos en la base y contrastan payloads y rutas aceptadas. No se ha demostrado que sean la causa de los incidentes productivos.

En capturas H, el fixture de 120 señales y dos símbolos reduce las adquisiciones de marcos de 120 a dos, conservando los 120 payloads completos e identidades frente al legacy congelado. No equivale a una medida de RAM: el loop legacy ahora retiene un marco por símbolo y puede aumentar su memoria en esa subfase. El lector cierra al agotarse, fallar o recibir close; un generador suspendido y todavía referenciado sigue reteniendo recursos. El guard de estudios excluye duplicados únicamente dentro del mismo proceso y Store; no sustituye leases entre procesos ni garantiza el avance del postmarket.

La auditoría EXIT sigue separada de BUY y del aprendizaje; la cobertura no sustituye candidatos ni métricas legacy; stop/take reutiliza fuentes ya cargadas, no añade consultas y declara protección real del broker unavailable. Estas garantías tienen evidencia sintética focal, no una demostración económica de un ciclo productivo completo.

## Validación del árbol combinado

Intérprete `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`, PYTHONPATH exacto del src de este checkout; DATA_DIR temporal, Settings con `_env_file=None` y proveedores locales/dobles. Sin broker, red, LLM ni datos productivos desde tests.

Primera batería: `86 passed in 5.29s`, ejecutada una vez sobre el árbol funcional definitivo:

```text
python -m pytest tests/test_oct07_postmarket_missing_portfolio.py tests/test_oct07_exit_rejection_audit.py tests/test_oct07_symbol_coverage.py tests/test_oct07_stop_take_observation.py tests/test_oct08_outcome_memory.py tests/test_oct08_event_reader_lifecycle.py tests/test_oct08_study_dedup.py tests/test_storage_read_connection.py tests/test_signal_learning.py::test_outcome_for_signal_includes_exit_policy_v2_partial_and_trailing tests/test_signal_learning.py::test_outcome_for_signal_marks_matured_when_future_bars_exist tests/test_signal_learning.py::test_outcome_for_signal_keeps_pending_when_history_is_short -q --tb=short
```

Segunda batería, caso distinto no incluido arriba: `tests/test_market_cycle_timing_integration.py::test_exit_audit_wiring_is_fail_open_and_separate`, `1 passed in 0.71s`. Total 87 casos distintos; no se suman los resultados solapados de los lotes individuales.

Ruff focal sobre siete archivos funcionales, siete archivos nuevos de tests y el test de wiring: `All checks passed!`. NUL: `OK (544 archivos)`. `git diff --check` verde. Revisión independiente Luna sin bloqueantes: signal_learning y sus fixtures son idénticos al candidato de memoria; scheduler añade al candidato dedup sólo la observación stop/take y su wiring. Revisión no implica ejecución adicional de suites.

## Producción y gates pendientes

Última observación real: XNYS cerrado, siguiente apertura 15:30 Madrid; paper activo, live y auto-apply desactivados. Imagen activa observada `sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae`, scheduler PID 6, RestartCount 4; último arranque 03:29:42 UTC. Postmarket `pmr_150611d46dd9` seguía con lease activo en outcome_update; dos intentos anteriores fallaron por database is locked. Memoria observada casi al límite de 2 GiB, sin eventos oom/oom_kill: no se atribuyen los reinicios a OOM. HEAD/tree productivos y equivalencia de imagen/release no quedan resueltos por la versión de este checkout.

No se ejecutaron suite completa, smoke operativo, kernel/config gates, promoción, merge productivo, despliegue, reinicio, órdenes ni push. HTTP y salud integral posterior a despliegue no se certifican. Sigue pendiente el fallo `test_economic_parity_true_false_none_identical_payloads`, previamente reproducido sobre la base; no se oculta ni se vuelve a ejecutar sin nueva causa. No se presenta este ensayo como aprobación de esos gates.

Siguiente secuencia: verificar nuevamente schedule-status, terminal postmarket y ausencia de jobs/reintentos/leases/validaciones; resolver identidad .321/.340 y reservar versión; completar validación proporcional pendiente y revisar el fallo económico de base antes de considerar release. La automatización `validar-mejoras-bolsa-tras-cierre` permanece PAUSED; la revisión del 12 de octubre no se altera.

Auditoría de optimización adicional: EXPLAIN sobre SQLite temporal con esquema base demuestra SCAN agent_events y ordenación temporal para la consulta por tipo/ciclo. Se propone un lote específico de consulta agrupada/índice, conservando legacy sin ciclo, orden e histórico completo. No se añade esquema ni se recorta a ciegas el histórico de 200000 señales. Cambiar atomicidad de escrituras requiere estudiar reintentos y paridad; queda fuera de estas correcciones.
