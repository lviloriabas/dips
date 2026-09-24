@echo off
rem Auditor de DIPs: arrastre el Excel de entrada sobre este archivo.
rem Por defecto usa solo el Excel. Con --icam lee en ICAM todos los DIPs del archivo
rem (si se lo pide, inicie sesion en la ventana de Edge).
rem Uso en consola: auditar.bat "entrada.xlsx" [--icam] [--fecha ...] [...]
rem Parametros: -i/--icam, -c/--categorias, -e/--excluir-categorias, --hoja, ...
rem (ver: python -m dips_audit auditar --help)
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel de entrada sobre este archivo, o ejecute:
    echo     auditar.bat "entrada.xlsx" [--icam]
    pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit auditar %*
pause
