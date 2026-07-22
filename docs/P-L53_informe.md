# P-L53B-T — ledger canónico predecisión y matching same-cycle

## Dictamen

`ready_for_p53b_implementation`.

La caracterización cierra el contrato de identidad, estados, matching y madurez
sin conectar ninguna ruta productiva. La causa del bloqueo de P-L53A queda
reproducida: `selected_for_llm` no representa una orden, el control puede mezclar
universos y el matching válido exige una frontera predecisión común que hoy no se
conserva de forma completa. El siguiente lote puede implementar el contrato en
shadow, pero no debe cambiar la política de selección.

## Alcance y estado

- Fecha de ejecución: 22-jul-2026, XNYS cerrado.
- Base: `24537e813ff0905696cda0b3925a212045ee7b09`.
- Producción observada: versión `0.4.185`, tree
  `4747f27f3d5dc152410203bf089baee500440897`; suciedad conocida preservada.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl53b_selection_ledger_tests`.
- Rama: `codex/pl53b-selection-ledger-tests`.
- Versión final del worktree: `0.4.186`. El bump fue exigido por
  `tests/test_version_policy.py` al añadir el test; es un candidato de
  caracterización, no una versión desplegada ni una reserva funcional de
  producción.
- Solo se modifican tests, este informe y el marcador de versión
  `src/agente_bolsa/__init__.py`, obligado por `test_version_policy`; no se toca
  código productivo, configuración ni SQLite operativa.

## Contrato caracterizado

Schema: `p-l53b.canonical-selection-ledger.v1`.

Una fila representa un candidato predecisión dentro de un ciclo. La identidad
primaria es `(cycle_id, action, signal_capture_id)` y usa `signal_id` solo como
fallback canónico. `candidate_id` es auxiliar y nunca autoridad.

| Dominio | Campos obligatorios o explícitos | Regla |
|---|---|---|
| Identidad | `cycle_id`, `signal_capture_id`/`signal_id`, `action` | BUY y EXIT separados; símbolo/fecha no son fallback |
| Decisión | `recommendation_id`, `plan_id`, `broker_order_id` | Se conservan separados y pueden ser `null` |
| Contexto | sesión, timestamps UTC, strategy/setup | Timestamp naive, invertido o futuro queda `unavailable` |
| Scores | `score`, `selection_score`, `learning_prior` | No se mezclan dominios ni etapas |
| Ranks | `score_rank`, `selection_rank`, dirección | Descendente; rango 1 es mejor solo dentro de su universo |
| Frontera | calidad, freshness, `eligible_at_selection`, `gate_frontier` | Matching solo en la misma frontera predecisión |
| Selección | `selected_for_llm`, `llm_considered`, `llm_selected`, `decision_source` | Son campos independientes; `selected_for_llm` no es orden |
| Etapas | recommended/planned/ordered/exclusion | Estados distintos; una recomendación no implica plan u orden |
| Integridad | schema/revision/event ID/hash/`captured_at` | Hash estable; `captured_at` fuera del hash |

Los estados conservan la diferencia entre `eligible`, `ineligible`,
`identity_unavailable`, `identity_ambiguous`, `shadow_inputs_unavailable`,
`selected`, `not_selected`, `recommended`, `not_recommended`, `gated_out`,
`planned`, `ordered`, `rejected`, `not_generated` y `unavailable`. La ausencia no
se convierte en `false` ni en cero.

Las fuentes se normalizan a `llm`, `deterministic_capacity_fill`, `fallback`,
`hold_override`, `deterministic` u `other`. `llm_considered=True` puede coexistir
con `decision_source=deterministic_capacity_fill` y `llm_selected=False`.

## Matching predecisión

Un control solo es válido si cumple simultáneamente:

1. mismo `cycle_id` y `session_date`;
2. acción `buy`;
3. misma strategy y setup;
4. ambos elegibles en la misma `gate_frontier`;
5. misma calidad de datos y bucket de freshness;
6. timestamps predecisión válidos y compatibles;
7. identidad canónica exacta;
8. control explícitamente `selected_for_llm=False` y no marcado como
   recommended postdecisión.

El matcher registra el primer motivo de exclusión: `cycle_mismatch`,
`action_mismatch`, `strategy_setup_mismatch`, `ineligible_at_frontier`,
`data_quality_mismatch_or_unavailable`, `freshness_mismatch_or_unavailable`,
`predecision_timestamp_incompatible`, `identity_unavailable` o
`postdecision_recommended_not_control`. No lee texto libre ni une por
`source_run_id + symbol`.

La fixture produce controles válidos dentro del mismo ciclo y excluye una
recomendación no ordenada por `entry_quality_gate` o `cycle_capacity_limit` como
control de selección. Una posición recommended-not-ordered puede ser una
observación de etapa, pero no se presume alternativa elegible comparable.

## Madurez de outcomes

El ledger no contiene retornos, fills, P/L, MFE, MAE, first-hit ni otros campos
futuros. El helper de test une outcomes después y solo por `signal_id`,
`cycle_id` y `action`, exigiendo:

- sesión XNYS de madurez estrictamente posterior;
- `matured=True` y número suficiente de sesiones completadas;
- `price_basis` igual y declarado;
- horizonte entre `3d`, `5d` y `10d`.

Una ausencia permanece `unavailable`; un forward return bruto no es beneficio
neto y no incorpora costes.

## Fixtures y denominadores

| Caso | Resultado caracterizado |
|---|---|
| Ciclo grande | 443 candidatos, 20 finalistas, 5 recomendaciones, 3 planes, 2 órdenes |
| Fuentes | LLM, deterministic capacity fill y fallback separados |
| Selección | `selected_for_llm=True` sin recomendación/plan/orden |
| Control | Alternativas same-cycle elegibles y exclusiones por frontera |
| Rank | Rango 1 repetido en dos universos score distintos; no se compara entre ellos |
| Identidad | Mismo símbolo en ciclos distintos; BUY y EXIT con la misma señal quedan separados |
| Colisión | Mismo `source_run_id + symbol` no sustituye la identidad exacta |
| Reporter | Fila genérica sin IDs queda `identity_unavailable` |
| Duplicado | Mismo contenido es idempotente; contenido distinto es conflicto |
| Truncación | `truncated_count` se publica; la muestra no se presenta como universo completo |
| Madurez | 3d maduro; 5d y 10d `unavailable`/inmaduros |
| Calidad temporal | Timestamps naive, invertidos, futuros y price basis ausente degradan a unavailable |

La fixture de 443 filas devuelve `raw_count=443`, `canonical_count=443`,
`eligible_count=443`, `selected_count=20`, `recommended_count=5`,
`planned_count=3`, `ordered_count=2`, sin conflictos ni duplicados. Una segunda
prueba simula el límite `200000` con `truncated_count=199557`; no lo interpreta
como 200.000 señales únicas.

## Persistencia caracterizada en test

El archivo de pruebas usa una SQLite temporal independiente con una tabla de
fixture no productiva. La operación es:

- preparar y hashear fuera de la transacción;
- `BEGIN IMMEDIATE` solo para la inserción;
- mismo event ID y hash: `idempotent`;
- mismo event ID y hash distinto: `conflict`, conservando el original;
- ningún `INSERT OR REPLACE`;
- dos escritores concurrentes: `inserted + idempotent`, sin
  `database is locked`;
- `captured_at` no altera el hash y el orden JSON tampoco.

No se crean tablas, migraciones, wiring, eventos operativos ni backfill en este
lote.

## Seguridad y paridad

Los tests comprueban que el helper no muta candidatos ni altera scores, ranks,
gates, sizing, planes, cantidades, precios, stops, takes, órdenes, exposición o
límites. No hay código funcional nuevo en `src/agente_bolsa/`; solo se actualiza
`__version__` por el gate. No se modifican `kernel.py`, `broker.py`,
`execution.py`, `risk.py`, `config.py` ni `.env`.

## Validación

Ejecutado en el worktree con `PYTHONPATH` apuntando a su `src` y sin acceder a
SQLite productiva:

- `tests/test_p53b_selection_ledger_characterization.py`: 15 passed.
- Ruff focal del nuevo test: verde.
- `check_no_nulls.py`, `git diff --check` y el test de política de versión:
  verdes.
- Suite completa, smoke, jobs, postmarket, reconciliación, broker, red,
  yfinance y LLM: omitidos por alcance; no eran necesarios para esta
  caracterización aislada.

## Siguiente paso único

P-L53B-W: implementar el ledger en shadow en una frontera no protegida,
construirlo una vez por ciclo a partir de objetos predecisión ya existentes y
probar con outcomes maduros, sin activar selección, cambiar gates ni dar
autoridad al ledger sobre trading.

---

## P-L53B-W — implementación shadow

### Dictamen provisional

`ready_for_integration_rehearsal`.

La implementación queda limitada a telemetría shadow. La frontera lograda es la
proyección del universo completo entregado por el ranking en fase A y de los
objetos ya producidos por recomendaciones, gates, planes y envíos en fase B.
No se recalculan ranking, aprendizaje, LLM, gates, RiskManager, controles,
planes ni órdenes.

### Referencias

- Fecha de trabajo: 22-jul-2026; `schedule-status` verificó XNYS cerrado y
  siguiente apertura a las 15:30 CEST.
- Base exacta: `4ec81a0c3740f4ca9d4c71601910357d7ef59904`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl53b_selection_ledger_impl`.
- Rama: `codex/pl53b-selection-ledger-impl`.
- Versión candidata: `0.4.191`.
- Commits feature/test/docs/QA: `e5ace319`, `eea3794a`, `e07601bb` y
  `731002ec`.
- Producción no modificada: HEAD
  `24537e813ff0905696cda0b3925a212045ee7b09`, versión `0.4.185`, con su
  suciedad conocida preservada.

### Contrato y persistencia

El evento canónico es `canonical_selection_ledger:<cycle_id>` con schema
`p-l53b.canonical-selection-ledger.v1`. La identidad es
`cycle_id + action + signal_capture_id`, con `signal_id` como fallback
explícito; `candidate_id` no es autoridad y `source_run_id + symbol` nunca se
usa para unir observaciones. BUY y EXIT permanecen separados.

El productor conserva `score`, `selection_score`, `learning_prior`, dominios y
dirección de rank, calidad/freshness predecisión, elegibilidad, frontera de
gate, `selected_for_llm`, `llm_considered`, `llm_selected`, fuente de decisión,
recommendation/plan/order y razones de exclusión. No serializa outcomes futuros,
fills, P/L, MFE/MAE ni slippage.

`agent_events` se reutiliza sin tablas, migraciones, backfill ni
`runtime_state` como historia. La preparación y el hash ocurren fuera de la
transacción; la inserción usa `BEGIN IMMEDIATE` corto, sin `INSERT OR REPLACE`.
Mismo ID y contenido es `idempotent`; contenido distinto conserva el evento
original y añade un conflicto separado. `captured_at` queda fuera del hash y
el lector devuelve `collecting` con denominadores nulos cuando no existe
evento. Los lectores no reconstruyen filas.

### Captura y fail-open

`scheduler.market_cycle_job` transfiere el contexto completo de fase A fuera de
`technical_context`, por lo que el prompt activo no cambia. `cycle_runner`
captura una vez tras la ruta activa; en bloqueos o fallos de decisión captura
la fase disponible y degrada a `unavailable`. Un fallo de build, serialización,
persistencia o lectura solo emite un warning durable cuando es posible y no
bloquea, retrasa ni cambia trading.

El lector de matching same-cycle exige BUY, mismo ciclo/sesión,
strategy/setup, frontera, calidad/freshness y timestamps predecisión
compatibles; una recomendación bloqueada no se convierte en control. El helper
de madurez une 3d/5d/10d solo por identidad canónica, sesiones XNYS
completadas y `price_basis`; el `forward_return` queda explícitamente separado
de beneficio neto.

### Denominadores y QA

La fixture adversarial de ciclo grande conserva 443 candidatos y 20
seleccionados, con 5 recomendaciones, 3 planes y 2 órdenes. También cubre
BUY/EXIT, recompras semánticas por ciclo, selected-for-LLM sin orden,
deterministic capacity fill, controles excluidos, IDs ausentes/ambiguos,
duplicados/conflictos, cap/truncación 199.557, timestamps inválidos,
madurez 3d y 5d/10d inmaduros.

La batería productiva P-L53B-W más la caracterización P-L53B-T ejecutó
`28 passed` en focales (15 P-L53B-T + 13 P-L53B-W). Incluye persistencia concurrente `inserted +
idempotent`, conflicto con original intacto, lector `collecting`, fail-open,
no mutación, wiring del ciclo con una única captura y paridad del contexto
prompt. La caracterización temporal de 100 ciclos × 500 candidatos pasó en
78.551 s, con pico Python de 8,374,632 bytes, evento estable de 711,358 bytes,
WAL temporal de 0 bytes al cierre y 0 errores de lock. El resultado es
descriptivo, no un umbral de promoción.

Ruff completo, `check_no_nulls.py`, `git diff --check`, la política de versión
y `validate-agent-config --json` quedaron verdes en el worktree. La suite
segura final ejecutó `1719 passed, 1 deselected` en 689.80 s; el único caso
deseleccionado es una regresión preexistente que apunta a una ruta SQLite fija
de historial productivo. El consumidor CLI con DATA_DIR vacío devuelve ahora
`collecting` y denominadores nulos. Smoke operativo, broker, red, LLM,
postmarket y reconciliación productivos no se ejecutaron. La validación
completa cerrada y el ensayo integrado P-L53BR1 siguen pendientes.

### Seguridad

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. P-L53B no aparece como autoridad de
`trade_decision`, gates, sizing, planes u órdenes. No hubo despliegue,
reinicio, acceso a SQLite productiva ni push.

### Siguiente paso único

Ensayo integrado aislado P-L53BR1 desde este candidato, con XNYS cerrado y
precondiciones completas verificadas, antes de cualquier promoción.

---

## P-L53BR1 — ensayo integrado sobre P-L52BR1 (22-jul-2026)

### Dictamen

`needs_fix` para el candidato integrado. La integración P-L53B-W es
funcionalmente compatible y la QA propia queda verde, pero la suite canónica
completa todavía contiene tres fallos heredados de P-L51/P-L51C que se
reproducen sin cambios en el padre P-L52BR1. No se atribuyen al merge P-L53 y
no se corrigen en este lote.

### Referencias y Git

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl53br1_integration_rehearsal`.
- Rama: `codex/pl53br1-integration-rehearsal`.
- Base exacta: `134ec525f10ce96d571071b8eea497fcc5ce16be`,
  árbol `42ba58b6f4cb7407273191bbc4b2a9febd323378`, versión `0.4.190`.
- Merge requerido: `fc4eb767`, `merge: integrate P-L53B-W into P-L52BR1`.
- QA integrada: `52668b42`, `qa: verify P-L53BR1 integrated shadow parity`.
- Versión final: `0.4.191`. El árbol queda limpio después del commit
  documental de este informe.
- P-L53B-W de origen: `0e07c1c9`, árbol
  `92d752243fa64b10e4fb9e17f08b5960a7374507`; producción y el worktree de
  origen no se modificaron.

Los conflictos del merge se resolvieron campo a campo en `__init__.py`,
`cycle_runner.py`, `storage.py`, plan y relevo: se conservaron las fases P-L49,
P-L50/P-L44, P-L51 y P-L52, y se añadieron las proyecciones P-L53 sin reemplazo
global. `main.py` y `scheduler.py` se fusionaron automáticamente y fueron
revisados; no se usó squash, rebase, cherry-pick ni amend.

### Orden real e interacción

La ruta de mercado comprobada es:

`market data/observaciones → market_state → P-L49 Fase A → aprendizaje y
ranking → P-L50/P-L44 Fase A → P-L53 Fase A → selección/recomendaciones →
gates/límites/cuotas/pausas → controles/planes → P-L49/P-L50 Fase B →
persistencia/envío activo → P-L53 finalización y persistencia`.

La Fase A recibe el mismo `ranked_context` en memoria producido por el ranking;
no recalcula ranking, aprendizaje, LLM, gates, RiskManager, controles, planes ni
órdenes. La finalización P-L53 se ejecuta después del envío activo cuando el
objeto exacto de envío existe; si no existe una identidad de orden exacta,
`ordered/broker_order_id` permanece `null/unavailable`.

El PMR no fue alterado por P-L53. Su orden validado en P-L52BR1 permanece:
`reconciliation → outcome_update → daily_learning → postmarket_report →
P-L48 canonical_operation_telemetry → P-L51 canonical_trade_attribution →
P-L52 canonical_eod_account_snapshot → performance → measurement → thesis →
terminal`. P-L53 no entra en ese pipeline.

Las identidades siguen separadas: P-L49 usa observación/proveedor/intervalo/barra
exacta; P-L50 usa `signal_capture_id → signal_id` más `action/recommendation_id`;
P-L53 usa `cycle_id + action + signal_capture_id` y solo el fallback `signal_id`;
P-L51 usa `broker_order_id` y provenance de lotes; P-L52 usa sesión/equity/
contribuciones. No hay unión por símbolo, fecha, texto ni
`source_run_id + symbol`; BUY y EXIT permanecen separadas.

### QA adversarial y denominadores

La prueba combinada temporal cubrió 500 observaciones/símbolos, 37 anomalías
P-L49, 443 candidatos P-L50/P-L53, 20 finalistas, 5 recomendaciones, 3 planes
y 2 órdenes. Los denominadores P-L53 fueron:

| Campo | Valor |
|---|---:|
| raw/canonical/eligible | 443 / 443 / 443 |
| selected/recommended/planned/ordered | 20 / 5 / 3 / 2 |
| identity unavailable/ambiguous | 0 / 0 |
| shadow inputs unavailable/conflicts | 0 / 0 |
| truncated | 0 |

Se verificó una atribución P-L51 exacta `attributed=1` y una contribución P-L52
por IDs exactos en la misma batería. Se comprobaron selected-for-LLM sin orden,
`deterministic_capacity_fill`, BUY/EXIT con la misma señal, controles
excluidos, cap/truncación explícita, estados `collecting`, conflictos separados
y madurez 3d disponible frente a 5d/10d inmadura. El evento predecisión no
contiene outcomes, fills, P/L, MAE/MFE, first-hit ni prompts LLM; un forward
return nunca se etiqueta como beneficio neto.

La persistencia concurrente de P-L49/P-L48/P-L53 produjo tres estados
`inserted` sin `database is locked`. La repetición idéntica fue idempotente y el
contenido P-L53 distinto produjo `conflict` conservando el original; el evento
P-L48 quedó intacto. Los event IDs y schemas de P-L49, P-L48, P-L51, P-L52 y
P-L53 no colisionaron. No hay tablas, migraciones, backfill, `INSERT OR
REPLACE`, runtime_state como historia ni conexión por candidato.

### Volumen y persistencia

En 100 ciclos sintéticos × 500 candidatos, la descomposición observada fue:

| Medida | p50 | p95 | máximo |
|---|---:|---:|---:|
| captura Fase A (ms) | 198,7762 | 207,9281 | 227,9587 |
| finalización (ms) | 16,0091 | 17,3014 | 25,8787 |
| construcción completa (ms) | 373,9511 | 406,0575 | 434,1302 |
| serialización (ms) | 59,1514 | 63,0870 | 78,9222 |
| `BEGIN IMMEDIATE` (ms) | 4,7631 | 17,7848 | 20,0429 |
| persistencia total (ms) | 67,8627 | 82,5894 | 86,6022 |
| tamaño evento (bytes) | 760154 | 760154 | 760154 |

Memoria pico: 12.029.144 bytes. WAL observado: 0 bytes al cierre. Hubo 100
transacciones y 100 conexiones, una por ciclo, no por candidato; los resultados
no muestran trabajo O(n²) ni copia del conjunto activo completo en la frontera
de persistencia. Como estimación descriptiva, 26 ciclos diarios equivaldrían a
19.764.004 bytes de payload y 100 ciclos a 76.015.400 bytes, sin presentarlo
como capacidad garantizada ni incluir overhead de SQLite.

### Validación exacta y gates

- QA integrada: `4 passed`; volumen incluido: `1 passed in 76,93 s`.
- Focales combinados antes de la suite: `295 passed, 3 failed`; los tres
  fallos se reprodujeron en el padre exacto P-L52BR1.
- P-L45B2 de 33.336 filas: `1 passed in 2,10 s`.
- Ruff completo: verde.
- `check_no_nulls.py`: `OK (421 archivos)`.
- `git diff --check`: verde.
- `validate-agent-config --json`: `ok=true`, sin errores ni warnings.
- `test_version_policy.py`: `1 passed` después del commit QA.
- Suite segura final: `1928 passed, 4 deselected, 1 warning in 780,95 s`.
- El warning fue la deprecación externa de `websockets.legacy`.

Las cuatro exclusiones de línea de comandos no son skips/xfails añadidos:

1. `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`,
   que abre literalmente `data/state/agente_bolsa.sqlite3`; se reprodujo por
   inspección estática en la base y producción, y no se ejecutó para proteger
   SQLite productiva.
2. `tests/test_p51br1_combined_integration.py::test_real_boundary_is_not_mistaken_for_synthetic_exact_capture`;
3. `tests/test_p52br1_integration.py::test_e2e_carrier_reconciliation_p48_p51_p52_keeps_exact_contribution_ids`;
4. `tests/test_p51c_provenance_carrier.py::test_selected_order_plan_metadata_survives_store_reconciliation_and_p48_projection`.

Los tres últimos fallaron en el ensayo y con el mismo resultado en el padre
P-L52BR1: respectivamente `buy_order_count=0`, estado de atribución
`unavailable` y ausencia de `sell-1` en la proyección P-L48. Quedan como deuda
heredada P-L51/P-L51C, no como regresión P-L53; no se modificaron en este lote.

Smoke operativo real, broker, red, LLM, jobs productivos, postmarket y
reconciliación manual quedaron omitidos por alcance y seguridad. No se ejecutó
`run-once`; un smoke totalmente aislado equivalente no aporta evidencia de
despliegue y queda pendiente de un lote cerrado autorizado.

### Seguridad y paridad

La QA confirma paridad byte/estructura de candidatos, scores, ranks, selección,
recomendaciones, gates, sizing, microexperimentos, controles, planes,
cantidades, precios, stops/takes/trailing, órdenes, broker requests, exposición,
límites y cadencia. P-L53 no aparece como autoridad en `trade_decision`, risk,
broker o execution y sus fallos son fail-open.

Los hashes Git de los protegidos coinciden con producción: `kernel.py`
`35788edf80cc02c015fdef24f7c62fe8a490a442`, `broker.py`
`2050468ca4d81f06bb58464a688eaf4d916f80e5`, `execution.py`
`018c52f0754bec4a1f8cf8440f308bc10b01a588`, `risk.py`
`75c1242c2f10c989120243ca1149e22749d342bb` y `config.py`
`912e943b24160b5e4b1fb4b1f60dbdf15f4c9e9f`. `.env` no se modificó. Producción,
P-L52BR1 base, P-L53B-W y los demás candidatos permanecieron intactos; no hubo
SQLite productiva, despliegue, reinicio ni push.

### Siguiente lote mínimo

Resolver y revalidar únicamente la deuda heredada de los tres focales P-L51/
P-L51C, manteniendo P-L53 en shadow; después repetir la suite cerrada completa
y el preflight operativo. No cambiar thresholds, ranking, gates, sizing ni
política de trading.
