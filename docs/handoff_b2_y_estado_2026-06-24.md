# Handoff — estado y tarea en vuelo (24-jun-2026)

Objetivo general: mejorar agenteBolsa de forma **medida y segura** (paper-only).
Disciplina: shadow → guarded → active; nada se promueve sin evidencia OOS neta de
costes. **NUNCA tocar** `risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`,
ni `ALLOW_LIVE_TRADING` (debe seguir `false`). `.env` está sellado por el kernel
(cualquier cambio requiere `kernel-seal` + `kernel-status`).

## TAREA EN VUELO: B2 — embudo del ciclo (cycle-funnel)

Objetivo: un report que muestre, para el último `market_cycle`, el embudo
universo → candidatos → finalistas → recomendaciones → review determinista →
review adversarial → gate entry-quality → gate backtest → planes → órdenes/fills,
con los **motivos de rechazo** y el **cuello** ("por qué no se compró"). Solo lectura.

### Estado: código COMPLETO y compila (py_compile OK). FALTA validar (pytest) y commitear.

Ficheros (sin commitear):
- `src/agente_bolsa/tools/cycle_funnel.py` (NUEVO): `build_cycle_funnel(store, settings)`,
  `format_cycle_funnel`, `_summarize`, `_identify_bottleneck`. Lee el último evento
  `paper_auto_trade_completed` (payload con reviews/gates/motivos/submitted) +
  `data/reports/latest_closed_market_technical_study.json` (universo/candidatos).
- `src/agente_bolsa/storage.py`: añadido método `latest_event_of_type(event_types)`
  justo tras `latest_events`.
- `src/agente_bolsa/main.py`: añadido `command_cycle_funnel` + subcomando `cycle-funnel`
  (con `--json`).
- `src/agente_bolsa/__init__.py`: versión 0.4.42 → **0.4.43**.
- `tests/test_cycle_funnel.py` (NUEVO): 2 tests.
- `docs/plan_mejoras_y_tareas.md`: B2 marcado hecho.

### ⚠️ INCIDENTE QUE CODEX DEBE CONOCER
Al añadir `latest_event_of_type` a `storage.py`, la herramienta de edición **truncó el
fichero DOS veces** exactamente en el string `"SELECT event_id, agent, event_type,..."`
(quedaba cortado en `"SELECT ev`), perdiendo el resto del fichero. Se **recuperó** así:
`git show HEAD:src/agente_bolsa/storage.py > storage.py` y luego se insertó el método
con un script Python (no con el editor). Ahora `storage.py` = 4535 líneas, compila, y
contiene `latest_event_of_type` + `event_from_dict` + `hypothesis_to_dict`.
**Recomendación: tras cualquier escritura de `storage.py`, verificar `wc -l` + `py_compile`.**

### Validación pendiente (en Windows)
```
Remove-Item .git\index.lock -ErrorAction SilentlyContinue   # lock atascado de un commit colgado
.\.venv\Scripts\python.exe -m pytest -q -p no:warnings       # esperaba verde (734 passed antes de B2)
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel # probar el comando
```
Commit sugerido (solo ficheros propios; hay otros docs .pine/operating_model modificados
que NO son de esta tarea):
```
git add src/agente_bolsa/storage.py src/agente_bolsa/tools/cycle_funnel.py src/agente_bolsa/main.py src/agente_bolsa/__init__.py tests/test_cycle_funnel.py docs/plan_mejoras_y_tareas.md docs/estudio_universo_y_seleccion_2026-06-24.md scripts/study_edge_by_score.py
git commit -m "B2: comando cycle-funnel (embudo del ciclo con motivos) v0.4.43"
```

## Ya COMPLETADO y COMMITEADO (contexto)
- **A1 (v0.4.38):** bug en `market_snapshot.build_market_snapshot` (el bucle iteraba
  `symbols` en vez de `unique_symbols`) → el benchmark SPY no entraba → regime "unknown"
  + fuerza relativa rota. Arreglado + test.
- **A1b:** decisión de NO conectar FMP (el plan gratis no trae earnings; además PARTIAL
  no bloquea comprar, solo baja size).
- **A2 (v0.4.39/0.4.41/0.4.42):** shadow por ciclo del setup-edge; `setup_quality_key`
  corregido a `{base}|{quality}` (casaba mal con la edge_table → sesgo inerte); shadow
  extendido a `all_candidates`.
- **Lock atómico (v0.4.40):** `_acquire_scheduler_lock` con `O_CREAT|O_EXCL` (evita
  schedulers duplicados por carrera).
- **Ops:** el `.venv` estaba montado sobre el python de codex-runtime → recreado sobre
  Python 3.11 estable del sistema (adiós procesos duplicados). `check_services.ps1`
  mejorado (veredicto por lock, no por conteo).

## HALLAZGO ESTRATÉGICO (importante)
La taxonomía `setup_quality` es **degenerada** (87% de los ~343 candidatos del S&P500
caen en `confirmed_pattern|strong`). El estudio de edge (`scripts/study_edge_by_score.py`,
250k muestras) parecía mostrar que la extensión/score alto es tóxica y los pullbacks
ganan — **pero NO es robusto**: `signal_outcomes` solo cubre **2026-05-06 → 2026-06-24
(7 semanas, 2 meses)** y el efecto lo dispara el selloff de junio (en mayo la extensión
ganaba). **DECISIÓN: NO cambiar la selección** (sería overfit a junio). Único patrón
consistente: score medio 8-16 ~+0.87%/10d (modesto). Detalle:
`docs/estudio_universo_y_seleccion_2026-06-24.md` (secciones 6-8).

## SIGUIENTE (tras B2), según prioridad elegida por Antonio
B2 (en vuelo) → luego el resto del menú: arreglar el clasificador degenerado,
acelerar ciclos (C2, paralelizar sentimiento), disciplina de salida (exits). Todo
medido en shadow antes de tocar conducta.

## Notas de entorno
- Servicios = 2 tareas programadas Windows (`AgenteBolsaScheduler` vía
  `run_scheduler_supervisor.ps1`, `AgenteBolsaWeb`). Reinicio limpio:
  `scripts\restart_services.ps1`. Diagnóstico: `scripts\check_services.ps1`.
- La copia de la BD en el sandbox Linux dio `database disk image is malformed` en una
  query (posible WAL inconsistente en el snapshot de solo-lectura); la BD de Windows
  es la buena. Validar siempre en Windows con el `.venv`.
- pytest verde de referencia: **734 passed** (antes de añadir los tests de B2).
