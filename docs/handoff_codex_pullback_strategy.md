# Tarea para Codex: estrategia de candidatos "pullback" en SHADOW

## Contexto (autocontenido)
agenteBolsa = sistema multiagente de trading **paper** (Alpaca). Rama `codex/mejora_continua`.
Hoy (25-jun) desatascamos el embudo de decisión: 3 "paredes" de bugs/config abajo
(v0.4.45–0.4.49). Diagnóstico final, con datos en vivo (`cycle-funnel --history`):

- El sistema genera **candidatos de momentum EXTENDIDO** — la estrategia `builtin_breakout`
  propone líderes ya disparados (~17% sobre la SMA20), el MISMO nombre cada ciclo.
- El gate de calidad de entrada los **rechaza correctamente** (~82–92% de rechazos son
  "precio demasiado extendido sobre SMA20"). Nuestro estudio de edge confirma que lo
  extendido **revierte/pierde** a 5–10 días.
- Resultado: **0 trades**, que es **disciplina correcta**, no un bug.

**El lever real para operar nombres BUENOS es generar candidatos de PULLBACK / no-extendidos**
(comprar retrocesos de calidad en tendencia, no perseguir máximos). Eso es esta tarea.

## Objetivo
Implementar una **estrategia de generación de candidatos "pullback"** (mean-reversion suave)
en el registro de estrategias, **registrada como SHADOW**: acumula outcomes para medir su
edge, pero **NUNCA llega a decisión ni a ejecución**. Es **medir-primero**: no se promueve a
ACTIVE sin evidencia.

## Diseño propuesto
- Una estrategia nueva tipo `Strategy` (ver `strategies/base.py`) que, por cada símbolo del
  universo, construye el `technical_state` reutilizando `validate_symbol_technical_state`
  (igual que `builtin_breakout.build_breakout_candidate`) y emite como candidato SOLO los
  **pullbacks de calidad**, p.ej.:
  - tendencia mayor intacta: `close > sma_200` (y preferiblemente `> sma_50`),
  - **NO extendido**: `distance_sma20` por DEBAJO del umbral del gate (aprox. < 0.08–0.10;
    idealmente entre −0.05 y +0.05 = cerca de la SMA20 o ligeramente por debajo),
  - RSI moderado (p.ej. 40–60), NO sobrecomprado,
  - opcional: `return_20d` modesto o ligeramente negativo (retroceso reciente).
- Devuelve `CandidateSignal` (mismo dict que el scan; `direction="long"`).
- `name="builtin_pullback"`, `status="SHADOW"`, `target_regime="any"`.

## Cómo encaja (el mecanismo SHADOW ya existe)
`tools/technical_study.py:66–91`: `build_closed_market_technical_study` ejecuta
`registry.discover(store)`; las estrategias **ACTIVE** alimentan la decisión, las **SHADOW**
van a `report["shadow_candidates"]` y **se saltan decisión/ejecución**. Hoy solo
`builtin_breakout` está ACTIVE.

Registro: añadir la factory a `strategies/registry.py:BUILTIN_FACTORIES` y/o registrar vía
`registry.register(store, name="builtin_pullback", source_path=..., status="SHADOW")`.
El validador (`registry.validate_strategy_source`) **prohíbe** imports de
broker/execution/red — respétalo.

## Ficheros clave (leer antes)
- `src/agente_bolsa/strategies/base.py` — interfaz `Strategy`, `CandidateSignal`, `MarketContext`.
- `src/agente_bolsa/strategies/builtin_breakout.py` — ejemplo completo (~80 líneas), cópialo de patrón.
- `src/agente_bolsa/strategies/registry.py` — `discover`, `register`, `BUILTIN_FACTORIES`, validación AST.
- `src/agente_bolsa/tools/technical_study.py` (66–91) — ejecución de estrategias; SHADOW→shadow_candidates.
- `src/agente_bolsa/tools/technical_state_validator.py` — `validate_symbol_technical_state` (dict + setup_quality, umbrales).
- `docs/estudio_universo_y_seleccion_2026-06-24.md` — estudio de selección/edge.
- `docs/plan_desbloqueo_embudo_2026-06-25.md` — embudo de hoy (§1–§3, wall-check).
- `scripts/study_edge_by_score.py`, `scripts/study_signal_duplication.py` — herramientas de medición.

## Medición (cómo se valida después)
Tras unos días, comparar el forward `return_5d/10d` (neto de costes) de los candidatos
`builtin_pullback` (shadow) vs los de `builtin_breakout` (active), **por símbolo-día**
(no por fila — ver abajo). Promover a ACTIVE solo si el pullback muestra **expectativa
positiva out-of-sample, en varios regímenes, neta de costes**.

## Restricciones (CRÍTICAS)
- **NUNCA** tocar `tools/risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `config.py`, `.env`. `ALLOW_LIVE_TRADING` sigue `false`.
- La estrategia es **SHADOW** (cero impacto en trading) hasta que haya evidencia.
- Disciplina por entrega: **pytest verde** + `ruff check src tests` limpio + **subir
  `__version__`** en `src/agente_bolsa/__init__.py` (hay un test que lo exige) + dejar
  el sistema reiniciado. Con test del nuevo módulo.
- `.env` está sellado por kernel: si lo tocas (no deberías para esto), `kernel-seal` + `kernel-status`.

## Avisos prácticos
- **El editor trunca ficheros grandes** (p.ej. `trade_decision.py`, `storage.py`) en
  inserciones largas. Para ficheros grandes, edita en bloques pequeños y verifica con
  `python -m py_compile` tras CADA escritura (`wc -l` para detectar truncados). Los ficheros
  de estrategia son pequeños (~80 líneas) → sin problema.
- **Datos débiles / no sobreajustar:** `signal_outcomes` tiene **96.3% de duplicados**
  (mismo símbolo grabado ~27×/día por ciclo); la muestra INDEPENDIENTE real es ~11.473
  (símbolo-día) sobre 2026-05-11→06-24 (≈1 régimen). Por eso esto es SHADOW y medir-primero;
  **no promover** sin más días/regímenes. Idealmente arreglar antes **T6** (dedup por
  símbolo-día en `record_signal_candidates`, `tools/signal_learning.py:125`) para medir limpio.

## Definición de hecho
Estrategia `builtin_pullback` en SHADOW, con test, pytest+ruff verdes, versión subida,
documentada en `docs/plan_mejoras_y_tareas.md`, sistema reiniciado. SIN cambiar la conducta
de trading (sigue en breakout-active; pullback solo mide).
