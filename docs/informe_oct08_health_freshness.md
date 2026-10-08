# Informe Oct08: frescura del bloqueo operativo

## Dictamen

El defecto queda reproducido en la base `0.4.348` (`HEAD 52cc0fa5921ff690cfec4d08d5eda5c9c1bbccb1`, `tree 28a76ff51aa66139c02700ce0f86789842b51b4c`):
`load_operational_block_context` conservaba un `data_pipeline_down` emitido por un informe de salud anterior aunque existía evidencia posterior. En esta rama se implementa el mínimo aislado N3 en `operational_health.py`, con pruebas negativas y de recuperación selectiva. La versión de la rama queda en `0.4.350`; no se modifica configuración, producción ni política activa.

La ventana operativa queda `precondition_not_met` para cualquier suite completa, smoke, despliegue o comprobación productiva: el `schedule-status` SSH aportado para el 8-oct a las 22:15 Europe/Madrid indicó XNYS cerrado, pero `PMR8` aún no tenía terminal `completed|failed`. Por tanto no se ejecutaron gates operativos.

## Causa y contrato actual

Productor: `build_operational_health_report` calcula `_data_pipeline_heartbeat` y publica `reports/latest_operational_health.json`. El scheduler refresca ese informe al arrancar y cada 45 minutos (`operational_health_refresh_job`). El heartbeat ahora conserva explícitamente `calendar`, `local_timezone` y `session_date` para que el consumidor no tenga que inventar configuración.

Antes del fix, la función aceptaba `now` pero decidía la edad con el reloj real y el `st_mtime` del JSON; no comparaba `payload.as_of` con evidencia posterior. Así, un informe reciente como archivo (menos de seis horas) podía conservar un diagnóstico de pipeline obsoleto. La ausencia o antigüedad superior a seis horas conserva la semántica existente de `stale_operational_health_report` con bloqueo de compras desactivado.

El consumidor corregido usa un `now` aware explícito; un `now` naive produce bloqueo de incertidumbre. Para refrescar `data_pipeline_down`, exige JSON de salud no vacío y un `as_of` aware válido, no futuro; si la forma no es utilizable conserva el bloqueo. Toma calendario y zona del heartbeat o de `Settings` explícitos; sin ninguno, permanece bloqueado. Requiere sesión abierta actual, `session_date` coincidente y un artefacto `market_state_*.json` de forma canónica, con `as_of` aware posterior al health report, no futuro y de edad máxima de 30 minutos. Filtra mtime futuro, anterior al informe o fuera de la ventana y recorre candidatos en una sola pasada de memoria acotada. Una fecha `YYYY-MM-DD` de un `market_snapshot` no demuestra hora de captura y no autoriza recuperación.

Cuando la recuperación es válida, el resultado expone `data_pipeline_recovery` con `path`, `captured_at`, `observed_at`, `session_date` y `evaluated_at`, además de `report_as_of` separado. El JSON de salud no se muta. Si queda cualquier crítico —incluido otro `data_pipeline_down` con scope distinto de `market_data`— `kill_switch_active` sigue activo y bloquea la operación; la evidencia fresca solo resuelve el diagnóstico exacto `data_pipeline_down:market_data`.

Contrato de seguridad para el siguiente lote:

1. Refrescar solo la observación de `data_pipeline_down` con reloj explícito, calendario y zona declarados, y artefacto de datos canónico posterior; exigir edad de captura dentro de los 30 minutos cuando el mercado esté abierto.
2. Mantener cada alerta crítica independiente (`job_failed`, `missing_report`, `stale_required_report`, etc.). Un snapshot nuevo no puede descartar el resto del kill switch ni reescribir la historia append-only.
3. Evaluar primero `operational_kill_switch.json`. Un override persistente manual o de integridad sigue bloqueando hasta su propia ruta explícita de recuperación; el refresco de datos no lo borra ni lo sustituye.
4. Ante timestamp ausente o naive, reloj incoherente, copia/touch del mtime, snapshot no verificable o evidencia `unavailable`, conservar bloqueo de seguridad. No inferir salud por la mera existencia de un archivo.

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
| `portfolio_watch_started` del artefacto de cuenta | 19:15:49.692459 | 21:15:49.692459 | Cuenta tenía 9 posiciones y 1 orden abierta; es un evento separado del health. |

El snapshot de 18:47:06 UTC precede al bloqueo de 19:15:00 UTC por 27m54.686408s, pero no hubo refresh de `latest_operational_health` entre ambos. Esto prueba obsolescencia del diagnóstico consumido; no prueba por sí solo que todos los datos, cotizaciones o gates fueran sanos. El payload `portfolio_watch` no contiene health; el health aparece como hermano en el JSON de cuenta.

El mismo resultado registra para `mkt_92a9836a3a39` un primer intento LLM fallido con error HTTP `402` y texto `Insufficient account funds`, seguido de un segundo intento que terminó tras aproximadamente 27 minutos. Es un degradado separado que alarga el ciclo; no es evidencia causal del bloqueo de frescura.

## Reproducción aislada

Archivo focal: `tests/test_oct08_health_freshness_characterization.py`.

Casos cubiertos:

- informe de salud con `data_pipeline_down` a `T0` y snapshot legacy posterior con solo fecha: el loader conserva el bloqueo;
- informe de salud con `data_pipeline_down` a `T0` y `market_state` posterior con captura aware a `T1`: se recupera solo el pipeline;
- `data_pipeline_down` obsoleto junto con `job_failed`: la recuperación selectiva conserva el crítico ajeno;
- informe sano junto con `operational_kill_switch.json` manual activo: el override persistente sigue bloqueando y el archivo permanece;
- informe con más de seis horas: se obtiene `stale_operational_health_report:<edad>s`, sin inventar un bloqueo fresco;
- timestamp ausente, naive o futuro, sesión distinta, JSON vacío/inválido, artefacto desconocido, mtime futuro del artefacto o del health report, copia con contenido antiguo, captura antigua y ausencia de calendario sin `Settings`: no recuperan;
- otro `data_pipeline_down` con scope `global` sobrevive junto al `market_data` recuperado y mantiene el bloqueo;
- `Settings(_env_file=None)` explícitos permiten el caso legacy con metadatos de calendario ausentes, sin llamar a `get_settings()`.

Todas las pruebas usan `tmp_path`, reloj congelado, JSON local y `os.utime`; no usan broker, red, yfinance, LLM, servicios ni SQLite productiva.

Resultados:

```text
pytest tests\test_oct08_health_freshness_characterization.py -q
21 passed in 1.92s

pytest tests\test_oct08_health_freshness_characterization.py tests\test_operational_health.py -q
30 passed in 6.57s

pytest tests\test_oct08_health_freshness_characterization.py tests\test_operational_health.py tests\test_p59c_llm_selected_authority.py -q
77 passed in 6.97s

ruff check src\agente_bolsa\tools\operational_health.py src\agente_bolsa\__init__.py tests\test_oct08_health_freshness_characterization.py tests\test_p59c_llm_selected_authority.py
All checks passed!

scripts\check_no_nulls.py
check_no_nulls: OK (546 archivos)
```

`git diff --check` también quedó limpio. La prueba focal verifica el contrato corregido en aislamiento; no sustituye la validación operativa pendiente.

## Estado, límites y siguiente decisión

Worktree: `C:\Users\utopi\.codex\worktrees\oct08-health-freshness\agenteBolsa`, rama `codex/oct08-health-freshness`, base exacta indicada arriba. La secuencia de commits aislados es `6380d0d4` (caracterización), `f1e8b635` (revalidación selectiva), `c5fd589c` (evidencia aware, reloj y memoria acotada), `98a37a82` (scope, mtime futuro, observación y pin `.350`) y el commit documental final. La versión queda fijada en `0.4.350`; `.349` permanece reservada para la reutilización de digest. No se modifica ninguna fuente protegida, configuración, plan maestro, relevo, dato productivo, lock, lease, servicio, broker, red, LLM o remoto.

No se ejecutaron `pytest tests/ -x -q`, smoke `run-once --skip-crew`, `validate-agent-config`, `kernel-status`, `schedule-status`, postmarket, reconciliación, despliegue ni promoción. La razón es el encargo explícito y la precondición PMR8 no terminal, no un resultado verde omitido.

Decisión: el contrato mínimo queda implementado y probado en aislamiento. El gate de integración/operación sigue pendiente porque PMR8 no estaba terminal y el encargo excluye fullsuite, smoke, deploy y producción. No se afirma paridad económica ni paridad de BUY: el cambio altera intencionadamente el gate de frescura. La evidencia de snapshot de las 20:47 tampoco se presenta como aceptación de cotizaciones; al carecer de una captura aware consumible por este contrato, solo conserva el hallazgo histórico de obsolescencia.
