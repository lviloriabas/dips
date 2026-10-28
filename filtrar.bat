@echo off
rem Filtra el Excel "DIPs Audit (...)": arrastrelo sobre este archivo.
rem Deja los DIPs ACTV sin "DIP Open Audit User" y los COMPLETE sin "DIP Closed Audit User".
rem Guarda una copia en la subcarpeta filtered del original con " FILTERED" al final del nombre.
rem Uso en consola: filtrar.bat "DIPs Audit (25SEP2026).xlsx"
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
rem Busca una version mas nueva en GitHub y pregunta si se actualiza; si se actualiza, se relanza
rem (en una sola linea: cmd sigue leyendo este archivo y la actualizacion pudo cambiarlo;
rem "call exit /b %%^ERRORLEVEL%%" sale con el codigo de la corrida relanzada).
"%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\actualizar.py" & if errorlevel 3 (set "DIPS_SIN_ACTUALIZAR=1" & call "%~f0" %* & call exit /b %%^ERRORLEVEL%%)
if "%~1"=="" (
    echo Arrastre el Excel "DIPs Audit (...)" sobre este archivo, o ejecute:
    echo     filtrar.bat "DIPs Audit (25SEP2026).xlsx"
    "%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
    exit /b 1
)
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit.filtrar %*
set CODIGO=%ERRORLEVEL%
rem Espera una tecla solo si la ventana se abrio al arrastrar o con doble clic (desde el Explorador).
"%RAIZ%.venv\Scripts\python.exe" "%RAIZ%dips_audit\pausa.py" && pause
exit /b %CODIGO%
