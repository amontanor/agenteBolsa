# P-L75 — ensayo combinado P-L73 + P-L74

## Dictamen

`ready_for_closed_market_full_validation`. El ensayo se ejecutó con XNYS
abierto, por lo que no se autoriza todavía suite completa, smoke ni despliegue.

## Integración

Base productiva: `36077a0681d3a2bdd487e395052766d8daa5985a`, árbol
`b15ac3a28e12dd98fce0f6afe959d7b6c14a88bb`, versión 0.4.206.

- Merge P-L73 `2d44ba945550412d6580b2069931e385ba78c0ae` con `--no-ff`.
- Merge P-L74 `a5c5ba46a74910cba3904076dd6b1be39ece5c06` con `--no-ff`.
- Merge resultante: `bbdbdd38`; el candidato final queda en versión 0.4.208.
- QA combinada pendiente de commit separado; no hubo conflictos funcionales.

El único conflicto fue documental/de versión: se conservaron el registro P-L73,
la autoridad P-L74 y la versión final 0.4.208. No se usó resolución global
`ours/theirs`.

## Contratos verificados

P-L73 conserva total y P/L diario de cada posición desde el mismo
`PositionSnapshot` de Alpaca (`alpaca_position_snapshot`), sin segunda lectura,
joins por símbolo ni reconstrucción. Missing sigue siendo `n/d`.

P-L74 conserva:

- apertura SPY dedicada explícita frente a caché broad contradictoria;
- current mutable seleccionado por frescura, con provenance compatible;
- `.pkl` legible/coherente obligatorio junto a metadata;
- estados terminales `inserted`, `available`, `idempotent`, `recovered`;
- retry sin límite artificial, solo en la cadencia natural de
  `market_cycle_job`;
- captura posterior a la ruta activa y fail-open, sin captura en
  `portfolio_watch_job`.

La UI mantiene `Rendimiento desde apertura: Sistema vs SPY`, `Sesión iniciada`,
intervalos Europe/Madrid, tabla descendente, gráfica cronológica y estados
`Final`/`En curso`. Telegram no recibe un benchmark conflictivo o no
autorizado.

## QA

- Focales P-L73/P-L74/P-L75/P-L72/web/Telegram/market-data:
  `139 passed` antes del gate de formato; tras corregir imports, la batería
  combinada P-L73/P-L74/P-L75 pasó `25 passed`.
- Ruff completo: OK.
- `scripts/check_no_nulls.py`: OK, 454 archivos.
- `git diff --check`: OK.
- `py_compile`: OK.
- `validate-agent-config --json` aislado: OK, sin errores ni warnings.

No se ejecutaron suite completa, smoke, servicios, red/yfinance, broker, LLM,
SQLite productiva, reinicio, despliegue ni push porque XNYS estaba abierto.

## Paridad y siguiente paso

Los archivos protegidos `kernel.py`, broker, execution, risk, `config.py` y
`.env` son idénticos a la base. No cambiaron señales, candidatos, gates,
capacity, sizing, RiskManager, planes, requests, órdenes, exposición ni
límites. Producción y los dos candidatos de origen permanecen intactos.

Siguiente lote: validación cerrada completa del ensayo, con precondiciones
terminales, suite canónica y smoke temporal. No desplegar antes de ese gate.
