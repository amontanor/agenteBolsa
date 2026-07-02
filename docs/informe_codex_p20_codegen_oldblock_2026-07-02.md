# Informe P20 - Codegen old-block persistente

Fecha: 2026-07-02

## Veredicto

El fallo P15 no fue un problema de espacios: los bloques `old` generados para
`src/agente_bolsa/continuous_improvement/digest.py` no existian en el fichero real.
El modelo reconstruyo/parafraseo lineas plausibles de un fichero mediano en lugar
de copiar bloques verbatim. La mejora aplicada permite modo fichero-completo para
targets de hasta 900 lineas, eliminando esta clase de fallo en ficheros como
`digest.py`.

No se aprobo ni aplico ningun diff de codegen.

## Diagnostico de artefactos P15

Fuente: artefactos `code_diff_attempt` de la propuesta
`ci_prop_p15_core_sleeve_null_order_digest`. Fichero real comparado:
`git show fa126d40^:src/agente_bolsa/continuous_improvement/digest.py`
(779 lineas, estado previo al hotfix manual P15).

| # | artifact | old lineas | exacto | whitespace | similitud | linea aprox. | tipo | bloque generado |
|---:|---|---:|---|---|---:|---:|---|---|
| 1 | `ci_artifact_e2f1883deca0` | 4 | no | no | 0.55 | 597 | lineas parafraseadas | `order = decision['order'] / if order: / symbol = order['symbol']` |
| 2 | `ci_artifact_a9078c3b8dca` | 4 | no | no | 0.53 | 724 | bloque inexistente | `order = decision['order'] / if order: / symbol = order['symbol']` |
| 3 | `ci_artifact_1584a7e63b24` | 4 | no | no | 0.55 | 597 | lineas parafraseadas | `order = decision['order'] / if order: / symbol = order['symbol']` |
| 4 | `ci_artifact_5dae0b25b26b` | 1 | no | no | 0.66 | 548 | lineas parafraseadas | `order = decision.get("order")` |
| 5 | `ci_artifact_f109df5cf588` | 2 | no | no | 0.68 | 353 | lineas parafraseadas | `decision = row.get("decision") / order = decision.get("order")` |
| 6 | `ci_artifact_5d752e9ce1a8` | 1 | no | no | 0.69 | 548 | lineas parafraseadas | `order = decision.get("order")` |
| 7 | `ci_artifact_ef337657e05e` | 1 | no | no | 0.68 | 362 | lineas parafraseadas | `order = decision.get("order") if decision else {}` |

Lectura:

- 0/7 bloques `old` de `digest.py` coincidian exactamente.
- 0/7 eran arreglables por normalizacion de espacios.
- 6/7 eran lineas plausibles pero no verbatim; 1/7 no tenia contexto util.
- El ultimo intento que ya no dependia de un `old` de `digest.py` llego a diff,
  pero fallo por test generado invalido/no alineado, no por aplicacion de bloque.

## Mejora implementada

Cambio elegido: subir el modo fichero-completo.

- `CODEGEN_FULL_CONTENT_MAX_LINES`: 300 -> 900.
- `CODEGEN_FULL_CONTEXT_MAX_LINES`: 800 -> 900, para que el prompt y el contexto
  real sean coherentes.
- `content_mode_allowed` pasa a ser inclusivo (`<=`) en contexto inicial y en
  contexto de autocorreccion.
- Los prompts dejan de hardcodear `300` y usan la constante.
- Tests nuevos/actualizados en `tests/test_ci_codegen.py` cubren targets de 500 y
  700 lineas con `content_mode_allowed=true`.

Justificacion: `digest.py` esta en el rango 700-800 lineas. En ese tamano el LLM ya
recibe el contenido completo, pero si se le fuerza a `{old,new}` puede inventar
bloques. Permitir `{content}` completo hace que el diff lo compute git y elimina
la dependencia de copiar bloques exactos para ficheros medianos.

## Validacion real acotada

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --demo --json
```

Resultado:

- `ok=true`
- `status=READY_FOR_HUMAN_REVIEW`
- `proposal_id=ci_prop_codegen_demo_51f112150ca0`
- `artifact_id=ci_artifact_d393a4101a29`
- `applied=false`
- `target_paths=["docs/ci_codegen_demo.md"]`
- Sandbox: `910 passed, 1 skipped`

No se ejecuto `approve`.

## Seguridad operativa

- `trading_mode=paper`.
- `allow_live_trading=false`.
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- `data/config/core_sleeve.json`: `dry_run=true`.
- No se tocaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py` ni `.env`.

## Verificacion

- `pytest tests\ -x -q`: `912 passed, 1 warning`.
- `ruff check src tests scripts`: limpio.
- `python -m agente_bolsa.main status`: OK, `trading_mode=paper`,
  `allow_live_trading=false`.
- `python -m agente_bolsa.main validate-agent-config --json`: `ok=true`, sin
  errores ni warnings.
- `python -m agente_bolsa.main run-once --skip-crew`: OK, ciclo
  `20260702-223609`, sin LLM ni ordenes automaticas.
- `continuous-improvement-lab autonomy-status`: `allow_auto_apply=false`,
  `allow_live_trading=false`.
- Configuracion real cargada desde `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
  `core_sleeve_dry_run=true`.
