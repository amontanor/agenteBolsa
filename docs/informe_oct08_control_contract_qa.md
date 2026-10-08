# QA P-L80B — contrato canónico del control same-cycle

## Dictamen

`needs_fix`. La caracterización test-only confirma una brecha real del
matcher: acepta un control con el mismo `signal_id` y `cycle_id`, pero con
`signal_date` distinta. El contrato documentado exige misma fecha/sesión. La
prueba queda roja de forma intencionada; no se relajó ningún assert ni se tocó
fuente.

La brecha anterior quedó cuantificada: el negativo histórico de
`tests/test_p80b_same_cycle_control_carrier.py` construía cuatro casos
(`DATE`, `SOURCE`, `REASON`, `DECISION`) sin `comparable_control_set`; los
cuatro fallaban antes del filtro de identidad del matcher por carrier ausente.
Por tanto, 4/4 = 100% de esos filtros no quedaban aislados. La nueva prueba
usa un carrier canónico válido y separa también `IDENTITY`.

## Identidad y alcance

- Fecha: 2026-10-08, Europe/Madrid.
- Worktree: `C:\Users\utopi\.codex\worktrees\oct08-control-contract-qa\agenteBolsa`.
- Rama: `codex/oct08-control-contract-qa`.
- Candidato exacto de partida: `c7619f571b0430a252eba036cd55cffef790557a`.
- Tree exacto de partida: `4b45e5bb16d9fe1f8b7c5b5c9550a91b3fb49ae3`.
- Base declarada: `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`.
- Commit de caracterización: `4e383a906025887ede3be8897f9321a9cbc8c799`.
- Tree tras caracterización: `88fe6f1cd7171b9a04e1783b728deddfe10d27ed`.
- HEAD final tras documentación: `d00da0bed66f5e577b7f11f305832e2ef223d6e2`.
- Tree final: `cd6f78eada8b426085bcac93a45f84d6c7c39d29`.
- Cambios permitidos: `tests/test_p80b_same_cycle_control_carrier.py` y este
  informe. No hay cambios en `src/`, versión, configuración, `.env`, archivos
  protegidos, Telegram, producción o datos persistentes.

## Caracterización añadida

`_canonical_verified_pair()` en
`tests/test_p80b_same_cycle_control_carrier.py:205-257` llama al productor
real `build_comparable_control_sets()` y valida con
`validate_comparable_control_set()`. La fixture contiene schema v2, ciclo,
identidades `signal_id`/`candidate_id`, snapshot de contexto, precio,
`actual_final_plans`, ledger de gates, razón `capacity_limit`, control
`gate_eligibility=verified` y `content_hash` válido.

`test_canonical_control_contract_is_one_to_one()` en
`tests/test_p80b_same_cycle_control_carrier.py:599-679` ejecuta un positivo y
cinco negativos. Cada negativo cambia exactamente una propiedad del control
materializado, conservando tratamiento, carrier canónico y ciclo:

| Caso | Mutación única | Resultado esperado |
|---|---|---|
| `POSITIVE` | Ninguna; fecha `2026-08-03`, `cycle-1`, ID, decisión y carrier válidos | Un control |
| `DATE` | Control en `2026-08-04`; mismo ID, `cycle-1`, decisión y estado | Cero controles |
| `SOURCE` | `source_run_id`/ciclo del control `cycle-2` | Cero controles |
| `REASON` | `plan_rejected` con `operator_note` | Cero controles |
| `DECISION` | Decisión del control `candidate` | Cero controles |
| `IDENTITY` | ID materializado con sufijo `:OTHER`; carrier conserva ID canónico | Cero controles |

`Settings(_env_file=None, DATA_DIR=tmp_path)` queda comprobado en cada caso;
SQLite vive en `tmp_path`, timestamps de fixture están congelados a
`2026-08-03T13:30:00+00:00`, y no se invocan proveedores, red, broker o LLM.

## Resultados exactos

Comando focal del nuevo contrato:

```text
python -m pytest tests/test_p80b_same_cycle_control_carrier.py::test_canonical_control_contract_is_one_to_one -q
1 failed, 5 passed in 1.41s
```

El único rojo es `...[DATE]`. El assert esperado
`matched_controls == []` recibe el control
`2026-08-04:CONTROL:learning_experiment`. Esto demuestra que el negativo
cross-date no queda aislado por falta de carrier: el carrier fue validado y
materializado correctamente.

Regresión del fichero existente, excluyendo solamente los seis casos nuevos:

```text
python -m pytest tests/test_p80b_same_cycle_control_carrier.py -q -k "not canonical_control_contract_is_one_to_one"
9 passed, 6 deselected in 1.46s
```

QA estático focal:

```text
python -m ruff check tests/test_p80b_same_cycle_control_carrier.py
All checks passed!
git diff --check
pass
```

No se ejecutaron suite completa, smoke, broker, red, yfinance, LLM,
producción, scheduler ni servicios.

## Clasificación y evidencia del defecto

En `src/agente_bolsa/tools/learning_scoreboard.py:198-202`,
`eligible_capacity_control()` acepta decisión `approved_buy*` más estado
`approved_not_planned`, que el caso `DATE` conserva. En
`src/agente_bolsa/tools/learning_scoreboard.py:213-223`, el candidato se
selecciona por ID exacto, ciclo explícito y elegibilidad; no se compara
`row["signal_date"]` con la fecha del tratamiento. El ID exacto, ciclo y gate
válido del caso `DATE` pasan esas condiciones, así que el matcher devuelve un
control cross-date.

La semántica esperada está documentada en
`docs/informe_p_l80_aprendizaje_evidencia.md:98-103,110-128`: el scoreboard
agrupa observaciones por `signal_date` y exige controles de misma fecha, además
de `source_run_id`, decisión y razón de capacidad. P-L53 describe en
`docs/P-L53_informe.md:227-232` la exigencia de mismo ciclo/sesión y
timestamps predecisión compatibles.

`SOURCE`, `REASON`, `DECISION` e `IDENTITY` quedan verdes con la misma fixture
canónica. No hay evidencia aquí de un defecto en esas cuatro fronteras.
Tampoco se reclasifica el comportamiento intencional de timing LLM
`failed if ANY segment failed`.

## Propuesta mínima pendiente

En un lote separado y tras revisar la autoridad de fecha/sesión, añadir al
predicado de candidatos una igualdad temporal canónica, manteniendo identidad,
ciclo, decisión, estado y razón existentes:

```python
and str(row.get("signal_date") or "") == str(item.get("signal_date") or "")
```

Si el contrato final usa una clave de sesión XNYS distinta de la fecha de
señal, comparar esa clave canónica en ambos rows. Después repetir este foco y
su regresión. No se implementó la propuesta en este lote porque la tarea exige
dejar rojo el caso DATE si revela defecto de fuente.

## Cierre

Commit test-only creado sin push. El commit emitió además el warning Git
`bad object refs/codex/turn-diffs/captures/1786628847747/4ee266fa-eceb-479d-a4a7-b513226192d9/base`
durante `geometric repack`, pero terminó creando el commit indicado y dejó el
worktree limpio. El informe se añade en commit documental separado. No se
retiraron gates ni se sustituyó `end_state` por un check de paso.
