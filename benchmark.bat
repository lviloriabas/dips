@echo off
rem Benchmark del auditor: audita los DIPs de benchmark\dips_auditados.xlsx con
rem reglas y modelo local, mide al modelo con benchmark\casos_modelo_local.yaml y
rem compara con la linea base. No tiene opciones: se ajusta en config\config.yaml.
rem El resultado queda en benchmark\resultados\ (JSON y Markdown).
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit benchmark
set "CODIGO=%ERRORLEVEL%"
pause
exit /b %CODIGO%
