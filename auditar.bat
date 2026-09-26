@echo off
rem Auditor de DIPs: arrastre el Excel de entrada sobre este archivo.
rem Por defecto usa solo el Excel. Con --icam lee en ICAM todos los DIPs del archivo
rem (si se lo pide, inicie sesion en la ventana de Edge).
rem Uso en consola: auditar.bat "entrada.xlsx" [--icam] [--fecha ...] [...]
rem Parametros: -i/--icam, -c/--categorias, -e/--excluir-categorias, --hoja, ...
rem (ver: python -m dips_audit auditar --help)
rem Un solo DIP, sin Excel: auditar.bat T40S0099V9C [T40S...] [--fecha ...]
rem (lo lee en ICAM y muestra el resultado en consola, sin generar archivos)
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
if "%~1"=="" (
    echo Arrastre el Excel de entrada sobre este archivo, o ejecute:
    echo     auditar.bat "entrada.xlsx" [--icam]
    echo     auditar.bat T40S0099V9C      ^(un solo DIP, desde ICAM^)
    "%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
    exit /b 1
)
if not exist "%~1" goto barcode
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit auditar %*
set CODIGO=%ERRORLEVEL%
goto fin
:barcode
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit barcode %*
set CODIGO=%ERRORLEVEL%
:fin
rem Espera una tecla solo si la ventana se abrio al arrastrar o con doble clic (desde el Explorador).
"%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
exit /b %CODIGO%
