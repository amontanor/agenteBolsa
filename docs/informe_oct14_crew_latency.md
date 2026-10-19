# Informe de latencia CrewAI/fallback — 14 de octubre de 2026

## Alcance y trazabilidad

- Base exacta: `2999414f0dd506e69e75435965de5c3bb64d9056` (`.4.369`).
- Cambio funcional: commit `c8665a81b87acc1cbc0881c3ef8f0bec0ebddbda`.
- Reserva de versión: `.4.371`; `.4.370` queda reservado para gates.
- Rama y worktree: `codex/oct14-crew-latency`, worktree aislado `C:\Users\utopi\.codex\worktrees\oct14-crew-latency\agenteBolsa`.
- El árbol del worktree se verificó limpio después del commit documental.

## Causa y corrección

El ciclo `mkt_b020b7593667` registró `1625.8109 s` totales. El primer intento CrewAI falló en `6.4115 s` con HTTP 402 (`Insufficient account funds`), pero el error envuelto como `Upstream request failed` coincidía con el marcador de reintento. Eso iniciaba una segunda ruta CrewAI/fallback de `1170.7889 s`; la estructuración final tardaba `75.3205 s`.

La corrección mínima clasifica HTTP 402 como terminal aunque CrewAI lo envuelva, evitando la segunda CrewAI y conservando la ruta directa de decisión LLM (`direct_llm_decision`) y sus contratos de fallback, error y liberación de recursos. Los estados 408, 429 y 5xx mantienen la política retryable existente. No se modificaron proveedor, configuración, prompt, umbral, estrategia, órdenes ni archivos protegidos.

El cambio altera el tiempo y el número de intentos cuando aparece 402. La reducción potencial solo está acotada al tramo observado de `1170.7889 s`; este informe no declara mejora de rendimiento en vivo.

## Verificación

- Validación offline independiente de raíz: 7 pruebas verdes en `1.18 s`; la ruta terminal 402 no quedó colgada.
- Validación focal de este worktree: los 6 casos del contrato nuevo llegaron a `PASSED`; el proceso pytest no emitió resumen final y quedó pendiente de finalización del entorno.
- `tests/test_p147_crew_session_headers.py`: 2 pasadas reportadas.
- Política de versión: pasada.
- Ruff sobre archivos modificados, comprobación de NULs (572 archivos), compilación por `compile()` y `git diff --check`: OK.
- No se ejecutaron full suite, ARM, smoke, integración, producción, red, broker ni LLM en vivo; quedan pendientes para sus gates correspondientes.

## Fuentes y mantenimiento

- Evidencia de tiempos: `EF99/audit_oct13_results_ledger.json`, reporte `latest_market_cycle_timing`.
- Contrato modificado: `src/agente_bolsa/cycle_runner.py`, `_crew_provider_failure_retryable`.
- Evidencia de tests: `tests/test_oct14_crew_latency.py`, `tests/test_p147_crew_session_headers.py`.
- El commit funcional emitió un aviso de mantenimiento por una referencia ajena corrupta `refs/codex/turn-diffs/captures/.../base` y fallo de repack geométrico. No se reparó esa referencia; el commit y el árbol del worktree quedaron utilizables y limpios.
