# Informe Codex P16 - horizonte de salida 5-10d

Fecha: 2026-07-02

## Alcance

Tarea read-only. No se cambia conducta de trading ni flags. La fuente usada es la
maquinaria C2 existente:

- `linked_executed_buy_signals(settings, store, since_date="2026-04-01")`
- retornos forward de SPY vía `_build_spy_forward_returns`
- stale guard shadow vía `scripts.exit_shadow_analysis._stale_guard_shadow`

Muestra acumulada vinculada a compras ejecutadas: `n=4`, fechas `2026-05-13` a
`2026-06-11`.

## Métricas globales

Retornos en fracción decimal. Coste neto aplicado por trade: 10 bps = `0.001`,
20 bps = `0.002`.

| Política | Coste | n maduro | Expectativa | Hit-rate | PF | Alpha vs SPY |
|---|---:|---:|---:|---:|---:|---:|
| Actual 1-3d | 0 bps | 4 | -0.196075 | 0.2500 | 0.0297 | -0.188376 |
| Shadow 5-10d | 0 bps | 4 | -0.167325 | 0.2500 | 0.2172 | -0.169315 |
| Actual 1-3d | 10 bps | 4 | -0.197075 | 0.2500 | 0.0283 | -0.189376 |
| Shadow 5-10d | 10 bps | 4 | -0.168325 | 0.2500 | 0.2153 | -0.170315 |
| Actual 1-3d | 20 bps | 4 | -0.198075 | 0.2500 | 0.0270 | -0.190376 |
| Shadow 5-10d | 20 bps | 4 | -0.169325 | 0.2500 | 0.2134 | -0.171315 |

Comparación pareada:

| Coste | n pareado | Delta expectativa 5-10d menos 1-3d | Delta alpha |
|---:|---:|---:|---:|
| 0 bps | 4 | 0.028750 | 0.019061 |
| 10 bps | 4 | 0.028750 | 0.019061 |
| 20 bps | 4 | 0.028750 | 0.019061 |

La diferencia pareada no cambia con el coste porque se aplica el mismo coste a
ambas políticas.

## Desglose por mes

Métrica: pareada neta 20 bps.

| Mes | n | Actual neta | Shadow neta | Delta | Delta alpha |
|---|---:|---:|---:|---:|---:|
| 2026-05 | 1 | 0.022000 | 0.183700 | 0.161700 | 0.140213 |
| 2026-06 | 3 | -0.271433 | -0.287000 | -0.015567 | -0.021322 |

La ventaja se concentra en mayo con un solo caso. Junio es negativo para el
shadow 5-10d frente al actual.

## Desglose por régimen

Métrica: pareada neta 20 bps.

| Régimen | n | Actual neta | Shadow neta | Delta | Delta alpha |
|---|---:|---:|---:|---:|---:|
| bullish | 4 | -0.198075 | -0.169325 | 0.028750 | 0.019061 |

Solo hay un régimen cubierto.

## Pares maduros

| Señal | Símbolo | Fecha | Régimen | Actual | Shadow | Delta |
|---|---|---|---|---:|---:|---:|
| `scan_507e88fcb67f:HPE` | HPE | 2026-05-13 | bullish | 0.024000 | 0.185700 | 0.161700 |
| `mkt_262c548ab2c0:PSX` | PSX | 2026-06-04 | bullish | -0.023200 | -0.093400 | -0.070200 |
| `mkt_7b163fff3d1b:CRWD` | CRWD | 2026-06-05 | bullish | -0.765300 | -0.755300 | 0.010000 |
| `mkt_cec9ae1d9395:FRT` | FRT | 2026-06-11 | bullish | -0.019800 | -0.006300 | 0.013500 |

## Stale guard

Perfil evaluado:

```json
{
  "days": 10,
  "max_peak_return": 0.05,
  "min_return": 0.01
}
```

Resultado sobre las 4 compras vinculadas:

| Métrica | Valor |
|---|---:|
| n | 4 |
| Expectativa política actual exit_policy_v2 | -0.020625 |
| Expectativa shadow stale_guard | -0.020625 |

No hubo cambio efectivo: todos los casos salieron por `take_profit` o `stop_loss`
antes de la ventana stale.

| Símbolo | Fecha | Retorno actual | Retorno stale shadow | Razón shadow |
|---|---|---:|---:|---|
| HPE | 2026-05-13 | 0.085600 | 0.085600 | take_profit |
| PSX | 2026-06-04 | -0.028100 | -0.028100 | stop_loss |
| CRWD | 2026-06-05 | -0.109900 | -0.109900 | stop_loss |
| FRT | 2026-06-11 | -0.030100 | -0.030100 | stop_loss |

## Criterios pre-registrados

Criterios del responsable:

1. `n >= 20` pareado maduro.
2. Delta de expectativa positiva neta de 20 bps.
3. Ventaja presente en al menos 2 meses distintos.
4. Ventaja presente en al menos 2 regímenes.

Evaluación:

| Criterio | Resultado |
|---|---|
| n pareado maduro >= 20 | NO, n=4 |
| Delta expectativa neta 20 bps positiva | SI, +0.028750 |
| Ventaja en >=2 meses | NO, solo 2026-05 |
| Ventaja en >=2 regímenes | NO, solo bullish |

Veredicto binario: **NO CUMPLE**.

No se diseña ni activa cambio guarded porque no supera los criterios mínimos.

## Verificación P16

Versión: `0.4.97`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
# 897 passed, 1 warning

.\.venv\Scripts\ruff.exe check src tests scripts
# All checks passed

.\.venv\Scripts\python.exe -m agente_bolsa.main status
# trading_mode=paper; allow_live_trading=false

.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
# ok=true; errors=[]; warnings=[]

.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
# cycle_id=20260702-215825; used_crew=false; market_state_quality=PARTIAL
```

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_path": "data\\config\\core_sleeve.json",
  "core_sleeve_dry_run": true
}
```

No se tocaron ficheros del suelo de kernel.
