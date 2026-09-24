@echo off
rem Auditor de DIPs: arrastre el Excel de entrada sobre este archivo.
rem Lee en ICAM los DIPs del archivo (antes abra abrir_icam.bat e inicie sesion).
rem Uso en consola: auditar.bat "entrada.xlsx" [--sin-icam] [--hoja NOMBRE] [--llm]
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel de entrada sobre este archivo, o ejecute:
    echo     auditar.bat "entrada.xlsx" [--sin-icam]
    pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit auditar %* --leer-icam
pause
