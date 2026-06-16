@echo off
REM Lanzador manual del scheduler de agenteBolsa en una ventana normal.
REM Mantiene el proceso vivo mientras la ventana este abierta. Para arranque
REM persistente (sobrevive al cierre de ventana) usa scripts\install_scheduler_task.ps1
cd /d C:\Antonio\Bref\agenteBolsa
".\.venv\Scripts\python.exe" -m agente_bolsa.main schedule
pause
