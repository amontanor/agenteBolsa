# Prompt P4 para Codex — 2-jul-2026 (tarde) — dirección del responsable

Contexto: P1 (v0.4.82) validó vol-target 12% fijo contra criterios pre-registrados
(CUMPLE) y P2 (v0.4.83) destapó la cola READY_TO_APPLY con propuestas de agresividad
sin evidencia. Esta tarea tiene tres partes independientes; si alguna se complica,
entrega las otras y repórtalo. Nada de esto cambia conducta de trading real.

## Parte 1 — Shadow del overlay vol-target 12% (observabilidad, sin órdenes)

Antes de cualquier decisión estratégica sobre el overlay, necesitamos verificar que
la señal calculada EN VIVO replica la del backtest.

1. Nuevo módulo/script aislado (patrón telegram-radar: fuera del scheduler de
   trading) que cada día de mercado calcule y persista:
   - exposición objetivo según vol-target 12% sobre SPY (misma matemática y ventana
     de vol realizada que `study_drawdown_overlay_deep.py` — reutiliza el motor, no
     lo dupliques);
   - también la de vol-target 10% y régimen SMA200 como comparadores;
   - vol realizada trailing usada, precio SPY, fecha de datos.
2. Persistencia append-only en `data/research/overlay_shadow/overlay_shadow_<fecha>.json`
   + un acumulado `overlay_shadow_log.jsonl`. Read-only respecto a trading: NO crea
   órdenes, NO toca el book, NO se registra en el scheduler operativo.
3. Script one-shot + supervisor sin admin (mismo patrón que
   `run_telegram_radar_daily.ps1` / supervisor). No lo arranques: documenta el comando.
4. Test que verifique que, alimentado con la misma serie histórica, el cálculo del
   shadow reproduce exactamente la exposición del estudio deep (paridad
   backtest-vivo). Este test es el corazón de la parte 1.
5. En el informe: aclara la inconsistencia detectada por el responsable en P1 —
   "peor mes" de la tabla de episodios vs la tabla de criterios (¿rolling vs
   calendario?). Define ambos explícitamente y di cuál usa cada tabla.

## Parte 2 — Gate de evidencia para propuestas de agresividad de trading

El digest mostró que `max_daily_buy_orders` y `max_orders_per_cycle` llegaron a
READY_TO_APPLY justificadas con "más trades → más outcomes", sin evidencia de edge.
La política de la casa: los aumentos de agresividad son human-gated CON evidencia.

1. Regla determinista en el lab (mismo estilo que la constitución v1/v2): una
   propuesta que aumente parámetros de agresividad de trading (lista explícita:
   `max_daily_buy_orders`, `max_orders_per_cycle`, `trade_selection_top_n`, y los
   análogos que identifiques en `Settings` con criterio documentado) NO puede pasar
   a READY_TO_APPLY sin un experimento PASSED enlazado que aporte evidencia de edge
   (expectancy/alpha forward positiva neta de costes). Sin evidencia → queda
   VALIDATING o se rechaza con razón `aggressiveness_requires_edge_evidence`.
2. Aplica la regla retroactivamente a la cola actual: las propuestas de agresividad
   hoy en READY_TO_APPLY sin evidencia pasan a REJECTED con esa razón, dejando
   registro auditable. Lista en el informe cada una con su id.
3. Audita por qué `deterministic_gate_error_severity` (relajación de severidad del
   gate) alcanzó READY_TO_APPLY sin ser bloqueada por la constitución v2. Si es un
   hueco de cobertura, ciérralo con la misma mecánica y añade el caso al
   test-candado contra `Settings.model_fields`; si es intencional, justifícalo.
4. Tests: propuesta de agresividad sin evidencia → bloqueada; con experimento
   PASSED enlazado → puede llegar a cola humana (nunca auto-apply); caso
   `deterministic_gate_error_severity` cubierto.

## Parte 3 — Limpieza del digest (dos fixes menores)

1. PIDE APROBACIÓN no debe listar propuestas ya APPLIED o ROLLED_BACK (hoy re-lista
   la demo codegen revertida).
2. Harmoniza el KPI `% exp→aplicado` con la columna `Applied` (semana 29-jun mostró
   Applied=1 con conversión 0.00%): documenta la definición exacta y haz que sean
   consistentes. Añade test con BD sintética que cubra ese caso.

Informe único en `docs/informe_codex_p4_overlay_shadow_gate_<fecha>.md`. Sé escéptico:
en la parte 1, si la paridad backtest-vivo no es exacta, NO la fuerces — documenta la
divergencia y su causa.

Bloque de verificación obligatorio:
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde (con los tests nuevos).
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio. Arreglos de lint en
  ficheros ajenos a esta tarea: commit separado, no mezclados.
- Bump de `__version__`.
- Ejecución real de la parte 1 (un JSON de shadow generado contra datos reales) y
  del digest tras la parte 3.
- Commit(s) con diff revisable.
- Confirmar `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` intactos.
- NO tocar: `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`.
