@echo off
setlocal
chcp 65001 >nul
set "DIPS_RAIZ=%~dp0.."
if not exist "%DIPS_RAIZ%\.venv\Scripts\python.exe" (
    echo Primero ejecute setup.bat desde la carpeta DIPS.
    pause
    exit /b 1
)
"%DIPS_RAIZ%\.venv\Scripts\python.exe" "%~dp0generar_regla.py" %*
set "DIPS_CODIGO=%ERRORLEVEL%"
"%DIPS_RAIZ%\.venv\Scripts\python.exe" "%DIPS_RAIZ%\dips_audit\pausa.py" && pause
exit /b %DIPS_CODIGO%
