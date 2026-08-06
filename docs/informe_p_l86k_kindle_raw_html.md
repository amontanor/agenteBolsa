# P-L86K — dictamen y evidencia

**Dictamen: `ready_for_closed_market_full_validation`.**

## Causa y solucion

La respuesta productiva actual de `GET /kindle` es el bootstrap JavaScript de
Streamlit (HTTP 200, `text/html`, 1522 bytes), por lo que un Kindle sin
JavaScript no recibe la cartera. Streamlit 1.58 ofrece el hook ASGI oficial
`st.App(..., routes=[Route(...)])`: las rutas de usuario preceden a las rutas
internas y se mantienen en el mismo proceso, tarea y puerto.

El candidato registra una ruta raw `GET /kindle`. La primera respuesta contiene
solo `Cargando...` y un meta-refresh de 2 segundos; la vista cargada es HTML
autocontenido, sin JavaScript, recursos externos ni shell Streamlit, y refresca
cada 300 segundos. Usa unicamente el `PortfolioSnapshot` ya cargado para la
metrica `equity - account.last_equity`; si no existe un carrier SPY exacto de
la ventana `previous_close_to_as_of`, muestra `n/d` y no reutiliza apertura.
La tabla contiene `Accion`, `Entrada`, `Actual`, `P/L total` y `P/L hoy`, sin
`Cantidad`. Valores y fechas se escapan y los missing quedan en `n/d`.

## Identidad y validacion

- Base/produccion: `563e95aae66a3fadab9c14c6fe5284e200110725`, tree
  `b7fa172a45bb3c61b91bcb020f5baeac74593b04`, v0.4.222, limpia.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl86k_kindle_raw_html`.
- Rama: `codex/pl86k-kindle-raw-html`.
- Commits: `3a1549eb` (caracterizacion) y `c7e7feb6` (implementacion+bump).
- Version candidata: v0.4.223.
- Archivos funcionales: `src/agente_bolsa/web_app.py` (+95/-0) y version
  `src/agente_bolsa/__init__.py`; el bloque funcional nuevo es de 89 lineas.

Focales raw/Streamlit P-L86: **14 passed**; version policy: **1 passed**;
Ruff, NUL y `git diff --check`: verdes. La deteccion CLI devuelve
`web_app:app` y `web_app.app` registra exactamente `/kindle`. No se ejecuto
suite completa, smoke ni despliegue por el margen preapertura; no se toco
produccion ni se reinicio el servicio web.

No cambian broker, trading, riesgo, ejecucion, LLM, config, `.env`, SQLite,
scheduler, firewall, tarea LAN ni P-L80. No se crean procesos, puertos,
persistencia, snapshots o tareas nuevas. El siguiente unico paso es validacion
cerrada proporcional, integracion `merge --no-ff` y comprobacion HTTP real solo
si existe margen suficiente antes de la apertura.
