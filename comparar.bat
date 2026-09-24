@echo off
rem Compara el programa con la auditoria manual: arrastre el Excel "DIPs Audit (...)" sobre este archivo.
rem Lee en ICAM los DIPs del archivo (antes abra abrir_icam.bat e inicie sesion).
rem Uso en consola: comparar.bat "DIPs Audit (23SEP2026).xlsx" [--hoja NOMBRE]
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel "DIPs Audit (...)" sobre este archivo, o ejecute:
    echo     comparar.bat "DIPs Audit (23SEP2026).xlsx"
    pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit comparar %* --leer-icam
pause
