@echo off
REM Actualizar.bat - doble clic para traer la ultima version del panel.
REM
REM Reemplaza SOLO el codigo. Tus credenciales, tu configuracion y tu historico
REM quedan intactos: son archivos que ni siquiera viajan en la descarga.

cd /d "%~dp0"

where python >nul 2>&1 && (set PY=python) || (set PY=py)

%PY% instalar.py --actualizar

echo.
pause
