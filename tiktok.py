#!/usr/bin/env python3
"""
tiktok.py — Lectura de métricas de TikTok para el panel (Display API).

POR QUÉ EXISTE
TikTok rechaza las apps para PUBLICAR ("no aprobamos apps de uso personal
o interno"). Pero publicar y leer son dos permisos distintos: la Display API lee los
datos de la cuenta que vos mismo autorizás, y el Sandbox —que ya existe y tiene a
tu propia cuenta como Target User— no necesita App Review.

Lo que sí trae (verificado en la doc, no supuesto):
  - user.info.stats → followers, following, likes totales, cantidad de videos
  - video.list      → tus videos, y por cada uno views, likes, comentarios, shares

Lo que NO trae por esta vía, y por eso el panel no lo va a mostrar:
  - retención, impresiones, alcance y demografía. Esos campos no existen en el
    Video Object de la Display API; viven en la app de TikTok o en la Business API.

USO
    python3 tiktok.py auth          # imprime la URL para autorizar
    python3 tiktok.py code "<url>"  # pegá la URL entera a la que te redirigió
    python3 tiktok.py datos         # baja y muestra las métricas

El token se guarda en .tiktok_token.json con permisos 0600 y se refresca solo:
el access_token de TikTok dura 24 h, el refresh_token bastante más.

Autochequeo (sin red):
    python3 tiktok.py test
"""

import json
import os
import secrets
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import entorno

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = AQUI  # el .env está al lado de los scripts (ver instalar.py)
TOKENS = os.path.join(RAIZ, ".tiktok_token.json")

AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com/v2"

# Sólo lectura. NO pedimos video.publish/video.upload: son los que TikTok rechazó,
# y pedir permisos que no se usan es lo que hace fallar los reviews.
SCOPES = "user.info.basic,user.info.stats,video.list"

# Tiene que estar registrada en Login Kit → Redirect URI de tu app de TikTok.
# Cualquier página estática tuya sirve: recibe el `code` en la URL y no hace nada
# con él. Ojo: NO uses un redirect que canjee el code (como el de Postiz), porque
# un authorization code es de un solo uso y te lo quema.
REDIRECT = entorno.valor("TIKTOK_REDIRECT", "")

CAMPOS_PERFIL = "open_id,display_name,follower_count,following_count,likes_count,video_count"
CAMPOS_VIDEO = "id,title,create_time,view_count,like_count,comment_count,share_count,share_url"


def credenciales():
    """Client key y secret del .env de la raíz. El entorno pisa al archivo."""
    datos = {}
    ruta = os.path.join(RAIZ, ".env")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if "=" in linea and not linea.strip().startswith("#"):
                    k, v = linea.strip().split("=", 1)
                    datos[k] = v.strip().strip('"').strip("'")
    key = os.environ.get("TIKTOK_CLIENT_KEY") or datos.get("TIKTOK_CLIENT_KEY")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET") or datos.get("TIKTOK_CLIENT_SECRET")
    if not key or not secret:
        sys.exit("Faltan TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET en el .env de la raíz.")
    return key, secret


def _post_form(url, campos):
    """POST application/x-www-form-urlencoded. Devuelve el JSON de respuesta."""
    datos = urllib.parse.urlencode(campos).encode()
    req = urllib.request.Request(
        url, data=datos,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # TikTok manda el motivo real en el cuerpo del error; sin esto se ve un 400 pelado.
        sys.exit(f"TikTok respondió {e.code}: {e.read().decode('utf-8', 'replace')}")


def _api(ruta, campos, cuerpo=None):
    """Llamada a la Display API con el token vigente. GET si no hay cuerpo, POST si hay."""
    tok = token_vigente()
    url = f"{API}{ruta}?fields={urllib.parse.quote(campos)}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        url, data=datos,
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        cuerpo_err = e.read().decode("utf-8", "replace")
        # El error más probable acá: un scope que no está habilitado en el portal.
        sys.exit(f"TikTok respondió {e.code} en {ruta}:\n{cuerpo_err}")


# ---------------------------------------------------------------- autorización

def url_autorizacion():
    key, _ = credenciales()
    params = {
        "client_key": key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "state": secrets.token_urlsafe(16),
    }
    return f"{AUTORIZAR}?{urllib.parse.urlencode(params)}"


def extraer_code(texto):
    """Acepta la URL entera de vuelta o el code pelado. TikTok manda el code
    URL-encoded (termina en %2A); hay que decodificarlo antes de canjearlo."""
    texto = texto.strip()
    if "code=" in texto:
        query = urllib.parse.urlparse(texto).query or texto.split("?", 1)[-1]
        valores = urllib.parse.parse_qs(query)
        if "error" in valores:
            sys.exit(f"TikTok devolvió un error: {valores.get('error_description', valores['error'])}")
        if "code" not in valores:
            sys.exit("Esa URL no trae ningún `code`.")
        return valores["code"][0]          # parse_qs ya decodifica
    return urllib.parse.unquote(texto)


def canjear(code):
    key, secret = credenciales()
    r = _post_form(TOKEN, {
        "client_key": key, "client_secret": secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": REDIRECT,
    })
    return guardar_token(r)


def guardar_token(r):
    if "access_token" not in r:
        sys.exit(f"TikTok no devolvió token: {json.dumps(r, ensure_ascii=False)}")
    r["expira_en"] = time.time() + int(r.get("expires_in", 86400))
    with open(TOKENS, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    os.chmod(TOKENS, stat.S_IRUSR | stat.S_IWUSR)   # 0600: es una credencial
    return r


def token_vigente():
    """El access_token, refrescándolo si le quedan menos de 5 minutos de vida."""
    if not os.path.exists(TOKENS):
        sys.exit("No hay token todavía. Corré:  python3 tiktok.py auth")
    with open(TOKENS, encoding="utf-8") as f:
        t = json.load(f)
    if t.get("expira_en", 0) - time.time() > 300:
        return t["access_token"]
    key, secret = credenciales()
    print("  (el token venció, lo refresco)")
    nuevo = _post_form(TOKEN, {
        "client_key": key, "client_secret": secret,
        "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
    })
    return guardar_token(nuevo)["access_token"]


# ---------------------------------------------------------------------- datos

def perfil():
    return _api("/user/info/", CAMPOS_PERFIL).get("data", {}).get("user", {})


def videos(cantidad=20):
    """Los últimos videos. TikTok pagina de a 20 como máximo por llamada."""
    salida, cursor = [], None
    while len(salida) < cantidad:
        cuerpo = {"max_count": min(20, cantidad - len(salida))}
        if cursor:
            cuerpo["cursor"] = cursor
        d = _api("/video/list/", CAMPOS_VIDEO, cuerpo).get("data", {})
        salida += d.get("videos", [])
        cursor = d.get("cursor")
        if not d.get("has_more") or not cursor:
            break
    return salida


def resumen(cantidad=20):
    """Perfil + videos para el panel. Devuelve (datos, None) o (None, motivo).

    El resto del módulo corta con sys.exit() porque se usa a mano desde la terminal,
    donde eso es lo correcto. El recolector no se lo puede permitir: un TikTok sin
    conectar no puede voltear la recolección de Instagram y YouTube. Acá se traduce
    esa salida en un motivo que el panel puede mostrar.
    """
    try:
        return {"perfil": perfil(), "videos": videos(cantidad)}, None
    except SystemExit as e:
        return None, str(e.code if e.code else "") or "no se pudo leer TikTok"
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        return None, f"{type(e).__name__}: {e}"


def _mostrar():
    p = perfil()
    print(f"\n  @{p.get('display_name', '?')}")
    print(f"  {p.get('follower_count', 0):>8,} seguidores")
    print(f"  {p.get('likes_count', 0):>8,} likes totales")
    print(f"  {p.get('video_count', 0):>8,} videos publicados\n")
    vs = videos()
    if not vs:
        print("  Sin videos (o la cuenta no tiene contenido público).")
        return
    print(f"  {'VISTAS':>8} {'LIKES':>7} {'COMENT':>7} {'SHARES':>7}  TÍTULO")
    for v in vs:
        titulo = (v.get("title") or "")[:44]
        print(f"  {v.get('view_count', 0):>8,} {v.get('like_count', 0):>7,} "
              f"{v.get('comment_count', 0):>7,} {v.get('share_count', 0):>7,}  {titulo}")
    print()


# ----------------------------------------------------------------- autochequeo

def _autochequeo():
    # El code llega URL-encoded dentro de la URL de vuelta: si no se decodifica,
    # el canje falla con un 400 que no dice por qué.
    assert extraer_code("https://x.com/cb?code=abc%2A&state=1") == "abc*"
    assert extraer_code("abc%2A") == "abc*", "no decodificó un code pelado"
    assert extraer_code("  abc*  ") == "abc*"

    # La URL de autorización tiene que pedir los tres scopes de lectura y ninguno de escritura.
    os.environ.setdefault("TIKTOK_CLIENT_KEY", "k")
    os.environ.setdefault("TIKTOK_CLIENT_SECRET", "s")
    # keep_blank_values: sin esto, un TIKTOK_REDIRECT vacío hacía DESAPARECER la clave
    # y el chequeo reventaba con un KeyError en vez de decir qué falta configurar.
    def _params():
        return urllib.parse.parse_qs(
            urllib.parse.urlparse(url_autorizacion()).query, keep_blank_values=True)

    q = _params()
    assert set(q["scope"][0].split(",")) == {"user.info.basic", "user.info.stats", "video.list"}
    assert "publish" not in q["scope"][0] and "upload" not in q["scope"][0]
    assert q["redirect_uri"][0] == REDIRECT and q["response_type"][0] == "code"
    assert q["state"][0] != _params()["state"][0], "el state se repite"

    # `resumen()` NO puede tumbar al recolector: sin token tiene que devolver un
    # motivo, no cortar el proceso. Es la única diferencia con el resto del módulo.
    global TOKENS
    original, TOKENS = TOKENS, "/tmp/no-existe-este-token.json"
    try:
        datos, motivo = resumen()
        assert datos is None and motivo, "sin token tendría que devolver un motivo"
        assert "auth" in motivo, f"el motivo no dice cómo arreglarlo: {motivo}"
    finally:
        TOKENS = original

    print("tiktok.py: todo OK")


COMANDOS = {
    "auth": lambda: print(
        "\n  1. Abrí esta URL logueado con la cuenta de TikTok del panel:\n\n"
        f"  {url_autorizacion()}\n\n"
        "  2. Autorizá. Te va a redirigir a tu URL de redirect.\n"
        "  3. Copiá la URL ENTERA de la barra del navegador y corré:\n\n"
        '     python3 tiktok.py code "<pegá la URL acá>"\n'),
    "code": lambda: print(
        f"  Token guardado en {TOKENS} (scopes: {canjear(extraer_code(sys.argv[2]))['scope']})"),
    "datos": _mostrar,
    "test": _autochequeo,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "datos"
    if cmd not in COMANDOS:
        sys.exit(f"Comandos: {', '.join(COMANDOS)}")
    COMANDOS[cmd]()
