# Informe Oct08: frescura del bloqueo operativo

## Dictamen

El defecto queda reproducido en la base `0.4.348` (`HEAD 52cc0fa5921ff690cfec4d08d5eda5c9c1bbccb1`, `tree 28a76ff51aa66139c02700ce0f86789842b51b4c`):
`load_operational_block_context` sigue bloqueando compras por un `data_pipeline_down` emitido por un informe de salud anterior aunque existe un snapshot de mercado posterior. El lote queda `ready_for_implementation` para un parche aislado de frescura, con seguridad N3. No se modifica fuente, versión, configuración, producción ni política activa en este lote.

La ventana operativa queda `precondition_not_met` para cualquier suite completa, smoke, despliegue o comprobación productiva: el `schedule-status` SSH aportado para el 8-oct a las 22:15 Europe/Madrid indicó XNYS cerrado, pero `PMR8` aún no tenía terminal `completed|failed`. Por tanto no se ejecutaron gates operativos.

## Causa y contrato actual

Productor: `build_operational_health_report` calcula `_data_pipeline_heartbeat` y publica `reports/latest_operational_health.json`. El scheduler refresca ese informe al arrancar y cada 45 minutos (`operational_health_refresh_job`). Consumidor: `load_operational_block_context` lee el último JSON y conserva todas las alertas críticas durante `KILL_SWITCH_MAX_REPORT_AGE_SECONDS = 6 * 60 * 60`.

La función acepta `now`, pero para decidir si el informe ha caducado usa `datetime.now(timezone.utc)` y el `st_mtime` del JSON. No compara `payload.as_of` con el snapshot más reciente, no vuelve a observar `data_pipeline` y no elimina selectivamente `data_pipeline_down` cuando aparece evidencia posterior. Así, el informe es reciente como archivo (menos de seis horas) aunque su diagnóstico de pipeline sea obsoleto. La ausencia o antigüedad superior a seis horas conserva la semántica existente de `stale_operational_health_report` con bloqueo de compras desactivado; esta frontera se caracteriza y no se cambia aquí.

Contrato de seguridad para el siguiente lote:

1. Refrescar solo la observación de `data_pipeline_down` con reloj explícito, calendario XNYS y artefacto de datos canónico posterior; exigir edad de snapshot dentro de los 30 minutos cuando XNYS esté abierto.
2. Mantener cada alerta crítica independiente (`job_failed`, `missing_report`, `stale_required_report`, etc.). Un snapshot nuevo no puede descartar el resto del kill switch ni reescribir la historia append-only.
3. Evaluar primero `operational_kill_switch.json`. Un override persistente manual o de integridad sigue bloqueando hasta su propia ruta explícita de recuperación; el refresco de datos no lo borra ni lo sustituye.
4. Ante timestamp ausente, reloj incoherente, snapshot no verificable o evidencia `unavailable`, conservar bloqueo de seguridad y publicar razón/edades explícitas. No inferir salud por la mera existencia de un archivo.

## Evidencia operacional fechada

Artefactos usados, solo lectura:

- `C:\Users\utopi\.codex\worktrees\ef99\agenteBolsa\audit_oct08_evening_results.json`, raíz `as_of=2026-10-08T19:20:16.953686+00:00`, `version=0.4.321`.
- `C:\Users\utopi\.codex\worktrees\ef99\agenteBolsa\audit_oct08_evening_account.json`, snapshot de cuenta y payload de salud del mismo corte.

Secuencia productor-evento-consumidor verificada en `audit_oct08_evening_results.json`:

| Hecho | UTC | Europe/Madrid | Lectura |
|---|---:|---:|---|
| `latest_operational_health` consumido por bloqueo, `as_of` | 17:55:06.413376 | 19:55:06.413376 | Alertó `data_pipeline_down`; última referencia `market_state_mkt_e7262a5649c1.json`, `2460s` de edad. |
| Snapshot posterior, evento `market_snapshot_completed` | 17:58:14.226969 | 19:58:14.226969 | `mkt_790e09534e15`, `Snapshot guardado con 25 simbolos`. Ocurrió 3m07.813593s después del `as_of` de salud. |
| Snapshot posterior adicional, evento `market_snapshot_completed` | 18:47:06.306643 | 20:47:06.306643 | `mkt_92a9836a3a39`, `Snapshot guardado con 24 simbolos`. |
| `paper_auto_trade_blocked` | 19:15:00.993051 | 21:15:00.993051 | Volvió a consumir exactamente `as_of=17:55:06.413376`; `block_new_buys=true`, `block_buy_execution=true`, razón única `data_pipeline_down`. |
| `portfolio_watch_started` del artefacto de cuenta | 19:15:49.692459 | 21:15:49.692459 | Cuenta tenía 9 posiciones y 1 orden abierta; el payload repite el mismo health `as_of=17:55:06.413376`. |

El snapshot de 18:47:06 UTC precede al bloqueo de 19:15:00 UTC por 27m54.686408s, pero no hubo refresh de `latest_operational_health` entre ambos. Esto prueba obsolescencia del diagnóstico consumido; no prueba por sí solo que todos los datos o gates fueran sanos.

El mismo resultado registra para `mkt_92a9836a3a39` un primer intento LLM fallido con error HTTP `402` y texto `Insufficient account funds`, seguido de un segundo intento que terminó tras aproximadamente 27 minutos. Es un degradado separado que alarga el ciclo; no es evidencia causal del bloqueo de frescura.

## Reproducción aislada

Archivo nuevo: `tests/test_oct08_health_freshness_characterization.py`.

Casos cubiertos:

- informe de salud con `data_pipeline_down` a `T0` y snapshot posterior a `T1`: el loader actual mantiene el bloqueo;
- `data_pipeline_down` obsoleto junto con `job_failed`: el loader actual conserva ambas alertas, fijando que una futura limpieza selectiva no descarte el crítico ajeno;
- informe sano junto con `operational_kill_switch.json` manual activo: el override persistente sigue bloqueando y el archivo permanece;
- informe con más de seis horas: se obtiene `stale_operational_health_report:<edad>s`, sin inventar un bloqueo fresco.

Todas las pruebas usan `tmp_path`, reloj congelado, JSON local y `os.utime`; no usan broker, red, yfinance, LLM, servicios ni SQLite productiva.

Resultados:

```text
pytest tests\test_oct08_health_freshness_characterization.py -q
4 passed in 0.87s

pytest tests\test_oct08_health_freshness_characterization.py tests\test_operational_health.py -q
13 passed in 6.58s

ruff check tests\test_oct08_health_freshness_characterization.py
All checks passed!

scripts\check_no_nulls.py
check_no_nulls: OK (546 archivos)
```

`git diff --check` también quedó limpio. La prueba focal reproduce el comportamiento actual; no pretende declarar corregido el defecto.

## Estado, límites y siguiente decisión

Worktree: `C:\Users\utopi\.codex\worktrees\oct08-health-freshness\agenteBolsa`, rama `codex/oct08-health-freshness`, base exacta indicada arriba. Estado final: dos archivos nuevos sin commit; ninguna fuente protegida, configuración, versión, plan maestro, relevo, dato productivo, lock, lease, servicio, broker, red, LLM o remoto fue modificado.

No se ejecutaron `pytest tests/ -x -q`, smoke `run-once --skip-crew`, `validate-agent-config`, `kernel-status`, `schedule-status`, postmarket, reconciliación, despliegue ni promoción. La razón es el encargo explícito y la precondición PMR8 no terminal, no un resultado verde omitido.

Decisión: conservar este lote como caracterización y usarlo como contrato para un único parche posterior en el consumidor de frescura. Ese parche debe demostrar resolución selectiva de `data_pipeline_down`, conservación de críticos ajenos y precedencia de overrides persistentes antes de cualquier ensayo de integración o validación cerrada.
