# Informe Codex - lote giro hoy

Fecha: 2026-07-07

## Estado

- `G0` completada
- `G1` completada
- `G2` completada
- `G3` completada
- `G4` completada

Version final del repo: `0.4.119`

## Commits por tarea

- `G0` -> `f8c54a4c` -> `fix: harden date-sensitive suite for g0`
- `G1` -> `53764d40092d3ce229a827c0f9c095550819dacd` -> `feat: add learning mode experiment cohort`
- `G2` -> `882f0297` -> `feat: instrument learning experiment loop`
- `G3` -> `09f3cf9d` -> `feat: add weekly learning scoreboard`
- `G4` -> `3a1c6742` -> `fix: harden codegen version bump and test context`

## Informes por tarea

- `docs/informe_codex_g0_suite_2026-07-07.md`
- `docs/informe_codex_pl2_learning_mode_2026-07-07.md`
- `docs/informe_codex_pl3_bucle_2026-07-07.md`
- `docs/informe_codex_pl4_scoreboard_2026-07-07.md`
- `docs/informe_codex_p31_bump_contexto_2026-07-07.md`

## Verificacion final

- `.venv\Scripts\python.exe -m pytest tests -x -q` -> `995 passed, 1 warning`
- `.venv\Scripts\python.exe -m ruff check src tests scripts` -> limpio
- `.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json` -> `ok=true`
- `.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`

## Estado G4 para Antonio

Las tres propuestas P25 quedan listas para revision humana:

- `ci_prop_b3f950033a99` -> `ci_artifact_0f5f1ea3c39f`
- `ci_prop_0327e166f163` -> `ci_artifact_6fbd8a753e50`
- `ci_prop_82a01dd92356` -> `ci_artifact_aa50bbd64b02`

No se ha ejecutado `approve`.

## Comandos exactos para Antonio

Ver cambios por tarea:

- `git show --stat f8c54a4c`
- `git show --stat 53764d40092d3ce229a827c0f9c095550819dacd`
- `git show --stat 882f0297`
- `git show --stat 09f3cf9d`
- `git show --stat 3a1c6742`

Leer informes:

- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_g0_suite_2026-07-07.md`
- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_pl2_learning_mode_2026-07-07.md`
- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_pl3_bucle_2026-07-07.md`
- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_pl4_scoreboard_2026-07-07.md`
- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_p31_bump_contexto_2026-07-07.md`
- `Get-Content C:\Antonio\Bref\agenteBolsa\docs\informe_codex_lote_giro_hoy_2026-07-07.md`

Revisar propuestas G4:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_b3f950033a99`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_0327e166f163`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_82a01dd92356`

Aprobar manualmente si procede:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_b3f950033a99 --actor Antonio`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_0327e166f163 --actor Antonio`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_82a01dd92356 --actor Antonio`
