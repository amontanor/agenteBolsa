# Tutorial de arranque diario - agenteBolsa

Audiencia: agente u operador que levanta o verifica el proceso cada dia.
Horarios en Europe/Madrid. En junio de 2026 NYSE abre a las 15:30 y cierra a las 22:00 Madrid.

## 1. Regla por dia

El proceso se levanta o verifica todos los dias laborables por la manana, idealmente entre 08:00 y 12:00 Madrid, antes de la apertura NYSE.

| Dia | Accion |
|---|---|
| Lunes a viernes con NYSE abierto | Arranque o verificacion normal |
| Sabado y domingo | No hace falta arrancar; si ya corre 24/7, solo verifica que no haya alertas |
| Festivo NYSE | No arrancar para operar; se puede dejar 24/7 en modo espera |

Referencia actual: domingo 14 de junio de 2026 no hay sesion. La proxima apertura esperada es lunes 15 de junio de 2026 a las 15:30 Madrid.

Festivos NYSE restantes de 2026:
- Viernes 19 de junio: Juneteenth.
- Viernes 3 de julio: Independence Day observado.
- Lunes 7 de septiembre: Labor Day.
- Jueves 26 de noviembre: Thanksgiving.
- Viernes 25 de diciembre: Navidad.

En caso de duda:

```powershell
python -m agente_bolsa.main schedule-status
```

## 2. Verificacion previa obligatoria

Desde PowerShell:

```powershell
cd C:\Antonio\Bref\agenteBolsa
.\.venv\Scripts\Activate.ps1
python -m agente_bolsa.main status
python -m agente_bolsa.main kernel-status --json
python -m agente_bolsa.main broker-status
python -m agente_bolsa.main schedule-status
python -m agente_bolsa.main operational-health --json
```

Condiciones para arrancar:
- `kernel-status` debe mostrar `violations: []`.
- `broker-status` debe mostrar Alpaca paper activo.
- `TRADING_MODE` debe seguir en `paper`.
- `ALLOW_LIVE_TRADING` debe seguir en `false`.
- `operational-health` no debe tener alertas criticas.

Si hay violaciones de kernel, no se arranca. Avisar a Antonio. Solo se ejecuta `kernel-seal` si el cambio fue intencionado, revisado y validado.

## 3. Arranque

Si no hay proceso vivo:

```powershell
python -m agente_bolsa.main schedule
```

Dejar esa ventana abierta. Si aparece que el scheduler ya esta arrancado, no lanzar una segunda instancia.

Dashboard:

```powershell
python -m agente_bolsa.main web
```

## 4. Que debe pasar durante sesion

| Hora Madrid | Actividad esperada |
|---|---|
| Antes de 15:30 | Espera y, si toca, estudio de mercado cerrado |
| 15:30-22:00 | Vigilancia de cartera y ciclos de mercado cada 15 minutos |
| 16:00, 19:00, 21:00 | Snapshots de oportunidades |
| Tras 22:00 | Post-market review, aprendizaje y laboratorio |

Alerta nueva importante: si NYSE esta abierto y pasan mas de 30 minutos sin snapshots/reportes frescos de datos, `operational-health` debe emitir `data_pipeline_down` y bloquear nuevas compras hasta que vuelva a haber datos frescos.

## 5. Revision rapida

Durante la sesion:

```powershell
python -m agente_bolsa.main schedule-status
python -m agente_bolsa.main production-health --json
python -m agente_bolsa.main market-data-quality --json
```

Al final del dia:

```powershell
python -m agente_bolsa.main performance --days 7 --json
python -m agente_bolsa.main autonomy-digest --json
python -m agente_bolsa.main live-readiness --json
```

Avisar si:
- aparece `data_pipeline_down`, `kernel_integrity_violation`, `job_failed` critico o kill switch activo;
- `market-data-quality` no cubre el universo;
- hay varios dias de mercado sin ejecuciones;
- `lab_flow.resolved_last_7d` sigue en 0 y `oldest_open_days` crece.

## 6. Parada

Parada normal: `Ctrl+C` en la ventana de `schedule`.

Parada de emergencia: boton de pausa total en el dashboard. Debe usarse si hay riesgo operativo, alertas criticas o comportamiento inesperado con mercado abierto.

## 7. Estado recomendado

Hasta acumular muestra estadistica suficiente:
- mantener paper trading;
- no activar live;
- usar modo medicion/freeze si se quiere evaluar edge sin que el laboratorio auto-aplique cambios;
- revisar `edge-report` solo como orientacion hasta acercarse a 60 sesiones.
