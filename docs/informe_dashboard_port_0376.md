# Revisión y port del dashboard — 24 de octubre de 2026

Dictamen de rama: `ready_for_integration_rehearsal`; integrado en candidato local
`.378`, aún no desplegado. La rama antigua 0.1.13 no se integró completa: el port
selectivo conserva la línea moderna .376.

## Identidad y coordinación

- Base exacta: `856740a074f7e6ac314abc1cd8339a834af51a78`, tree
  `2311d35f47a7ab330d9d5cf2886c08d69162a715`.
- Rama: `codex/dashboard-port-0376`; versión reservada `0.4.378`.
- Implementación: `4aa64bcd`; QA: `399a5b3def5aa58fe26d7346562ea1ba79c4293b`.
- Tree funcional y QA: `497d2117150b268084a5db2916173c64b43a8d7e`.
- Coordinador: chat `[AgenteBolsa] Analiza resultados del S&P 500`,
  `01a11779-d5e7-7bd2-a159-b6dce99763ba`. Sus commits se integraron selectivamente
  junto con el recibo de despliegue; la integración final y sus gates se registran
  en la sección de abajo y en `docs/informe_oct24_coordinacion.md`.
- La automatización del 23 de octubre estaba pausada tras despertar fuera de
  ventana. No se ha reactivado ni creado otro despliegue desde este lote.
- Calendario local aislado: XNYS cerrado, 24oct18:58Madrid; siguiente apertura
  26oct14:30Madrid. Esto no certifica quietud ni salud productiva.

## Causa y cambios

La entrada esperaba cartera, fills, curva diaria e intradía secuencialmente.
Además, plegar los expanders no evitaba ejecutar sus paneles: el rendimiento
avanzado podía descargar precios. La entrada también ejecutaba retención y DDL.

El dashboard hidrata snapshots por cuenta/entorno/credenciales/DB y actualiza
cuatro recursos en segundo plano. Publica cartera y posiciones antes de completar
fills y curvas. Conserva previous_close_equity y campos intradía modernos,
Enum.value del broker y los cálculos de equity/apertura existentes. La fecha
observada real se conserva al hidratar; se muestran edad y cobertura parcial.
La curva que termina antes de la cuenta se guarda cuando llega esa identidad.

Tres workers y como máximo cuatro trabajos pendientes globales; lecturas
idénticas en curso se comparten. Cadencias: cartera30s/300s abierto/cerrado,
fills120s/300s, curvas900s. Poll de2s comprueba finalización; no implica descarga.
Refresco desactivado permite completar la carga inicial sin programar nuevas
lecturas periódicas. Los paneles avanzados requieren activar un control explícito.
No hay retención ni DDL repetido en el render del dashboard.

Adaptador nuevo dashboard_broker.py solo GET FILL, assert_trading_safety,
page_token como ID, after como fecha/hora y timeout socket5s. Pagina arrays hasta
página vacía, falla ante payload inválido/cursor repetido, y rechaza duplicados
con contenido distinto. Persistencia append-only e idempotencia por ID/hash;
conflictos conservan original, transacciones cortas y conexiones Store cerradas.
Las lecturas de caché usan mode=ro/query_only. No backfill ejecutado ni servicio
nuevo. Los esquemas de presentación se crean por los repositorios mediante Store.

## Validación

Árbol funcional final: 113passed en11.31s, sin skips. Batería:

```powershell
python -m pytest tests/test_dashboard_snapshot.py tests/test_dashboard_fills.py tests/test_dashboard_release_review.py tests/test_dashboard_modern_port.py tests/test_dashboard_modern_ui.py tests/test_p158b_dashboard_perf.py tests/test_p158a_dashboard_timing.py tests/test_p152_dashboard_today.py tests/test_p87_dashboard_cards.py tests/test_p88_portfolio_value_labels.py tests/test_p83d_dashboard_temporal_dates.py tests/test_version_policy.py -q --tb=short --maxfail=2
```

Python del proyecto, PYTHONPATH de este worktree, DATA_DIR temporal y fixtures
_env_file=None. AppTest verifica render con y sin snapshot mientras el proveedor
está bloqueado por Event, y bloquea sockets, curl_cffi e yfinance; comprueba que
no hubo intentos de red tragados por catches. Prueba cola global, timeout lógico,
resultado tardío, hidratación sin descarga, campos modernos, identidad y cobertura.
Ruff src/tests completo verde; NUL590archivos y git diff --check verdes.
Las baterías intermedias solapan estas113 y no se suman.

Fallos encontrados durante el port, corregidos antes del cierre:
- Fixture antiguo parcheaba el broker equivocado:3tests intentaron DNS y fallaron
  con getaddrinfo; no se obtuvo respuesta del broker. Se cambió al adaptador y
  se bloquearon sockets explícitamente.
- Fixture descartaba un ítem inválido; contrato actual exige fallo cerrado.
- Curvas terminadas antes de cuenta no persistían; regresión añadida y corregida.
- AppTest del wrapper superó10s por cálculo avanzado y descargas yfinance/curl
  fallidas. Bloquear solo socket Python no cubría curl nativo. Se añadió bloqueo
  curl/yfinance y activación explícita de paneles. AppTest final pasa offline.
- Se corrigió una conversión temporal de encoding detectada en diff; textos
  preexistentes preservados. No se presenta el primer AppTest como prueba offline.

## Protegidos y límites

Objetos Git base/candidato iguales:

| Archivo | Blob |
|---|---|
| kernel.py | eb0a71f93847087f693b65c26b1ff3c2c82a4b78 |
| tools/broker.py | 24b8fa9f99e48dd388e26bb336371e9ff36c9d81 |
| tools/execution.py | c8fc766370c558fb1aec6303e966c48202c2b584 |
| tools/risk.py | 75c1242c2f10c989120243ca1149e22749d342bb |
| config.py | e8c8fea58dcece471f717854f0b169d1b8e3e627 |

.env ausente en worktree; manifiesto, trading y fuentes protegidas sin cambios.
No push, producción, reinicio, backfill ni despliegue. La paridad de código
protegido no equivale a una verificación de órdenes futuras.

Timeout efectivo SDK de cartera: `unavailable`. El presupuesto lógico10s permite
mostrar degradación y descartar resultados tardíos, pero no mata un socket SDK
bloqueado. Curvas conservan transporte moderno. No afirmar P2 completo.
Otras páginas (Cartera/Histórico/Kindle) conservan su ruta actual; este port limita
el trabajo al dashboard. Historial local y consultas SQLite aún requieren medición
sobre volumen productivo. No se aplicaron todos los índices de la rama antigua.

## Siguiente paso y aceptación objetiva

Integrar recibo .377 y dashboard .378, revisar conflictos y una sola fullsuite
del árbol combinado, smoke aislado Windows/ARM, Ruff/NUL/diff, config/kernel y
preflight productivo. Exigir terminal postmarket y sin jobs/leases/reintentos,
imagen/digest ARM correctos, memoria suficiente y kernel sin violaciones. El
coordinador conserva control del corte único y rollback; doble salud separada
al menos75s y observación OOM600s. No resellar kernel para ocultar diferencias.

Tras el corte medir al menos20 entradas calientes y20 frías, registrar volumen,
hardware y p50/p95 separados de latencia broker. Objetivos propuestos: primera
vista útil p95<2s con snapshot y carcasa usable p95<5s sin snapshot; ninguna
espera remota en el hilo de render, edades visibles y cero ráfagas por pestañas.
Estos tiempos son objetivos, no resultados productivos verificados. Si falla,
perfilar consultas/reportes locales y SDK bloqueado antes de ampliar arquitectura.

## Integración coordinada —24oct2026 19:31 Europe/Madrid

El port quedó integrado por cherry-pick selectivo en `codex/oct19-corrective-integration`
con el recibo/UI de despliegue. Versión final reservada `.378`; HEAD funcional
`032539c56d35e256099ee9f449146cb139bcbfdf`, tree
`668f6525b27a296c6c8566a992907f04168525a6`. Pasan 160 focales combinadas y Ruff,
NUL y diff. La fullsuite permanece bloqueada por el wrapper de procesos del
sandbox tras 1.590 pruebas; no es dictamen de despliegue. No se construyó imagen,
no se accedió a producción y no hubo reinicios.

Informe conjunto y decisiones pendientes:
`docs/informe_oct24_coordinacion.md`. La UI de timestamp funciona para `.378`;
la imagen de rollback `.369` sigue sin lector de recibos, por lo que aún no se
certifica que el timestamp se vea en el navegador tras una reversión.
