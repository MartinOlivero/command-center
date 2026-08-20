@echo off
REM Abrir panel.bat - doble clic para levantar el panel ya instalado.

cd /d "%~dp0"

if not exist ".env" (
  echo.
  echo   Todavia no esta instalado: hace doble clic en "Instalar.bat" primero.
  echo.
  pause
  exit /b 1
)

where python >nul 2>&1 && (set PY=python) || (set PY=py)

echo.
echo   Abriendo el panel... (se abre solo en el navegador)
echo   Deja esta ventana abierta. Para cerrarlo: Ctrl+C
echo.

%PY% servidor.py

echo.
pause
