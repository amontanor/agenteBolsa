# Informe Codex P4 - Overlay shadow, gate de agresividad y digest

Fecha: 2026-07-02

## Resumen

- Overlay shadow SPY implementado como modulo read-only aislado: `src/agente_bolsa/research/overlay_shadow.py`.
- Persistencia append-only generada en `data/research/overlay_shadow/overlay_shadow_2026-07-01.json` y `data/research/overlay_shadow/overlay_shadow_log.jsonl`.
- Gate deterministico de agresividad implementado en `continuous_improvement.aggressiveness_gate` e integrado en `ValidationAgent`.
- Saneo retroactivo aplicado a la cola `READY_TO_APPLY` sin tocar trading real, book, broker ni scheduler operativo.
- Digest corregido: `PIDE APROBACION` excluye propuestas ya `APPLIED` o `ROLLED_BACK`, y `% exp->aplicado` cuadra con la columna `Applied`.

## Parte 1 - Overlay shadow SPY

El overlay no registra jobs en el scheduler operativo ni emite ordenes. El calculo usa el mismo motor que `scripts/study_drawdown_overlay_deep.py`:

- `exposure_vol_target(close, target_vol=0.12)` para vol-target 12%.
- `exposure_vol_target(close, target_vol=0.10)` como comparador.
- `exposure_regime_on_off(close, sma_window=200)` como comparador SMA200.
- Volatilidad realizada trailing: 20 sesiones anualizadas, via `DEFAULT_OVERLAY_VOL_LOOKBACK`.

Ejecucion real:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.research.overlay_shadow --start 2020-01-01 --out-dir data\research\overlay_shadow --json
```

Resultado real generado:

- `data_date`: 2026-07-01
- `price`: 745.76001
- `realized_vol_annualized`: 0.182797
- `vol_target_10pct`: 0.547054
- `vol_target_12pct`: 0.656465
- `regime_sma200`: 1.0

Scripts PowerShell disponibles, no arrancados:

```powershell
.\scripts\run_overlay_shadow_daily.ps1
.\scripts\run_overlay_shadow_supervisor.ps1 -RunAt 22:30
```

## Aclaracion P1 - "peor mes"

En el informe P1 habia una aparente inconsistencia porque se comparaban tablas con ventanas distintas:

- Tabla de episodios: "peor mes" es el peor mes calendario dentro de cada episodio de drawdown concreto.
- Tabla de criterios: "peor mes" es el peor mes calendario dentro de cada anio calendario que cumplia el criterio anual de drawdown profundo.

Ambas tablas usan retornos mensuales calendario. Ninguna de esas dos columnas era un peor mes rolling de 21 sesiones. Si se necesitara un criterio rolling, debe etiquetarse aparte como peor ventana movil de 21 sesiones.

## Parte 2 - Gate de agresividad

Regla nueva: una propuesta que aumente agresividad operativa no puede pasar a `READY_TO_APPLY` sin un experimento enlazado `PASSED` con evidencia de edge forward neto positivo de costes, medida como expectancy/alpha/edge/excess positivo en metrica neta, after-cost, forward u OOS.

Parametros directos cubiertos:

- `max_daily_buy_orders`: subir aumenta agresividad.
- `max_orders_per_cycle`: subir aumenta agresividad.
- `trade_selection_top_n`: subir aumenta agresividad.
- `trade_aggressiveness_profile`: mover a perfil mas agresivo aumenta agresividad.

Analogos encontrados en `Settings` y criterio:

- `min_order_notional`, `min_llm_confidence_to_trade`, `entry_quality_min_score`: bajar aumenta agresividad.
- `entry_quality_max_rsi`, `entry_quality_max_sma20_distance`: subir aumenta agresividad.
- Familia `entry_quality_*_min_score`, `entry_quality_*_min_rsi`, `entry_quality_*_min_return`, `entry_quality_*_min_relative_return`, `entry_quality_*_min_volume_z`: bajar relaja entrada.
- Familia `entry_quality_*_max_rsi`, `entry_quality_*_max_sma20_distance`, `entry_quality_*_max_selection_rank`, `entry_quality_*_max_volume_z`: subir relaja entrada.
- `max_risk_per_trade`, `risk_off_buy_factor`, `*_trade_target_exposure_pct`: subir aumenta exposicion o capacidad de compra.

Saneo retroactivo ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\ci_aggressiveness_gate_audit.py
```

Rechazadas por `aggressiveness_requires_edge_evidence`:

- `ci_prop_a490c5529a93` - `max_daily_buy_orders`
- `ci_prop_c22b977d2085` - `max_orders_per_cycle`
- `ci_prop_4a759922e290` - `trade_selection_top_n`

Auditoria `deterministic_gate_error_severity`:

- El codigo ya cubria `deterministic_gate_error_severity` por token `deterministic_gate` en el gate de seguridad.
- La llegada a `READY_TO_APPLY` fue una cola historica previa o no revalidada.
- Se cerro con saneo retroactivo constitucional y test candado.

Rechazadas por saneo constitucional:

- `ci_prop_165fc2e6f882` - `deterministic_gate_error_severity` - `self_safety_modification_forbidden`
- `ci_prop_b0bcaad6345c` - `deterministic_gate_error_severity` - `self_safety_modification_forbidden`
- `ci_prop_862f4196e8a3` - `ci_recurring_cooldown_hours` - `self_governance_modification_forbidden`

## Parte 3 - Digest

Cambios:

- `PIDE APROBACION` ignora artifacts de propuestas con applied change `APPLIED` o `ROLLED_BACK`, y tambien si la propuesta ya tiene status terminal aplicado/revertido.
- `% exp->aplicado` queda definido como `Applied / Experimentos de la semana`, por lo que usa el mismo numerador que la columna `Applied`.

Digest real generado:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 7 --out data\reports\ci_digest_p4_2026-07-02.md
```

Linea verificada para la semana 2026-06-29:

- `Experimentos=146`
- `Applied=1`
- `% exp->aplicado=0.68%`
- `PIDE APROBACION`: no hay propuestas con `READY_FOR_HUMAN_REVIEW` y `tests_ok=true`.

## Verificacion

- Tests focalizados: `12 passed`.
- Suite completa: `863 passed, 1 warning`.
- Lint: `ruff check src tests scripts` sin errores.
- `python -m agente_bolsa.main status`: OK, modo paper.
- `run-once --skip-crew`: OK, sin traceback ni ordenes enviadas.
- Validacion interna de configuracion de agentes: `ok=true`. El comando historico `validate-agent-config --json` no esta registrado en el parser actual.
- Ejecucion real overlay shadow: OK.
- Ejecucion real digest: OK.
- Flags operativos confirmados al cierre: `trading_mode=paper`, `allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- No se han modificado archivos protegidos: `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py`, `.env`.
