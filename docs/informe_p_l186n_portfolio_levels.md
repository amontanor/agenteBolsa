# P-L186N: niveles de cartera por direccion y dataset de pruebas

## Dictamen

`ready_for_integration_rehearsal`. Cambio N1/N2 de lectura y presentacion. No
crea, cierra ni modifica ordenes; no cambia politica, riesgo, sizing ni kernel.

## Causa raiz

`_local_buy_risk_plans` leia solo `broker_orders.side='buy'`:

- ocultaba el stop/take de un corto, porque un corto entra con `sell`;
- podia tomar una cobertura de corto (buy con niveles invertidos) como si
  fuera una entrada larga;
- las posiciones sin ninguna orden local no tenian nivel ni fecha de compra.

Casos reales 2026-11-03:

- APP corto: plan `plan_1b06deddb202`, stop 261,3766 / take 204,0601; la UI
  mostraba “-”.
- APO/WAT: compradas el 2026-08-17 13:59:18/19Z como bracket en el broker,
  APO 7 @ 137,55 y WAT 2 @ 409,62. Las patas de venta estan EXPIRED/CANCELED.
  El ledger local tiene 0 ordenes y 0 planes para ambas; no hay fecha local ni
  niveles, y el monitor automatico las ignora.
- DHR cerro el 2026-11-03 15:51:33Z; no pertenece a la cartera actual.

## Cambio

- `_local_entry_risk_plans` devuelve el ultimo plan de entrada por simbolo y
  direccion (`open_long`/`open_short`). Una cobertura (`close_short`) nunca es
  entrada; un buy legado sin efecto sigue siendo `open_long`.
- `_local_buy_risk_plans` se conserva como vista legada solo-largos.
- `build_trade_history` publica `risk_levels_by_direction`; conserva
  `risk_levels` con la forma anterior para no romper consumidores.
- `_attach_risk_levels` elige el plan por direccion de la posicion o del trade.
- `_position_rows` usa el mapa por direccion, rellena Stop/Take y marca
  `Riesgo estado=sin_plan_local` cuando no hay plan.
- La tabla de cartera avisa: “Sin plan de entrada local: ... Sin stop/take y
  fuera del monitor automatico.”

## Dataset de pruebas

`tests/fixtures/p186n_portfolio_cases.py` fija los casos canonicos:

1. largo con plan (EVRG);
2. corto con plan (APP);
3. plan legado sin `position_effect` (MO);
4. cobertura de corto que no debe ser entrada y largo anterior (ADM);
5. posicion huerfana sin orden local (APO).

`tests/test_p186n_portfolio_risk_levels.py` verifica el lector, la seleccion por
direccion y el estado `sin_plan_local`. Es el juego de datos reproducible para
las pruebas de cartera.

## Validacion

- Focales P-L186N + trade history + portfolio + web: 93 passed.
- Regresiones de trade_history, portfolio, postmarket, web, P-L186, P153, P73
  y ops_reports: 195 passed.
- Ruff, NUL y `git diff --check`: verdes.
- Suite completa y despliegue: pendientes al escribir este informe.

## Limites y decisiones

- No se colocan stops/takes ni se cierran APO/WAT: seria una accion de trading.
- No se hace backfill de las ordenes del 17-ago: requiere autorizacion.
- Mientras no se adopten, APO/WAT siguen fuera del monitor automatico y se
  muestran como `sin_plan_local`.
