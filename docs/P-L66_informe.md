# P-L66 — resumen diario por Telegram

## Dictamen

`ready_for_integration_rehearsal`

## Contrato

El envío ocurre una sola vez por sesión efectiva, después de que
`post_market_review` tenga terminal durable `completed`. Telegram es
observabilidad fail-open: una configuración incompleta, timeout o rechazo de la
API no cambia el resultado del postmarket ni trading.

El mensaje reutiliza `performance_daily.pnl_pct`, `performance_daily.spy_pct` y
el mismo `PortfolioSnapshot` ya obtenido por postmarket. Los campos intradía
proceden de la respuesta de posiciones que ya devuelve Alpaca; no se añade otra
petición. Si faltan permanecen `n/d`, nunca cero.

## Seguridad

- Desactivado por defecto.
- Token excluido de Git, payloads, eventos y errores.
- El `chat_id` no se deduce de la URL de Telegram.
- Recibo append-only `telegram_daily_summary:<session_date>` tras un envío
  confirmado; un terminal ya recibido no se reenvía.
- Sin tablas, migraciones, backfill ni cambios de política.
- Sin autoridad sobre señales, ranking, gates, riesgo, sizing u órdenes.

## Configuración local

```dotenv
TELEGRAM_DAILY_SUMMARY_ENABLED=false
TELEGRAM_BOT_TOKEN=<token de BotFather>
TELEGRAM_DAILY_SUMMARY_CHAT_ID=<chat_id de Bot API>
TELEGRAM_TIMEOUT_SECONDS=15
```

Validación sin revelar secretos:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main telegram-daily-summary --json
```

Prueba explícita de red, solo después del despliegue y configuración:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main telegram-daily-summary --send-test
```

## Límite de idempotencia externa

Si Telegram acepta el mensaje pero el proceso cae antes de persistir el recibo,
un retry manual podría duplicarlo. No se reintenta automáticamente una sesión
terminal. Telegram no ofrece una transacción común con SQLite; se prioriza no
bloquear postmarket.
