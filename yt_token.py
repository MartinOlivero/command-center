#!/usr/bin/env python3
"""
yt_token.py — Regenera el token de YouTube sumando el permiso de comentarios.

POR QUÉ HACE FALTA
El token actual tiene un solo permiso: `https://www.googleapis.com/auth/youtube`.
Alcanza para subir videos, editarlos y leer métricas, pero NO para leer comentarios:
la API devuelve `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. Probado el 2026-08-07 contra la v3,
tanto con `allThreadsRelatedToChannelId` como por video.

Para comentarios hace falta además `youtube.force-ssl`. Un permiso no se "agranda":
hay que volver a pedir autorización con la lista completa, y por eso este script pide
LOS DOS. Si pidiéramos solo el nuevo, perderíamos el de subir videos.

SOBRE GOOGLE CLOUD: NO HAY QUE TOCAR NADA
Verificado el 2026-08-07 en el proyecto gmail-personal-422814: `youtube.force-ssl` ya
figura declarado en "Acceso a los datos → Tus permisos sensibles". El permiso estaba
disponible desde siempre; lo que pasaba es que el token se generó pidiendo solo
`youtube`, y un token guarda los permisos con los que nació. Por eso alcanza con
volver a hacer el login.

(Si alguna vez el paso 1 falla con `invalid_scope`, ENTONCES sí falta declararlo:
Google Cloud → Google Auth Platform → Acceso a los datos → Agregar o quitar permisos.)

USO
    python3 yt_token.py auth          # imprime la URL para autorizar
    python3 yt_token.py code "<url>"  # pegá la URL entera de la barra
    python3 yt_token.py ver           # qué permisos tiene el token de hoy

El token viejo se respalda antes de pisarlo: si algo sale mal, está al lado con
sufijo .bak y se vuelve renombrándolo.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.parse

import entorno

AQUI = os.path.dirname(os.path.abspath(__file__))
_ENV = entorno.leer()

# Dónde queda el token una vez conseguido. Por defecto al lado del panel, para que
# todo lo de esta instalación viva en una sola carpeta.
TOKEN = os.path.expanduser(
    _ENV.get("YT_TOKEN_FILE") or os.path.join(AQUI, "youtube_token.json"))

# El JSON de credenciales que baja Google Cloud (Credenciales > OAuth 2.0 >
# descargar). Antes esto era una ruta absoluta a una máquina concreta, lo que hacía
# que el script solo funcionara en esa computadora.
CLIENT = os.path.expanduser(
    _ENV.get("YT_CLIENT_FILE") or os.path.join(AQUI, "client_secret.json"))

# Los dos juntos, siempre. `youtube` es el que ya tenías; force-ssl es el que suma
# los comentarios. Pedir solo el nuevo dejaría la subida de videos sin permiso.
SCOPES = ("https://www.googleapis.com/auth/youtube "
          "https://www.googleapis.com/auth/youtube.force-ssl")

# Las credenciales son de tipo "Desktop app" y tienen registrado http://localhost.
# El navegador va a mostrar un error de conexión al volver: es lo esperado, el
# código que necesitamos ya está en la barra de direcciones.
REDIRECT = "http://localhost"


def credenciales(obligatorias=True):
    """El client_id y el client_secret de Google, del .env o del JSON que baja
    Google Cloud. Se aceptan las dos formas porque son dos momentos distintos:
    quien acaba de crear el proyecto tiene el archivo descargado a mano; quien ya
    lo configuró una vez lo tiene en el .env y no quiere volver a buscarlo.

    Esta es la ÚNICA fuente para todo el panel. Antes el recolector y el servidor
    miraban solo el `.env` por su cuenta, y quien seguía las instrucciones al pie de
    la letra —dejar el JSON en la carpeta y correr `yt_token.py auth`— conseguía el
    token pero se quedaba sin poder refrescarlo: YouTube andaba una hora y después
    aparecía desconectado sin decir por qué.

    `obligatorias=False` para quien puede seguir sin YouTube: devuelve ("", "") en
    vez de cortar el programa. El panel muestra las otras tres redes igual.
    """
    if _ENV.get("YT_CLIENT_ID") and _ENV.get("YT_CLIENT_SECRET"):
        return _ENV["YT_CLIENT_ID"], _ENV["YT_CLIENT_SECRET"]
    if not os.path.exists(CLIENT):
        if not obligatorias:
            return "", ""
        sys.exit(
            "Faltan las credenciales de Google. Dos opciones:\n"
            "  a) poné YT_CLIENT_ID y YT_CLIENT_SECRET en el .env\n"
            f"  b) dejá el JSON que baja Google Cloud en {CLIENT}\n"
            "Se sacan en console.cloud.google.com > Credenciales > OAuth 2.0")
    with open(CLIENT, encoding="utf-8") as f:
        c = json.load(f)
    c = c.get("installed") or c.get("web") or {}
    return c.get("client_id", ""), c.get("client_secret", "")


def _curl(url, campos):
    """POST con curl y no con urllib: en esta Mac urllib falla el handshake TLS
    contra los endpoints de Google (ya nos pasó al refrescar el token)."""
    datos = urllib.parse.urlencode(campos)
    r = subprocess.run(["curl", "-s", "-X", "POST", url, "-d", datos],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"Respuesta inesperada de Google:\n{r.stdout[:400]}")


def auth():
    cid, _ = credenciales()
    params = {
        "client_id": cid,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        # Sin esto Google no vuelve a mandar refresh_token si ya autorizaste antes,
        # y te quedás con un token que caduca en una hora y no se puede renovar.
        "prompt": "consent",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    print(f"""
  1. Abrí esta URL con la cuenta del canal:

  {url}

  2. Autorizá. Fijate que aparezca el permiso de administrar comentarios.
  3. El navegador va a mostrar "no se puede acceder a este sitio" (localhost).
     ESO ESTÁ BIEN. Copiá la URL ENTERA de la barra y corré:

     python3 yt_token.py code "<pegá la URL acá>"

  Si Google dice `invalid_scope`, falta declarar youtube.force-ssl en la pantalla
  de consentimiento de Google Cloud (ver el encabezado de este archivo).
""")


def code(texto):
    cid, secret = credenciales()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(texto.strip()).query)
    if "error" in q:
        sys.exit(f"Google devolvió: {q['error'][0]}. "
                 "Si dice invalid_scope, falta declararlo en Google Cloud.")
    if "code" not in q:
        sys.exit("Esa URL no trae ningún `code`.")
    r = _curl("https://oauth2.googleapis.com/token", {
        "client_id": cid, "client_secret": secret, "code": q["code"][0],
        "grant_type": "authorization_code", "redirect_uri": REDIRECT,
    })
    if "access_token" not in r:
        sys.exit(f"No hubo token: {json.dumps(r, ensure_ascii=False)[:300]}")
    if os.path.exists(TOKEN):
        shutil.copy2(TOKEN, TOKEN + ".bak")   # por si el nuevo sale mal
    with open(TOKEN, "w", encoding="utf-8") as f:
        json.dump(r, f)
    os.chmod(TOKEN, stat.S_IRUSR | stat.S_IWUSR)
    print(f"  Token guardado. Permisos: {r.get('scope')}")
    print(f"  El anterior quedó en {TOKEN}.bak")


def ver():
    if not os.path.exists(TOKEN):
        sys.exit("No hay token todavía.")
    t = json.load(open(TOKEN, encoding="utf-8"))
    r = subprocess.run(
        ["curl", "-s", "https://www.googleapis.com/oauth2/v1/tokeninfo"
         f"?access_token={t['access_token']}"], capture_output=True, text=True, timeout=30)
    try:
        real = json.loads(r.stdout).get("scope", "(el token venció)")
    except json.JSONDecodeError:
        real = "(no se pudo consultar)"
    print(f"  guardado: {t.get('scope')}")
    print(f"  real:     {real}")
    print("  comentarios: " + ("SÍ" if "force-ssl" in str(real) else "NO — falta youtube.force-ssl"))


COMANDOS = {"auth": auth, "ver": ver,
            "code": lambda: code(sys.argv[2] if len(sys.argv) > 2 else "")}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ver"
    if cmd not in COMANDOS:
        sys.exit(f"Comandos: {', '.join(COMANDOS)}")
    COMANDOS[cmd]()
