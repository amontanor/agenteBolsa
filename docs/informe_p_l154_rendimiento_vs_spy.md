# P-L154 — rendimiento frente a SPY y plan de mejora económica

Auditoría: 22-sep-2026. Dictamen: `ready_for_implementation` para la
caracterización P-L154-A. Mejora económica y promoción: `unavailable`.
Este lote es N0: análisis read-only y documentación; no activa políticas.

## Dictamen y resultados

El sistema queda por detrás de SPY en las ventanas examinadas. Mantiene muy poco
capital invertido y no demuestra que sus propuestas de aprendizaje añadan valor.
Falta atribuir cuánto corresponde a exposición, selección, salidas, costes y
flujos externos. Aumentar tamaños antes de demostrar ventaja puede agravar pérdidas.
El plan prioriza evidencia reciente, experimentos económicos y uso del capital.
No hay base suficiente para estimar un porcentaje de mejora futura.

Fuente: `opening_performance_context` desplegado, evaluado con
`now=2026-09-22T13:30:00Z`, intervalos finales hasta el 21-sep. Sistema:
`alpaca_portfolio_history_15Min`; SPY: caché `yfinance`, `adjusted_ohlc`.
Composición sobre los mismos intervalos: `100 * (producto(1 + retorno_i) - 1)`.

| Ventana apertura a apertura | Intervalos | Sistema | SPY | Diferencia |
| --- | ---: | ---: | ---: | ---: |
| 29-jul a 21-sep, subconjunto con huecos | 35 | -0,587930% | +3,487651% | -4,075581 pp |
| 10-ago a 21-sep, tramo continuo | 29 | -0,856878% | -0,575488% | -0,281390 pp |
| 9-sep a 21-sep, tramo continuo reciente | 8 | -0,226486% | +0,533151% | -0,759637 pp |

El primer renglón NO es la rentabilidad continua del periodo: faltan 6-ago/7-ago
y 7-ago/10-ago por `account_open_unavailable`. También se excluyó 21-sep/22-sep:
`spy_open_unavailable` en el corte. No se anualizan estos resultados.

Son variaciones brutas de equity, indicativas: falta verificar flujos externos
y equivalencia de dividendos/ajustes. No son rentabilidad neutral a flujos ni
alpha causal. SPY es el ETF comparador, no el índice publicado. El benchmark
total return debe incluir dividendos reinvertidos, conforme a la
[metodología S&P DJI](https://www.spglobal.com/spdji/en/methodology/article/index-mathematics-methodology/).

Último cierre auditado, 21-sep: equity **70.237,37 USD**, efectivo
**65.188,42 USD**, inversión bruta **5.048,95 USD**, seis posiciones:
**7,188410% invertido**, **92,811590% efectivo**. Media de nueve fotografías EOD,
9–21-sep: exposición **5,086399%**; no es media intradía ponderada por tiempo.
La exposición reducida puede explicar parte del retraso; no cuantifica su causa
ni autoriza invertir el efectivo. Incluso el límite total actual es 50%, frente
a un benchmark al 100%: hay que distinguir participación de mercado y selección.

## Hallazgos verificados

1. **El resumen principal no representa la cohorte reciente.** Declara 18.437
   observaciones, cero ejecutadas y duplicación 0,7831. La DB contiene 54.720
   `learning_observations` hasta 21-sep; 80 con `executed_buy=1`, 80
   `best_signal_id` distintos: 78 `learning_experiment` y dos `intraday_scan`.
   Esto no demuestra 80 órdenes únicas. En el código desplegado,
   `build_learning_daily_run` llama `_rebuild_signal_cohorts` con default
   `include_learning_experiment=False`. Existe un apartado separado para esa
   cohorte: no se ha demostrado truncado ni ausencia total de aprendizaje reciente.
   Las otras fuentes terminan el 7-jul: 6.327 `closed_market_study`, 64.263
   `intraday_scan`, 14.406 `opportunity_snapshot` = **84.996** señales. La fuente
   reciente tiene **28.975** señales hasta 22-sep en la consulta posterior.
   Por tanto, `resolved=84996, pending=0` no describe todas las señales actuales.
   Falta cerrar qué evidencia consume cada agente/prior.
2. **No hay control comparable.** Scoreboard `learning_experiment`, 7-jul/21-sep:
   78 ejecutadas, linaje declarado 78/78, controles **0/78**, `learns=false`.
   Maduras a 1/3/5/10 días: 77/74/74/71, controles maduros cero. Otro digest
   registra 82 conjuntos de control, todos `unavailable` por
   `no_eligible_alternatives`. Contadores de informes distintos no se suman.
3. **Atribución no suficientemente segura.** `_rebuild_signal_cohorts`
   desplegado usa `(signal_date, symbol)` para asociar órdenes. El linaje de
   una orden no prueba su correspondencia con cada señal agrupada.
   Elegibilidad requiere señal/decisión/plan/orden exactos; no texto ni símbolo.
4. **No hay mejora económica demostrada.** El scoreboard informa medias semanales
   de expectativa con 10 bps de -0,78% en semanas 1–4 y -3,55% en 5–8.
   No son rentabilidad de cartera ni prueba causal. Su estado
   `pending_weeks_5_8` resulta incoherente con semanas posteriores presentes.
   Drawdown por señal no puede publicarse como drawdown de cartera.
5. **Propuestas sin experimento cerrado.** Último digest CI: muestra de 200
   propuestas, 192 `PROSA`, ocho `EJECUTABLE`, cero contratos completos;
   `experiments.run=0`, `evidence_experiments=0`, `applied_changes.total=0`.
   Describe ese informe; no niega los despliegues manuales ya realizados.
6. **Contrato económico incompleto.** Nueve fotos EOD recientes sin benchmark
   canónico; cobertura de flujos `unavailable`, costes parciales. Snapshot
   21-sep inválido: `position_side_invalid` con `positionside.long`,
   `position_market_value_missing`, `window_timestamp_invalid_or_naive`,
   `benchmark_missing`, `contributions_missing`, `costs_partial`,
   `external_flow_ledger_missing`. La UI apertura/apertura usa otra ruta.

Los outcomes extremos requieren verificar precios y ajustes corporativos. Una
fila legacy CRWD del 5-jun informa -76,13% a un día: no se declara error ni se
elimina por magnitud; hay que contrastar basis, splits, calendario y proveedor.
Un `crew_fallback_started` tampoco demuestra fracaso final ni compra determinista:
se necesitan terminales y linaje de decisión.

Luna completó la auditoría y Astra contrastó los consumidores en el checkout:
`trade_decision.py::_candidate_learning_prior` (1806),
`_annotate_technical_context_with_learning` (2524),
`_build_decision_learning_context` (2626) y
`_sizing_adjustment_for_recommendation` (2690) usan los priors principales;
la sección `learning_experiment_yesterday` no alimenta esos priors. Además,
`daily_learning.py::build_learning_daily_run` y `build_learning_digest_report`
escriben el mismo `latest_daily_learning_digest.json` con alcances distintos.
Esto exige identidad de productor/cohorte y un único contrato explícito.
La ruta de productores se verificó en `.310`; la equivalencia de estos
consumidores locales con la imagen sigue como gate de P-L154-A. No se afirma
qué prior exacto influyó en cada orden sin su evento de consumo.

**Frontera de seguridad:** corregir datos que alimentan ranking o sizing puede
cambiar trading aunque se llame corrección de aprendizaje. B+C solo añaden
evidencia/contratos observacionales; conservan los campos y entradas de la ruta
activa. El nuevo contexto se consume en shadow. Su conexión activa es N3,
con autorización/revisión, paridad de fronteras no afectadas y evidencia económica.

## Plan por lotes

El backlog oficial está en `plan_mejoras_y_tareas.md`; este es el informe único.
Una tarea Luna nativa nueva por lote, modelo/esfuerzo explícitos según AGENTS,
worktree `codex/<lote>` y revisión de Astra. Sin Muse ni Planner. Un único
experimento económico en evaluación cada vez; no mezclar política y telemetría.

| Lote | Objetivo | Resultado exigido antes de continuar |
| --- | --- | --- |
| P-L154-A | Base real y caracterización | Objetos desplegados identificados y defectos reproducibles |
| P-L154-B | Evidencia reciente y exacta | Coberturas reconciliadas y consumidor trazable |
| P-L154-C | Contabilidad y atribución económica | Retorno/costes/efectivo comparables, o exclusión explícita |
| P-L154-D | Una regla de selección shadow | Comparación OOS neta contra champion |
| P-L154-E | Uso del capital shadow | Núcleo SPY/satélite comparados con mismo riesgo |
| P-L154-F | Bucle de agentes verificable | Propuestas con contrato y resultado durable |

### A. Fijar la base y reproducir, sin ampliar alcance

Inventariar los módulos relevantes `.310`, hashes, parent de imagen y configuración
no secreta. Preparar base Git reproducible: `.253` local no equivale a `.310`.
Contrastar UTC/as_of y mapear productor, evento, reporte y consumidor por cohorte.
Reutilizar P-L130–137/P-L117 donde los objetos existan realmente. Verificar antes
de reimplementar las correcciones anteriores de expectativa cero y calibración.

Caracterización con fixtures temporales: múltiples señales/órdenes en mismo
símbolo/día, cohortes separadas, as_of reciente sobre datos antiguos y side enum.
Aceptación: referencias exactas, denominadores y lista mínima de cambios.
Presupuesto: auditoría acotada y focales, sin suite ni infraestructura nueva.

### B. Hacer que los agentes reciban evidencia pertinente

Conservar cohortes explícitas; suministrar universo reciente, seleccionados,
omitidos, decisiones y outcomes maduros de la política correspondiente. No mezclar
automáticamente las 84.996 señales legacy con la cohorte actual. Publicar rango
de datos/as_of por separado, cobertura antes/después de filtros, conflictos,
exclusiones, madurez, fuente y versión de política.

La atribución elegible necesita IDs exactos y features disponibles en decisión.
Legacy ambiguo permanece excluido; no backfill ni reescritura histórica.
Control ausente sigue ausente. Si no hubo alternativas elegibles, usar replay
champion/challenger sobre el mismo snapshot para medir la regla, sin inventar
controles ni llamar causal al simple contraste entre cohortes diferentes.
Aceptación: contadores reconciliados, idempotencia, conflictos y paridad de
selección activa, sizing, gates, órdenes y límites.

### C. Medir rentabilidad y por qué el capital no se utiliza

Cerrar EOD/periodo con carriers existentes: normalización de posiciones/side,
UTC, flujos externos, dividendos y costes de ambas piernas. Desconocido no es cero.
Corregir la frontera observacional; cualquier broker/config protegido se separa
para revisión humana. `signal_to_fill_bps` no certifica coste de ida y vuelta.

Comparar cartera, SPY total return y referencia SPY/efectivo con mismo presupuesto
de riesgo, sobre ventanas continuas comunes. Mantener SPY al 100% visible como
objetivo: no sustituirlo por un benchmark fácil de superar. Atribuir con replay
exposición temporal/caja, selección, salidas, costes y oportunidades perdidas
por disponibilidad operativa, reutilizando el funnel existente.

Aceptación: conciliación equity/caja/posiciones, flujos, costes, huecos, early
closes, splits y dividendos; métricas por señal separadas de cartera.
Primera release: B+C observacionales, paridad y QA cerrado, sin esperar a terminar
todos los experimentos económicos.

### D. Un challenger de selección con expectativa neta

Antes de la abstención se caracteriza el efecto del contexto reciente. Si hay
un defecto reproducido en el consumidor, P-L154-D1 compara solo el contexto de
ranking corregido frente al actual: misma función de selección, sizing y salidas
congelados. P-L154-D2 evalúa después la regla de abstención descrita abajo sobre
una base fijada; no se mezclan ambos cambios en una aceptación. Si no se confirma
el defecto, D1 se cierra con evidencia y D2 mantiene el ensayo original.
Hipótesis: abstenerse cuando la expectativa neta conservadora sea negativa evita
más pérdidas que ganancias. Evidencia insuficiente conserva la selección actual.
Perfiles existentes de setup/régimen/bucket de confianza; confianza no es
probabilidad. Estimar con pasado maduro, regularizar perfiles pequeños hacia la
media de entrenamiento y elegir intensidad solo en validación cronológica.

Mismo universo/snapshot/capacidad/sizing/salidas/costes que champion. Expectativas
positivas, cero, negativas y ausentes tienen orden correcto y desempate canónico.
Shadow no crea, bloquea ni demora órdenes. Reutilizar lo ya implementado.
Auditar veto/cuota P-L149 por separado; cualquier ablación es otro experimento.
P-L148 no se activa solo por cumplir cinco sesiones ni aumenta tamaño para
compensar expectativa negativa o no demostrada.

### E. Evaluar núcleo SPY y satélite activo

Reutilizar `core_sleeve`, actualmente disabled. Comparar cartera actual,
referencia SPY/efectivo y candidata con núcleo indexado/satélite activo. Prerregistrar
asignación/rebalanceo sencillos; parámetros se seleccionan en validación.
La selección activa debe justificar coste y capital frente al índice.

Respetar capacidad compartida, cash floor y riesgo total. El límite actual de
5% por posición afecta también a SPY: no existe excepción implícita para invertir
50%/100%. Esas referencias son benchmarks analíticos, no permisos de ejecución.
Si acercarse al índice exige más riesgo o cambiar límites, presentar esa frontera
al operador; no promover automáticamente ni redefinir el éxito.

### F. Aprender de experimentos y, después, revisar salidas

Cada propuesta exige una regla, hipótesis, IDs/ventana de evidencia, error
reproducible, control, versión, métricas, coste, criterio de rechazo y rollback.
Rechazar prosa sin contrato antes de validar. Registrar todos los intentos y
limitar variantes, evitando escoger por azar el mejor resultado.

Evaluar utilidad del LLM contra control determinista con universo/snapshot
comunes: beneficio neto marginal, riesgo, latencia, cobertura y coste operativo.
Agente propone; Luna reproduce/implementa; evaluador determinista mide; Astra
revisa. El LLM no concede elegibilidad ni promoción. Reutilizar eventos/tablas;
sin nuevos daemons, esquemas o dependencias.

Tras atribución y B–D, abrir un solo ensayo P-L138 de salida si la evidencia lo
justifica, manteniendo selección/tamaño fijos. Comparar beneficio retenido/MFE,
MAE, duración y rotación; nunca decidir con futuros. Cerrar ese resultado antes
de ajustar otra regla. No activar sizing y nuevas salidas simultáneamente.

## Aceptación, releases y seguridad

- Hipótesis, costes y criterios antes de test. Separar entrenamiento, validación
  y test cronológicos; purgar horizontes que crucen fronteras, aplicar embargo
  por horizonte y exigir al menos tres ventanas OOS válidas. Intervalos por
  bloques de sesiones; miles de señales correladas no son miles de ensayos.
- Validar universo PIT, delistings/acciones corporativas, ejecución factible,
  liquidez y slippage de estrés. Costes ausentes impiden elegibilidad económica.
  No borrar pérdidas extremas sin demostrar defecto de procedencia.
- Medir expectativa neta incremental y retorno de cartera, drawdown, p10, MAE,
  concentración, exposición, rotación y ganadores omitidos/perdedores evitados.
  Para revisión de promoción: límite inferior del intervalo de mejora mayor que
  cero y riesgo no peor frente a control comparable. Datos insuficientes:
  `collecting`. No estimar mejora solo por acierto o una sesión.
- Separar eras/políticas y validar prospectivamente en paper. Sin nueva
  autorización para H, política activa, live ni auto-apply. El exceso de pruebas
  infla la selección aparente: registrar intentos conforme al problema descrito
  por [Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
- Focales/regresiones por lote, versión única y revisión. Una suite completa por
  árbol final, Ruff/NUL/diff/config/kernel/smoke aislado y paridad según AGENTS.
  Despliegue N3 separado: XNYS cerrado, postmarket terminal, sin jobs/leases
  incompatibles, recursos/configuración válidos, Git limpio, rollback y doble
  salud separada al menos 75 segundos. Seguimiento automático sigue pausado.

## Estado técnico y evidencia

Checkout auditado: `0.4.253`, HEAD
`694359a6f96b862b0fa4b18e640eb569fca9b767`, tree
`230e405c0a54c1b9f06ddc0c35c5410bfdc7c754`. Producción leída: paquete `0.4.310`,
tres contenedores core healthy, imagen
`sha256:9ffd565d051972952601ccc1b6408eaaa6b8493c46d6143b2dd6b0438712194a`.
Etiqueta de revisión `port-p141-0.4.305`, insuficiente para identificar `.310`.
HEAD/tree Git de imagen: unavailable. No se certifica un despliegue nuevo.

Configuración efectiva: paper, live false, auto-apply false; exposición total
máxima 50%, por posición 5%; fallback determinista/ranker y veto/cuota habilitados.
`core_sleeve.status=disabled`: su campo exposure1.0 no demuestra una inversión.

Auditoría con XNYS abierto verificado a `2026-09-22T13:46:20Z`. Windows mantiene
lock `stale_dead_owner`, entorno de rollback, no incidente probado en Jetson.
Discrepancia observada de aproximadamente dos horas entre reloj Jetson y local;
`NTPSynchronized=yes` no identifica cuál es correcto. Contrastar UTC independiente
antes de aceptar nuevos artefactos PIT; no se cambió ningún reloj.

Lecturas SQLite: `mode=ro`, `PRAGMA query_only=ON`, timeout tres segundos;
`Store` de auditoría con conexiones read-only. Sin broker/LLM operativo, órdenes,
escritura productiva, cambio de configuración, reinicio ni push. No se verificó
preflight completo de despliegue. Sin suite/smoke: lote documental.

Consultas de denominadores:

```sql
SELECT source, COUNT(*), MIN(signal_date), MAX(signal_date)
FROM signal_outcomes GROUP BY source;
SELECT COUNT(*), MIN(signal_date), MAX(signal_date), SUM(executed_buy)
FROM learning_observations;
SELECT source_family, COUNT(*) FROM learning_observations
WHERE executed_buy=1 GROUP BY source_family;
```

SHA256 capturas temporales locales:
`pl154_readonly_audit.json` =
`f64fba14caff8c924106d43910046c393d2e900520e9e5e6acf1b5504b6c517e`;
`pl154_readonly_details.json` =
`e7562df5bc1844c4453dde28d655fb93706cde7db32062eba06d16cb2220f592`.
Los hechos relevantes se conservan aquí; las capturas completas son temporales.
Hashes productores desplegados: `daily_learning.py` =
`c922d8b842b97c700bcfa1a64a0d2fe47f847981c675794313f582c51191735c`;
`counterfactual_analysis.py` =
`82a8df4896392580ef02a97d39feb8dd30844afad8b6c61be020fe40dfc142ca`.

Luna auditora: `01a0c94d-dc10-7023-936a-6dca1444f089`, worktree
`C:/Users/utopi/.codex/worktrees/126c/agenteBolsa`. Auditoría terminada tras
reanudar el límite de uso; dictamen `needs_fix` de medición/consumo. Astra acepta
la separación de cohortes y el defecto de contrato entre productores/consumidores.
No acepta como gates económicos suficientes la sugerencia de subir caps al
10–15%, esperar 20 sesiones o umbrales fijos de 30 ejecuciones/70% de atribución:
no están sustentados por potencia estadística ni presupuesto de riesgo. Mandan
los gates OOS/cobertura/integridad del plan; sizing permanece sin cambios.

Cierre documental a las 22:34 Europe/Madrid: XNYS cerrado, siguiente sesión
23-sep. La evidencia económica conservada termina el 21-sep; no incorpora el
resultado de hoy. Validación N0: `git diff --check` verde y conciliación de las
35 filas del anexo con ambos retornos compuestos; sin espacios finales ni NUL.
No suite ni smoke, porque no cambia código. HEAD/tree Git sin cambios; árbol de
trabajo contiene únicamente estos tres documentos nuevos/modificados y los
archivos ajenos previamente identificados. Sin commit ni despliegue.

Archivos ajenos preservados: `.playwright-cli/`,
`docs/jetson_orin_acceso_y_migracion.md`, `p_l117_luna_retry_prompt.txt`.
Siguiente único encargo: P-L154-A. B–F planificados, no iniciados.

## Anexo: retornos auditados por intervalo

Fracciones, no porcentajes; permiten reproducir las composiciones anteriores.

| Inicio | Fin | Sistema | SPY |
| --- | --- | ---: | ---: |
| 2026-07-29 | 2026-07-30 | -0.000655317921211096 | -0.005297543767466162 |
| 2026-07-30 | 2026-07-31 | -0.00013202782557242276 | 0.011724813574502058 |
| 2026-07-31 | 2026-08-03 | 0.00015372221701159816 | 0.006392004652413741 |
| 2026-08-03 | 2026-08-04 | -9.122755026691465E-05 | 0.014931101384522805 |
| 2026-08-04 | 2026-08-05 | 0.0035071976462277554 | 0.02000973053803179 |
| 2026-08-05 | 2026-08-06 | -6.691717785134443E-05 | -0.007269380316248575 |
| 2026-08-10 | 2026-08-11 | 0.0008506097707321469 | 0.002498188212575858 |
| 2026-08-11 | 2026-08-12 | -0.000699657887041516 | 0.0002323361245555322 |
| 2026-08-12 | 2026-08-13 | -0.001943615802955878 | 0.00020655324623586324 |
| 2026-08-13 | 2026-08-14 | -0.0005962845363449709 | 0.004736216921268355 |
| 2026-08-14 | 2026-08-17 | -0.0003628524048312487 | -0.003031291964784688 |
| 2026-08-17 | 2026-08-18 | -0.000895851589895913 | -0.009636902734386554 |
| 2026-08-18 | 2026-08-19 | -0.0003018133455910954 | 0.002159402394110055 |
| 2026-08-19 | 2026-08-20 | -2.1119138588487907E-05 | -0.005711502301547378 |
| 2026-08-20 | 2026-08-21 | -0.00020510093247927408 | 0.00011742464677388931 |
| 2026-08-21 | 2026-08-24 | 0.00011029803720519205 | -0.0016578262067199478 |
| 2026-08-24 | 2026-08-25 | -0.0003576494309787126 | 0.0018043690918312372 |
| 2026-08-25 | 2026-08-26 | -0.0003193478723589882 | -0.0018664492594758775 |
| 2026-08-26 | 2026-08-27 | 5.404547394682879E-05 | 0.004929928610410084 |
| 2026-08-27 | 2026-08-28 | 0.0012398581560284505 | 0.004242040936983438 |
| 2026-08-28 | 2026-08-31 | -0.0005563315044425643 | -0.0057401440105234736 |
| 2026-08-31 | 2026-09-01 | -0.00071993393447356 | -0.006933131291915973 |
| 2026-09-01 | 2026-09-02 | -0.0016437497295997971 | 0.0005774371450439908 |
| 2026-09-02 | 2026-09-03 | 0.002882718988392874 | 0.00714803162651334 |
| 2026-09-03 | 2026-09-04 | -0.0018521100141730695 | 0.005352245094289776 |
| 2026-09-04 | 2026-09-08 | -0.00025080325882420595 | -0.0038082970489780044 |
| 2026-09-08 | 2026-09-09 | -0.0007375493994830062 | -0.00648830186337912 |
| 2026-09-09 | 2026-09-10 | 0.0002510513396436487 | -0.00791804036703636 |
| 2026-09-10 | 2026-09-11 | -0.0022107426981855527 | 0.008825444557740036 |
| 2026-09-11 | 2026-09-14 | 0.0014510426495217832 | -0.007479855061475527 |
| 2026-09-14 | 2026-09-15 | -0.0010639965872505375 | 0.0014756485316762546 |
| 2026-09-15 | 2026-09-16 | 0.00026795451802907877 | -0.0008156179452648571 |
| 2026-09-16 | 2026-09-17 | 7.995225626844515E-05 | 0.004805824508427259 |
| 2026-09-17 | 2026-09-18 | 5.035735943637043E-05 | 6.609134761337288E-05 |
| 2026-09-18 | 2026-09-21 | -0.0010883185201484569 | 0.0064901012987497175 |
