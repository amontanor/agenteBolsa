# P-L37B-T — caracterización aislada

Este documento pertenece exclusivamente al worktree `codex/pl37b-tests` y no
modifica el plan ni el informe del workspace productivo.

## Base y aislamiento

- Base: `6640ed91ed4d83f598950517e4997a82a2043e9a`, versión `0.4.171`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl37b_tests`.
- Pruebas: Store y JSON bajo `tmp_path`; sin `data/state` productivo, red,
  LLM, broker, scheduler, órdenes, postmarket ni reconciliación.

## Mapa de reproducción

| Pérdida | Funciones | Evidencia |
|---|---|---|
| Captura B sustituye la procedencia A | `record_signal_candidates` → `Store.save_signal_outcomes_bulk` (`ON CONFLICT(signal_id) DO UPDATE`) | `test_current_upsert_replaces_capture_source_and_breaks_first_cycle_exact_match` |
| El informe técnico se escribe antes de enriquecer la identidad | `build_closed_market_technical_study` → `write_json_report`; después `scheduler.closed_market_technical_study_job` llama `record_signal_candidates` | `test_current_persisted_technical_report_precedes_identity_enrichment` |
| La recomendación A conserva un ID lógico pero el Store solo conserva `source_run_id=B` | `build_decision_lineage` → `_decision_context_snapshot_for_recommendation` | `test_current_first_recommendation_has_symbol_date_match_but_source_mismatch` |
| Símbolo/fecha no desambigua dos estrategias | `_candidate_for_symbol` / resolver de test exacto | `test_same_symbol_date_with_two_strategies_is_ambiguous_not_unknown` |

## Comportamiento actual caracterizado

1. Dos capturas con el mismo `signal_id` lógico dejan una sola fila en
   `signal_outcomes`; la segunda sustituye el `source_run_id` y no hay un
   historial de capturas inmutable.
2. `record_signal_candidates` enriquece las copias independientes en memoria,
   pero el JSON ya persistido conserva `strategy_name`, `strategy_version`,
   `last_date` y `symbol` sin `signal_id`, `signal_source_run_id` ni
   `candidate_id`.
3. Al volver a leer ese JSON y compactarlo, `build_decision_lineage` no puede
   resolver un ID canónico y devuelve `lineage_status=unavailable`.
4. Tras la segunda captura, símbolo, fecha y estrategia pueden coincidir con
   la recomendación de la primera captura, aunque la comparación exacta de
   `source_run_id` sea `mismatch`.
5. Dos estrategias para un mismo símbolo y fecha generan IDs lógicos distintos;
   un resolver por símbolo/fecha no puede elegir y debe permanecer
   `ambiguous`/`unavailable`, nunca fabricar `UNKNOWN`.
6. Score, ranking, orden, acción, geometría, gates y `risk_plan` permanecen
   iguales durante el enriquecimiento actual.

## Matriz de pruebas

| Prueba | Tipo | Resultado esperado en la base |
|---|---|---|
| Dos ciclos, misma señal | `current_behavior` | `source_run_id` B reemplaza A; exact match A → `mismatch` |
| Copias profundas independientes | `current_behavior` | memoria enriquecida, JSON persistido sin identidad |
| Compactación desde JSON | `current_behavior` | lineage `unavailable`, no `UNKNOWN` |
| Recomendación A tras ciclo B | `current_behavior` | símbolo/fecha/estrategia coinciden, source run no |
| Dos estrategias mismo símbolo/fecha | `current_behavior` | IDs distintos; unión débil no verificable |
| Paridad funcional | `characterization` | score/rank/gates/geometría/planes no cambian |

## Contrato reservado para P-L37B

Las pruebas futuras deberán volver verificables, sin cambiar la política de
selección, estas propiedades: `signal_id` lógico estable, `signal_capture_id`
por captura, historial append-only, separación literal de `signal_source_run_id`
y `cycle_id`, propagación por todos los buckets y resolución exacta por
`signal_capture_id`, manteniendo legacy explícito. Este worktree no añade el
productor ni implementa dicho contrato.

