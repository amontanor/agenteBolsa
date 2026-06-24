# Estudio: universo y selección de candidatos (24-jun-2026)

> Origen: el shadow de A2 (`latest_setup_edge_cycle_shadow.json`) mostró 24/24
> candidatos `confirmed_pattern|strong` (edge medido −0.15%) y **0 `sin_patron`**,
> mientras el edge positivo medido está en `sin_patron|mixed` (+0.49%),
> `confirmed_pattern|watchlist` (+0.21%) y `sin_patron|weak` (+0.19%). Pregunta:
> ¿es el universo demasiado estrecho? ¿por qué no surgen los setups con edge?

## 1. El universo NO es el cuello

- `default_universe` = solo 9 megacaps (`SPY,QQQ,AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA`).
  Es la propiedad `settings.universe`, pero **el `market_cycle` no la usa** como
  universo de escaneo (solo como `default_symbols` de fallback).
- El `market_cycle` (intradía) escanea con
  `intraday_technical_scan_universe = "sp500_plus_intraday_focus"` y
  `max_symbols = closed_market_study_max_symbols = 500`
  (`scheduler.py:1346-1361`).
- `resolve_study_universe("sp500_plus_intraday_focus", …)` (`tools/universe.py:278`)
  = **S&P 500 completo** (`load_sp500_symbols()`, baja la lista de Wikipedia/GitHub;
  fallback ~250 large caps) **+ overlays** de `latest_breakout_scan.json` y
  `latest_closed_market_technical_study.json`, recortado a 500.

**Conclusión:** el universo ya es ~500 (S&P 500). No está limitado a unos pocos.
La sensación de "estaba recortado" viene del `default_universe` (9), que es de otro
propósito. *(Mejora menor posible: subir `max_symbols` por encima de 500 o
asegurar que `load_sp500_symbols` no cae al fallback de 250 por fallo de red — pero
no es la causa del problema.)*

## 2. El cuello real: el RANKING por `score`, no la generación

- La generación de candidatos vive en estrategias plugables
  (`technical_study.py:66-91`, registro en `strategies/registry.py`). Solo
  `builtin_breakout` está ACTIVE.
- **Pero `builtin_breakout` NO filtra por patrón:** genera un candidato para
  **cada símbolo** del universo vía `validate_symbol_technical_state`
  (`strategies/builtin_breakout.py:58-74`). Es decir, `all_candidates` ≈ los ~500
  símbolos, **incluidos los `sin_patron`**, cada uno con su `setup_quality` y su
  clasificación patrón/sin-patrón.
- El recorte ocurre después: `top_longs = sorted(by score)[:15]`
  (`technical_study.py:97-101`) y luego la selección
  (`_selected_candidates` → `_selection_score_for_candidate`), cuyos perfiles
  premian momentum + patrón confirmado. **Los `sin_patron|mixed` (edge +) quedan
  por debajo del corte y nunca llegan a la decisión.**

**Conclusión:** no falta una estrategia ni universo; el `score`/selección está
sesgado hacia `confirmed_pattern|strong` (líderes de momentum extendido), que
resulta tener edge medido ligeramente **negativo**. El sistema "mira" todo el
S&P 500 pero solo "elige" el grupo equivocado.

## 3. Por qué el sesgo de A2 aún no lo arregla

- El sesgo `setup_edge` (que reordena hacia setups con edge positivo) **solo se
  aplica en dos sitios**: el fallback determinista (cuando cae el LLM) y la
  medición shadow por ciclo. **NO se aplica en el ranking del scan** que produce
  los finalistas.
- Además, el shadow por ciclo mide sobre los **24 finalistas ya seleccionados**
  (todos `confirmed_pattern|strong`), no sobre `all_candidates`. Por eso reordenar
  esos 24 no cambia nada (`changed:false`): no hay `sin_patron` entre ellos que
  promover.

## 4. Cómo mejorarlo (medido, sin tocar la conducta primero)

El objetivo: **que los setups con edge positivo medido (`sin_patron|mixed`, etc.)
suban a los finalistas**, aplicando el sesgo de edge **antes** del corte top-N,
sobre `all_candidates`. Disciplina: shadow → guarded → active.

- **Paso 1 (shadow, observabilidad).** Extender la medición del shadow para rankear
  `all_candidates` (los ~500, no solo los 24) con la `edge_table`, y reportar qué
  `sin_patron|mixed`/`|weak` **entrarían** en el top si se aplicara el sesgo, frente
  al baseline. Esto responde con datos: ¿cuántos hay, qué symbols, con qué edge?
  Sin tocar la selección real.
- **Paso 2 (guarded).** Si el shadow muestra que el sesgo subiría setups con edge
  positivo y muestra consistente varias sesiones, aplicar el sesgo en el ranking
  del scan **limitado** (p.ej. reservar K plazas del slate para el mejor
  `sin_patron|mixed`), midiendo forward returns netos de costes.
- **Paso 3 (active/promote).** Promover solo si el cohorte surfaceado mantiene
  expectativa positiva out-of-sample neta de costes; revertir si no.

### Cautelas honestas
- Los edges medidos son **pequeños y con muestra limitada** (±0.5% a 5 días).
  `sin_patron|mixed` +0.49% es prometedor pero modesto; `sin_patron|watchlist` es
  **−0.82%** (negativo). No todo "sin_patron" es bueno: el grupo con señal es
  `sin_patron|mixed` (y quizá `|weak`). Nada se promueve sin expectativa+ neta de
  costes.
- Riesgo de sobreajuste a 7 claves de edge: tratar como hipótesis a validar en
  walk-forward, no como verdad.

## 5. Estado
- Universo: estudiado → no es el cuello (es S&P 500 ~500). **HECHO.**
- Causa de 0 `sin_patron`: el ranking/selección por `score`, no la generación.
  **HECHO.**
- Diseño de mejora: shadow sobre `all_candidates` → guarded → active.
  **HECHO (Paso 1, v0.4.42).**

## 6. Resultado del Paso 1 (shadow sobre all_candidates) — REDIRECCIÓN

Primer dato real sobre los 343 candidatos del S&P 500:

| setup_quality_key | nº | % |
|---|---|---|
| confirmed_pattern\|strong | 298 | 87% |
| confirmed_pattern\|mixed | 39 | 11% |
| sin_patron\|mixed | 2 | 0.6% |
| sin_patron\|strong | 3 | 0.9% |
| confirmed_pattern\|watchlist | 1 | — |

**Dos conclusiones que cambian el rumbo:**

1. **El Paso 2 (promover `sin_patron|mixed`) NO está justificado.** En vivo son
   **2 nombres** en todo el S&P 500 (BA, J), con score 7 (vs 16-18 de los
   finalistas). El "+0.49%" de la `edge_table` está medido sobre un subconjunto
   minúsculo → ruido, no señal accionable. El shadow nos ahorró meter en producción
   una "ventaja" de 2 acciones. **Paso 2: DESCARTADO con evidencia.**

2. **La clasificación es degenerada.** El 87% cae en `confirmed_pattern|strong`. La
   causa está en `technical_state_validator.py:322-332`: `setup_quality="strong"`
   con **score ≥ 7** (umbral bajo), y `confirmed_pattern` si hay ≥1 patrón alcista
   confirmado. En mercado alcista casi todo acumula ≥7 puntos y un patrón → un solo
   cajón. La taxonomía `setup_quality` **no discrimina**, así que el `setup_edge`
   (que reordena por ella) tiene poco recorrido, y la `edge_table` histórica está
   medida sobre esa clasificación degenerada.

**Nueva dirección (medir antes de tocar):** el `score` (continuo, 6→18) SÍ varía.
Estudio `scripts/study_edge_by_score.py` (read-only sobre `signal_outcomes`): mide
el forward `return_5d` neto de costes por **bucket de score**, por `setup_quality`
y por **extensión `return_20d`** (hipótesis: los líderes más extendidos revierten a
corto). Output: `data/reports/edge_by_score_study.json`. Según el resultado:
- si el score alto bate al bajo → el ranking ya captura señal; el "0 trades" es
  defendible (mercado sin edge claro ahora);
- si el score alto es plano/negativo (reversión) → el problema es el scoring (compra
  extensión que revierte), y ahí está el trabajo real.

Tarea derivada anotada: revisar el clasificador degenerado (umbral `strong`=7 y el
detector de patrones que marca "confirmado" en casi todo).
