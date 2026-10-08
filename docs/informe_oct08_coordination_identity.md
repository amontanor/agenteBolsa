# Dictamen N2 — identidad de recuperación postmarket — 8-oct-2026

Dictamen: `ready_for_integration_rehearsal`. El lote corrige la identidad de
recuperación entre sesiones y tipos de lease sin cambiar la autoridad de
trading, el historial append-only ni `last_session`. No es un release ni un
despliegue productivo.

## Identidad y alcance

- Worktree: `C:\Users\utopi\.codex\worktrees\oct08-coordination-identity\agenteBolsa`
- Rama: `codex/oct08-coordination-identity`
- Base exacta: `ab28bd86193ef48a18d1f058e2f79492721c1412`
- Tree de base: `daa3f125e2da5b0504924dce5a6858764a9aa1f9`
- HEAD funcional final: `f84e275a5d002bd27afeb25e0988c337ca7d002e`
- Tree funcional final: `b6de6405f5231dae905ceece2bf5202211e8a69b`
- Versión: `0.4.346` (se atravesaron `.344` y `.345` en commits intermedios; el
  plan no contenía reserva previa)
- Informe único del lote: este archivo.
- El plan maestro y el relevo compartidos no se modificaron.

Commits separados:

- `2962e6a6` — caracterización focal de identidad y recuperación.
- `ca311574` — corrección funcional y bump de versión a `0.4.344`.
- `79dcfacd` — sesión ausente como `unavailable`, conflicto PMR/recon y bump
  final a `0.4.345`.
- `f84e275a` — guard de dueño vivo entre PMR/reconciliación y bump final a
  `0.4.346`.

## Causa y contrato corregido

Al recuperar un lease muerto, `acquire()` y `acquire_reconciliation()` construían
el evento terminal y el marker con la `session_date` del adquirente. El run
recuperado de 7-oct podía quedar etiquetado como 8-oct, mientras su vista
`post_market_coordination:session:2026-10-07` seguía `active`. Además, un
terminal tardío podía sobrescribir una vista de sesión que ya pertenecía a otro
run.

El cambio es acotado:

- terminal y marker de recuperación conservan la sesión del propietario
  original; si falta en el lease queda `unavailable`, nunca se copia la sesión
  del adquirente. El marker añade `replacement_session_date` para la sesión que
  toma el lease;
- la vista de sesión anterior sólo se elimina mediante compare-and-swap cuando
  coinciden exactamente `run_id`, PID y token del propietario recuperado;
- terminal sólo marca la vista de sesión si la vista actual conserva esa misma
  identidad exacta;
- dueño vivo, PID reutilizado con token distinto y vista conflictiva no se
  roban ni se liberan;
- un PMR no inicia mientras exista una reconciliación viva, y una
  reconciliación no sobrescribe una reconciliación viva aunque haya un terminal
  PMR residual;
- el evento terminal ya existente se conserva sin sobrescritura ni conflicto;
  la idempotencia sigue siendo la de `Store.record_append_only_event`;
- no se toca `agent_events` histórico ni `post_market_review_last_session`.

No se modificaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py`, `config.py` ni `.env`.

## Reproducción y resultados

Antes de corregir, las pruebas focales existentes del coordinador pasaron:
`24 passed in 18.85s`. La caracterización inicial contra esta base reprodujo
el defecto en cuatro casos: `3 failed, 1 passed in 0.60s`. Los fallos fueron
la sesión nueva en el terminal/marker recuperado, la vista de sesión vieja sin
liberar y el terminal tardío sobrescribiendo al dueño nuevo.

Después del cambio:

- `tests/test_oct08_coordination_identity.py` más las regresiones
  `test_p45b_postmarket_reliability.py`, `test_p45b1_integration_qa.py` y
  `test_p45b2_integration_qa.py`, además de `test_version_policy.py`:
  `35 passed in 17.77s`;
- Ruff focal sobre coordinador y pruebas: `All checks passed!`;
- `scripts/check_no_nulls.py`: `OK (545 archivos)`;
- `git diff --check`: verde;
- worktree final: limpio.

Los nuevos casos también cubren un dueño vivo que ya tiene un terminal antiguo
sin robarlo, una vista de sesión ausente que debe seguir `unavailable`, y un
terminal PMR que no libera un lease de reconciliación con otra identidad, y los
dos sentidos del conflicto con un lease vivo PMR/reconciliación.

Los fixtures usan `Settings(_env_file=None)`, `PYTHONPATH` del worktree,
SQLite temporal y propietarios sintéticos; no usan red, broker, LLM, yfinance,
servicios ni datos productivos.

## Estado operativo y límites

La dirección comunicó para la ventana del 8-oct: XNYS cerrado, próxima apertura
15:30 Madrid, sin jobs activos ni leases activos observados, `paper=true`,
`live=false` y `auto-apply=false`. Este lote no volvió a consultar ni mutar
producción y no despliega.

Se omitieron fullsuite, smoke, validación integral de configuración/kernel,
integración conjunta, merge productivo, reinicio, build, push y cualquier
interacción con broker/red/LLM. El conflicto entre PMR y reconciliación se
verifica para no liberar la identidad ajena; resolver ordenamiento global o
concurrencia adicional entre ambos tipos de lease queda fuera del lote y
requiere una revisión independiente.
