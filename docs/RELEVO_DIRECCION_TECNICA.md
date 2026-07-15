# Relevo de dirección técnica — agenteBolsa

> Última actualización: **14-jul-2026** · Versión **0.4.172** · Release nocturno P-L41D.

## Estado operativo

- Solo paper; live y auto-apply de mejoras permanecen desactivados.
- El scheduler, postmarket, health, locks y digest están conectados. P-L34BR confirmó la suite completa: 1.248 passed en aproximadamente 215 segundos.
- Los instrumentos prospectivos P-L27/P-L29/P-L30/P-L31/P-L32/P-L33 permanecen `collecting`; P-L37B y P-L40B comienzan su captura prospectiva tras este release. No interpretar ausencia de registros como rendimiento cero.
- P-L35B está **deferred**, no rechazado ni autorizado: reconsiderar cuando haya una investigación `ready_for_analysis` o tras la primera revisión de madurez de P-L27D.
- P-L37A quedó `partially_verified_capture`; P-L37B está integrado con historial de capturas append-only y resolución exacta.
- P-L40A permanece `insufficient_sample`/`lower_return_with_lower_risk`/`data_quality_blocked`: la ventana 7–13 jul fue cuenta −0,0401%, SPY +0,1953%, exceso −0,2354 pp. No se ha demostrado edge frente a SPY.
- P-L40B publica benchmark diario como observabilidad. `exposure-matched` y `cash_drag` siguen `unavailable` hasta disponer de exposición temporal; no hay backfill.
- P-L41R/P-L41D integra y despliega ambos lotes secuencialmente, sin cambios de trading ni de `adaptive_config.json`.

## Capacidades entregadas P-L17–P-L34B

- Outcomes honestos y scoreboard, con madurez por sesiones XNYS.
- Identidad canónica por captura (`signal_capture_id`) con historial append-only, resolución exacta y propagación hasta observaciones.
- Benchmark diario `p-l40b.performance-benchmark.v1` con un único snapshot de cartera, SPY desde caché local, payload completo, alpha persistido y conflictos auditables.
- Integración postmarket de identidad y benchmark fail-open, con exposición EOD separada de media temporal y compatibilidad legacy.
- Linaje de decisión y controles contemporáneos verificables.
- Contratos de evidencia y atribución de origen para propuestas nuevas.
- Postmarket, timings, locks, heartbeats, digest y health operacional.
- Corrección MFE/MAE: las métricas R v1 son dimensionalmente inválidas; usar sólo esquema v2.
- Cohorte RR prospectiva, con primera madurez posible el 27-jul-2026, no evaluación completa.
- Telemetría `agent_run`, contexto de decisión, controles comparables, ledger de gates y calidad de ejecución prospectiva.
- Publicación postmarket de calidad de gates, tolerante a fallos y separada de trading.

## Agenda y pausa técnica

No añadir instrumentos analíticos ni cambios funcionales salvo fallos reproducibles o alertas críticas. No modificar estrategias, gates, ranking, stops, exposición, límites ni trading.

- 13-jul-2026: primera sesión prospectiva completa; observar.
- 14-jul-2026: revisar ciclo, snapshots, controles, gates, ejecución, postmarket, digest y health.
- 20-jul-2026: P-L25 `builtin_pullback` con criterios pre-registrados e inmutables.
- 27-jul-2026: primera madurez RR técnicamente posible; no equivale a evaluación completa.
- Tras muestra suficiente: análisis de controles, gates y ejecución.
- Tras 45 días de `agent_run`: evaluar roles antes de reorganizar agentes.
- 1-sep-2026: `learning_confirmed` o `learning_not_confirmed` con criterio original.

Prioridades activas: `builtin_pullback`, reward/risk prospectivo y selección/gates/ejecución. El resto permanece backlog, no consume WIP de análisis ni activa LLM.

## Equipo autónomo objetivo

Las funciones objetivo son DataQualityObserver, MarketOutcomeAnalyst, ResearchPortfolioManager, HypothesisDesigner, EvidenceValidator, AdversarialReviewer y SafetyGuardian. No crean 16 agentes nuevos: las tareas deterministas no usan LLM; ningún rol formula, valida, aprueba y evalúa por sí solo. Apply y cambios sensibles continúan siendo humanos.

El objetivo no es producir más propuestas: es mayor expectativa neta, menor drawdown y pérdidas extremas, decisiones demostrablemente mejores y autonomía con evidencia y seguridad.

## Reglas de seguridad y promoción

- Mantener paper, archivos protegidos y apply humano.
- Mantener dos admisiones nuevas/día, WIP nuevo dos y un codegen nocturno.
- `unavailable`, linaje/control insuficiente o concentración excesiva impiden promoción.
- No promover mejoras que empeoren drawdown, MAE o tail loss aunque aumenten retorno.
- Los criterios se congelan antes de observar resultados.

## Operación vigente

Usar `status`, `validate-agent-config --json`, `kernel-status --json`, `schedule-status`, `operational-health --json` y `scripts\check_services.ps1`. Reiniciar servicios sólo tras código/configuración cargada. El plan maestro `docs/plan_mejoras_y_tareas.md` es la fuente única de tareas; no crear un segundo plan.

## P-L43B — estado del candidato shadow (15-jul-2026)

- P-L43BR4 desplegó en producción la versión `0.4.173` mediante merge no destructivo.
- `legacy_calendar_days` es la única ruta activa de `time_stop_v2`; XNYS es exclusivamente shadow.
- La evidencia histórica usa eventos append-only por `position_identity` y `shadow_observation_id`; `runtime_state` es `latest_view`.
- Los datos prospectivos reales permanecen `collecting`; la activación XNYS requiere autorización humana y otro lote.

## P-L44BR2 — ensayo de integración shadow (15-jul-2026)

- El candidato `0.4.174` integra P-L44B sobre P-L43B desplegado mediante un
  merge no destructivo en un worktree aislado.
- `legacy_double_application` sigue activa; `single_application` es sólo
  shadow y los datos reales permanecen `collecting`.
- Dictamen del ensayo: `ready_for_future_shadow_deployment`; producción no se
  modificó ni reinició.
