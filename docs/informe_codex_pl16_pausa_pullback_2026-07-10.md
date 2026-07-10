# P-L16 — Pausa operativa de builtin_pullback con sombra activa

Fecha: 2026-07-10
Versión: 0.4.139
Autorización: Antonio, 2026-07-10

## Resultado

`builtin_pullback` queda en **SOMBRA operativa** dentro de `learning_experiment`.
No puede generar un plan persistido ni un envío al broker; `builtin_breakout` sigue
siendo ejecutable. La generación de señales, los outcomes a 1d/3d/5d/10d y el
registro `would_buy` se conservan. La revisión de la evidencia queda para
2026-07-20.

El cambio efectivo en `data/config/learning_mode.json` es:

```json
"shadow_strategies": ["builtin_pullback"]
```

La nota de autorización es: `Antonio 2026-07-10: pausa operativa
builtin_pullback, sombra activa, revision 2026-07-20`. `human_gated` permanece
en `true`.

## Implementación y trazabilidad

- `tools/learning_mode.py` normaliza `shadow_strategies` a una lista segura,
  deduplicada; una estrategia desconocida se ignora sin abrir ni bloquear otras.
- Antes de crear planes o enviar órdenes, el ciclo separa los planes cuya etiqueta
  es `strategy:builtin_pullback`. Se registran como
  `learning_mode_strategy_pause / strategy_paused_shadow_active` en el embudo de
  ejecución y nunca llegan a `broker_orders`.
- El informe de sombra conserva símbolo, hora de la sesión, entrada, stop, take,
  notional, estrategia y `shadow_reason=strategy_paused`. Las dos escrituras del
  informe de sombra son atómicas mediante reemplazo de fichero temporal.
- `config-audit` y la línea Safety del digest muestran
  `builtin_pullback=SOMBRA`.

## Aprendizaje de ayer en el digest matinal

`ci_digest_2026-07-10.md` se regeneró con el bloque **Aprendizaje de ayer**.
Incluye fills/P&L por símbolo, estado de bracket, lecciones y el tally de sombra.
Para la sesión 2026-07-09 el bloque muestra:

| símbolo ejecutado | bracket | P&L abierto |
|---|---|---:|
| EXPE | open | +6,00 USD |
| SBUX | open | -4,59 USD |
| STT | open | -10,50 USD |

Total de los tres fills de la sesión: **-9,09 USD** abierto; P&L realizado
0,00 USD. El tally también declara `builtin_pullback (SOMBRA por pausa): habría
comprado 0`; no hubo un nuevo plan pullback aprobado en el último informe de
sombra disponible. La ausencia de una compra hipotética hoy no equivale a apagar
la medición: las señales de pullback y sus outcomes continúan en `signal_outcomes`.

## Comparativa del cohorte a 2026-07-10

### Operaciones ejecutadas

| ventana | pullback ejecutado, atribución verificable | breakout ejecutado, atribución verificable | ejecutado sin estrategia persistida |
|---|---:|---:|---:|
| 2026-07-08 a 2026-07-09 | 0 | 0 | 6 fills buy |
| sesión 2026-07-09 | 0 | 0 | 3 fills buy (EXPE, SBUX, STT) |

Los seis fills anteriores a P-L16 no persistían `strategy_name` en el payload de
`order_plan`/`broker_order`; por ello no es honesto adjudicarlos retrospectivamente
a breakout o pullback, aunque sus símbolos aparezcan en candidatos. Desde esta
entrega, la etiqueta de estrategia viaja en el plan, por lo que la próxima lectura
sí podrá separar ejecutado por estrategia. En consecuencia, **no existe una
comparación ejecutada pullback vs breakout evaluable aún**.

### Sombra del cohorte

Se deduplicaron las señales `source=learning_experiment` por
fecha-símbolo-estrategia, ventana 2026-07-07 a 2026-07-09. Son retornos crudos;
la muestra no tiene aún 3d/5d/10d maduros.

| estrategia | señales | 1d maduro (n) | retorno medio 1d | 3d/5d/10d maduros |
|---|---:|---:|---:|---:|
| builtin_pullback | 220 | 136 | +0,20% | 0 / 0 / 0 |
| builtin_breakout | 1.492 | 995 | -0,44% | 0 / 0 / 0 |

La lectura 1d no cambia el veredicto P-L15: es demasiado corta y no sustituye los
criterios pre-registrados 5d/10d. Como referencia de la ventana más madura del
estudio P-L15 (todas las señales comparables desde 2026-06-25), pullback seguía en
-1,25% neto a 5d y -2,42% de excess frente a SPY, `n=295`; 10d continuaba `n=0`.

## Pruebas y verificación

- Pruebas focalizadas: 38 verdes (`test_learning_mode`, `test_config_audit`,
  `test_ci_phase3_digest`, `test_learning_loop`). Cubren pausa sin ejecución,
  registro de sombra, lista vacía y estrategia desconocida.
- `config-audit`: Safety OK y `builtin_pullback=SOMBRA` visible.
- `validate-agent-config --json`: OK.
- Digest regenerado mediante `powershell.exe` 5.1 con
  `scripts/run_ci_digest_daily.ps1`.

No se modificaron `kernel.py`, broker, execution, risk, `config.py` ni `.env`.

## Hotfix P-L16-bis — aislamiento de contextos de decisión

La suite completa detectó un fallo en
`test_deterministic_trade_fallback_allows_leader_pullback_extension`. El diagnóstico
descarta que la pausa case por el texto `pullback`: la excepción líder del candidato
DELL evaluaba `True`. El bloqueo venía de un tercer acoplamiento: `validate_entry_quality`
leía `data/reports/latest_daily_learning_digest.json` dentro de una función pura y
aplicaba al fixture el prior real de producción `expected_edge_3d=-2,64%`.

Se eliminó esa lectura implícita. El digest diario, la respuesta operativa y la
configuración de learning se reciben como dependencias opcionales; el ciclo operativo
las carga una vez y las inyecta. Las llamadas puras usan `{}` por defecto para los
contextos de aprendizaje. Con el `DATA_DIR=data` por defecto, un `Settings()` de
prueba no consulta datos reales; un sandbox con `DATA_DIR` aislado conserva la
posibilidad explícita de preparar allí su propio digest. La configuración de pausa
no se inspecciona por `selection_reason`, setup ni
texto: el bloqueo continúa requiriendo el `strategy_name` exacto
`builtin_pullback` que viaja en el plan.

Evidencia: DELL vuelve a producir una recomendación determinista con
`ENTRY_QUALITY_MAX_SMA20_DISTANCE=0,12`; los tests de pausa siguen demostrando que
un plan con `strategy:builtin_pullback` queda fuera de ejecución y se guarda con
`shadow_reason=strategy_paused`.
