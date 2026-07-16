# Relevo de direccion tecnica — agenteBolsa

> Actualizado: **16-jul-2026**. Produccion **0.4.174** (`5c0b1ea9`).
> Candidato secuencial validado: **0.4.176**.

## Objetivo

Mejorar beneficio neto sin aceptar grandes caidas y construir expertos
autonomos que aprendan con evidencia. Live, apply, configuracion sensible y
promociones siguen human-gated.

## Produccion

- Paper activo; live y auto-apply desactivados.
- Kernel sellado sin violaciones. `unsealed` temporal no describe produccion.
- P-L45B1 desplegado: un postmarket efectivo, reconciliacion coordinada, una
  actualizacion de outcomes y terminales duraderos.
- P-L43: legacy gobierna time-stop; XNYS es exclusivamente shadow.
- Cohortes P-L27/P-L29/P-L30/P-L31/P-L32/P-L33 siguen collecting.
- Overrides adaptativos historicos permanecen; la frontera actual impide nuevas
  promociones con auto-apply false.

## Secuencia validada

1. **0.4.175 P-L45B2**: observations en chunks de 250; 33.336 filas, 134
   commits, paridad exacta y sin locks normales.
2. **0.4.176 P-L43BR5**: autoridad desde buy order exacta; corrige
   `PositionSide.LONG -> unsupported_side` solo en shadow.
3. **0.4.177 P-L44B**: penalizacion unica solo shadow; esperar evidencia real.
4. **0.4.178 P-L46B UI**: Cartera abierta por ultima compra y fecha/hora.

No combinar releases sin ensayo conjunto. Despliegue: XNYS cerrado, sin jobs,
suite verde, hash sensible intacto y rollback por revert.

## Evidencia reciente

- P-L43C: 69 portfolio watches, cinco eventos idempotentes, cero ordenes XNYS.
- P-L45A: postmarket p50 ~23 min, maximo ~41 min; P-L45B1 coordina y P-L45B2
  reduce commits.
- 7–13 jul: cuenta -0,0401%, SPY +0,1953%; muestra/exposicion insuficientes.
- Salidas time-stop: muestra pequena/mixta; no cambiar politica aun.

## Agenda

- Cada sesion: ciclos, identidad, shadow, ejecucion y terminal PMR.
- Tras P-L45B2: cinco sesiones antes de juzgar duracion/locks.
- 20-jul: relectura `builtin_pullback`.
- 27/28-jul: primeras madureces tecnicas RR/salidas, aun no muestra suficiente.
- Tras 45 dias agent_run: evaluar roles.
- 1-sep: dictamen de aprendizaje con criterio original.

## Reglas

- No rellenar legacy ni IDs por simbolo/fecha.
- No usar fills/P&L como forward.
- No promover collecting/unavailable.
- No tocar archivos protegidos sin revision humana.
- No desplegar/reiniciar con XNYS abierto salvo emergencia expresa.
- No servicios manuales: tareas y `scripts/stack_*.ps1`.
- No ocultar suite roja con skip/xfail.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

`docs/plan_mejoras_y_tareas.md` es la unica fuente de tareas.
