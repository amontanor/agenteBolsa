# Auditoría de salidas y próximos pasos, 7 de octubre de 2026

Dictamen provisional: candidato N2 para validación con mercado cerrado, sin despliegue. Se registra por qué se descarta una salida sin cambiar la política, planes, cantidades, límites ni órdenes. La rentabilidad adicional sigue siendo una hipótesis; estos cambios mejoran integridad y diagnóstico.

## Identidad y alcance

Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`, versión de base 0.4.321; rama `codex/oct07-exit-audit`. Worktree aislado `C:/Users/utopi/.codex/worktrees/bolsa-exit-audit-oct07/agenteBolsa`. La versión global sigue siendo la de base: no es una release y necesita reserva de versión antes de integración. Existe evidencia local de una línea .340 que no coincide con la imagen productiva observada .321; resolver esta divergencia precede a cualquier despliegue.

## Hallazgos y cambio

El constructor de planes descartaba silenciosamente salidas por capacidad, orden abierta, confianza, posición ausente, política excepcional, reducción innecesaria o precisión de cantidad. Ahora ofrece un carrier opcional `exit_rejections` separado de `rejected` y el ciclo emite el evento `exit_plan_rejections`. La emisión es fail-open: una excepción al registrar no cambia los planes. La capacidad agotada se etiqueta como política de salida no evaluada; no se afirma que el resto de gates hubiese pasado.

La revisión independiente rechazó la primera propuesta de reutilizar `rejected_order_plans`: `gate_evaluation`, `signal_learning` y `daily_learning` pueden unir por señal o símbolo y contaminar una compra con el rechazo de una salida. Esa propuesta no se integra. El carrier final no entra en retornos, gates, aprendizaje ni atribución existentes. Los IDs se copian de la recomendación/linaje explícitos; no se reconstruyen por símbolo y fecha. Las recomendaciones ausentes conservan identidad ausente.

## APO: hecho y límite de atribución

Consulta al broker a las 18:17:30Z: siete acciones APO, precio 115.32, P/L abierto -155.61 USD. Segunda consulta a las 18:29:02Z confirma siete acciones, cero órdenes OPEN con `nested=True` y origen local ausente mediante SELECT en conexión `mode=ro/query_only`; precio 115.19 y P/L abierto -156.52 USD. El vigilante necesita ese origen para recuperar stop/take y omite símbolos sin él. Esto demuestra una carencia de protección en las rutas comprobadas, no el origen de la posición ni una autorización para inventar niveles o vincular compras por coincidencias.

Configuración efectiva consultada: confianza general mínima 0.65, excepcional 0.95, drawdown excepcional 0.08. La recomendación `rec_5260f35b8e77` tiene confianza 0.58: no pasa el umbral general. Una reproducción local de la política textual con posición sintética también detecta `rotacion` en «no es rotacion» y devuelve `ordinary_rotation_or_capital_release`. Otras recomendaciones pasan 0.65 pero no 0.95. No se afirma que esto sea un replay completo del ciclo: la capacidad y cartera históricas completas no se han reconstruido.

No se modifica el veto textual ni la confianza para hacer ejecutables esas recomendaciones. La solución requiere evidencia estructurada de riesgo y revisión de la frontera de ejecución. Recuperar origen exige IDs exactos de broker/plan; si no existen, conservar `unavailable` y diseñar el tratamiento explícito de posiciones heredadas. No reescribir históricos.

## Validación aislada

Python del proyecto, `PYTHONPATH` de este worktree, Settings nuevos con `_env_file=None` y DATA_DIR temporal en los tests nuevos; sin broker, red, LLM ni datos productivos. La regresión histórica conserva sus fixtures originales.

- Caracterización inicial: ocho fallos y un caso de paridad pasando sobre la base. Se corrigió posteriormente el fixture de precisión a menos de nueve decimales; no se atribuye su primera falla al producto.
- Final focal: 38 passed, 125 deselected: tests nuevos, `test_trade_decision.py` filtrado por `build_order_plans`, `test_cycle_runner_summary.py` y la nueva prueba del wiring en `test_market_cycle_timing_integration.py`.
- Incluye salida admitida con economía idéntica, IDs ausentes, rechazo por cada frontera cubierta y BUY/EXIT con señal compartida sin contaminación del carrier BUY.
- Ruff focal, NUL (538 archivos) y diff verdes.
- Wiring real `_auto_paper_trade` con dobles: sink vacío, emisión normal y emisión fallida conservan resultado, secuencia y economía/IDs de la orden enviada; gates y actualización del aprendizaje reciben siempre el carrier BUY sin filas EXIT.
- Ampliación de integración: 52 passed y 1 failed (`test_economic_parity_true_false_none_identical_payloads`, `rec_payloads` distintos entre True/False). Mismo fallo reproducido en el worktree postmarket, cuyo `cycle_runner.py` es idéntico al de la base exacta. No se corrige ni oculta esta deuda en el lote.
- Pendientes: integración y paridad completa del ciclo, suite completa/gates de release y versión. Los focales no equivalen a readiness de despliegue.

## Secuencia autorizada

1. Validación aislada esta noche a las 23:00 Europe/Madrid, solo si XNYS cerrado, postmarket terminal y sin jobs/reintentos/leases activos. Automatización `validar-mejoras-bolsa-tras-cierre`. No despliega ni reinicia; pausa tras el intento.
2. Integridad postmarket en lote separado: [informe](C:/Users/utopi/.codex/worktrees/bolsa-oct07-321/agenteBolsa/docs/informe_oct07_postmarket.md). Guard probado con 24 tests; no resuelve por sí mismo el fallo de adquisición de cartera.
3. Auditar origen/protección de APO y diseñar criterios estructurados de salida, conservando gates. No aumentar exposición para compensar pérdidas.
4. Medir latencia por etapa/proveedor y clasificar 402/saldo frente a indisponibilidad transitoria. No desactivar todo fallback: el reintento observado cambia de endpoint; aún falta evidencia para fijar un presupuesto sin alterar la ruta activa.
5. Corregir denominadores en lote separado: `symbols_with_data` usa número de candidatos, que puede superar símbolos por múltiples estrategias. Mantener número de candidatos y cobertura de símbolos como conceptos distintos; no tocar ahora consumidores operativos sin caracterización.
6. Evaluar oportunidades en simulación: cohortes prospectivas de descartados y admitidos del mismo instante, controles comparables, costes, pérdidas evitadas, exposición, drawdown/MAE y colas. No optimizar reglas sobre HPE/CIEN ni llamar beneficio ejecutable a sus diferencias de precio. Sin controles suficientes, estado `collecting`, sin promoción.
7. Revisión el lunes 12 de octubre a las 10:00 Europe/Madrid, sesiones completadas 5–9 de octubre; comparar con auditoría del 7, separar equity/flujos/P&L realizado/abierto y usar SPY con ventanas y autoridad temporal comparables. Automatización `revisar-bolsa-el-12-de-octubre`; solo lectura y pausa tras entregar.

Producción permanece sin cambios. Ningún archivo protegido, configuración, histórico o límite de riesgo modificado. No hay merge productivo, órdenes, reinicios ni despliegue en este lote.

## Cierre de revisión

Revisión independiente final: `ready_for_integration_rehearsal`, sin bloqueantes nuevos. Se comprobaron consumidor/evento, separación BUY/EXIT y la prueba de fallo de emisión. Gates completos de release siguen pendientes; no se interpreta el fallo de base como aprobado.

Commits separados: caracterización `f4931e13`; implementación `2ed53d1e`; QA `12e61e1634bff0686a34a05fc87adf2b107ce6dd`, tree `5ae76444df1b937a5a29fb2c0c4bd8271ccbd887`. Documentación posterior no modifica los bytes funcionales probados. No hay bump ni release con el mismo número que producción. Se desactivó únicamente el mantenimiento automático de Git en cada comando de commit para evitar la referencia ajena inválida observada; no se reparó esa referencia.
