# P-L67R1 — ensayo combinado P-L65B/P-L63 + P-L62 + P-L66

## Dictamen

**`ready_for_deployment`**, sin desplegar.

La causa del único fallo encontrado fue una aserción de versión fijada en
0.4.197 y una prueba heredada de P-L57A que no reflejaba el contrato P-L65B
de comparación atómica: una fila sin el par equity/SPY queda `pending`, no
publica una serie aislada como comparable. Ambas correcciones quedaron en
commits QA separados y la suite completa final terminó verde.

## Referencias y merge

- XNYS: abierto durante el ensayo, verificado con el calendario local a las
  19:07 CEST; sesión 2026-07-28, 15:30–22:00 CEST.
- Base P-L65B: `757500786bc706b6eb7972061ee3d7fbc00cbf75`, tree
  `272b902694f9f266011424210424d77659b7db8a`, versión 0.4.200.
- P-L62 aislado: `b7e0f35f` (implementación) y `3c60570b` (tests).
- P-L66 fusionado con `--no-ff`: `8411db565522a371c54b0d0fa41dd1b03e6067e`;
  merge `d3a75c9828de2a51ef59948218f98a796c9acca5`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl67_p65_p62_p66_deployment_rehearsal`.
- Rama: `codex/pl67-p65-p62-p66-deployment-rehearsal`.
- HEAD final: `62de552529964faf85509762d4f3933acd2c5abe`.
- Tree final: `77ec5a4ff1b0f2c92fd1fdb7cc3d8b0b2967520f`.
- Versión: 0.4.201.
- Commits QA: `7d3bf126` recibo Telegram real/idempotencia, `38da3ce5`
  imports, `348d134f` contrato pending P-L57/P-L65B y `62de5525` política de
  versión.

## Contratos verificados

### P-L65B/P-L63

La fila canónica `performance_benchmark` es la fuente primaria de variación
de equity frente a SPY. Exige dos cierres SPY, misma sesión/ventana,
`price_basis`, `source`, `generated_at`, `as_of` y freshness comparables.
Partial, stale, interpolated, missing o mismatched quedan `pending` y no
ganan una sesión. La exposición-normalizada queda descriptiva y no decide el
ganador.

El selector 7/15/30/90/Desde inicio usa un rowset visible único. La cartera
usa el corte del 1 de abril, el primer/último equity visible para importe,
porcentaje y fechas, y mantiene P/L abierto separado. No se añade llamada al
broker desde presentación. Los tooltips de líneas y puntos comparten fecha,
serie y `% ganancias` con `+.2%`; las capas auxiliares no exponen `y0/y1`.

### P-L62

El diff dirty conserva únicamente la semántica de frescura en Estado
operativo: `generated_at` derivado de mtime, edad legible y estado rancio para
quality/readiness/weekly. La frescura es contexto visual, no gate ni autoridad
de trading. `n/d` y futuro no se convierten en cero ni en dato fresco.

### P-L66

- Job único `telegram_daily_summary`, `22:05`, zona `Europe/Madrid`,
  `max_instances=1`, `coalesce=True`.
- Configuración desactivada por defecto en `.env.example`; token con
  `repr=False`; no aparece en payload de evento, mensaje de error ni prueba.
- El resumen reutiliza la cartera y performance local del job; el hook
  postmarket queda como fallback idempotente mediante
  `telegram_daily_summary:<session_date>` en `agent_events`.
- Los avisos solo observan cambios `filled` después de reconciliación. BUY usa
  el fill real; SELL calcula P/L bruto únicamente con `source_plan_id` que
  resuelve una única BUY filled. Falta o ambigüedad produce `n/d`; no hay join
  por símbolo/fecha. Ambos caminos usan
  `telegram_trade_fill:<broker_order_id>`.
- Un fallo de Telegram es fail-open y no altera reconciliación, PMR ni trading.
  El intervalo entre envío aceptado y recibo persistido puede repetir un envío;
  queda documentado como límite operacional, no como idempotencia falsa.

## Equivalencia del checkout dirty

Producción comprometida: HEAD `24537e813ff0905696cda0b3925a212045ee7b09`,
tree `4747f27f3d5dc152410203bf089baee500440897`. Se preservó intacta.
Dirty tracked observado:

- `web_app.py`: SHA-256
  `FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A`.
- `tests/test_web_app.py`: SHA-256
  `9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B`.
- `__init__.py` y `docs/plan_mejoras_y_tareas.md`: solo bump/comentarios
  dirty a 0.4.187; no se copiaron. El árbol final conserva 0.4.201.

La implementación P-L62 se trasladó campo a campo en `b7e0f35f`. Las
funciones dirty de ventana completa de P-L61 quedan subsumidas por P-L63; el
panel dirty `_render_daily_vs_spy_table` y sus fallbacks yfinance no se
copiaron: P-L65B los reemplaza por el lector canónico persistido, sin red.
Los tests de ventana completa de P-L61 quedan cubiertos por las pruebas P-L63
del árbol combinado. Los untracked `AGENTS.md`, `.agents/skills/*`, `.opencode`,
`opencode.json` y `skills-lock.json` permanecen en producción y fuera del
merge. No se hizo stash, reset, clean, stage ni commit en producción.

## QA ejecutada

- Focal P-L62/P-L66: 25 passed; focal P-L63/P-L65 y UI relacionada: 54 passed;
  focal combinada posterior: 44 passed.
- Suite final: **2242 passed, 1 skipped, 1 warning**, 992.34 s.
- Skip preexistente exacto: `tests/test_pre_earnings.py:1041`,
  `local SQLite history is not available`; no se añadió skip/xfail.
- Ruff completo `src tests`: `All checks passed`.
- `scripts/check_no_nulls.py`: OK, 446 archivos.
- `git diff --check`: OK.
- `py_compile`/`compileall`: OK.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`, sin
  errores ni warnings.
- `kernel-status --json` temporal: `unsealed`, sin violaciones, esperado al
  no existir manifiesto en el DATA_DIR aislado. No se ejecutó kernel-seal.
- Smoke CLI `run-once --skip-crew` real: `smoke_unavailable_by_safety`, porque
  la CLI crea proveedores desde configuración y no permite garantizar desde
  fuera que no llame broker/red. Sustituto aislado de entrypoint:
  `test_observable_cycle_wiring_captures_phase_a_once_without_prompt_mutation`
  pasó con DATA_DIR temporal, `use_crew=False` y proveedores de mercado
  monkeypatched; no inició servicios ni scheduler.
- El scheduler temporal construyó exactamente un job Telegram con trigger
  `cron[hour='22', minute='5']`, zona `Europe/Madrid`, `max_instances=1` y
  `coalesce=True`.

## Paridad y protección

Los hashes Git de `kernel.py`, `tools/execution.py` y `tools/risk.py` son
idénticos entre producción comprometida y candidato. `config.py` solo añade
campos Telegram con defaults seguros y `repr=False` para el token. `broker.py`
solo proyecta los dos campos intradía opcionales de posición para el resumen;
no cambia submit ni payload de broker. `.env` no se modificó ni se copió.

No hay cambios en señales, candidatos, ranking, gates, capacity, sizing,
RiskManager, planes, cantidades, precios, stops/takes/trailing, órdenes,
exposición, límites ni cadencia existente. P-L66 es consumidor externo
fail-open; P-L62 es presentación; P-L65B/P-L63 son lectura/UI.

## Estado de entrega

No se detuvo ni reinició producción, no se ejecutaron jobs reales, broker,
red, yfinance, LLM, SQLite productiva, postmarket ni reconciliación manual.
No hubo despliegue ni push. El candidato quedó limpio tras la documentación;
el siguiente paso autorizado es un preflight de mercado cerrado y la
normalización controlada del checkout dirty, preservando los untracked y sin
descartar hunks del operador.

## Addendum de despliegue productivo — 28-jul-2026

Dictamen final: `deployed`.

- Producción se normalizó de forma auditable en `b2d7c5c6` y fusionó este
  candidato con `--no-ff` en `915481ab325d46c81a92986bfd603f13c5134dd9`.
  El árbol funcional `f3a2eda76f3c317d68d8679ce00a7ea43a6aa023` coincide
  exactamente con el candidato final `b25c9603`.
- Suite productiva con stack detenido: `2243 passed, 1 warning` en 915,36 s.
  Ruff completo, `check_no_nulls.py` (446), `git diff --check`,
  `validate-agent-config --json` y kernel quedaron verdes.
- El sello kernel se actualizó únicamente después de revisar los cambios
  autorizados: `broker.py` añade dos campos intradía opcionales sin cambiar
  requests; `.env` contiene una sola copia de cada clave Telegram.
- Arranque gestionado y dos comprobaciones separadas: HTTP raíz y `/health`
  200; cadena scheduler única, lock v1 PID 18888 y token
  `134297337742205338` coherentes; configuración válida y kernel sin
  violaciones.
- La alerta transitoria `data_pipeline_down` causada por la parada desapareció
  tras el ciclo natural `mkt_2fe0c3db689e`, completado en 598,277 s. Salud
  final: `warning`, cinco warnings preexistentes y cero críticos.
- SQLite se leyó con `mode=ro` y `query_only=ON`: cero órdenes desde el
  reinicio y `post_market_coordination:active = null`.
- `adaptive_config.json` conservó SHA-256
  `60833B60F83EDB1B5ECBE0785BDACD68F58AF6D5DFB307649749A8DBF6C7F4D0`.
  No hubo push ni jobs manuales de mercado, postmarket o reconciliación.
