@echo off
echo Instalando dependencias faltantes en el venv...
cd /d "%~dp0"
.venv\Scripts\pip install "lxml>=5.0.0"
echo.
echo Listo. Puedes cerrar esta ventana.
pause
