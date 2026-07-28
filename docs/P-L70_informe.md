# P-L70 — rediseño UX del resumen diario Telegram

## Dictamen

`ready_for_integration_rehearsal`.

El cambio queda aislado en el resumen diario Telegram. No modifica el
consumidor de fills, reconciliación, PMR, scheduler cadence ni ninguna ruta de
trading. La suite completa y el smoke aislado quedan pendientes de la
validación cerrada con precondiciones operativas verificadas.

## Base y commits

- Base: `87d2901894ed9f3b31000b31ba1cfb974b7c9b88`.
- Árbol base: `fd690a939c9f887fc6929a8badfc1d1b79f76260`.
- Versión base: `0.4.202`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl70_telegram_summary_ux`.
- Rama: `codex/pl70-telegram-summary-ux`.
- Caracterización: `b5b3fec4` (`test: characterize Telegram summary UX`).
- Implementación: `f78de077` (`feat: redesign Telegram daily summary UX`).
- QA focal: `0a18924c` (`test: verify Telegram summary UX contract`).
- QA de versión: `b3c4d1c2` y `7e96191a`.
- Versión candidata: `0.4.203`.

La caracterización contra la base demostró el saldo absoluto con signo y la
lista plana sin grupos ni cobertura. La implementación usa
`p-l70.telegram-daily-summary.v2`, conserva el `event_id`
`telegram_daily_summary:<session_date>` y mantiene la idempotencia de sesiones
ya recibidas, incluidas las recibidas con el schema anterior.

## Contrato resultante

La fuente sigue siendo el objeto `performance` ya construido por PMR. La
variación monetaria de equity solo se calcula desde
`performance_benchmark.account.equity` y `previous_equity`; si falta la pareja,
el importe es `n/d`. Un porcentaje legacy puede conservarse, identificado como
`legacy_percentage`, pero no reconstruye el importe.

El benchmark conserva el valor numérico cuando existe, pero solo se marca
`comparable` si están disponibles la pareja de cierres, `price_basis`, calidad,
fuente y `as_of`. En cualquier otro caso se publica como `Provisional`, sin
declarar ganador ni diferencia canónica. Si faltan valores, se publica `n/d`.

Las posiciones se agrupan por `total_pl`: beneficio, pérdida, sin cambio y
datos incompletos. Dentro de cada grupo el orden es impacto absoluto
descendente y símbolo como desempate. Los totales incluyen cobertura
`known/total` y estado `complete`, `partial`, `unavailable` o
`not_applicable`; los valores faltantes nunca se convierten en cero.

Para superar el límite de Telegram se conserva un único mensaje con truncado
determinista y explícito: el payload conserva todas las posiciones y el texto
indica cuántas se muestran y cuántas quedan resumidas. Esto evita mensajes
multipartiales y conserva un único recibo/idempotencia por sesión. El recibo
v2 incluye longitud, total de posiciones y si hubo truncado.

## Fixture de aceptación

La fixture reproduce exactamente:

- equity `70,638.81 USD`;
- variación de equity `+100.22 USD` desde `70,538.59`;
- P/L abierto total `+85.54 USD` con cobertura `8/8`;
- variación abierta `+73.87 USD` con cobertura `8/8`;
- seis posiciones en beneficio y dos en pérdida;
- comparación SP500 comparable y comparación provisional con basis/calidad no
  comparables.

También cubre cartera vacía, cero válido, `NaN`/`Infinity`, valores faltantes,
Unicode y 100 posiciones con mensaje de longitud máxima 4096.

## Validación

- `tests/test_telegram_daily_summary.py`: 16 verdes.
- Telegram daily summary + trade notifications + P-L68/P-L63/P-L65:
  46 verdes y un fallo preexistente de fecha dinámica en
  `test_explicit_june_window_has_date_authority_and_exact_visible_dates`.
- El fallo se reprodujo contra la base exacta 87d29018: devuelve `2026-07-29`
  frente a una aserción fija `2026-07-28`; queda fuera de P-L70.
- Ruff completo, `check_no_nulls.py` (`447 archivos`), `git diff --check`,
  compilación y `validate-agent-config --json` aislado: verdes.
- Suite completa aislada: `1618 passed, 1 failed, 1 warning` en 696,99 s; el
  único fallo es el mismo test preexistente de P-L63, reproducido contra la
  base exacta, por `2026-07-29` frente a una aserción fija `2026-07-28`.
- Smoke real no ejecutado: habría requerido una ruta de ejecución y no se
  autoriza ningún mensaje Telegram real. El envío queda cubierto con sender
  monkeypatched y Store temporal.

No se enviaron mensajes reales, no se leyó token/chat_id, no se usó red ni
SQLite productiva.
