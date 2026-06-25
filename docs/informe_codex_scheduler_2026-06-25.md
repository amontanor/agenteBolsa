# Informe Codex — auditoría read-only del scheduler — 2026-06-25

## Alcance

Auditoría read-only de qué ejecuta cada loop del scheduler y coste aproximado usando código, `schedule-status`, `agent_events`, `runtime_state`, `llm_usage` y `signal_outcomes`.

No se cambiaron cadencias, configuración, `.env` ni runtime. No se disparó ningún ciclo pesado extra.

## Dónde se define el scheduler

Entrada CLI:

- `src/agente_bolsa/main.py:2780` — `command_schedule(...)` llama a `run_scheduler_forever(...)`.
- `src/agente_bolsa/main.py:2787` — `command_schedule_status(...)` expone estado/calendario.
- `src/agente_bolsa/main.py:3954` — parser `schedule`, descrito como “Ejecuta scheduler 1m/15m/diario”.

Construcción de jobs:

- `src/agente_bolsa/scheduler.py:2722` — `build_scheduler(...)`.
- `src/agente_bolsa/scheduler.py:2729-2738` — `portfolio_watch_job`, `IntervalTrigger(seconds=settings.portfolio_watch_interval_seconds)`, id `portfolio_watch_1m`.
- `src/agente_bolsa/scheduler.py:2739-2749` — `market_cycle_job`, `IntervalTrigger(minutes=settings.market_cycle_interval_minutes)`, id `market_cycle_15m`.
- `src/agente_bolsa/scheduler.py:2750-2760` — `closed_market_technical_study_job`, comprobador cada `closed_market_study_interval_minutes`.
- `src/agente_bolsa/scheduler.py:2761-2771` — `daily_study_job`, `CronTrigger` diario.
- `src/agente_bolsa/scheduler.py:2772-2782` — `post_market_review_job`, comprobador cada `closed_market_study_interval_minutes`.
- `src/agente_bolsa/scheduler.py:2783-2793` — `broker_reconciliation_job`, comprobador cada `closed_market_study_interval_minutes`.
- `src/agente_bolsa/scheduler.py:2794-2804` — `pre_earnings_job`, comprobador cada `closed_market_study_interval_minutes`.
- `src/agente_bolsa/scheduler.py:2805-2816` — `overnight_learning_heartbeat_job`, `CronTrigger` diario.
- `src/agente_bolsa/scheduler.py:2817-2828` — `continuous_improvement_job`, `IntervalTrigger(seconds=settings.continuous_improvement_runtime_interval_seconds)` si está habilitado.
- `src/agente_bolsa/scheduler.py:2829-2841` — `opportunity_snapshot_job`, un `CronTrigger` por slot.
- `src/agente_bolsa/scheduler.py:2842-2852` — `agents_healthcheck_job`, `IntervalTrigger(minutes=settings.agents_healthcheck_interval_minutes)`.

Estado reportado:

- `src/agente_bolsa/scheduler.py:2909-3017` — `scheduler_status(...)`, usado por `schedule-status`.

## Dónde vive el knob de cadencia

Los knobs están en `src/agente_bolsa/config.py`, que es archivo bloqueado por las reglas del proyecto. Las variables tienen alias de `.env`; `.env` también está bloqueado y aparece sellado por `kernel-status`.

Referencias:

- `src/agente_bolsa/config.py:940` — `continuous_improvement_runtime_interval_seconds`, alias `CONTINUOUS_IMPROVEMENT_RUNTIME_INTERVAL_SECONDS`.
- `src/agente_bolsa/config.py:981` — `portfolio_watch_interval_seconds`, alias `PORTFOLIO_WATCH_INTERVAL_SECONDS`.
- `src/agente_bolsa/config.py:985` — `market_cycle_interval_minutes`, alias `MARKET_CYCLE_INTERVAL_MINUTES`.
- `src/agente_bolsa/config.py:989` — `closed_market_study_interval_minutes`, alias `CLOSED_MARKET_STUDY_INTERVAL_MINUTES`.
- `src/agente_bolsa/config.py:993` — `agents_healthcheck_interval_minutes`, alias `AGENTS_HEALTHCHECK_INTERVAL_MINUTES`.
- `src/agente_bolsa/config.py:1331` — `pre_earnings_time_market`, alias `PRE_EARNINGS_TIME_MARKET`.
- `src/agente_bolsa/config.py:1341` — `daily_study_time_local`, alias `DAILY_STUDY_TIME_LOCAL`.
- `src/agente_bolsa/config.py:1342` — `opportunity_snapshot_times_local`, alias `OPPORTUNITY_SNAPSHOT_TIMES_LOCAL`.
- `src/agente_bolsa/config.py:1373-1376` — propiedad `opportunity_snapshot_times`.

Implicación futura: cambiar cadencia implica tocar `config.py` o `.env`/variables de entorno. En esta instalación, `.env` está sellado por kernel:

```text
kernel-status: ok=true, violations=[]
.env match=true
sealed_at=2026-06-25T09:19:03.070458+00:00
```

## Qué hace cada job

| Intervalo/cadencia | Job | Función | Qué hace |
|---|---|---|---|
| 60s | `portfolio_watch_1m` | `portfolio_watch_job` (`scheduler.py:1198`) | Comprueba calendario, snapshot Alpaca, posiciones/órdenes abiertas, guardas intradía, exits stop/take si hay posiciones. Sin universo técnico ni LLM en el caso normal sin actividad. |
| 15m | `market_cycle_15m` | `market_cycle_job` (`scheduler.py:1313`) | Si mercado abierto: escaneo técnico intradía, breakout scan, selección de candidatos y `run_observable_cycle` con LLM/decisión/paper execution. |
| 15m comprobador | `closed_market_technical_study` | `closed_market_technical_study_job` (`scheduler.py:1527`) | Si mercado cerrado y no se ejecutó para la próxima sesión: estudio técnico amplio, señalización para aprendizaje y, si aplica, sentimiento LLM/finalistas y ciclo LLM post-cierre. |
| Diario 23:00 Europe/Madrid | `daily_study` | `daily_study_job` (`scheduler.py:1860`) | Tras cierre si corresponde: ejecuta `run_observable_cycle`. |
| 15m comprobador | `post_market_review` | `post_market_review_job` (`scheduler.py:2130`) | Tras cierre y una vez por sesión: reconciliación broker, post-market review, performance daily, watchdog de cambios, macro thesis, retrospectiva, hypothesis factory. |
| 15m comprobador | `broker_reconciliation` | `broker_reconciliation_job` (`scheduler.py:2660`) | Tras cierre: reconcilia órdenes Alpaca y actualiza tracking de fills/aprendizaje. |
| 15m comprobador | `pre_earnings_daily` | `pre_earnings_job` (`scheduler.py:2479`) | Si mercado abierto y se alcanza ventana pre-cierre: estudio pre-earnings una vez por sesión, snapshots de analistas, learning digest y operación paper si habilitada. |
| Diario 00:10 Europe/Madrid | `overnight_learning_heartbeat` | `overnight_learning_heartbeat_job` (`scheduler.py:2367`) | Heartbeat nocturno de aprendizaje, frescura LLM y propuestas low-risk; research-only. |
| 60s | `continuous_improvement_lab` | `continuous_improvement_job` (`scheduler.py:2246`) | Tick residente de mejora continua en dry-run: eventos, tareas, hipótesis, propuestas; puede llamar LLM de mejora. |
| 30m | `agents_healthcheck` | `agents_healthcheck_job` (`scheduler.py:2627`) | Watchdog de salud LLM/agentes y oportunidades deterministas; no cambia decisiones de trading con fallback desactivado. |
| Diario 16:00/19:00/21:00 Europe/Madrid | `opportunity_snapshot_*` | `opportunity_snapshot_job` (`scheduler.py:1739`) | Escaneo técnico y snapshot top oportunidades. |

## Coste estimado por intervalo/job

Fuentes:

- `schedule-status` para último runtime de cada job.
- `agent_events` para pares start/end históricos.
- `llm_usage` para llamadas/tokens por fuente/rol.
- `signal_outcomes` para filas generadas por fuente/run.

Limitación: APScheduler puede solapar jobs. La atribución por ventana temporal puede incluir llamadas LLM de otro job concurrente, especialmente `continuous_improvement_lab`. Por eso la columna LLM separa fuente registrada y observación de ventana.

| Intervalo | Job | Wall-time observado | LLM | Símbolos | Filas BD por ejecución / efecto |
|---|---|---:|---|---:|---|
| 60s | `portfolio_watch_1m` | Últimos 20 eventos: mediana ~0,027s; último `runtime_state` ~0,828s | No registra LLM en flujo normal sin posiciones. | 0 universo; solo posiciones/órdenes si existen. | Eventos + runtime status; no escribe `signal_outcomes`. |
| 15m | `market_cycle_15m` | Última ejecución completa en `runtime_state`: 613,879s. Scan técnico+breakout de últimos 20: mediana ~54,063s. | Última ventana completa: `trade_decision` role `decision`, 1 llamada, 36.110 tokens. La misma ventana incluyó 2 llamadas `continuous_improvement_lab` por solape. | Últimos ciclos: 500 símbolos intradía + 501 breakout. Selecciona ~24 símbolos para LLM. | Últimos ciclos: `signals_saved` 537/538; `signal_outcomes` reciente desde 2026-06-25: `intraday_scan` 8.464 filas, 1.043 grupos símbolo-día-estrategia, 49 shadow. Es el principal contribuyente a duplicación histórica. |
| 15m comprobador | `closed_market_technical_study` | Últimas 20 ejecuciones reales: mediana ~51,010s; últimos ejemplos 78,360s / 117,600s / 72,462s. Durante mercado abierto salta en ~0,475s. | Código puede llamar `news_sentiment` y `run_observable_cycle` si hay finalistas (`scheduler.py:1676`, `1717`). En últimas 24h hubo `news_sentiment` 24 llamadas, 98.217 tokens en ventana post-cierre. | 500 símbolos (`closed_market_study_max_symbols`). | Ejemplos recientes: 498 señales antes de v0.4.51; desde datos limpios 2026-06-25, `closed_market_study` 538 filas, 42 shadow, 538 grupos. |
| Diario | `daily_study` | Últimas 15: mediana ~24,520s; últimas tres sesiones: 320,915s / 337,743s / 166,506s. | Ejecuta `run_observable_cycle`; no se aislaron llamadas LLM en la ventana última, pero el flujo puede usar decisión LLM vía ciclo observable. | Usa universo configurado/default del ciclo, no escaneo amplio propio en este wrapper. | Escribe artefactos del ciclo observable; no es el driver principal de `signal_outcomes` salvo lo que genere el ciclo. |
| 15m comprobador | `post_market_review` | Últimas 20 ejecuciones reales: mediana ~1.014,769s; últimos ejemplos 1.141,835s / 1.055,298s / 1.375,360s. Si no toca, salta en ~0,476s. | Fuente propia `post_market_review`: 1 llamada, 1.781 tokens en últimas 24h. En la ventana post-cierre también aparecen `operational_learning` 1 llamada/56.192 tokens y `news_sentiment` 24/98.217 por jobs concurrentes. | No escanea universo técnico directo; revisa trades/órdenes/memoria. | Reconciliación y tablas de aprendizaje/performance; no crea `signal_outcomes` masivo. |
| 15m comprobador | `broker_reconciliation` | Último skip ~0,506s. | Sin LLM. | 0. | Actualiza broker/execution learning si post-cierre; no crea candidatos. |
| 15m comprobador | `pre_earnings_daily` | Últimas 20 ejecuciones reales/skips mezcladas: mediana ~416,479s; últimas reales 654,100s / 509,712s / 490,838s. Skip actual ~0,455s. | Puede ejecutar operación/decisión pre-earnings; por ventana puede solaparse con `trade_decision`. No hay fuente LLM separada `pre_earnings` en `llm_usage`. | 500 símbolos (`pre_earnings_max_symbols` / `closed_market_study_max_symbols`). | Escribe `pre_earnings_predictions` y snapshots de analistas; no contribuye a `signal_outcomes`. |
| Diario | `overnight_learning_heartbeat` | Últimas 8 reales: mediana ~21,040s; skip actual ~0,090s. | Fuente `overnight_learning_heartbeat`: histórico 4 llamadas, 4.024 tokens; últimas 24h sin llamada registrada. | 0 universo técnico amplio. | Estado/reportes de aprendizaje nocturno; no crea `signal_outcomes`. |
| 60s | `continuous_improvement_lab` | Últimos 20 ciclos: mediana ~42,866s; rango ~3,160s–149,013s. | Hoy: 45 llamadas, 333.576 tokens. Últimas 24h: 99 llamadas, 730.834 tokens. Rol `continuous_improvement`. | 0 símbolos de mercado directo. | Escribe tablas `continuous_improvement_*`; no crea `signal_outcomes`. |
| 30m | `agents_healthcheck` | Último runtime ~0,469s. | No se observó LLM directo en `llm_usage` para este job; usa watchdog sobre registros. | 0. | Eventos/estado de salud; no crea `signal_outcomes`. |
| Diario 16/19/21 | `opportunity_snapshot_*` | Últimas 20: mediana ~49,631s; últimos 16:00/19:00/21:00: 61,068s / 100,232s / 47,548s. | Sin LLM registrado en ventanas representativas. | 500 símbolos. | Desde 2026-06-25: `opportunity_snapshot` 990 filas, 497 grupos; por snapshot reciente ~496/497 filas. |

## LLM por fuente registrada

Últimas 24h (`llm_usage`):

| Fuente | Rol | Llamadas | Tokens | Nota |
|---|---|---:|---:|---|
| `trade_decision` | `decision` | 43 | 1.526.061 | Asociado a ciclos de decisión (`market_cycle`, `daily_study`, operaciones pre-earnings si coinciden). |
| `continuous_improvement_lab` | `continuous_improvement` | 99 | 730.834 | Loop residente de 60s; puede solaparse con otros jobs. |
| `news_sentiment` | `sentiment` | 24 | 98.217 | Usado en estudios técnicos/sentimiento post-cierre cuando aplica. |
| `operational_learning` | sin rol | 1 | 56.192 | Parte del aprendizaje/review post-cierre. |
| `post_market_review` | sin rol | 1 | 1.781 | Review post-mercado. |

Hoy 2026-06-25 hasta la auditoría:

| Fuente | Rol | Llamadas | Tokens |
|---|---|---:|---:|
| `trade_decision` | `decision` | 19 | 688.435 |
| `continuous_improvement_lab` | `continuous_improvement` | 45 | 333.576 |

No aparecen roles `fast` o `deep` en las últimas 24h; sí hay históricos anteriores para `news_sentiment` role `fast`.

## Signal outcomes y duplicación

Desde `signal_outcomes`:

| Fuente | Filas totales | Grupos símbolo-día-estrategia | Shadow | Lectura |
|---|---:|---:|---:|---|
| `intraday_scan` | 278.075 | 12.015 | 49 | Principal causa histórica de duplicación. |
| `opportunity_snapshot` | 27.025 | 7.972 | 0 | También genera candidatos, pero con menor frecuencia. |
| `closed_market_study` | 13.002 | 12.003 | 42 | Mucho menos duplicado históricamente. |
| `manual_scan` | 3.493 | 998 | 0 | Manual/histórico. |
| `closed_market_study_backfill` | 660 | 489 | 0 | Backfill. |

Desde 2026-06-25:

| Fuente | Filas | Grupos | Shadow |
|---|---:|---:|---:|
| `intraday_scan` | 8.464 | 1.043 | 49 |
| `opportunity_snapshot` | 990 | 497 | 0 |
| `closed_market_study` | 538 | 538 | 42 |

Ejemplos recientes de `market_cycle_15m`:

| Run | Símbolos intradía | Símbolos breakout | `signals_saved` |
|---|---:|---:|---:|
| `mkt_a98552da808e` | 500 | 501 | 537 |
| `mkt_6dd665b146a9` | 500 | 501 | 537 |
| `mkt_36e8a3026d3e` | 500 | 501 | 537 |
| `mkt_9fa6afa3936c` | 500 | 501 | 538 |

## Conclusión factual

El ciclo pesado recurrente durante mercado abierto es `market_cycle_15m`: combina escaneo técnico de ~500 símbolos, breakout scan de ~501 símbolos, escritura de ~537 señales por ejecución y al menos una llamada LLM de decisión (~36k tokens en la última ventana completa observada). La última ejecución completa registrada duró ~614s, aunque la parte de scan técnico+breakout suele estar alrededor de ~54s de mediana; el resto corresponde al ciclo observable/LLM/decisión/ejecución paper.

El job de 1m `portfolio_watch_1m` es ligero en el caso normal observado: chequea cartera/órdenes/riesgo intradía, no escanea universo, no crea `signal_outcomes` y no llama LLM cuando no hay posiciones/órdenes; los últimos eventos están en decenas de milisegundos y el último runtime agregado en ~0,8s.

`continuous_improvement_lab` también corre cada 60s y consume LLM de forma relevante, pero no escanea símbolos ni genera candidatos de trading. En tokens de LLM, el dominante de las últimas 24h fue `trade_decision`; en frecuencia de LLM residente, `continuous_improvement_lab` aporta muchas llamadas pequeñas-medias.

No se propone ningún cambio de cadencia en este informe.

## Comandos/consultas ejecutadas

```powershell
rg -n "schedule|scheduler|every|interval|..." src scripts tests
rg -n "run_interval_seconds|market_cycle_interval_minutes|..." src\agente_bolsa\config.py .env .env.example src\agente_bolsa\scheduler.py
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main status
```

Además se ejecutaron consultas SQLite read-only (`file:data/state/agente_bolsa.sqlite3?mode=ro`) sobre:

- `agent_events`
- `runtime_state`
- `llm_usage`
- `signal_outcomes`

No se ejecutó `run-once`, `job-once`, `schedule` ni ningún ciclo pesado.
