@echo off
rem Benchmark del auditor: audita los DIPs de benchmark\dips_auditados.xlsx y
rem compara con benchmark\linea_base.json. Tarda unos segundos.
rem El resultado queda en benchmark\resultados\.
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit benchmark
set "CODIGO=%ERRORLEVEL%"
pause
exit /b %CODIGO%
