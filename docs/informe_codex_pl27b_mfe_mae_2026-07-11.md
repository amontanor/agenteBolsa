# Informe P-L27B — auditoría MFE/MAE y geometría stop/take

Fecha: 2026-07-11
Versión: 0.4.153
Commit de partida: 9fedb90b

## Resultado

Se añadió el comando solo lectura `excursion-quality-report`. Lee
`signal_outcomes` sin crear experimentos, alterar históricos ni escribir
artefactos. Su JSON tiene schema `p-l27b.excursion-quality.v1`, incluye los
parámetros de fecha/horizonte/muestra y un `content_hash` determinista. La
ventana por defecto es la reciente; `--historical` solicita explícitamente todo
el historial disponible.

## Definiciones y límites

`risk_distance = entry_price - stop_loss`, `reward_distance = take_profit -
entry_price`, `stop_distance_pct = risk_distance / entry_price`,
`take_distance_pct = reward_distance / entry_price`, `reward_risk_ratio =
reward_distance / risk_distance`, `mae_r = abs(min(mae, 0)) / risk_distance`,
`mfe_r = max(mfe, 0) / risk_distance`, `target_attainment = mfe_r /
reward_risk_ratio`. MFE/MAE son fracciones decimales respecto a la entrada,
producidas por `signal_learning.py`, y actualmente corresponden a la ventana
10d; por ello no se reinterpretan como excursiones 1d/3d/5d. La geometría se
evalúa para señales long; señales no-long se conservan como exclusión auditable
porque el productor actual no publica excursiones direccionales comparables.
No se calculan alpha, exceso frente a SPY, causalidad, significancia ni
drawdown de cartera: no hay datos locales suficientes para ello.

## Lectura local determinista

Ejecución: `excursion-quality-report --from 2026-06-01 --to 2026-07-10
--min-sample 300 --json`.

- 328.266 filas seleccionadas; 582.007 observaciones maduras por horizonte
  (una fila puede aportar varios horizontes), 11.149 inmaduras y 80.471
  excluidas por `direction_not_long`.
- Cobertura válida sobre maduras: 1.0; imputaciones: 0; linaje: 582.007
  `legacy_unverified`, 0 verificadas.
- 1d: n=148.289, media/mediana retorno -0,000116/-0,001600, MFE medio
  0,063059, MAE medio -0,051997.
- 3d: n=148.289, media/mediana -0,000922/-0,000100.
- 5d: n=145.749, media/mediana 0,002992/0,005400.
- 10d: n=139.680, media/mediana 0,009844/0,015900.
- En los cuatro horizontes la geometría reward/risk mediana es 1,5 y el
  estado es `evaluable` con la muestra mínima 300.

Estas cifras describen retornos forward y excursiones de señales, no profits
ejecutados ni una mejora de trading.

## Compatibilidad y seguridad

Los registros históricos no se reescriben ni se rellenan. La salida distingue
madurez, exclusiones, cobertura, concentración temporal/simbólica y deuda de
linaje. No se tocaron estrategias, señales, ranking, gates, órdenes, exposición,
horarios, timeouts ni archivos protegidos. El límite de dos admisiones diarias,
WIP nuevo máximo dos, un codegen nocturno y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
permanece sin cambios; este informe no admite propuestas ni puede aplicar código.

## Pruebas

`tests/test_excursion_quality.py` cubre geometría completa, fórmulas, campos
ausentes/no numéricos, inmadurez, filtros de fechas/horizonte, vista histórica,
muestra mínima, argumentos inválidos, salida `unavailable` y ausencia de
mutaciones. No llama a red ni a LLM. La suite completa y los gates operativos se
registran en la entrega del commit.

La siguiente hipótesis de investigación queda deliberadamente fuera de P-L27B.
