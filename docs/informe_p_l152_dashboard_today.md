# P-L152 — dashboard "Hoy" + corte Jetson 0.4.308 — `deployed`

Dictamen: `deployed`. Ejecutado sábado 19-sep-2026 (~09:08 CEST),
XNYS cerrado.

## Candidato Windows

- Merge `--no-ff` a producción: HEAD `9c3a6225`, versión `0.4.252`.
- Suite completa por bloques (22 chunks): todos verdes salvo 2 fallos
  **preexistentes** reproducidos en base `6d262af8` sin este lote:
  `test_learning_mode.py::test_learning_mode_relaxes_partial_market_state_only_when_enabled`
  y `test_p71_eod_authority.py::test_future_bar_in_an_otherwise_valid_cache_is_rejected`
  (entorno de test; ajenos a P-L152).
- Ruff/NUL/diff verdes. Focales P-L152 (10) verdes.

## Contenido portado a Jetson

- **web_app.py** (Jetson diverge de Windows): parche por anclas de 8
  hunks — `_intraday_metric_display`, `_outside_trading_session`,
  `_today_breakdown`, `_render_today_breakdown`, dedup fila en curso,
  `market_open` en `_account_group` y `as_of` acotado a sesión real.
  `py_compile` OK.
- **equity_metrics.py**: copia directa (idéntico), con campo `all_zero`.
- **__init__.py** → `0.4.308`.
- Incidente propio: dos builds iniciales llevaban el `equity_metrics.py`
  viejo (bundle no recopiado tras el primer fallo de copia); detectado
  verificando `all_zero` en el contenedor y reconstruido `--no-cache`.
  Imagen final `sha256:8c3ed2ec422dcd211f`.

## Corte y salud

- Preflight `diagnose` ok; escritores detenidos por `compose stop`
  (`WRITERS_STOPPED`); snapshot frío
  `cold-pre-0.4.308-20260919T0708Z` ok.
- Selector → `0.4.308-arm64` (backup `runtime.env.bak-p152`);
  `deploy-agente-bolsa` verde a la primera.
- Doble salud: HTTP x4 = 200, 3 contenedores healthy restarts=0,
  version `0.4.308`, kernel True sin violaciones, PAPER/live-off/
  auto-off, lock owner_alive/token_match, 0 órdenes, 0 locks.

## Efecto visible

El dashboard (Windows y Jetson) ahora: dice `n/d · mercado cerrado` en
vez de `$0.00` con el mercado cerrado, acota el `as_of` a la última
sesión real, añade la tarjeta "Hoy" (equity + realizado + compras +
ventas de la sesión) y elimina el duplicado del héroe SPY.
