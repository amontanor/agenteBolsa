# Restauración del contrato scoreboard v3 — 8-oct-2026

Dictamen `partially_verified_scoreboard_contract_candidate`, N2, no desplegado.
La reconstrucción Jetson 784e6cd7 retiró capacidades P-L131/P-L132 del productor
sin actualizar sus pruebas: schema 2, calibración y cobertura semanal ausentes.
El fallo schema 2 != 3 apareció en la validación integrada: 691 passed, 1 failed.
No se corrige sólo una etiqueta ni se vuelve al matching legacy por fecha/fuente.

Base del lote e0c908647cedb110b1cfbefa8618ff3f51b39912, rama
codex/oct08-scoreboard-contract, worktree bolsa-scoreboard-contract-oct08.
Implementación 251c1fd1, QA 1ff558d7c3766bfaa9ab55c8c975a27cf362dec8,
tree probado b179f7c993cce32c4710e20c42d3c2e427d40194. Versión reservada 0.4.343,
separada de la candidata .342; producción sigue .321. Sin push ni despliegue.

Se restaura calibración explícita por mediana de signal_to_fill_bps, al menos
diez muestras finitas numéricas no booleanas, |bps| <= 200; sin muestra suficiente
se conservan bandas asumidas 10/20 bps y columna calibrada unavailable. El informe
declara cost_calibration, campos semanales de costes y cobertura matched/unmatched
con denominador maduro. No cambia criterio de promoción, órdenes, política activa,
riesgo, kernel, configuración ni esquema SQLite. Los retornos siguen dirección
canónica; trade_memory, inmaduros y dirección ausente siguen excluidos. La
calibración representa la métrica de fills observada, no certifica coste total.

Se conserva sin cambios el matching por comparable_control_set verified, IDs de
señal y ciclo exactos y elegibilidad de capacidad. Fixtures históricos carecían
de dirección y de contratos explícitos; se actualizan sus datos sintéticos, no
se permite que producción infiera esas identidades. Caso negativo nuevo confirma
que compartir ciclo sin contrato verificado no produce controles comparables.

QA: 16 passed in 3.28s sobre test_learning_scoreboard.py,
test_p131_calibrated_costs.py y test_p132_same_cycle_controls.py. Incluye short
con retorno firmado, missing incluso con fills calibrados, valores inválidos,
inmutabilidad, bandas legacy y muestras insuficientes. Ruff focal y diff verdes.
Sólo Python del proyecto, PYTHONPATH exacto, Settings(_env_file=None), SQLite y
DATA_DIR temporales; benchmark local mockeado. Sin broker, red, LLM ni producción
desde tests. La primera caracterización del productor restaurado frente a
fixtures antiguos dio 8 failed/4 passed por dirección y contratos ausentes;
no se ocultaron con skip/xfail. Suite completa integrada sigue pendiente.

La recuperación operativa anterior y sus recibos pertenecen al informe de
integración; este lote no vuelve a limpiar leases ni modifica históricos.
