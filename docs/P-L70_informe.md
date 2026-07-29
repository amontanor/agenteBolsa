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
- Implementación de auditoría: `12de9be5` (`feat: audit Telegram summary receipt and UTF-16 limit`).
- QA y regresión determinista: `1b64dc5a` (`test: close P-L70 audit and P-L63 date regression`).
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
indica cuántas se muestran y cuántas quedan resumidas. El límite se valida en
unidades UTF-16 conservadoras (`4096`); no se cortan caracteres ni se emiten
encabezados de grupo sin filas. El recibo v2 conserva, además de los metadatos,
el texto renderizado exacto (`text`) y su SHA-256 (`text_sha256`). Este hash es
distinto de `content_hash`, que identifica el payload canónico antes del
renderizado. No se incluyen token ni `chat_id`; los recibos v1 existentes siguen
siendo idempotentes y no se reenvían.

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
Unicode y 100 posiciones con mensaje de longitud máxima 4096. La fixture
anonimizada con la forma de `performance_daily.payload_json` del 28-jul fija
equity `70,634.91`, `previous_equity` `70,534.69`, delta `+100.22`, retorno
`+0.142086%` y SP500 `-0.304428%`; con `price_basis=unknown` y calidad
`partial` queda `Provisional`, aunque calidad se reciba como string o mapping.
Con fuente/as-of y base comparable explícitos, el test permite `comparable`.

Mensaje exacto de aceptación (8/8 posiciones, ordenado por impacto absoluto):

```text
📊 Cierre · 28 jul 2026

💼 Cuenta
• Equity: 70,634.91 USD
• Variación de equity hoy: +100.22 USD (+0.14%)
• SP500: -0.30% · Provisional
• Diferencia: +0.45 pp · Provisional

📈 Posiciones abiertas · 8
• P/L abierto total (8/8): +85.54 USD
• Variación abierta hoy (8/8): +73.87 USD

⚠️ Comparación provisional: SP500 no tiene base histórica plenamente comparable.

🟢 En beneficio · 6
• KHC  Total +42.94 USD (+4.32%) · Hoy +40.28 USD (+4.04%)
• CPAY  Total +24.90 USD (+3.35%) · Hoy +9.22 USD (+1.21%)
• AAPL  Total +21.27 USD (+2.13%) · Hoy +10.05 USD (+0.99%)
• TMO  Total +17.96 USD (+3.21%) · Hoy +17.27 USD (+3.09%)
• PRU  Total +17.20 USD (+1.76%) · Hoy +16.32 USD (+1.67%)
• GD  Total +16.72 USD (+2.17%) · Hoy +9.78 USD (+1.26%)

🔴 En pérdida · 2
• UNP  Total -37.25 USD (-4.02%) · Hoy -9.35 USD (-1.04%)
• VTR  Total -18.20 USD (-1.82%) · Hoy -19.70 USD (-1.97%)
```

## Validación

- Reproducción inicial de P-L63: el test esperaba `2026-07-28` y la ruta
  devolvía `2026-07-29`; la fecha se congela en el test, sin tocar la lógica
  funcional.
- Focales P-L70/P-L63 y resumen Telegram: `22 passed`.
- Suite completa aislada final: `2261 passed, 1 skipped, 1 warning` en
  `772,83 s`. El único skip es condicional y preexistente en
  `test_score_study_regression_current_sqlite`, cuando la historia local no
  está disponible o no alcanza el mínimo de eventos; no se añadió skip/xfail.
  La única advertencia es la deprecación `websockets.legacy` en un test de
  wiring existente.
- Ruff completo, `check_no_nulls.py`, `git diff --check`, compilación y
  `validate-agent-config --json` aislado: verdes.
- El sender y Store se probaron con dobles/SQLite temporal, incluyendo retry,
  idempotencia v1/v2, fallo, texto Unicode en frontera UTF-16 y ausencia de
  secretos. Smoke real y envío Telegram real no ejecutados por seguridad.

No se enviaron mensajes reales, no se leyó token/chat_id, no se usó red ni
SQLite productiva.

## P-L70BR1 — ensayo integrado cerrado

### Dictamen

`ready_for_closed_market_deployment`.

Este dictamen solo autoriza el siguiente paso de despliegue; no se ha hecho
despliegue, reinicio, push ni envío Telegram desde este ensayo.

### Merge y paridad

- Base documental: `87d2901894ed9f3b31000b31ba1cfb974b7c9b88`, árbol
  `fd690a939c9f887fc6929a8badfc1d1b79f76260`, versión `0.4.202`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl70br1_telegram_summary_rehearsal`.
- Rama: `codex/pl70br1-telegram-summary-rehearsal`.
- Merge `--no-ff`: `0083f414dd235d4b75fb207365702f1c06090d01`; su tree funcional
  coincidió exactamente con `53b8daa68994ad26f68a1b9cc625d7a5c2c211a9`.
- QA integrada: `a64c493a`.
- Versión final: `0.4.203`.

El diff funcional respecto a producción queda limitado a
`telegram_daily_summary.py` y `__init__.py`; el resto son tests y
documentación. `telegram_trade_notifications.py`, scheduler, Store,
reconciliación, PMR y las rutas de trading no cambian. `kernel.py`, broker,
execution, risk, config y `.env` permanecen idénticos a producción.

### Preflight y validación

El 29-jul-2026 a las 02:23 CEST XNYS estaba cerrado y abría a las 15:30 CEST.
El PMR del 28-jul estaba en `terminal/completed` con razón
`pipeline_completed`, la lease estaba liberada y el intento posterior era
`session_already_completed`. No había pytest ni despliegue activo; el scheduler
residente y `continuous_improvement` dry-run no bloquearon el ensayo.

- Suite integrada: `2261 passed, 1 skipped, 1 warning` en `775,52 s`.
- Skip único, condicional y preexistente: `test_score_study_regression_current_sqlite`
  cuando la historia SQLite local no está disponible o no alcanza el mínimo.
- Warning único: deprecación existente de `websockets.legacy`.
- Focales Telegram/P-L63/P-L65/P-L68/config/version: `86 passed`.
- QA específica P-L70BR1: `1 passed`.
- Ruff completo, `check_no_nulls.py`, `git diff --check`, compilación y
  `validate-agent-config --json` temporal: verdes.
- `kernel-status` temporal: `unsealed` esperado por ausencia de manifiesto;
  `kernel-status` productivo: `ok`, sellado y hashes coincidentes.
- Smoke real y Telegram real: omitidos deliberadamente; sender monkeypatched y
  Store temporal cubren publicación, rechazo, idempotencia, recibo, Unicode y
  ausencia de secretos.

La fixture productiva anonimizada conserva equity `70,634.91`, previous equity
`70,534.69`, delta `+100.22`, SP500 `-0.304428%`, `price_basis=unknown` y
calidad `partial`; el estado es inequívocamente `Provisional`, sin ganador.
El recibo v2 contiene texto exacto, `text_sha256`, `content_hash` separado,
unidades UTF-16, total y truncado. Las sesiones v1/v2 previas permanecen
idempotentes y no se reenvían.
