#!/bin/bash
# Instalar.command — doble clic en macOS.
#
# Un .command es un script que Finder abre en la Terminal al hacerle doble clic.
# Existe para que nadie tenga que saber qué es una terminal ni escribir un comando.
#
# La primera vez macOS puede decir que "no se puede abrir porque es de un
# desarrollador no identificado". Es porque el archivo se descargó de internet, no
# porque tenga algo malo: clic derecho sobre el archivo > Abrir > Abrir.

# Pararse en la carpeta del script, no en la que estaba abierta antes. Sin esto,
# un doble clic desde el Finder corre con el HOME como directorio actual y no
# encuentra ni un solo archivo del panel.
cd "$(dirname "$0")" || exit 1

printf '\n  Panel de Métricas — instalación\n\n'

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
