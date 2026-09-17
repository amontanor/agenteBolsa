# P-L140D — guardia de superficie SPY unica (candidato Windows 0.4.244, sin bump)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

La suite de integracion detecto que P-L140B rompia
`test_baseline_render_is_single_store_read_and_no_broker_network_call`
(su sujeto, `_render_performance_baseline`, ya no existe) y que
`test_p71...future_bar...` falla igual en base limpia (preexistente,
`performance_benchmark.py` no tocado por la cadena).

## Cambio (solo tests, sin version)

- El test muerto se convierte en guardia del contrato nuevo:
  `page_dashboard` contiene `_render_daily_vs_spy_table` y no
  `_render_performance_baseline`.
- Sin cambios en `src`, sin bump (solo tests, precedente de los
  commits de caracterizacion).

## Commits (rama `codex/pl140d-spy-contract-guard`, base `15a3698d`)

- `67a0dac4` test: reescritura minima del contrato.

## QA (XNYS cerrado)

- `test_p65a_daily_vs_spy_contract.py`: 12 passed.
- `ruff check src tests`: All checks passed. `git diff --check`: limpio.
- p71 future-bar: preexistente en base (verificado en worktree pl130),
  fuera de alcance.
- Suite completa: en curso por chunks (ver informe de integracion).

## Siguiente paso

Merge a `codex/astra` → suite completa → port Jetson. Sin push.
