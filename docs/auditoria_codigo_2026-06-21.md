# Auditoría de código — agenteBolsa (21-jun-2026)

Objetivo: estado de salud del **código** (bugs, ineficiencias, deuda técnica),
no de la lógica de negocio. Método: análisis estático sobre `src/` (62.057 LOC,
112 módulos) + `tests/` (83 ficheros, 690 tests). Veredicto y backlog priorizado.

## Veredicto

**El código está fino en los fundamentos, pero arrastra deuda estructural.** No es
frágil ni chapucero: faltan los anti-patrones típicos y hay una suite de pruebas
grande. El riesgo real no es "bugs sueltos" sino **mantenibilidad** (ficheros
gigantes) y **observabilidad de fallos** (errores que se tragan en silencio — la
misma clase que ocultó la caída de LLM 10 días).

### Lo que está BIEN (base sólida)
- 0 `except:` desnudos, 0 `== None`, 0 `datetime.utcnow()` (deprecado), 0 `eval/exec`, 0 argumentos mutables por defecto.
- Las 7 llamadas de red tienen **timeout** explícito (sin riesgo de cuelgue).
- SQLite con **WAL + busy_timeout=30s** (concurrencia correcta scheduler/lectores).
- **690 tests**, solo 1 skip/xfail. Higiene reciente activa (pin de `jiter`, fix del bug de `Settings(DATA_DIR=...)`, fix de reconciliación por símbolo).
- `print` casi todo en `main.py` (CLI, legítimo); solo ~12 en librería.

## Deuda priorizada

### 🔴 D1 — God-files (mantenibilidad). Prioridad alta, esfuerzo alto.
| Fichero | LOC | nº funciones |
|---|---|---|
| `web_app.py` | 8.358 | 216 |
| `storage.py` | 4.479 | 137 |
| `tools/trade_decision.py` | 4.469 | 85 |
| `main.py` | 3.981 | 98 |
| `scheduler.py` | 2.987 | 59 |
| `tools/pre_earnings.py` | 2.814 | — |

Problema: difíciles de revisar, testear y editar con seguridad (de hecho ya
sufrimos corrupción al editar `scheduler.py` por su tamaño). Riesgo de regresión
alto y revisión humana inviable de un vistazo.
**Acción**: trocear por dominios, incremental y con tests por delante:
- `web_app.py` → un paquete `web/` con una página por módulo (scoreboard, strategy lab, estado, etc.) y helpers compartidos.
- `trade_decision.py` → separar selección de candidatos, gates (entry/backtest), y construcción de planes.
- `storage.py` → dividir el "god-class" `Store` por dominios (signals, broker, learning, CI) con mixins o repos.
- `main.py` → mover cada subcomando CLI a su módulo.
No hay que hacerlo de golpe: empezar por el más tocado (`trade_decision`) cuando haya un cambio funcional que lo justifique.

### 🟠 D2 — Observabilidad de fallos (la deuda que más nos ha costado). Media/baja.
- **190** `except Exception` y **27** que terminan en `pass` silencioso. Muchos son intencionados ("X nunca debe romper Y"), pero un `pass` sin siquiera un log deja invisibles fallos reales (fue lo que enmascaró la caída del LLM y el de sentimiento).
**Acción**: que todo swallow registre al menos un `logger.debug/warning` (o incremente un contador de degradación). Patrón único `except Exception as exc: log_and_continue(...)`. Barato y de altísimo retorno en diagnóstico.

### 🟠 D3 — Duplicación de helpers (DRY). Media, esfuerzo bajo.
- `_float()` reimplementado en **9 ficheros**; `_parse_iso()` en 3; `table_exists()`/`_f()` en 2; `human()` (bytes) y patrón `connect_ro` repetidos.
**Acción**: un módulo `tools/_utils.py` (coerción numérica, fechas ISO, formato bytes, helpers sqlite RO) e importar desde ahí. Reduce ruido y divergencias sutiles.

### 🟡 D4 — Arquitectura de persistencia. Media, esfuerzo medio.
- `Store.connect()` abre **una conexión nueva por método (115 sitios)** y hace `mkdir(parents=True)` en cada `connect()`. Con WAL funciona, pero es overhead innecesario.
- Columnas JSON con **87 `json.loads`**: flexible, pero es la causa del inflado a ~7 GB y del coste de (de)serialización por fila.
**Acción**: (a) reutilizar conexión / quitar el `mkdir` del camino caliente (hacerlo una vez en `__init__`); (b) para las tablas más voluminosas (`signal_outcomes`), valorar columnas tipadas para los campos consultados en caliente, dejando JSON solo para el payload accesorio.

### 🟡 D5 — Scripts acoplados a imports pesados. Baja.
- 8 scripts de `scripts/` ahora importan `agente_bolsa.config`/`crewai` a nivel módulo (p.ej. `weekly_improvement_report.py`), perdiendo la propiedad de "ejecutable ligero" que tenían algunos. No es un bug, pero los hace dependientes del venv completo y más lentos de arrancar.
**Acción**: imports diferidos dentro de `main()` donde sea razonable.

### 🟢 D6 — Limpieza menor. Baja.
- 14 `TODO/FIXME/HACK`: revisarlos y convertir en issues o resolver.
- ~12 `print` en módulos de librería (`eventing.py`, `continuous_improvement/*`): pasar a `logging`.
- Ficheros temporales y artefactos en raíz del repo (`tmp_*`, `comecocos.html`, `pacman.html`, `snake.html`) sin relación con el proyecto: mover/eliminar para reducir ruido.

## Cómo medirlo en adelante
- Integrar **ruff** en CI (ya es dependencia) con reglas: complejidad (C901), líneas por fichero, BLE001 (broad except) como warning, e imports sin usar. Hoy no hay constancia de que se ejecute en CI.
- Umbral de tamaño de fichero/función como guía (no bloqueante) para frenar el crecimiento de los god-files.

## Resumen en una frase
Cimientos correctos y bien testeados; la mejora de "código fino" pasa por (1)
trocear los 4-5 ficheros gigantes, (2) que los errores dejen de tragarse en
silencio, y (3) eliminar la duplicación de helpers — por ese orden de impacto.

## Ejecución del bloque seguro (1=D2, 2=D3, 3=ruff CI) — 21-jun

Hecho por Claude (cimientos verificados, sin tocar módulos existentes → riesgo nulo):
- **`src/agente_bolsa/_utils.py`** (NUEVO): helpers compartidos `to_float`, `parse_iso`,
  `utc_now`, `human_bytes`, `sqlite_connect_ro`, `table_exists` (D3) + **`log_swallow`**
  para que los `except` dejen rastro en vez de tragar en silencio (D2).
- **`tests/test_utils.py`** (NUEVO): 5 tests (4 verificados en sandbox; el de logging
  pasa con el `caplog` real de pytest).

Corrección a la auditoría: **ruff YA está en CI** (`.github/workflows/ci.yml` corre
`ruff check src tests` + pytest). El gap era endurecer reglas en `[tool.ruff.lint]`.

### COMPLETADO por Codex (3 commits, `694 passed`, ruff `All checks passed`):
- **`970fe62` D3**: 12 helpers duplicados + 3 conexiones RO eliminados (15 duplicados
  centralizados en `agente_bolsa._utils`). Se conservaron firmas con semántica especial
  (`_float(..., precision)`, `_float(default=0)`) fuera del bloque a propósito.
- **`ac3cae8` D2**: los 27 `except Exception: pass` silenciosos ahora registran contexto
  con `log_swallow(...)`. AST confirma **0 swallows silenciosos** en `src/` (el único
  `Exception: pass` restante es la red de seguridad interna del propio `log_swallow`).
- **`fc318c4` ruff**: `[tool.ruff.lint]` con `select = E,F,I,UP,B`; 213 fixes seguros
  automáticos + 19 correcciones explícitas. `BLE001`, `C901`, `E501` (2.923 líneas
  largas heredadas) y el `E402` intencional de `web_app.py` quedan **documentados como
  deuda no bloqueante** (ignore con TODO), reglas activas para código nuevo.
- Versión `0.4.21`. Rama local +3 commits, **sin push** todavía.

### Estado D5 y D4-deep (Codex, subidos a `codex/mejora_continua`):
- **D5** (`c16c687`): imports diferidos en los 10 scripts; `runpy` confirma 0 módulos
  `agente_bolsa` cargados al importar. Arranque ligero recuperado.
- **D4-deep** (`aa7ec82`): conexión lectora reutilizable + índice de lectura reciente
  en `signal_outcomes`. **Lectura 5.000 señales 4.029 ms → 17,1 ms; lecturas puntuales
  14,4×; índice +15,27 MB.** Migración a columnas tipadas **descartada con datos** (solo
  ~1,6% de ahorro de disco y obligaba a tocar todos los escritores → riesgo > beneficio).
  `699 passed`, ruff verde. Codex detectó y revivió el scheduler (329 min sin latido).
- Rama `codex/mejora_continua` **pusheada** (+8 commits).

Siguientes puntos (pendientes, sin prisa): D1 (trocear el resto de god-files —
`trade_decision.py`, `storage.py`, `main.py`, `scheduler.py`— incremental y con tests),
y la decisión de negocio del viernes (activar horizonte de salida 5-10d cuando n≥20).

## HALLAZGO ESTRATÉGICO (20-jun): el universo apunta al setup equivocado

Origen: 0 compras en toda la semana. El embudo colapsa en el **backtest gate**, pero
NO porque el gate esté mal. Dos estudios nuevos (`scripts/study_setup_edge.py`,
`scripts/study_near_miss_shadow.py`, solo lectura) lo prueban con n enorme:

**Edge por setup (return_5d, n≈212k-248k):**
- `sin_patron|mixed`  → mean +0.77%/+1.43%, hit 63-66%, PF 2.0-2.9  (n≈850-980)
- `sin_patron|strong` → mean +0.14%/+0.35%, hit 51-54%, PF 1.07-1.19 (n≈26-30k) — **edge positivo y muestra grande**
- `confirmed_pattern|strong` → mean −0.08%/−0.23%, PF 0.90-0.96 — **edge NEGATIVO y DOMINA el universo (n≈163-192k)**
- `confirmed_pattern|mixed/watchlist`, `sin_patron|watchlist` → todos negativos

**Conclusión:** el sistema genera y prioriza masivamente `confirmed_pattern` (edge
negativo) y la entry-quality **exige `confirmed_bullish_patterns>=1`** → el filtro
selecciona perdedores. El edge real está en **"sin patrón confirmado" con calidad
strong/mixed**.

**Decisión gate A/B = B (confirmada con datos):** los 33 candidatos bloqueados *solo*
por estabilidad de régimen tienen edge negativo (ret_3d −1.26%, hit 21%, PF 0.20).
El backtest gate ACIERTA → **NO abrir la micro-válvula**. El problema es el MIX de setups.

**Telemetría:** `market_regime` no se está poblando en `features_json` (cobertura 0 en
248k filas) → no podemos segmentar edge por régimen. Bug a corregir (alimenta decisiones).

**Plan (con flag default-OFF + shadow medido; nunca live a ciegas):** reorientar la
priorización de candidatos hacia `sin_patron|strong/mixed` y dejar de exigir
`confirmed_pattern` como requisito duro de entrada. Medir en shadow antes de promover.

**VALIDACIÓN OUT-OF-SAMPLE (walk-forward, `shadow_setup_edge_reweight.py`):**
TRAIN<2026-06-01<=TEST. En TEST (return_5d): política "setups-buenos" **+0.32%, hit
58.1%, PF 1.19 (n=11.588)** vs sesgo actual confirmed **−0.25%, PF 0.89 (n=79.446)**.
El signo persiste train→test en muestras grandes (`sin_patron|strong` +0.0038→+0.0031
n=11k; `confirmed_pattern|strong` −0.0020→−0.0028 n=70k) → **no es sobreajuste**. La
reorientación está justificada. Cambio de signo real (de PF 0.89 a 1.19); edge absoluto
modesto (encogerá con costes).

**M1 (21-jun): separación shadow vs activación.** El cableado original hacía que
`SETUP_EDGE_BIAS_ENABLED=true` cambiara la selección REAL del fallback (= activar, no
medir). Añadido `SETUP_EDGE_BIAS_SHADOW_ENABLED` (default OFF): mide y escribe
`latest_setup_edge_shadow.json` **sin tocar la selección real**. Disciplina shadow→active:
1) `SHADOW_ENABLED=true` varias sesiones (conducta intacta), 2) revisar el shadow report,
3) si confirma, `SETUP_EDGE_BIAS_ENABLED=true` (activa). Nota: el sesgo solo afecta al
**fallback determinista** (LLM caído/degradado), no al camino LLM. Edits en `.env`
re-disparan el sello del kernel → re-sellar tras cada toggle. (v0.4.31)

**Cableado seguro hecho (default-OFF, retrocompatible):** `opportunity_ranker.prioritize_candidates`
acepta `edge_table` opcional y aplica `setup_edge_bias` (neutral sin tabla). Tests en
`tests/test_setup_edge.py`. Pendiente (entorno con pytest): en el call-site del fallback,
calcular `edge_table` desde la BD (walk-forward) y pasarla solo si `SETUP_EDGE_BIAS_ENABLED`;
medir en shadow; relajar el requisito duro de `confirmed_pattern` en entry-quality;
poblar `features.market_regime`.

## D1-web — Simplificación del panel (22-jun)

Decisión (Antonio): enfocar la plataforma en "el grupo de agentes aprendiendo y
mejorando". Las páginas no son lógica: son **ventanas** sobre datos que produce el
bucle. Verificado que el motor (breakout, pre-earnings, opportunity_ranker,
operational_learning, etc.) lo usan 7-28 ficheros del core → **el motor se queda**;
solo se recortan vistas. Ningún test referencia las páginas quitadas.

Menú reducido de **21 → 10** páginas (hecho por Claude, edición segura de las listas
`page_names`/`pages` en `web_app.py`):

SE QUEDAN (10): Dashboard, Cartera, Compras/Ventas, Decisiones, Aprendizaje,
Mejora continua, Adaptativo, LLM, Estado del sistema, Configuracion.

SE QUITAN del menú (11 vistas; lógica de fondo intacta): Oportunidades, Estudios,
Rupturas, Pre-earnings, Historico, Senales, Diario aprendizaje, Aprendizaje operativo,
Backtest, Logs, Comandos.

Estado commits (Codex): `4abbffd` D6 artefactos eliminados (eran ignorados/no
trackeados → commit registra versión `0.4.22`); `abadd17` D4 mkdir perezoso + test de
regresión (`0.4.23`, `695 passed`, ruff verde). Rama local +5, sin push.

COMPLETADO por Codex (`960d44c`, v`0.4.24`): cierre transitivo por AST de helpers
huérfanos → 11 páginas + 31 helpers eliminados; **`web_app.py` 8.391 → 6.308 LOC
(-2.083)**. 14 helpers conservados porque los importa `test_web_app.py` (regla de
exclusividad respetada). `page_llm` intacta. Panel reiniciado, HTTP 200, `695 passed`,
ruff verde. El motor (jobs/tools/aprendizaje) sin tocar.
