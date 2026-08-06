# P-L86K — dictamen y evidencia

**Dictamen: `deployed`.**

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
- HEAD documental: `58a56ce46fbc60dfcb2f13a1303766948f053e9d`; tree final:
  `f7a7fc871bfa6b2ab70139dbf9fa224351c90bc5`.
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
persistencia, snapshots o tareas nuevas.

## Cierre productivo

Se integro con `merge --no-ff` el candidato exacto `67200bf0`. El merge
productivo es `9b9068f3f13f94077670d3ec2a09ca9f72b98259`, con primer padre
`563e95aa` y segundo padre `67200bf0`; tree `c2239e7c` y version v0.4.223.
Se reinicio unicamente la tarea gestionada `AgenteBolsaWeb`; no se reinicio el
scheduler ni se uso `stack_down` global.

Salud 1: `2026-08-06T15:17:47.4591793+02:00` CEST. Salud 2:
`2026-08-06T15:19:48.7424810+02:00` CEST, separadas 121.28 s. En ambas hubo
HTTP 200 para `/`, `/health` y `/kindle` en `127.0.0.1` y `192.168.1.136`,
listener unico `0.0.0.0:8501`, tarea Running, scheduler PID 29624/token
coherentes, kernel ok sin violaciones, paper activo y Git limpio. La vista
cargada comprobada devolvio HTML raw con `Cartera hoy`, refresh 300, datos de
posiciones, SPY explicito y sin shell Streamlit ni `Cantidad`.

La regla `AgenteBolsaWeb Private LAN 8501` permanece TCP 8501, perfil Private,
RemoteAddress LocalSubnet; Test-NetConnection LAN fue correcto. No hubo
rollback, push, jobs manuales, cambios de trading, broker, SQLite o firewall.
