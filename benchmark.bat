@echo off
rem Benchmark del auditor: audita los DIPs de benchmark\dips_auditados.xlsx y
rem compara el resultado con el veredicto del auditor y con la linea base.
rem Uso: doble clic, o en consola: benchmark.bat [--llm] [--guardar-linea-base]
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit benchmark %*
set "CODIGO=%ERRORLEVEL%"
pause
exit /b %CODIGO%
