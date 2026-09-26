@echo off
rem Compara el programa con la auditoria manual: arrastre el Excel "DIPs Audit (...)" sobre este archivo.
rem Por defecto usa solo el Excel. Con --icam lee en ICAM todos los DIPs del archivo
rem (si se lo pide, inicie sesion en la ventana de Edge).
rem Uso en consola: comparar.bat "DIPs Audit (23SEP2026).xlsx" [--icam] [--hoja NOMBRE] [...]
rem Parametros: -i/--icam, -c/--categorias, -e/--excluir-categorias, --hoja, ...
rem (ver: python -m dips_audit comparar --help)
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel "DIPs Audit (...)" sobre este archivo, o ejecute:
    echo     comparar.bat "DIPs Audit (23SEP2026).xlsx" [--icam]
    "%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit comparar %*
set CODIGO=%ERRORLEVEL%
rem Espera una tecla solo si la ventana se abrio al arrastrar o con doble clic (desde el Explorador).
"%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
exit /b %CODIGO%
