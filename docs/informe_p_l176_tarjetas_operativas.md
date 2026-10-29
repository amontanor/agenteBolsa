# P-L176 — tarjetas operativas con responsable (0.4.404)

Fecha: 2026-10-29. Nivel **N1**: presentación aislada, sin fuente nueva,
persistencia ni efecto operativo.

## 1. Dictamen

`ready_for_integration_rehearsal`. Las tres tarjetas de «Estado operativo»
dejaban de mostrar `n/d · rancio` sin explicar qué falta.

## 2. Hecho de producción

`web_app.py:5979-5981` lee:

- `latest_market_data_quality.json`
- `latest_live_readiness.json`
- `latest_weekly_trading_review.json`

Los **tres ficheros no existen** en `/data/reports` (verificado 2026-10-29).
Sus únicos productores son comandos manuales:

| Informe | Productor |
|---|---|
| `latest_market_data_quality.json` | `main.py market-data-quality` (`ops_reports.py:280`) |
| `latest_live_readiness.json` | `main.py live-readiness` (`main.py:1947/3033`) |
| `latest_weekly_trading_review.json` | `main.py weekly-review` (`ops_reports.py:406`) |

El job semanal programado (`weekly_learning_review_job`) escribe otros
artefactos, no este informe. Resultado: las tarjetas mostraban «-» con
`n/d · rancio`, sin `as_of`, sin motivo y sin job responsable.

## 3. Arreglo

Nuevo helper de presentación `_operational_report_detail(...)`:

- sin informe → `sin informe · ejecuta <comando>`;
- con informe → edad, `rancio` si procede y detalle del payload (proveedor,
  blocks, benchmark), como antes.

No se inventan datos ni se generan informes desde la UI. La UI sigue sin
escribir estado operativo ni ser fuente de identidad.

## 4. Evidencia

```text
pytest tests/test_p176_operational_cards.py      5 passed
pytest tests/test_web_app.py                    79 passed
ruff check (ficheros del lote)                  sin errores nuevos
check_no_nulls                                   OK (610)
git diff --check                                 limpio
```

## 5. Límites

- Sigue sin haber job programado que produzca esos informes: la tarjeta ahora
  lo dice, no lo arregla. Programarlos es un lote N2/N3 aparte.
- No se ha hecho QA visual en navegador; la verificación en producción se hará
  tras el despliegue.

## 6. Candidato

- Worktree `.worktrees/pl176-operational-cards`, rama
  `codex/pl176-operational-cards`, base `4a178a2c`.
- Commits: `b9d701fd` test, `7173e808` fix, `d6384ee0` versión.
- Versión `0.4.404`.
