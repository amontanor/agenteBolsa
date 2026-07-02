# Prompt P15 para Codex — 2-jul-2026 — la firma arregla su propio bug de producción

Contexto: el cambio aplicado de la firma (commit 6816b05e, `latest_core_sleeve_signal`
en digest.py) crasheó en su primera ejecución real:

```
File "digest.py", line 363, in latest_core_sleeve_signal
  "decision_order_side": (decision.get("order", {}).get("side") if decision else None),
AttributeError: 'NoneType' object has no attribute 'get'
```

Causa: `decision.get("order", {})` devuelve None cuando la clave `order` existe con
valor null (el default de `.get` solo aplica si la clave FALTA). Ese caso es el
estado normal futuro de la manga: decisión "hold" dentro de banda = decision dict
con `order: null`. Los tests del artefacto cubrían `decision: null` y orden
presente, pero no este estado intermedio. El digest diario de las 08:30 crashea
hasta que se arregle. Urgente pero con método.

## Parte 1 — Evidencia

1. Reproduce el crash del digest y captura la ÚLTIMA línea real de
   `data/research/core_sleeve/core_sleeve_log.jsonl` (la que lo dispara —
   probablemente la escrita por el run de las 15:45). Inclúyela literal en el
   informe.
2. Enumera desde `strategies/core_sleeve.py` TODOS los estados que el productor
   puede emitir (disabled, would_submit, submitted, market_closed, hold/no_op,
   error…) y qué forma tiene `decision`/`order` en cada uno. Esa tabla va al
   informe: es el contrato completo que los tests deben cubrir.

## Parte 2 — La firma arregla su propio bug (vía pipeline)

3. Siembra la propuesta por el cauce normal: fix de `latest_core_sleeve_signal`
   para tolerar `order: null` (patrón `((decision or {}).get("order") or {}).get(...)`
   o equivalente), con requisito de tests que cubran: la línea real del crash
   copiada verbatim, y UN caso por cada estado del productor de la tabla del punto 2.
   Targets: `digest.py`, tests, `src/agente_bolsa/__init__.py` (bump, ya permitido).
4. `gen-diff` hasta 3 intentos con la maquinaria completa (autocorrección, muestra
   de datos reales, gate de tests, suite completa). Si queda READY_FOR_HUMAN_REVIEW,
   cierra con los comandos `review`/`approve` para Antonio.
5. **Fallback con plazo**: si la firma falla los 3 intentos, aplica TÚ el hotfix
   directo en commit separado claramente etiquetado (el digest de mañana 08:30 no
   puede crashear), documentando los fallos literales de la firma.

## Parte 3 — Lección sistémica (pequeña)

6. En el gate de preview: cuando el diff parsea un fichero de datos, ya se adjunta
   una muestra real (P10); añade a la instrucción de codegen que los tests deben
   cubrir los valores null/ausentes de los campos anidados que aparezcan en la
   muestra. No hace falta análisis estático sofisticado: instrucción de prompt +
   la exigencia de la tabla de estados en la propuesta.

Informe: `docs/informe_codex_p15_hold_null_order_<fecha>.md`.

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde; `ruff check src tests scripts` limpio.
- El comando exacto que crasheó debe ejecutarse OK al cierre:
  `continuous-improvement-lab digest --days 1 --out data\reports\ci_digest_post_apply.md`
  (con la sección Core sleeve renderizando el estado real del día). Documenta la
  salida de la sección.
- Bump de `__version__` (en el artefacto de la firma o en tu hotfix).
- Commit(s) con diff revisable.
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar los 6 ficheros del suelo de kernel.
