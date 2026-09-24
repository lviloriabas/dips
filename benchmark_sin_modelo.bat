@echo off
rem Benchmark del auditor SIN modelo local: audita los DIPs de
rem benchmark\dips_auditados.xlsx solo con reglas (como auditar.bat sin --llm) y
rem compara con benchmark\linea_base_sin_modelo.json. No necesita Ollama y tarda
rem unos segundos. El resultado queda en benchmark\resultados\sin_modelo\.
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit benchmark sin-modelo
set "CODIGO=%ERRORLEVEL%"
pause
exit /b %CODIGO%
