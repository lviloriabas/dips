@echo off
rem Instala todo lo necesario para el Auditor de DIPs (ver setup.ps1 para opciones).
rem   setup.bat               instalacion completa
rem   setup.bat -SinPruebas   sin correr las pruebas al final
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set CODIGO=%ERRORLEVEL%
pause
exit /b %CODIGO%
