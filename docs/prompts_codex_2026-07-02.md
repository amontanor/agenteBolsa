# Prompts para Codex — 2-jul-2026 (dirección del responsable)

Orden de lanzamiento: P1 hoy. P2 cuando P1 esté entregado y revisado. P3 el lunes 6-jul.

---

## PROMPT P1 — Robustez histórica profunda del overlay vol-target (read-only)

Contexto: el estudio `docs/informe_codex_drawdown_overlay_2026-07-02.md` (v0.4.81)
identificó vol-target 10-12% como mejor candidato de control de caídas, pero su
walk-forward OOS solo aplica 2023-2026 (tramo favorable) y entrena con un único bear
(2022). Necesitamos saber si vol-target sobrevive a varios regímenes bajistas reales
antes de considerarlo palanca operativa. Estudio 100% read-only: no toca trading, no
crea órdenes, no modifica el scheduler.

Tarea:

1. Extiende `scripts/study_drawdown_overlay.py` (o crea `scripts/study_drawdown_overlay_deep.py`
   reutilizando el motor) para trabajar SOLO con SPY con el máximo histórico disponible
   vía yfinance (objetivo: desde 2000-01-01; documenta el primer dato real obtenido).
   NO uses la cesta equal-weight para el tramo largo (sesgo de supervivencia reconocido).
2. Rejilla SIN CAMBIOS respecto al estudio previo (pre-registrada): SMA150/200/250,
   vol-target 10/12/15%, drawdown-guard 10/15/20%, combos régimen+vol, buy&hold.
   Prohibido añadir parámetros nuevos o variantes a posteriori.
3. Walk-forward expansivo con bloques ANUALES: entrena 2000-2004, aplica 2005; entrena
   2000-2005, aplica 2006; ... hasta 2026. Reporta la secuencia de políticas
   seleccionadas y en cuántas transiciones cambia (métrica de estabilidad).
4. Análisis de POLÍTICA FIJA (el test sin cherry-picking, es lo más importante):
   evalúa vol-target 12% y vol-target 10% FIJOS en todos los bloques OOS, sin
   selección alguna, vs buy&hold. Costes 10/20/30 bps.
5. Para cada episodio de drawdown grande de SPY (>15%: 2000-02, 2008-09, 2011, 2015-16,
   2018, 2020, 2022), tabla específica: max DD, peor semana, peor mes, Ulcer, tiempo de
   recuperación, buy&hold vs vol-target fijo 10/12%.
6. Sanity-check de datos: compara los cierres de SPY contra ^GSPC (retornos diarios,
   correlación y desviaciones >1%); lista anomalías (splits/dividendos mal ajustados).
7. Criterios de éxito PRE-REGISTRADOS por el responsable (evalúalos explícitamente en
   el informe, no los reinterpretes): vol-target 12% fijo, neto 20 bps, debe (a) reducir
   max DD y peor mes vs buy&hold en >=80% de los años con drawdown >15%, y (b) mantener
   Sortino de periodo completo >= buy&hold. Veredicto binario: CUMPLE / NO CUMPLE, con
   los números al lado.

Informe único en `docs/informe_codex_drawdown_overlay_deep_2026-07-02.md` con método,
tablas, veredicto contra los criterios pre-registrados, limitaciones y verificación.
Sé escéptico: si el resultado sale bonito, busca activamente por qué podría ser falso
(sesgo de datos, ventana, coste infraestimado) y documéntalo.

Bloque de verificación obligatorio:
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde (incluye tests nuevos del estudio).
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio.
- Bump de `__version__` en `src/agente_bolsa/__init__.py`.
- Ejecución real del estudio con salida JSON en `data/reports/`.
- Commit con diff revisable.
- Confirmar `trading_mode=paper` y `allow_live_trading=false`.
- NO tocar: `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`.

---

## PROMPT P2 — Fase 3 mínima de la firma: digest diario + KPI funnel + calidad de propuestas (medición, sin enforcement)

Contexto: la firma tiene raíles completos (Fases 0-2: propuestas → experimentos →
codegen → apply humano reversible, con constitución v2 y auto-apply sellado OFF), pero
sigue sin gobierno continuo: no hay digest diario que llegue al humano, no hay KPI
funnel visible, y sabemos que genera prosa/busywork (1.600+ propuestas, experimentos
casi todos lanzados a mano). Antes de poner críticos que "muerdan" (enforcement),
medimos. Nada de esto cambia conducta de trading.

Tarea (tres entregas en una):

1. **Digest diario programado.** El comando `continuous-improvement-lab digest --days N`
   (v0.4.72) ya existe en modo lectura. Crea un mecanismo diario AISLADO del runtime de
   trading (mismo patrón que `run_telegram_radar_supervisor.ps1`: script one-shot +
   supervisor sin admin, o extiende el supervisor existente para encadenar ambos jobs)
   que escriba `data/reports/ci_digest_<fecha>.md`. El digest debe terminar con una
   sección "PIDE APROBACIÓN" listando propuestas `READY_FOR_HUMAN_REVIEW` con
   `tests_ok=true` (id, título, targets del diff) para que el humano pueda correr
   `continuous-improvement-lab review/approve`.
2. **KPI funnel de la firma.** Añade al digest (o a un subcomando `--kpis`) las métricas
   del plan estratégico, calculadas desde las tablas reales: propuestas/semana,
   experimentos/semana, applied_changes/semana, % propuestas→experimento,
   % experimento→aplicado, WIP actual, edad mediana propuesta→decisión, rollbacks.
   Serie de las últimas 4 semanas para ver tendencia.
3. **Medición de calidad de propuestas (SIN enforcement todavía).** Clasificador
   determinista (no LLM) sobre las últimas ~200 propuestas: EJECUTABLE (contiene
   parámetro+valor actual→propuesto, o spec de diff con targets, o regla shadow
   concreta) vs PROSA. Reporta distribución global, por agente proponente y por semana.
   Incluye en el informe 5 ejemplos literales de cada clase para que el responsable
   valide el clasificador. NO rechaces nada en intake aún: primero validamos la
   medición, el enforcement será tarea posterior.

Informe único en `docs/informe_codex_fase3_minima_<fecha>.md`. No arranques el
supervisor: deja el comando de arranque documentado para Antonio.

Bloque de verificación obligatorio:
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde (con tests nuevos: digest a
  fichero, KPIs contra BD sintética, clasificador con casos ejecutable/prosa).
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio.
- Bump de `__version__`.
- Ejecución real: un `ci_digest_<fecha>.md` generado contra la BD real, adjunto o citado
  en el informe.
- Commit con diff revisable.
- Confirmar `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` intactos.
- NO tocar los 6 ficheros del suelo de kernel.

---

## PROMPT P3 — (lanzar lunes 6-jul) Lectura pullback vs breakout con criterios pre-registrados

Contexto: `builtin_pullback` lleva en SHADOW desde el 25-jun con la cadena de medición
verificada end-to-end (v0.4.52-0.4.54). Hoy toca el veredicto con muestra madura.
Estudio read-only; la promoción, si procede, sería una tarea separada y aprobada por
el humano.

Tarea:

1. Ejecuta `scripts/study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10
   --cost-bps 10` y repite con `--cost-bps 20`.
2. Reporta cobertura de maduración por horizonte (n de símbolo-días maduros por
   estrategia). Si n<30 en 5d para pullback, dilo de frente: el veredicto se pospone.
3. Ajusta por mercado: excess return vs SPY del mismo periodo por horizonte (usa el
   benchmark del cache como en `edge_shadow_analysis`).
4. Desglosa por régimen de mercado y por semana; comprueba si el resultado depende de
   un solo día o de un solo sector (top-3 contribuidores por símbolo).
5. Compara también la CALIDAD de candidatos: distribución de `distance_sma20`/`rsi_14`
   de pullback vs breakout (scoreboard `cycle-funnel --shadow-scoreboard`), y cuántos
   candidatos pullback habrían pasado el gate de entrada real.
6. Criterios de promoción PRE-REGISTRADOS por el responsable (2-jul, antes de ver
   datos): pullback → ACTIVE solo si expectancy 5d Y 10d positiva neta de 10 bps,
   excess vs SPY positivo, n>=30 maduros, y sin dependencia de un solo día/sector.
   Veredicto binario contra estos criterios. El prior del backtest es que NO habrá
   edge robusto: si el resultado sale positivo, busca primero por qué podría ser
   espurio (pocos días, régimen único, un ganador outlier).

Informe único en `docs/informe_codex_pullback_verdict_2026-07-06.md`. NO promover nada
en esta tarea aunque los criterios se cumplan: la promoción sería tarea aparte.

Bloque de verificación obligatorio:
- `pytest` verde, `ruff` limpio, bump de `__version__` (si hay cambios de código; si es
  solo ejecución+informe, indícalo y no subas versión).
- Commit si hay cambios.
- Confirmar `trading_mode=paper`, `allow_live_trading=false`.
- NO tocar los 6 ficheros del suelo de kernel.
