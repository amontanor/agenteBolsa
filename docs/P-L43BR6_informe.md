# P-L43BR6 — lotes abiertos por identidad exacta

## Diagnóstico

CRWD y WELL tenían BUY locales `filled`, pero el lector temporal recibía todos
los BUY históricos del símbolo. No se restaban las ventas `filled` enlazadas al
`source_plan_id` de cada compra. Como los lotes tenían cantidades de orden, no
cantidades abiertas de posición, `evaluate_position_time_stop` aplicaba
correctamente `open_lot_quantities_not_verifiable` para evitar elegir la última
compra por símbolo.

## Corrección aislada

Se añadió `Store.executed_open_buy_lots_by_symbol()`. La función:

- conserva los BUY con identidad exacta;
- descuenta únicamente SELL `filled` con `source_plan_id` exacto;
- ignora SELL pendientes, rechazadas o canceladas;
- exige que la suma de cantidades abiertas coincida con `position_qty`;
- deja `open_qty` como `unavailable` ante cualquier procedencia ausente o
  ambigua;
- no crea tablas, migraciones, eventos ni órdenes.

El scheduler usa esta vista solo para la evidencia shadow. La regla activa
continúa siendo `legacy_calendar_days`; XNYS sigue `shadow_only=true`.

## Cobertura

Las fixtures cubren lote único, ventas parciales, cierre exacto de un lote,
recompra, parciales sin `first_fill_at`, ventas sin procedencia, estados no
terminales y reproducciones sanitizadas de CRWD/WELL. La historia append-only,
la idempotencia, los conflictos y la ausencia de órdenes XNYS permanecen
cubiertos por las focales P-L43BR5 existentes.

No se hizo backfill ni se tocaron datos productivos.

## Despliegue secuenciado P-L43BR6 (0.4.181)

El lote se desplegó sobre P-L47B1 mediante el merge productivo
`7cc432aee3f594d946f5a65d1f86f3e49fa82e4`, con tree funcional
`bc2d15ffd0d43f10359761b61efc07b0384c5072` y versión `0.4.182`.
La secuencia queda registrada como P-L47B1 `0.4.180`, P-L43BR6 `0.4.181` y
P-L44BR3 `0.4.182`.

`legacy_calendar_days` continúa activa y XNYS permanece exclusivamente shadow.
Los datos prospectivos siguen `collecting`/`partial`; no se hizo backfill y no
se generaron órdenes XNYS.
