# Estudio de rendimiento del Dashboard (25-sep-2026)

## Dictamen

Las grandes esperas del HAR del usuario (12:17-12:19 Madrid) son
ambientales, no el coste normal de la app. Medido en estado estable hoy
misma manana: documento `GET /` en 15 ms y `_stcore/health` en 2 ms desde
el propio Jetson. El HAR muestra 5 s de connect TCP, 270 ms en endpoints
triviales y 70 s de streaming con un paron de 47 s en mitad del render:
firma de host bajo presion y reinicios, no de codigo lento por defecto.
Dicho esto, cada sesion re-ejecuta el script entero (65 graficas/tablas) y
hay margen real de mejora. Sin cambios de codigo en este lote (estudio N0).

## 1. Que ocurre (linea de tiempo del HAR, `192.168.1.186.har`)

- `GET /` → 304 en 5059 ms: `connect=5036.9 ms`, `wait=18.4 ms`. El servidor
  responde en 18 ms; los 5 s son establecer TCP, no proceso.
- Estatico (JS/CSS/fuentes/favicon): 0-26 ms, casi todo desde cache del
  navegador. Servir ficheros esta sano.
- `/_stcore/health` 290 ms (`wait=271`), `/_stcore/host-config` 290 ms
  (`wait=270.8`). Respuestas de 2 y 687 bytes tardando ~270 ms en servidor.
- Websocket `/_stcore/stream` abierto 70.2 s con deltas de 10:17:48 a
  10:18:58 UTC. Hay un paron de ~47 s sin deltas (10:18:09 → 10:18:56) y
  luego una rafaga hasta completar. La pagina pinta por entregas durante
  mas de un minuto.
- A partir de 10:18:36 el navegador pide ~30 chunks JS lazy (cada uno rapido,
  0.02-18 ms): el render los va necesitando segun aparecen widgets.

## 2. Por que (capas, con evidencia)

1. **Connect 5 s**: el Jetson se reinicio 4-5 veces esa manana (09:12, 09:17,
   10:18, 10:29 y ~11:25 Madrid, `last -x`; causa sin determinar, dmesg sin
   OOM/panico/NVMe) y la carga media rondaba 4. Con la cola de aceptacion
   saturada o el host cayendo, el SYN espera segundos. Hoy estable: 15 ms.
2. **Waits 270 ms en endpoints triviales**: latencia de planificacion del
   proceso Streamlit bajo carga (mismo proceso monohilo que corre el
   script del dashboard). Hoy: 2 ms.
3. **Stream 70 s / paron 47 s**: el script `web_app.py` corre entero por
   sesion y emite decenas de deltas (cuenta, cartera, 65 graficas/tablas,
   research inbox, leaderboards). Existe cache de 60 s para snapshot e
   historial de Alpaca (`_dashboard_cache_get`, mas `st.cache_data` 120 s
   en dos puntos), asi que las llamadas al broker estan amortiguadas; lo
   que queda por sesion son lecturas de SQLite/reports, pandas y
   construccion de JSON vega. Bajo CPU contention (load ~4 en Orin Nano)
   una sola llamada bloqueante o el GC paran el render 47 s. El log del
   scheduler de esa ventana no muestra jobs pesados solapados (solo un
   `skipped` por max-instances); el log web no registra tiempos por sesion,
   asi que el tramo exacto de los 47 s queda `unavailable` sin instrumentar.

## 3. Como solucionarlo (propuestas, sin implementar)

1. **Instrumentar primero** (barato, N1/N2): logar duracion por seccion del
   `page_dashboard` (snapshot, historial, cada bloque de graficas) para
   atribuir los segundos a codigo y no a hipotesis. Sin esto, cualquier
   refactor es a ciegas.
2. **Cachear por panel, no solo broker**: subir TTL de paneles lentos y
   estables (hero/cuenta, research inbox) y usar `st.fragment` para que un
   widget no re-ejecute todo el script.
3. **Precomputar en background**: un job que escriba `latest_dashboard.json`
   (snapshot + metricas + series ya calculadas) y que la UI solo lo lea;
   el patron ya existe en `latest_*` de reports.
4. **Recortar trabajo por sesion**: paginar/limitar las 65 graficas y tablas
   (las visibles primero), reutilizar un unico snapshot ya cargado en todos
   los bloques (hoy hay 3+ puntos de carga de snapshot).
5. **Infra primero**: resolver el reboot-loop de hoy (riesgo mayor que el
   dashboard) y aliviar carga sostenida del Orin (load 4 con mercado
   cerrado). Sin host estable, ninguna optimizacion UI es medible.

## 4. Estado y siguiente paso

- HAR analizado; estado estable verificado hoy (15 ms / 2 ms); codigo
  inspeccionado solo en lectura; sin cambios en produccion ni en el repo.
- Siguiente lote minimo propuesto: instrumentacion de tiempos por seccion
  (P-L158-A, worktree aislado, N1), y con datos, el refactor que mas
  segundos explique.
