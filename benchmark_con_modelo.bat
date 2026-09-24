@echo off
rem Benchmark del auditor CON modelo local: audita los DIPs de
rem benchmark\dips_auditados.xlsx con reglas y modelo local (como auditar.bat --llm),
rem mide al modelo con benchmark\casos_modelo_local.yaml y compara con
rem benchmark\linea_base_con_modelo.json. Necesita Ollama; en CPU tarda unos 33 min.
rem El resultado queda en benchmark\resultados\con_modelo\.
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit benchmark con-modelo
set "CODIGO=%ERRORLEVEL%"
pause
exit /b %CODIGO%
