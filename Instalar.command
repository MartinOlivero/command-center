#!/bin/bash
# Instalar.command — doble clic en macOS.
#
# Un .command es un script que Finder abre en la Terminal al hacerle doble clic.
# Existe para que nadie tenga que saber qué es una terminal ni escribir un comando.
#
# La primera vez macOS puede decir que "Apple no ha podido verificar que no contenga
# software malicioso". Es porque el archivo se descargó de internet, no porque tenga
# algo malo. Se destraba con clic derecho > Abrir, o desde Configuración del Sistema >
# Privacidad y seguridad > "Abrir igualmente".

# Pararse en la carpeta del script, no en la que estaba abierta antes. Sin esto,
# un doble clic desde el Finder corre con el HOME como directorio actual y no
# encuentra ni un solo archivo del panel.
cd "$(dirname "$0")" || exit 1

# Si llegaste hasta acá es porque ya destrabaste ESTE archivo. Los demás vinieron en
# el mismo ZIP y arrastran la misma marca de "descargado de internet", así que sin
# esto habría que repetir el permiso en cada uno: al abrir el panel, al actualizar, y
# en el acceso del Escritorio. Se hace una vez, sobre la carpeta propia y nada más.
xattr -dr com.apple.quarantine . 2>/dev/null

printf '\n  IamAutom Command Center — instalación\n\n'

if ! command -v python3 >/dev/null 2>&1; then
  printf '  Falta Python 3, que es lo único imprescindible.\n\n'
  printf '  En macOS se instala solo: abrí la Terminal, escribí   python3   y dale Enter.\n'
  printf '  El sistema te va a ofrecer instalarlo. Después volvé a hacer doble clic acá.\n\n'
  read -r -p '  Enter para cerrar... '
  exit 1
fi

python3 instalar.py
CODIGO=$?

# La ventana no se cierra sola: si algo falló, el mensaje tiene que quedar leíble.
printf '\n'
[ $CODIGO -ne 0 ] && printf '  La instalación terminó con errores (código %s).\n' "$CODIGO"
read -r -p '  Enter para cerrar esta ventana... '
