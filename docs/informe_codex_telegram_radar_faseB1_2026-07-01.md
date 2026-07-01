# Informe Codex - Telegram radar Fase B.1 - 2026-07-01

## Objetivo

Robustecer la extraccion LLM del radar Telegram manteniendo el subsistema en
modo research read-only. No se tocaron `kernel.py`, `tools/broker.py`,
`tools/execution.py`, `tools/risk.py`, `config.py` ni `.env`; no se crearon
ordenes ni se reinicio el sistema.

## Diagnostico

Se capturo la respuesta cruda de `chat_for_role("deep")` sobre 3 posts reales.
El transporte completaba, pero el objeto OpenAI-compatible devolvia:

- `message.content == ""`
- `message.reasoning_content` con analisis/prosa interna y, en los casos
  observados, sin objeto JSON final parseable antes de agotar la respuesta.
- El endpoint usado fue `role:deep`, modelo `glm-5.2`.

Causa raiz: el extractor solo leia `message.content` y aplicaba `json.loads` a
una cadena vacia. Ademas, el prompt permitia que el modelo gastara salida en
razonamiento/prosa antes de producir el JSON.

## Fix

Cambios en `src/agente_bolsa/research/telegram_radar/extract.py`:

- Prompt mas estricto: respuesta completa debe empezar por `{` y acabar por `}`;
  sin explicaciones, markdown, fences ni texto fuera del JSON.
- Parser robusto `_extract_first_json_object`: extrae el primer objeto JSON
  balanceado, respetando strings y escapes.
- `_parse_json_object` ahora tolera JSON limpio, fences ```json y prosa
  circundante si hay un objeto JSON balanceado.
- `_response_message_text` lee `message.content` y, si viene vacio, usa el campo
  alternativo `reasoning_content` como texto parseable.
- Un reintento acotado para fallos de parseo, con prompt de correccion que pide
  solo el objeto JSON.
- Si el reintento falla, se conserva el fallback heuristico y
  `extraction_status=llm_unavailable_heuristic_fallback`.

## Ejemplo crudo a parseado

Antes del fix, el post 5014 devolvia `content=''` y no habia JSON en el campo
parseado por el extractor. Tras el fix, el mismo flujo real devolvio:

```json
{"is_opportunity":true,"tickers":["ASTS","AAOI","GOOGL","META","RDDT","ORCL"],"direction":"buy","thesis":"Operativa dando frutos en ASTS, AAOI, GOOGL, META. Sigue encantando Reddit y Oracle. No vende nada, mantiene posiciones.","timeframe":null,"confidence":0.6,"unresolved_mentions":[]}
```

Resultado parseado: `is_opportunity=true`, tickers `ASTS, AAOI, GOOGL, META,
RDDT, ORCL`, `direction=buy`, `confidence=0.6`.

## Validacion real

Se re-ejecuto el LLM real sobre 3 posts recientes con timeout acotado:

| Post | Resultado |
|---:|---|
| 5014 | `llm_ok`, tickers `AAOI, ASTS, GOOGL, META, ORCL, RDDT`, `direction=buy`, `confidence=0.6` |
| 5015 | `llm_ok`, tickers `MU, SNDK`, `direction=watch`, `confidence=0.5` |
| 5016 | `llm_ok`, sin tickers, `direction=none`, `confidence=0.2` |

La validacion real no forma parte de tests automatizados para mantenerlos sin
red ni LLM real.

## Tests

Tests sinteticos sin red/LLM real:

- JSON limpio parsea.
- JSON envuelto en fences ```json parsea.
- Prosa antes/despues del JSON parsea.
- Objeto balanceado respeta llaves dentro de strings.
- Respuesta no parseable hace un retry y parsea si el segundo intento es valido.
- Basura no parseable tras retry conserva fallback heuristico.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_telegram_radar.py -q` -> 9 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 840 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests` -> OK.
- Estado operativo: `trading_mode=paper`, `allow_live_trading=false`.
- Version final: `0.4.79`.
