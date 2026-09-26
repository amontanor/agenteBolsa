# P-L140A — franja Mis inversiones (candidato Windows 0.4.242)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

La tarjeta global mostraba el % sobre equity total (`_today_pl_display`
ignora el invertido): con ~92% en cash, la rentabilidad real de las
acciones quedaba invisible. El operador no podia responder "son
rentables mis inversiones" con el Dashboard.

## Cambio (solo `web_app.py`, N1, sin trading ni broker nuevo)

- Nuevo helper puro `_invested_day_metric`: primario % sobre
  invertido, secundario % sobre equity etiquetado, importe, tono y
  cobertura `known/total`. Sin invertido o sin dato → `n/d`, nunca
  division por cero.
- Nueva franja "Mis inversiones" tras la tira de cuenta, con la misma
  fuente ya cargada por `page_dashboard`: Invertido (+% del equity),
  P/L dia sobre invertido, P/L total abiertas (mismo `_portfolio_open_pl`
  que la tarjeta del grafico), Cash.
- Bump `0.4.241` → `0.4.242`; pin `test_p59c` actualizado.

Sin llamadas broker nuevas, sin escrituras, sin cambios de trading,
config o contratos. Clases CSS reutilizadas.

## Commits (rama `codex/pl140a-mis-inversiones`, base `a6655e10`)

- `587f711e` test: 6 tests del helper (rojo por coleccion) + render
  headless AppTest.
- `e7244de2` feat + bump 0.4.242 + pin version (incluye fix de sintaxis
  del ternario y closure del AppTest).

## QA (XNYS cerrado)

- Focales: 7 passed (6 helper + 1 render headless con asserts
  `Mis inversiones`, `+1.00%`, `+0.07% sobre equity`).
- Regresiones: 128 passed con `test_web_app.py` + p59c.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (508 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: pendiente de integracion conjunta.

## Siguiente paso

P-L140B (comparativa SPY unica + Leaderboard a Config) sobre esta rama
→ revision → `merge --no-ff` conjunto P-L130→P-L140 a `codex/astra` →
suite completa → port Jetson. Sin push.

## Re-add P-L140A-R (candidato 0.4.319, 26-sep-2026)

Dictamen: `ready_for_integration_rehearsal`. XNYS cerrado; sin merge,
despliegue, push ni escritura productiva.

Causa: la reconstruccion `784e6cd7` retiro los helpers/render P-L140A
dejando `tests/test_p140a_mis_inversiones.py` con ImportError
(`cannot import name '_invested_day_metric'`, reproducido contra la
base `baba2dd9` antes de tocar codigo). Referencia historica solo
para diff/contrato (candidato original `66103e2f`, feat `e7244de2`):
sin cherry-pick ni copia de rama.

Alcance minimo repuesto campo a campo en `src/agente_bolsa/web_app.py`
(+84 lineas, identico conteo al feat original): helper puro
`_invested_day_metric` (primario % sobre invertido, secundario % sobre
equity, importe, tono, cobertura `known/total`; invertido<=0 o missing
→ `n/d`, nunca cero inventado ni division por cero), franja
`_investments_group` de 4 tarjetas (Invertido, P/L dia sobre invertido,
P/L total abiertas con el mismo `_portfolio_open_pl`, Cash) tras la
tira de cuenta y antes del leaderboard, y wiring en `page_dashboard`
reutilizando snapshots ya cargados (`exposure`, `exposure_pct`,
`position_intraday`, `portfolio`/`stats`, `current_cash`, `today_pct`):
cero llamadas broker nuevas, sin persistencia ni autoridad.
P-L137/P-L133 preservados; sin P-L140B (`_spy_alpha_summary`,
leaderboard/baseline), P-L139, scoreboard, politica ni telemetry.

Commits (rama `codex/pl140a-readd-0319`, base P-L133-R `baba2dd9`,
tree base `06270950b4cd6bc1e753f4913cd1490c78df255b`, v0.4.318):
funcional `60fe034a`/tree `829fdae1` + version/pin `88ce177f`/tree
`0b4340d5` (bump 0.4.319) + documental previo `58e9497c`/tree
`f5cf652b` (informe/plan/relevo candidato 0.4.319).
Correccion N0 26-sep-2026: este bloque citaba antes HEAD/tree pre-docs
`88ce177f`/`0b4340d5` con docs pendientes; queda distinguido asi. El
HEAD/tree finales post-correccion N0 (nuevo commit solo documental) se
consignan en la entrega/HANDOFF; no se escribe aqui el hash del commit
aun no creado.

QA: focales P-L140A 7 passed (incluye render headless con asserts
`Mis inversiones`, `+1.00%`, `+0.07% sobre equity`); bateria combinada
113 passed (`test_web_app.py` + P-L152 + P-L153 + P-L158A + P-L158B);
version 54 passed (P-L140A + P-L59C con pin 0.4.319 +
`test_version_policy`). Ruff, NUL (536 archivos), `git diff --check` y
`validate-agent-config --json` (DATA_DIR temporal, `ok=true`) verdes.
Protegidos (`kernel`, `broker`, `execution`, `risk`, `config`, `.env`)
sin diff. Gates omitidos: suite completa, smoke, benchmark largo,
kernel-status e integracion final (pendientes de ensayo combinado).

Siguiente paso minimo: P-L140B re-add separado sobre esta base, luego
ensayo combinado de integracion. Sin push, sin despliegue.
