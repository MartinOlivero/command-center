#!/bin/bash
# Abrir panel.command — doble clic para levantar el panel ya instalado.
#
# Levanta un servidor local y abre el navegador solo. Mientras esta ventana esté
# abierta, el panel funciona; al cerrarla, se apaga. No sale a internet: sirve
# archivos de esta misma carpeta en 127.0.0.1.

cd "$(dirname "$0")" || exit 1

if [ ! -f .env ]; then
  printf '\n  Todavía no está instalado: hacé doble clic en "Instalar.command" primero.\n\n'
  read -r -p '  Enter para cerrar... '
  exit 1
fi

printf '\n  Abriendo el panel... (se abre solo en el navegador)\n'
printf '  Dejá esta ventana abierta. Para cerrarlo: Ctrl+C\n\n'

python3 servidor.py

printf '\n  Panel cerrado.\n'
read -r -p '  Enter para cerrar esta ventana... '
