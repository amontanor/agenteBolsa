# ============================================================================
# Commit unico del plan de autonomia (Etapas 0-4).
# Anade SOLO los archivos creados/editados por el plan, dejando intactos los
# ~67 archivos modificados/untracked previos que NO forman parte del plan.
#
# Uso:
#   1) Cierra cualquier proceso git abierto.
#   2) Desde C:\Antonio\Bref\agenteBolsa  ->  .\commit_autonomia.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

# --- 0) Quitar el lock colgado y asegurar identidad de git -----------------
if (Test-Path ".git\index.lock") {
    Remove-Item ".git\index.lock" -Force
    Write-Host "Lock .git/index.lock eliminado."
}
if (-not (git config user.name))  { git config user.name  "Antonio" }
if (-not (git config user.email)) { git config user.email "amontanor@gmail.com" }

# --- 1) Archivos NUEVOS del plan (100% del plan) ---------------------------
$nuevos = @(
    "src/agente_bolsa/kernel.py",
    "src/agente_bolsa/prompt_store.py",
    "src/agente_bolsa/risk_budget.py",
    "src/agente_bolsa/strategies",
    "src/agente_bolsa/continuous_improvement/autonomy.py",
    "src/agente_bolsa/continuous_improvement/dynamic_agents.py",
    "src/agente_bolsa/continuous_improvement/lesson_distiller.py",
    "src/agente_bolsa/continuous_improvement/promotion.py",
    "src/agente_bolsa/continuous_improvement/repo_context.py",
    "src/agente_bolsa/continuous_improvement/sandbox.py",
    "src/agente_bolsa/continuous_improvement/strategy_builder.py",
    "src/agente_bolsa/tools/autonomy_digest.py",
    "src/agente_bolsa/tools/change_watchdog.py",
    "src/agente_bolsa/tools/hypothesis_factory.py",
    "src/agente_bolsa/tools/macro_context.py",
    "src/agente_bolsa/tools/nightly_retrospective.py",
    "src/agente_bolsa/tools/pattern_scorecard.py",
    "src/agente_bolsa/tools/performance_baseline.py",
    "src/agente_bolsa/tools/prompt_replay.py",
    "tests/test_autonomy_digest.py",
    "tests/test_autonomy_tiers.py",
    "tests/test_change_watchdog.py",
    "tests/test_ci_sandbox.py",
    "tests/test_dynamic_agents.py",
    "tests/test_hypothesis_factory.py",
    "tests/test_kernel.py",
    "tests/test_lesson_distiller.py",
    "tests/test_live_readiness_path.py",
    "tests/test_macro_context.py",
    "tests/test_nightly_retrospective.py",
    "tests/test_pattern_scorecard.py",
    "tests/test_performance_baseline.py",
    "tests/test_programmer_flow.py",
    "tests/test_promotion.py",
    "tests/test_prompt_store.py",
    "tests/test_risk_budget.py",
    "tests/test_strategy_registry.py"
)

# --- 2) Archivos EXISTENTES editados por el plan ---------------------------
#     (tambien contienen cambios tuyos previos; van completos, como acordamos)
$editados = @(
    ".gitignore",
    ".env.example",
    "README.md",
    "docs/architecture.md",
    "src/agente_bolsa/config.py",
    "src/agente_bolsa/storage.py",
    "src/agente_bolsa/main.py",
    "src/agente_bolsa/scheduler.py",
    "src/agente_bolsa/llm_router.py",
    "src/agente_bolsa/llm_usage.py",
    "src/agente_bolsa/eventing.py",
    "src/agente_bolsa/web_app.py",
    "src/agente_bolsa/continuous_improvement/agents.py",
    "src/agente_bolsa/continuous_improvement/experiments.py",
    "src/agente_bolsa/continuous_improvement/runtime.py",
    "src/agente_bolsa/tools/execution.py",
    "src/agente_bolsa/tools/operational_health.py",
    "src/agente_bolsa/tools/trade_decision.py",
    "src/agente_bolsa/tools/news_sentiment.py",
    "src/agente_bolsa/tools/technical_study.py",
    "src/agente_bolsa/tools/live_readiness.py",
    "src/agente_bolsa/tools/command_catalog.py",
    "src/agente_bolsa/tools/counterfactual_analysis.py",
    "src/agente_bolsa/tools/portfolio_optimizer.py",
    "src/agente_bolsa/tools/retention.py",
    "tests/test_llm_router.py",
    "tests/test_market_data.py"
)

# --- 3) Stage explicito (nada fuera de estas listas) -----------------------
foreach ($f in ($nuevos + $editados)) {
    if (Test-Path $f) { git add -- $f }
    else { Write-Warning "No existe (omitido): $f" }
}

Write-Host "`n=== Archivos que se van a commitear ===" -ForegroundColor Cyan
git status --short | Select-String '^[AM]'

# --- 4) Commit unico --------------------------------------------------------
$msg = @"
feat: plan de autonomia del grupo de agentes (Etapas 0-4)

Implementa el plan completo de autonomia sobre el sistema de trading:

Etapa 0 - Kernel, medicion y sandbox:
  T0.1 kernel inmutable; T0.2 baseline e iq_score; T0.3 sandbox git real;
  T0.4 router LLM por roles; T0.5 watchdog de rollback por metricas.
Etapa 1 - Autonomia de codigo:
  T1.1 niveles de autonomia; T1.2 estrategias plugables; T1.3 champion/
  challenger con promocion; T1.4 ProgrammerAgent end-to-end.
Etapa 2 - Agentes que se mejoran:
  T2.1 prompts versionados con replay; T2.2 fabrica de agentes dinamicos;
  T2.3 retrospectiva generativa nocturna; T2.4 memoria destilada.
Etapa 3 - Comprension del mercado:
  T3.1 tesis de mercado viva; T3.2 fabrica de hipotesis + backtests en lote;
  T3.3 scorecard de figuras con pesos dinamicos.
Etapa 4 - Gobierno por riesgo y camino a live:
  T4.1 presupuesto de riesgo; T4.2 dashboard de autonomia y freno humano;
  T4.3 camino a live con capital progresivo.
"@

git commit -m $msg

Write-Host "`nCommit creado. Revisa con: git show --stat HEAD" -ForegroundColor Green
