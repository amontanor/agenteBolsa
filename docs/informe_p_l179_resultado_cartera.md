# Informe único P-L179 — resultado de la cartera separado del equity

Fecha: 2026-10-30, Europe/Madrid. XNYS cerrado (apertura 14:30).
Dictamen: **deployed** en producción 0.4.410, con doble salud y verificación
en navegador.

## 1. Causa raíz

El panel mostraba un único porcentaje grande calculado sobre el equity total,
que incluye la caja. Con el 41 % invertido, una cartera que sube un 5 % mueve
el equity +2,07 %, y con el 3 % de otras fechas, +0,16 %. El operador leía ese
número como «rentabilidad de mi cartera».

Hechos verificados en código antes del lote:

- `_today_pl_display` descartaba el P/L y usaba solo `equity_pct`
  (`web_app.py:466-478`); su caption decía «P/L diario de cartera».
- La cifra correcta existía en `_invested_day_metric` (P-L140A), cuarta fila de
  «Mis inversiones», sin jerarquía.
- `exposure_pct` se calculaba por sesión y nunca se renderizaba
  (`web_app.py:4208-4226`), y P-L65B lo declara descriptivo: equity sigue
  primario frente a SPY.
- `_invested_day_metric` no distinguía «mercado cerrado con ceros» de «cero
  ganado»; P-L152 sí lo hace en la tarjeta vecina.

## 2. Cambio desplegado

- `_today_pl_display` y `_daily_equity_detail`: el número grande se rotula
  «Variación de equity hoy (incluye caja)» y su caption deja de llamarlo
  cartera.
- `_dilution_note`: nota calculada en vivo — «con 41,47 % invertido, un 5,00 %
  de cartera mueve el equity +2,07 %».
- `_invested_day_metric`: guardia `all_zero` + mercado cerrado → `n/d`; marca
  `partial` cuando la cobertura no es completa. Sigue siendo P/L de posiciones
  abiertas sobre invertido, con paridad exacta con la tabla.
- `_investments_group`: «Resultado de la cartera hoy» pasa a primera tarjeta,
  con equity como secundario y realizadas del día en la misma línea.
- `_portfolio_day_result` + bloque «Hoy»: «Cartera de acciones hoy» suma
  posiciones abiertas y ventas cerradas; el importe es exacto con P/L de fills
  conocido y el porcentaje se declara estimado sobre invertido + ventas de hoy.
- `_position_rows_totals`: fila de totales en la tabla de posiciones y tarjetas
  equivalentes en la página «Cartera», calculadas de las mismas filas.
- `_performance_daily_series`: bloque «Cartera por sesión (cierre a cierre)» con
  P/L de equity / exposición registrada, cobertura declarada y aviso de que no
  entra en ganador ni alpha.
- «Evolución de la cuenta»: selector `Equity ($)` / `P/L acumulado (%)` sobre
  `cumulative_pnl_pct` ya persistido, en modo lectura.
- Kindle: «Variación de equity hoy (incluye caja)».

P-L65B, P-L140A, P-L140B y P-L152 quedan intactos: equity sigue primario en
Sistema vs SPY, una sola superficie de comparación y `all_zero` sigue siendo
`n/d` fuera de sesión.

## 3. Defectos encontrados durante la verificación en producción

1. **0.4.408 mostraba «estimado, base parcial» con cobertura completa.** El
   texto mezclaba «estimado» (por incluir ventas) con «parcial» (por faltar
   datos). Corregido en 0.4.409 separando ambas condiciones.
2. **La serie de `performance_daily` salía vacía.** `Store.performance_daily`
   devuelve `payload` ya parseado, no `payload_json`; el lector buscaba la
   clave cruda. Consecuencia: sin selector `P/L acumulado (%)` y sin bloque de
   cartera por sesión. Corregido en 0.4.410 aceptando ambas formas, y
   verificado contra la base real en un contenedor temporal antes de desplegar:
   64 sesiones, 35 con cartera calculable, 42 con acumulado.
3. **Las filas apertura→apertura no traen `avg_exposure`.** La columna
   «Cartera (sobre invertido)» habría salido `n/d` en 63 de 63 filas. Se
   retiró de la tabla SPY y la serie pasó a su propio bloque con su propia
   ventana (cierre a cierre), sin mezclar filas.

## 4. Producción

- Versión: `0.4.410`. Imagen `agente-bolsa:0.4.410-arm64`
  `sha256:63fc007fef775bd2e071e95fb7325df71e9e83ca1c1054b42ef1e752437a21bf`.
- Commit desplegado: `e57819883f238f9ac47a0840b5707cce0ddbf8ec`, tree
  `e259e692c31bbc5e2bfd09bdf6fe7742f75004c9`.
- Recibo verificado: 2026-10-30T08:22:34Z (`09:22:34` Madrid).
- Imágenes intermedias: `0.4.408` (`sha256:d6f35a78…`, commit `e4f06250`) y
  `0.4.409` (`sha256:2639f983…`, commit `e5fb0cb7`), ambas sustituidas por
  defectos de verificación; no se etiquetan como release.
- Despliegue: backup `runtime.env.bak-pl179-20261030T074436Z`,
  `…bak-pl179b-…` y `…bak-pl179c-…`; selector a `0.4.410-arm64`; `docker
  compose` con `docker-compose.yml` + `docker-compose.raspberry.override.yml`
  y `up -d --no-deps scheduler web auxiliary`. Sin `init-db` (sin cambio de
  esquema).
- Salud 1 y salud 2 (≥75 s): tres contenedores `running (healthy)`,
  `restarts=0`, `oom=false`, HTTP raíz 200 y `/_stcore/health` 200, runtime
  0.4.410, kernel `ok` sellado 2026-10-29 con 0 violaciones, flags
  `paper/True/False/False`, cero `database is locked`/`traceback`/`critical`
  en los logs de la ventana.
- Navegador: la raíz muestra `v0.4.410` y «Despliegue verificado 09:22:34».
  Comprobados en pantalla: variación de equity con nota de dilución, resultado
  de cartera hoy `$289,71 +0,99 %` con realizadas `$-0,24`, cartera de acciones
  hoy `$289,47 +0,97 %`, totales de la tabla `$29.219,30` con
  `11/11 con P/L día`, selector `Equity ($)` / `P/L acumulado (%)` funcionando
  (`Resultado del periodo -0,14 % · 7 sesiones`, `Acumulado actual -0,72 %`), y
  página «Cartera» con las mismas cuatro cifras que el dashboard.

## 5. Gates ejecutados

- Focales del lote y vecinos: `170 passed` (P-L179, web_app, P-L140A, P-L140B,
  P-L152, P-L65A, P-L65B, P-L63, P-L87, P-L86R).
- Suite completa: `3236 passed, 1 skipped, 1 failed` en 700 s. El único fallo
  es `tests/test_web_research.py::test_search_company_news_without_provider_is_no_provider`,
  preexistente por contaminación de entorno (`OPENCODE_*`/`TAVILY_API_KEY`);
  pasa aislado. La ejecución anterior (3234 passed, 3 failed) incluía dos
  aserciones de copy que se actualizaron en este lote.
- Ruff `src tests`: los mismos 4 errores preexistentes de la base, cero nuevos.
- `scripts/check_no_nulls.py`: `OK (612 archivos)`.
- `git diff --check`: limpio.
- Imagen verificada byte a byte en contenedor temporal con `--entrypoint
  python3`: `web_app.py 525ffa5a…` y `__init__.py db4e1aae…`, versión 0.4.410.

## 6. Precondiciones y excepciones declaradas

- XNYS cerrado; sin `market_cycle`, `portfolio_watch` ni PMR en ejecución;
  sin leases activos; scheduler con heartbeat fresco.
- **Excepción declarada**: `post_market_review_last_session=2026-10-19`. El PMR
  del 29-oct quedó `failed` a las 23:10:55Z con un reintento posterior sin
  evento terminal; el del 30-oct terminó `skipped/market_not_ready` a las
  07:21:31Z. AGENTS exige postmarket terminal de la sesión terminal; el
  despliegue se ejecutó por orden expresa del operador, sin reparar ni
  reintentar nada. P-L163c sigue pendiente de validarse con el PMR de hoy.

## 7. Límites

- «Cartera por sesión» es una estimación descriptiva: P/L de equity de la
  sesión / exposición de la foto, no una media intradía ni una base exacta por
  posición cerrada. Se etiqueta como tal y declara cobertura.
- La serie llega hasta 2026-10-19 (última fila de `performance_daily`); las
  sesiones posteriores no tienen epígrafe y no se inventan.
- `pnl_pct` es nulo en algunas filas; esas sesiones quedan sin cartera
  calculable y no suman a la cobertura.
- La página «Cartera» sigue leyendo yfinance para el detalle de posición
  (comportamiento previo, sin cambios).

## 8. Siguiente paso

1. Confirmar tag anotado `prod-jetson-0.4.410` y fast-forward de `main` con este
   lote.
2. Observar el PMR de hoy, que valida P-L163c; si falla, leer el frame nuevo
   antes de tocar nada.
3. No retirar el worktree ni la rama del lote sin autorización.
