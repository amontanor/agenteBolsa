# Informe único — 0.4.415 (P-L185)

Fecha: 2026-10-30, Europe/Madrid. XNYS **abierto** durante el corte, con
autorización operativa explícita del operador.
Dictamen: **deployed**, con doble salud, recibo y verificación en navegador.

## Causa

El panel seguía reejecutándose cada 10-20 s aunque el refresco estuviera en
10 minutos. `_poll_dashboard` (fragmento cada 10 s) llamaba a
`load.update()` y, si devolvía `changed`, ejecutaba `st.rerun()` completo. Ese
`changed` se activaba también por causas que no aportan dato visible:

- `_expire_budgets`: un recurso que supera `UPDATE_BUDGET_SECONDS` (10 s) se
  abandona y se marca como cambio.
- `_collect`: un error de refresco (`database is locked`, timeout de Alpaca)
  o un resultado descartado también marca cambio.

Con el host degradado, cada sondeo podía marcar cambio y forzar un repintado
completo de 4-7 s. Medido antes del arreglo: **64 `dashboard_timing` en 20
minutos** (~1 cada 19 s).

## Cambio

- `page_dashboard` sella `dashboard_last_paint_at` al renderizar.
- `_poll_dashboard` mantiene la actualización en segundo plano, pero solo
  repinta si ha pasado el intervalo elegido en «Refresco automatico». Con
  10 min, no hay repintado por cambios de fondo; al interactuar se repinta
  como siempre.
- Sin tocar datos, broker, política ni el loader.

## Validación

- Focales UI y vecinos: `114 passed` (P-L179, P-L182, web_app, P-L176,
  dashboard_modern_ui). Ruff limpio, NUL 616, diff limpio.
- Imagen `agente-bolsa:0.4.415-arm64`
  `sha256:6e5b39db0a752062edd1fbce5ab5e95b8ef78876a7c76d1dc7bc6d4da8a46ac6`,
  desde `0.4.414-arm64`; dos ficheros verificados byte a byte
  (`web_app 04dfcedb…`, `__init__ 0f549485…`).
- Commit `9b882ad58e91bb141e0a303e4083f3bca1360b07`, tree
  `6c1e5f07f1219ff0f73d4eaa804162bc3ae28328`, tag `prod-jetson-0.4.415`.
- Recibo: 2026-10-30T14:29:52Z (`15:29:52` Madrid). Tres contenedores
  `healthy`, `restarts=0`, `oom=false`, HTTP 200, kernel `ok`, flags paper.
- Navegador: `v0.4.415` con «Despliegue verificado». Medición posterior:
  **5 repintados en 7 minutos** (cargas y recargas mías) y **0 en los últimos
  3 minutos** sin interacción, frente a 64/20 min. Sin `traceback` ni
  `database is locked` en el contenedor web.

## Consecuencia declarada del corte en mercado abierto

El reinicio a las 13:36Z interrumpió un `intraday_technical_scan` en vuelo
(`agent_run_077e7044c905`, iniciado 13:33:11Z). Cerró como `failed` a las
13:41:08Z con `OperationalError('database is locked')`. El siguiente ciclo
(14:15:59Z) volvió a fallar en el scan por la misma causa (14:20:43Z): es el
I/O del host, no el reinicio. Consecuencia visible: 0 compras hoy y 8 ventas
de riesgo; el ciclo sigue degradado hasta la ventana de `whale-copy`.

## Límites

- El repintado se limita al intervalo elegido; si el operador pone
  «desactivado», se mantiene el comportamiento anterior (repintar al cambiar).
- Los fallos del loader no desaparecen: se dejan de pintar, pero la causa
  (`database is locked`, timeouts) sigue siendo el I/O del host.

## Siguiente paso

1. Ventana 21:55-23:15: parar `whale-copy`, auditar PMR y rearrancar.
2. PMR `completed` → baseline del 30-oct y serie al día; `failed` → P-L185b o
   P-L186 con la traza exacta.
3. LLM/credenciales y P-L178b; límite permanente de `whale-copy`; backfill de
   fills; PMR colgado del 29-oct.
