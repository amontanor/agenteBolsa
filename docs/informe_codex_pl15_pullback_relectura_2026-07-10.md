# P-L15 — Re-lectura del experimento pullback con datos maduros

Fecha de ejecución: 2026-07-10
Alcance: estudio read-only; no se modificaron lógica de trading, configuraciones ni `allowed_strategies`.

## Veredicto

**EXTENDER hasta 2026-07-20.** La muestra 5d ya es sustancial y desfavorable,
pero el criterio pre-registrado exige también 10d y hoy no hay ningún outcome 10d
maduro. No corresponde declarar una promoción; tampoco matar definitivamente la
hipótesis antes de poder contrastar el horizonte 10d que se fijó antes de ver estos
datos.

El dato que falta es: outcomes `return_10d` maduros de múltiples fechas de señal.
Además, la comprobación de concentración sectorial es inevaluable: 0 de 684 features
de `builtin_pullback` conserva `sector`. La extensión no convierte ese criterio en
evaluables; debe quedar explicitado en la siguiente lectura.

La agenda se actualizó por el cauce habitual a `pullback | pendiente | 2026-07-20`.

## Criterios pre-registrados recuperados

Fuente: `docs/prompts_codex_2026-07-02.md`, P3, redactado el 2-jul antes de la
lectura de outcomes. Promoción a ACTIVE solo si: expectancy neta a 5d **y** 10d
positiva después de 10 bps, excess frente a SPY positivo, `n >= 30` maduro y sin
dependencia de un único día o sector. No se alteraron los criterios.

## Ejecución reproducible

```powershell
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10 --benchmark SPY
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 20 --benchmark SPY
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --shadow-scoreboard --history 20 --json
```

Las 5.661 filas son observaciones deduplicadas por estrategia-símbolo-día. El
scoreboard reciente muestra cero `shadow_candidates` porque `builtin_pullback` ya
forma parte de `learning_experiment`; no se interpreta ese cero como ausencia de
candidatos históricos ni como un cambio de calidad.

## Cobertura y resultados

| estrategia | filas | 1d maduro | 3d maduro | 5d maduro | 10d maduro |
|---|---:|---:|---:|---:|---:|
| builtin_pullback | 684 | 600 | 448 | 295 | 0 |
| builtin_breakout | 4.977 | 4.480 | 3.484 | 2.488 | 0 |

| métrica neta de 10 bps | pullback 5d | breakout 5d | delta pullback − breakout |
|---|---:|---:|---:|
| retorno crudo | -1,25% | +0,59% | -1,84 pp |
| excess vs SPY | -2,42% | -0,61% | -1,80 pp |

Con el stress de 20 bps, el retorno crudo 5d neto de pullback es **-1,35%** y
el excess neto es **-2,52%**. No hay lectura 10d a ninguno de los dos costes.

### Tabla de decisión

| criterio pre-registrado | valor medido hoy | pasa |
|---|---|---|
| expectancy 5d neta de 10 bps positiva | -1,25% (`n=295`) | No |
| expectancy 10d neta de 10 bps positiva | `n=0` (684 pendientes) | No evaluable |
| excess vs SPY positivo a 5d | -2,42% neto (`n=295`) | No |
| excess vs SPY positivo a 10d | `n=0` | No evaluable |
| al menos 30 observaciones maduras | 5d: 295; 10d: 0 | No (el requisito abarca ambos horizontes) |
| sin dependencia de un único día | 5d procede de cinco fechas: 25-jun (53), 26-jun (57), 29-jun (58), 30-jun (63), 1-jul (64) | Sí a 5d; 10d no evaluable |
| sin dependencia de un único sector | `sector` persistido en 0/684 features | No evaluable |

En 5d, las medias por fecha de señal fueron -2,18%, -0,20%, -2,55%, -0,86% y
-0,17%, respectivamente. Por tanto, el mal resultado 5d no depende de una sola
fecha, aunque su concentración por sector no se puede medir. Los peores
contribuidores medios fueron CRWD (-71,28%, dos observaciones), TER (-21,07%) y
SNDK (-19,72%); los mejores fueron DDOG (+13,13%), TROW (+11,64%) e IFF (+8,59%).

## Implicación para `learning_experiment`

Recomendación al responsable: **suspender `builtin_pullback` de
`allowed_strategies` hasta la relectura del 20-jul**, no promoverlo ni ampliar su
cupo. Es una recomendación prudencial, no un cambio aplicado: el 5d ya incumple dos
criterios con 295 observaciones y el backtest previo tampoco mostró superioridad
robusta. Mantenerlo hoy como estrategia permitida añade exposición experimental pese
a evidencia actual negativa; el 10d pendiente decide si la hipótesis se mata de
forma definitiva.

## Estado operativo y límites

`data/config/learning_mode.json` sigue declarando `builtin_breakout` y
`builtin_pullback` en `allowed_strategies`; no se modificó. La configuración sigue
en paper y con aprobación humana para el experimento. No se tocaron archivos de
kernel, riesgo, broker, ejecución, configuración ni `.env`.

No se añadieron helpers ni código: no aplica ejecutar tests o lint para esta entrega
documental. No hay cambio de versión.
