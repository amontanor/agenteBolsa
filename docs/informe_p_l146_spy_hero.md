# P-L146 — tarjeta héroe diaria Sistema vs SPY (candidato 0.4.248)

Dictamen: `ready_for_review`. XNYS cerrado (18-sep-2026 ~12:20 CEST);
sin push, sin despliegue, sin broker/red/LLM en pruebas.

## Causa

La pregunta diaria (¿supero a SPY hoy?) exigía leer tabla + sesiones
omitidas + motivos. La tarjeta responde de un vistazo con los mismos
denominadores.

## Cambio (solo presentación)

- `_spy_hero_verdict` pura sobre `opening_context`: reutiliza
  `_opening_comparable_metric` en sesión en curso y la última fila
  `final` en otro caso. Tres estados: comparable (gana/empata/pierde),
  `unavailable` con motivo exacto (`spy_open_conflict`,
  `current_observation_*`), `empty` honesto.
- `_render_spy_hero_card` encima de la tabla existente; tabla, gráfica,
  omitidas y cobertura intactos. Sin nueva fuente ni persistencia.

## QA

- Nuevos: `tests/test_p146_spy_hero.py` (6 tests).
- Regresiones: `test_web_app.py` (76 tests). Total: 82 passed.
- `test_version_policy` verde tras bump `0.4.246` → `0.4.248`.
- Ruff, `check_no_nulls.py` (512 archivos), `git diff --check` verdes.
- Omitidos: suite completa, smoke, config/kernel (integración).

## Integración (18-sep, `9fc75525`, versión `0.4.248`)

- Mergeado con P-L143. Suite por bloques: ver
  `docs/informe_p_l143_spy_cent_tolerance.md` (mismas excepciones
  preexistentes). Dictamen: `ready_for_closed_market_deployment`.

## Límites (nota histórica: redactado pre-merge)

- Base `535f94ca` sin P-L143; el merge conjunto ordena versiones
  `0.4.247` + `0.4.248` sin solape.
- Siguiente: merge P-L143 + P-L146 con `--no-ff`, suite completa del
  árbol final, port Jetson posterior si se autoriza.
