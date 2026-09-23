@echo off
rem Auditor de DIPs: arrastre el Excel de entrada sobre este archivo.
rem Uso en consola: auditar.bat "entrada.xlsx" [--llm] [--hoja NOMBRE]
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel de entrada sobre este archivo, o ejecute:
    echo     auditar.bat "ruta\export.xlsx" [--llm]
    pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit auditar %*
pause
