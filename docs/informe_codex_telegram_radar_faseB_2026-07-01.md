# Informe Codex - Telegram radar Fase B - 2026-07-01

## Objetivo

Extender el radar Telegram de Fase A con analisis propio y marcador honesto,
manteniendo disciplina read-only respecto a trading. No se crearon ordenes ni se
toco `kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`,
`config.py` ni `.env`.

## Validacion LLM real

Se ejecuto ingesta publica de 1 pagina del canal y se probaron 3 posts reales con
`chat_for_role("deep")`, cada uno en proceso independiente con timeout de 40s.
La llamada completo en ~9s/post, pero la salida no fue JSON parseable:

- 5014 -> `llm_unavailable_heuristic_fallback`, error `Expecting value`.
- 5015 -> `llm_unavailable_heuristic_fallback`, error `Expecting value`.
- 5016 -> `llm_unavailable_heuristic_fallback`, error `Expecting value`.

Conclusion: la ruta de transporte no queda bloqueada por timeout, pero en esta
sesion no produjo JSON valido. La entrega conserva el fallback heuristico y lo
registra como limitacion. Los tests mockean el LLM y no llaman a red.

## Diseno

Nuevos modulos aislados:

- `src/agente_bolsa/research/telegram_radar/analysis.py`
- `src/agente_bolsa/research/telegram_radar/scorecard.py`

Persistencia dedicada bajo `data/research/telegram/`:

- `gate_verdicts.jsonl`: veredicto interno por `message_id+ticker`.
- `scorecard.jsonl`: marcador acumulado por `message_id+ticker+horizon+cost_bps`.

CLI:

- `telegram-radar report [--days N] [--json]`

El comando imprime markdown y, con `--json`, devuelve el payload completo. Es
read-only respecto al trading: solo lee posts/extracciones/precios y escribe
artefactos de investigacion en el store propio del radar.

## Analisis propio

Para cada ticker in-universe de posts marcados como oportunidad:

- calcula tecnicos con datos hasta `posted_at` usando `add_basic_technical_features`;
- comprueba regimen causal `SPY close > SMA200` en esa misma fecha;
- calcula extension sobre SMA20, RSI 14, retorno 20d, volumen z-score y R:R
  aproximado desde high/low/ATR recientes;
- construye una recomendacion sintetica read-only y pasa el candidato por
  `filter_entry_quality`;
- devuelve `our_gate=pass|fail`, `reasons[]` y metricas.

No usa datos posteriores al post para el veredicto.

## Marcador honesto

Para todas las menciones con direccion `buy`, `watch` o `sell`:

- entrada: siguiente barra disponible posterior a `posted_at`;
- horizontes: 5/10/20 dias de mercado;
- coste: 10/20/30 bps;
- `buy/watch`: retorno largo neto;
- `sell`: retorno direccional invertido, es decir, acierta si baja;
- `excess_vs_spy`: retorno direccional neto menos retorno direccional de SPY;
- beta-ajuste opcional si hay al menos 20 retornos historicos previos.

El resumen agrega `n`, `n_scored`, `hit_rate`, retorno neto medio y excess medio
por horizonte, coste y cobertura (`in_universe` / `out_of_coverage`).

## Ejemplo real reciente

`telegram-radar report --days 7 --json` proceso posts recientes del canal:

- 5031: "hoy NVIDIA muy comprable 194-195$" -> NVDA.
- 5015: "Micron o Sandisk... puede ser oportunidad" -> MU, SNDK.
- 5014: "ASTS, AAOI, Google, META... Reddit y Oracle" -> AAOI, ASTS, GOOGL, META, ORCL, RDDT.

Veredictos internos reales:

| Post | Ticker | Gate | Regimen | Extension SMA20 | RSI | R:R | Razones principales |
|---:|---|---|---|---:|---:|---:|---|
| 5031 | NVDA | fail | SPY bull | -3.62% | 46.91 | 3.52 | confidence_baja; entry_quality no strong |
| 5015 | MU | fail | SPY bull | 9.69% | 60.19 | 0.38 | confidence_baja; R:R bajo; entry_quality no strong |
| 5014 | GOOGL | fail | SPY bull | -1.61% | 44.40 | 1.05 | confidence_baja; R:R bajo; entry_quality no strong |

Marcador acumulado real en esta ventana: 9 menciones x 3 horizontes x 3 costes.
No hay todavia barras forward suficientes desde los posts de 2026-06-29/2026-07-01,
por lo que `n_scored=0` y el estado queda `sin_datos_forward`. Esto es correcto:
el marcador no inventa resultados antes de que transcurran los horizontes.

## Limitaciones

- El canal puede hacer cherry-picking de ideas y borrar mensajes: la fuente
  publica ya llega con sesgo de supervivencia.
- Solo se observa el canal gratuito, no el VIP ni el historico completo.
- Una mencion no equivale a orden real con precio, stop, salida, tamano y slippage.
- El veredicto interno es un filtro de admisibilidad, no una recomendacion.
- En esta sesion el LLM real completo transporte pero no devolvio JSON valido;
  el fallback heuristico queda activo y documentado.
- El marcador necesita que pasen 5/10/20 sesiones posteriores al post para
  producir resultados honestos.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_telegram_radar.py tests\test_telegram_radar_phase_b.py -q` -> 8 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 836 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests` -> OK.
- Smoke real: `telegram-radar report --days 7 --json` -> OK, 6 veredictos y 81 filas de scorecard persistidas.
- Estado operativo: `trading_mode=paper`, `allow_live_trading=false`.
- Version final: `0.4.78`.
