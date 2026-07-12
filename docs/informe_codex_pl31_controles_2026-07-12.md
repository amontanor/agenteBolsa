# P-L31B — Captura prospectiva de controles contemporáneos comparables

Fecha: 2026-07-12
Versión entregada: 0.4.162
Punto de partida: 0.4.161 / `7803ffc8`
Modo: paper activo; live desactivado.

## Alcance y fuente única

P-L31B no interpreta resultados ni reabre P-L27D, P-L29B o P-L30B. La fuente
única es `src/agente_bolsa/tools/comparable_controls.py`, que construye y
valida `p-l31b.comparable-control.v1`. El bloque se embebe en la recomendación
y en el plan existente, y se copia de forma profunda; no se crea una tabla
nueva.

El `candidate_id` se calcula como `cand_<hash(cycle_id, signal_id,
source_run_id)>`, sin score, rank ni resultados posteriores. Si falta la
identidad exacta no se inventa un ID y el conjunto queda `unavailable`.

## Momento y contenido de captura

`cycle_runner._auto_paper_trade` captura después de las revisiones/gates
disponibles y del ranking en memoria, pero antes de `build_order_plans`, de la
persistencia de planes y de cualquier orden o fill. Se reutilizan los objetos
del ciclo y el `decision_context_snapshot` P-L30B; nunca se consulta un informe
“más reciente”. El horizonte queda fijado en `10d` y no se calculan retornos,
MFE/MAE, P&L ni fills.

Cada control conserva un ledger ordenado (deterministic, adversarial,
entry-quality, backtest, strategy-pause, geometry, risk-eligibility,
duplicate/already-held, low-sample y capacity). Los gates ausentes se marcan
`not_evaluated` y no permiten estado `verified`. Solo `lower_rank` y
`capacity_limit` entran en `controls`; `gate_blocked`, riesgo, pausa,
geometría inválida, duplicidad, posición existente, límite diario y low-sample
quedan fuera o en `blocked_candidates`.

## Propagación e idempotencia

El mismo `content_hash` se conserva en la recomendación, el plan anidado y las
features de `signal_outcomes`/`learning_observations` cuando existe un vínculo
exacto. Una señal con vínculo roto no recibe el bloque en sus features. Los
outcomes posteriores se resuelven en una vista derivada por `signal_id` exacto;
la captura original nunca se muta. Repetir el mismo bloque es `idempotent` y
un mismo `control_set_id` con contenido diferente se informa como `conflict`.

## Estado inicial y compatibilidad

Antes de la primera ejecución de P-L31B, el diagnóstico real devolvió:

| Métrica | Estado inicial |
|---|---:|
| `treatments_total_new` | 0 |
| `verified_control_sets` | 0 |
| `partially_comparable_sets` | 0 |
| `unavailable_sets` | 0 |
| controles explícitos históricos | 0 |
| `rank_path` histórico con ≥2 elementos | 20.814 observaciones |
| `status` | `collecting` |

Las 1.661 recomendaciones históricas sin `comparable_control_set` permanecen
legado y no se completan retrospectivamente. Un `rank_path` histórico no se
reclasifica como control porque no conserva de forma conjunta ciclo, precio,
ledger de gates, motivo de no ejecución, horizonte y resultado futuro.

## Diagnóstico

La interfaz `comparable-control-quality --json` acepta `--from`, `--to`,
`--status` y lectura sin efectos laterales. Publica denominadores explícitos,
pares tratamiento-control, controles bloqueados, razones de no ejecución,
cobertura de ciclo/precio/market-state/ledger, madurez 10d por brazo y el
estado `collecting` cuando todavía no hay conjuntos nuevos o outcomes maduros.
No presenta `unavailable` como cero ni afirma utilidad o mejora de profits.

## Pruebas

`tests/test_comparable_controls.py` añade pruebas independientes de:

- determinismo y ausencia de identidad inventada;
- selección pre-plan, mismo ciclo, hash de mercado y máximo de tres controles;
- ledger completo y gates no evaluados como parcial;
- razones y separación de bloqueados;
- horizonte 10d y rechazo de campos post-decisión;
- idempotencia/conflicto;
- propagación a señal verificada y no propagación con enlace roto;
- vista derivada de outcomes por ID exacto;
- digest temporal vacío y parser CLI.

No se ejecutan red, LLM, CrewAI, codegen, apply ni órdenes en estas pruebas.

## Seguridad y límites

No se modifican ranking, gates, cupos, estrategias, stops/takes, órdenes,
exposición ni límites. `ALLOW_AUTO_APPLY_IMPROVEMENTS` permanece desactivado.
Los archivos protegidos y los 17 `idealista_terrenos_*` untracked quedan fuera
de alcance.

La evaluación futura exige diez sesiones XNYS maduras para tratamiento y
controles y se hará en una vista separada. Este lote solo instala la captura;
no permite seleccionar operaciones ni declarar un tratamiento superior.
