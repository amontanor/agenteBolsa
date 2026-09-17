# P-L140C — helpers del baseline conservados por contrato (candidato Windows 0.4.244)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

P-L140B retiro el contenedor duplicado y sus 3 funciones. La suite de
integracion revelo que `test_p63_april_equity_contract.py` importa
`_performance_baseline_chart` para el contrato de tooltips explicitos
P-L63R1: la eliminacion total rompia la suite, no solo un test.

## Cambio (solo `web_app.py`, aditivo)

- Se restauran verbatim `_performance_baseline_series` y
  `_performance_baseline_chart` con comentario de retencion (contrato
  P-L63R1, prohibido re-conectarlos a paginas). El contenedor
  `_render_performance_baseline` sigue fuera: el Dashboard no muestra
  el duplicado.
- Bump `0.4.243` → `0.4.244`; pin `test_p59c` actualizado.

Sin broker, sin escrituras, sin trading, sin cambios visuales.

## Commits (rama `codex/pl140c-baseline-contract`, base `b6e1a48c`)

- `0d53944c` fix + bump 0.4.244 + pin version (la deteccion la hizo la
  propia suite de integracion, no un lote aislado: leccion a favor de
  integrar pronto).

## QA (XNYS cerrado)

- `test_p63_april_equity_contract.py`: 11 passed.
- Bateria conjunta: 145 passed (p63 + p140b + p140a + web_app + p59c).
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (509 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: en curso sobre el merge final.

## Siguiente paso

Merge P-L140C sobre `codex/astra` tras P-L140B → suite completa →
port Jetson. Sin push.
