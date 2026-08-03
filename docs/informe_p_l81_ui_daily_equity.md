# P-L81 — métrica diaria de equity y continuidad visual

## Dictamen provisional

`ready_for_next_closed_market_deployment` hasta completar la validación cerrada
y el preflight final. Producción no fue modificada ni detenida.

## Causa y contrato

La tarjeta de cuenta reutilizaba `opening_context.account_current`, por lo que
un lunes preapertura mostraba viernes apertura→ahora como «hoy». El gráfico
codificaba `strokeDash` sobre toda la línea en curso y podía dejar el extremo
actual sin tramo visible. El adaptador tampoco transportaba `account.last_equity`.

El contrato canónico queda centralizado en `tools/equity_metrics.py`:

`daily_equity_pl = current_equity - previous_close_equity`

`daily_equity_return = daily_equity_pl / previous_close_equity`

`previous_close_equity` procede de `account.last_equity` y la ventana es cierre
XNYS anterior→instante actual. Si falta o no es válido, el resultado es
`unavailable`/`n/d`; no se sustituye por exposición, porcentajes de posiciones,
trade history ni apertura XNYS. La variación de equity no ajusta flujos
externos. El P/L abierto, el P/L diario de posiciones, el resultado del período
y desde apertura conservan sus ventanas propias.

`PortfolioSnapshot.previous_close_equity` es opcional para fixtures/legacy. La
lectura Alpaca hace una sola captura de cuenta ya existente; no se añadió una
llamada de broker desde UI. El resumen Telegram usa el carrier oficial cuando
está presente; payloads históricos sin carrier permanecen explícitamente en la
ruta legacy hasta que una captura oficial los sustituya.

## UX

- La tarjeta activa se etiqueta «Ganancia/pérdida global de hoy» y muestra
  importe, porcentaje, cierre anterior y fecha `DD/MM/YYYY → DD/MM/YYYY`.
- «Resultado del período», «P/L abierto» y «Rendimiento desde apertura» no se
  mezclan con la métrica diaria.
- La gráfica Sistema vs SPY mantiene históricos sólidos y dibuja el intervalo
  vigente como segmento discontinuo desde el último final hasta el punto
  actual. El eje usa la fecha visual/as_of (por ejemplo 03/08), mientras el
  tooltip conserva `Sesión iniciada` e intervalo exactos.

## QA aislada

Caracterización roja contra la base: la prueba P-L81 no podía importar el
carrier/helper (`ModuleNotFoundError`). Después del commit funcional:

- focales P-L81, web, P-L63/P-L65/P-L68/P-L72/P-L73/P-L74/P-L75 y Telegram:
  `167 passed`, `1 warning` externo de `websockets`;
- pruebas nuevas P-L81: carrier Alpaca sin llamada de cuenta adicional,
  denominador oficial, missing/invalid, reconciliación parcial de posiciones,
  Telegram y segmento discontinuo;
- Ruff de las fronteras modificadas: verde.

La suite completa, NUL, compilación integral, `validate-agent-config`,
`kernel-status` aislado, smoke aislado y preflight cerrado quedan pendientes.
No se ejecuta la suite productiva ni se hacen llamadas de broker/LLM reales.

## Seguridad y paridad

No se modifican `kernel.py`, `execution.py`, `risk.py`, `config.py` ni `.env`.
El único delta autorizado en `broker.py` es transportar el campo de lectura
`last_equity` al snapshot provider-neutral. El prompt de decisión elimina el
carrier informativo del modo no compacto para conservar el payload económico
previo. No cambian candidatos, scores, ranks, gates, sizing, planes, órdenes,
precios, stops/takes, exposición ni límites.

No se encontraron instrucciones obsoletas imprescindibles para este contrato;
`SKILL.md` y runbooks no requieren cambios en este lote.

## Producción y siguiente paso

Producción permanece en 0.4.216 (`e4fe1ddb`/tree `ce15c1b0`), stack arriba,
paper activo, live y auto-apply desactivados, kernel válido y cutoff P-L80
intacto. El siguiente paso único es ejecutar los gates aislados restantes y,
solo si hay margen suficiente antes de 15:30, el despliegue cerrado gestionado.
Si no lo hay, entregar el candidato para la próxima ventana cerrada sin tocar
producción.
## QA posterior y hard stop preapertura

El helper por defecto de la tarjeta tambien usa el contrato canonico: `P/L diario de cartera - cierre XNYS anterior -> ahora`. La QA focal posterior al ajuste fue `99 passed, 1 warning`; la bateria UI y regresiones P-L81/P-L63/P-L65/P-L68/P-L72/P-L73/P-L74/P-L75/Telegram fue `168 passed, 1 warning`. El warning es la deprecacion externa preexistente de websockets.

El carry autorizado de `account.last_equity` es solo lectura y provider-neutral. No se añadieron llamadas de broker, no se cambio la ruta opening-to-opening, y no se modificaron skills/runbooks porque no se detecto una instruccion obsoleta reproducible.

La suite completa, gates de cierre y smoke aislado quedan sujetos al margen preapertura. Si no existe margen razonable para rollback, stack_up y dos health checks antes de 15:30 Europe/Madrid, el resultado correcto es `ready_for_next_closed_market_deployment` y produccion permanece intacta.
