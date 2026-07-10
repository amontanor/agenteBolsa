# P-L23R - Prueba determinista de plan manual

Version: 0.4.147

## Causa raiz

`test_create_manual_opportunity_plan_saves_pending_plan` usaba
`pending_order_plans()`. Ese metodo expira planes PENDING tras el cierre de
XNYS, de forma correcta, antes de devolverlos. Por ello la prueba dependia del
reloj real y fallaba despues de las 16:00 America/New_York.

## Correccion

La prueba usa ahora `order_plans(statuses=[PENDING])`, una consulta directa que
no ejecuta la caducidad operativa. Verifica que el unico registro creado tiene
el simbolo AAPL, el `plan_id` devuelto y estado PENDING. No se modifico codigo
de produccion, politica TTL, ordenes, gates ni configuracion.

La expiracion por cierre ya se cubre por separado con horas inyectadas en
`tests/test_order_plan_expiration.py`; por tanto no se duplica ni se usa reloj
real.
