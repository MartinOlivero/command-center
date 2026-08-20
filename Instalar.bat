@echo off
REM Instalar.bat - doble clic en Windows.
REM
REM Windows puede mostrar una pantalla azul de "Windows protegio tu PC" porque el
REM archivo se descargo de internet: Mas informacion > Ejecutar de todas formas.

cd /d "%~dp0"

echo.
echo   Panel de Metricas - instalacion
echo.

REM En Windows el ejecutable puede llamarse python o py segun como se instalo.
where python >nul 2>&1 && (set PY=python) || (where py >nul 2>&1 && set PY=py)

if "%PY%"=="" (
  echo   Falta Python 3, que es lo unico imprescindible.
  echo.
  echo   Se baja de python.org/downloads
  echo   IMPORTANTE: en el instalador, tildar "Add Python to PATH" antes de seguir.
  echo   Despues volve a hacer doble clic aca.
  echo.
  pause
  exit /b 1
)

%PY% instalar.py

echo.
pause
