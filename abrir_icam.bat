@echo off
rem Abre el Edge de ICAM del programa, directo en ICAM. Inicie sesion en esa ventana
rem y dejela abierta: auditar.bat --leer-icam usa esa sesion para leer los DIPs.
chcp 65001 >nul
setlocal
set "RAIZ=%~dp0"
"%RAIZ%.venv\Scripts\python.exe" -m dips_audit abrir-icam
timeout /t 5 >nul
