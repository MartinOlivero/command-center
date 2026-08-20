#!/bin/bash
# Actualizar.command — doble clic para traer la última versión del panel.
#
# Reemplaza SOLO el código. Tus credenciales, tu configuración y tu histórico
# quedan intactos: son archivos que ni siquiera viajan en la descarga.

cd "$(dirname "$0")" || exit 1

python3 instalar.py --actualizar

printf '\n'
read -r -p '  Enter para cerrar esta ventana... '
