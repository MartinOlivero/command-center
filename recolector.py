#!/usr/bin/env python3
"""
Socials Command Center — recolector de datos REALES.

Baja las metricas de Instagram, Facebook y YouTube por sus APIs oficiales,
las cruza con el calendario de Postiz, saca conclusiones accionables, y
genera un unico archivo `panel.html` autocontenido: se abre con doble click,
sin servidor, sin CORS y sin que ningun token entre al HTML.

    python3 recolector.py [dias]

Que NO hace, y por que (las APIs oficiales no lo entregan):
  - Retencion segundo a segundo de reels: solo hay tiempo promedio visto.
  - Funnel de DMs: los DMs no se cuentan como metrica de insights.
  - Horario de audiencia (online_followers): Meta lo devuelve vacio en
    cuentas chicas, asi que no se muestra en vez de inventar un numero.
  - Alcance por publicación en Facebook: Meta lo borro en la v25.
  - Curvas diarias de YouTube: son de la Analytics API, no de la Data API.
"""
import base64
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import campanas
import comentarios
import competencia
import config
import entorno
import historico
import leads
import senales
import tiktok

AQUI = os.path.dirname(os.path.abspath(__file__))
# El panel es a la vez la salida y la fuente de lo que se hereda al actualizar
# una sola red, así que la ruta deja de estar escrita a mano en dos lugares.
PANEL_SALIDA = os.path.join(AQUI, "panel.html")
RAIZ = AQUI  # el .env está al lado de los scripts (ver instalar.py)
# Version de la Graph API. Meta le da ~2 años de vida a cada una y despues la
# apaga; quedarse atras es cuestion de tiempo hasta que algo deje de responder.
# Probado el 2026-08-03: las 9 llamadas del panel devuelven lo mismo en v26 que
# en v21. Antes de subirla de nuevo, correr esa comparacion.
GRAPH_VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
CFG = config.cargar()
# El argumento de la línea de comandos manda; si no, lo que diga config.json.
# Se busca el primer argumento NUMERICO y no `sys.argv[1]` a secas: desde que
# existe `--red instagram`, el primer argumento puede no ser la cantidad de días
# y `int("--red")` reventaba antes de empezar.
DIAS = int(next((a for a in sys.argv[1:] if a.lstrip("-").isdigit()),
                CFG.get("dias", 30)))
# Meta limita cada consulta de insights a 30 días; pedimos de a tramos.
TRAMO_MAX = 30


def credenciales():
    """Lee el token y el ID de cuenta del .env del proyecto (nunca del HTML)."""
    datos = {}
    with open(os.path.join(RAIZ, ".env")) as f:
        for linea in f:
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.strip().split("=", 1)
                datos[k] = v.strip().strip('"').strip("'")
    # Lo que esté en el entorno pisa al archivo. Sirve para probar una credencial suelta
    # sin escribirla en el .env, y para correr el recolector en otra máquina sin tocar nada.
    for k in ("IG_PAGE_TOKEN", "IG_USER_ID", "META_ADS_TOKEN"):
        if os.environ.get(k):
            datos[k] = os.environ[k]

    # El token de Ads puede vivir en OTRO archivo (el .env.local del proyecto de ese
    # cliente) y acá solo guardamos la ruta. Así el secreto existe en un solo lugar:
    # si el cliente lo rota, se cambia ahí y nada más. Copiar credenciales ajenas de
    # un archivo a otro es la forma más común de que después queden olvidadas en tres
    # lugares distintos.
    #
    #     META_ADS_TOKEN_FILE=/ruta/al/.env.local
    #     META_ADS_TOKEN_KEY=META_ACCESS_TOKEN     (opcional, ese es el valor por defecto)
    ruta_token = datos.get("META_ADS_TOKEN_FILE")
    if ruta_token and not datos.get("META_ADS_TOKEN"):
        clave = datos.get("META_ADS_TOKEN_KEY", "META_ACCESS_TOKEN")
        try:
            for linea in open(os.path.expanduser(ruta_token)):
                if linea.startswith(f"{clave}="):
                    datos["META_ADS_TOKEN"] = linea.split("=", 1)[1].strip().strip('"').strip("'")
                    break
            else:
                AVISOS.append(f"No encontré {clave} en {ruta_token}.")
        except OSError as e:
            AVISOS.append(f"No pude leer el archivo del token de Ads ({e}).")

    faltan = [k for k in ("IG_PAGE_TOKEN", "IG_USER_ID") if k not in datos]
    if faltan:
        sys.exit(f"Faltan variables en .env: {', '.join(faltan)}")
    return datos


AVISOS = []
# Competidores leídos en esta corrida. Igual que AVISOS: se llena durante el
# recorrido y se vuelca al final, para no arrastrar el dato por diez funciones.
COMPETENCIA = []


def get(url):
    """GET a la Graph API. Devuelve {} y anota el aviso si Meta rechaza."""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = f"HTTP {e.code}"
        AVISOS.append(msg)
        return {}
    except Exception as e:  # red caida, DNS, timeout
        AVISOS.append(str(e))
        return {}


# La API de Instagram tiene DOS modos y son excluyentes:
#   - serie dia por dia: SOLO estas dos metricas.
#   - total del período (metric_type=total_value): el resto, sin desglose diario.
# Por eso el grafico muestra alcance y seguidores, y las demas van como KPI.
CON_SERIE_DIARIA = ("reach", "follower_count")
SOLO_TOTAL = ("views", "profile_views", "total_interactions", "accounts_engaged",
              "likes", "comments", "saves", "shares", "website_clicks")


def insights_diarios(cred, metricas, desde, hasta):
    """Serie diaria de metricas de cuenta, partida en tramos de <=30 días.

    Devuelve {'2026-07-05': {'reach': 302, 'follower_count': 1}, ...}
    """
    serie = {}
    cursor = desde
    while cursor < hasta:
        fin = min(cursor + datetime.timedelta(days=TRAMO_MAX), hasta)
        q = urllib.parse.urlencode({
            "metric": ",".join(metricas),
            "period": "day",
            "since": int(cursor.timestamp()),
            "until": int(fin.timestamp()),
            "access_token": cred["IG_PAGE_TOKEN"],
        })
        for bloque in get(f"{GRAPH}/{cred['IG_USER_ID']}/insights?{q}").get("data", []):
            for punto in bloque.get("values", []):
                dia = punto["end_time"][:10]
                serie.setdefault(dia, {})[bloque["name"]] = punto.get("value", 0)
        cursor = fin
    return serie


def insights_totales(cred, metricas, desde, hasta):
    """Total del período para las metricas que no aceptan desglose diario.

    Ojo: el alcance total NO es la suma de los alcances diarios. Meta
    deduplica: si la misma persona te ve tres días, suma 3 en la serie
    diaria pero 1 en el total del período. El total es el numero honesto.
    """
    total = {}
    cursor = desde
    while cursor < hasta:
        fin = min(cursor + datetime.timedelta(days=TRAMO_MAX), hasta)
        q = urllib.parse.urlencode({
            "metric": ",".join(metricas),
            "period": "day",
            "metric_type": "total_value",
            "since": int(cursor.timestamp()),
            "until": int(fin.timestamp()),
            "access_token": cred["IG_PAGE_TOKEN"],
        })
        for bloque in get(f"{GRAPH}/{cred['IG_USER_ID']}/insights?{q}").get("data", []):
            valor = bloque.get("total_value", {}).get("value", 0)
            total[bloque["name"]] = total.get(bloque["name"], 0) + valor
        cursor = fin
    return total


DURACIONES = os.path.join(AQUI, "duraciones.json")


def duracion_video(media_id, url):
    """Segundos que dura un reel. None si no se puede saber.

    POR QUE ESTO EXISTE
    Sin la duracion, el tiempo de visualizacion no dice nada: 12 segundos son
    excelentes en un reel de 15 y un desastre en uno de 3 minutos. Y el tiempo de
    visualizacion es la señal #1 del algoritmo, asi que no poder leerla es quedarse
    ciego justo en lo que mas pesa.

    POR QUE HAY QUE SACARLA DEL ARCHIVO
    La API de Instagram NO la publica. Probado el 2026-08-07 contra la v26:
    `video_duration`, `duration` y `length` devuelven "Tried accessing nonexisting
    field". Lo unico que da es `media_url`, asi que la duracion se lee del propio
    archivo con ffprobe, que baja solo la cabecera y no el video entero.

    Se cachea en disco para siempre: la duracion de un video publicado no cambia
    nunca, y sin cache cada corrida del panel se llevaria varios segundos por reel.
    """
    try:
        with open(DURACIONES, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        cache = {}
    if media_id in cache:
        return cache[media_id]
    if not url:
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=45)
        seg = round(float(r.stdout.strip()), 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Sin ffprobe instalado, o el enlace ya vencio. No es motivo para romper
        # el panel: simplemente esa pieza no muestra retencion.
        return None
    cache[media_id] = seg
    try:
        with open(DURACIONES, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass
    return seg


def insights_desglose(cred, metrica, desglose, desde, hasta):
    """Una metrica de cuenta partida por un desglose. Hoy: alcance por tipo de seguidor.

    Devuelve {'FOLLOWER': 1234, 'NON_FOLLOWER': 567, 'UNKNOWN': 12} o {} si la cuenta
    no tiene datos suficientes (Meta devuelve vacio, no ceros, cuando no hay volumen).

    POR QUE IMPORTA
    El alcance total no distingue entre "me vieron 900 personas nuevas" y "me vieron
    900 veces los mismos de siempre". Es la diferencia entre un negocio que crece y
    uno que le habla al mismo circulo hasta agotarlo.

    LIMITES DE LA API (verificados en la doc, no supuestos):
      - solo funciona con metric_type=total_value: no hay serie diaria con desglose.
      - los valores de follow_type son FOLLOWER, NON_FOLLOWER y UNKNOWN.
      - pedir un desglose sobre una metrica que no lo soporta devuelve
        "An unknown error has occurred", que no dice nada. Por eso solo `reach`.
    """
    salida = {}
    cursor = desde
    while cursor < hasta:
        fin = min(cursor + datetime.timedelta(days=TRAMO_MAX), hasta)
        q = urllib.parse.urlencode({
            "metric": metrica,
            "period": "day",
            "metric_type": "total_value",
            "breakdown": desglose,
            "since": int(cursor.timestamp()),
            "until": int(fin.timestamp()),
            "access_token": cred["IG_PAGE_TOKEN"],
        })
        for bloque in get(f"{GRAPH}/{cred['IG_USER_ID']}/insights?{q}").get("data", []):
            for grupo in bloque.get("total_value", {}).get("breakdowns", []):
                for fila in grupo.get("results", []):
                    clave = (fila.get("dimension_values") or ["?"])[0]
                    salida[clave] = salida.get(clave, 0) + fila.get("value", 0)
        cursor = fin
    return salida


def publicaciones(cred, desde):
    """Cada post del período con sus metricas. Reels y feed traen campos distintos."""
    campos = ("id,media_type,media_product_type,caption,timestamp,permalink,"
              "thumbnail_url,media_url")
    url = (f"{GRAPH}/{cred['IG_USER_ID']}/media?fields={campos}&limit=50"
           f"&access_token={cred['IG_PAGE_TOKEN']}")
    salida = []
    while url:
        pagina = get(url)
        for m in pagina.get("data", []):
            fecha = datetime.datetime.fromisoformat(
                m["timestamp"].replace("+0000", "+00:00"))
            if fecha < desde:
                return salida  # media viene ordenado del mas nuevo al mas viejo
            es_reel = m.get("media_product_type") == "REELS"
            base = "reach,views,likes,comments,saved,shares,total_interactions"
            extra = (",ig_reels_avg_watch_time" if es_reel else ",profile_visits,follows")
            ins = get(f"{GRAPH}/{m['id']}/insights?metric={base}{extra}"
                      f"&access_token={cred['IG_PAGE_TOKEN']}")
            if not ins:  # si el campo extra no aplica, reintentamos con lo basico
                ins = get(f"{GRAPH}/{m['id']}/insights?metric={base}"
                          f"&access_token={cred['IG_PAGE_TOKEN']}")
            d = {i["name"]: i["values"][0]["value"] for i in ins.get("data", [])}
            alcance = d.get("reach", 0)
            # Solo para reels: la duracion sale del archivo, no de la API (ver
            # duracion_video). La primera corrida tarda unos segundos por pieza;
            # despues sale del cache.
            dur = duracion_video(m["id"], m.get("media_url")) if es_reel else None
            texto = re.sub(r"\s+", " ", (m.get("caption") or "")).strip()
            salida.append({
                # Lo necesita comentarios.py para pedir la conversación de este post.
                "media_id": m["id"],
                "fecha": m["timestamp"][:10],
                "hora": m["timestamp"][11:16],
                "tipo": "Reel" if es_reel else ("Carrusel" if m["media_type"] == "CAROUSEL_ALBUM" else "Post"),
                "texto": texto[:110],
                "link": m.get("permalink", ""),
                "miniatura": incrustar_miniatura(m.get("thumbnail_url") or m.get("media_url", "")),
                "alcance": alcance,
                "vistas": d.get("views", 0),
                "likes": d.get("likes", 0),
                "comentarios": d.get("comments", 0),
                "guardados": d.get("saved", 0),
                "compartidos": d.get("shares", 0),
                "interacciones": d.get("total_interactions", 0),
                # engagement sobre alcance: que porcentaje de los que lo VIERON reaccionaron
                "engagement": round(d.get("total_interactions", 0) / alcance * 100, 1) if alcance else 0,
                # Meta lo entrega en milisegundos; lo pasamos a segundos
                "seg_vistos": round(d.get("ig_reels_avg_watch_time", 0) / 1000, 1) if es_reel else None,
                "visitas_perfil": d.get("profile_visits") if not es_reel else None,
                "seguidores_ganados": d.get("follows") if not es_reel else None,
                "duracion": dur,
                # El numero que de verdad importa: que PORCENTAJE del video miraron.
                # Puede pasar del 100% y no es un error: significa que lo reprodujeron
                # mas de una vez, que es la señal mas fuerte que existe en Reels.
                "retencion": (round(d.get("ig_reels_avg_watch_time", 0) / 1000 / dur * 100, 1)
                              if es_reel and dur else None),
            })
        url = pagina.get("paging", {}).get("next")
    return salida


def incrustar_miniatura(url):
    """Baja la miniatura y la mete adentro del HTML como data URI.

    Las URLs del CDN de Meta vienen firmadas y caducan a las pocas horas: si
    dejaramos el link, el panel guardado se quedaria sin imagenes. Bajandolas
    el archivo queda completo y funciona incluso sin internet.
    """
    if not url:
        return ""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            crudo = r.read()
            tipo = r.headers.get("content-type", "image/jpeg")
        return f"data:{tipo};base64," + base64.b64encode(crudo).decode()
    except Exception:
        return url  # si falla, al menos queda el link original


def demografia(cred, dimension):
    """Top de seguidores por pais o ciudad (dato de por vida, no del período)."""
    q = urllib.parse.urlencode({
        "metric": "follower_demographics", "period": "lifetime",
        "metric_type": "total_value", "breakdown": dimension,
        "access_token": cred["IG_PAGE_TOKEN"]})
    d = get(f"{GRAPH}/{cred['IG_USER_ID']}/insights?{q}")
    try:
        res = d["data"][0]["total_value"]["breakdowns"][0]["results"]
    except (KeyError, IndexError):
        return []
    filas = [{"nombre": r["dimension_values"][0], "valor": r["value"]} for r in res]
    return sorted(filas, key=lambda x: -x["valor"])[:8]


# ---------------------------------------------------------------- FACEBOOK
# Meta fue borrando metricas de Página; estas son las que respondieron OK
# el 2026-08-02. Si alguna deja de existir, get() la anota como aviso.
FB_METRICAS = ("page_post_engagements", "page_views_total", "page_follows",
               "page_daily_follows", "page_video_views", "page_total_actions")


def facebook(cred, desde, hasta):
    """Página de Facebook: perfil, serie diaria y ultimas publicaciónes."""
    tok = cred["IG_PAGE_TOKEN"]
    pag = cred.get("FB_PAGE_ID")
    if not pag:
        # Sin el ID de la Página no hay a quién preguntarle. Antes esto era un acceso
        # directo que reventaba con KeyError y se llevaba puesta la recolección entera,
        # incluidas las redes que sí estaban bien configuradas.
        AVISOS.append("Falta FB_PAGE_ID en el .env, así que Facebook queda sin datos. "
                      "Se completa solo volviendo a correr: python3 instalar.py")
        return {}, {}, []
    perfil = get(f"{GRAPH}/{pag}?fields=name,fan_count,followers_count,link"
                 f"&access_token={tok}")
    serie = {}
    q = urllib.parse.urlencode({
        "metric": ",".join(FB_METRICAS), "period": "day",
        "since": int(desde.timestamp()), "until": int(hasta.timestamp()),
        "access_token": tok})
    for bloque in get(f"{GRAPH}/{pag}/insights?{q}").get("data", []):
        for punto in bloque.get("values", []):
            valor = punto.get("value", 0)
            if isinstance(valor, int):
                serie.setdefault(punto["end_time"][:10], {})[bloque["name"]] = valor

    campos = ("id,created_time,message,permalink_url,"
              "reactions.summary(total_count).limit(0),"
              "comments.summary(total_count).limit(0),shares")
    posts = []
    for p in get(f"{GRAPH}/{pag}/posts?fields={campos}&limit=25"
                 f"&access_token={tok}").get("data", []):
        fecha = datetime.datetime.fromisoformat(
            p["created_time"].replace("+0000", "+00:00"))
        if fecha < desde:
            continue
        reac = p.get("reactions", {}).get("summary", {}).get("total_count", 0)
        com = p.get("comments", {}).get("summary", {}).get("total_count", 0)
        comp = p.get("shares", {}).get("count", 0)
        posts.append({
            "fecha": p["created_time"][:10],
            "tipo": "Post",
            "texto": re.sub(r"\s+", " ", (p.get("message") or ""))[:110],
            "link": p.get("permalink_url", ""),
            "miniatura": "",
            # Meta eliminó el alcance por publicación en v25: no lo inventamos.
            "alcance": None,
            "interacciones": reac + com + comp,
            "likes": reac, "comentarios": com, "compartidos": comp,
        })
    return perfil, serie, posts


# ---------------------------------------------------------------- YOUTUBE
# Estas tres salen del .env, nunca del código. Antes estaban escritas acá adentro:
# funcionaba mientras el panel viviera en una sola máquina, y era una filtración de
# credenciales el día que el código se publicara. Un client secret de Google en un
# repo público es acceso al proyecto de Google Cloud de alguien.
_YT = entorno.leer()
YT_TOKEN = os.path.expanduser(
    _YT.get("YT_TOKEN_FILE") or os.path.join(AQUI, "youtube_token.json"))
YT_CLIENT_ID = _YT.get("YT_CLIENT_ID", "")
YT_SECRET = _YT.get("YT_CLIENT_SECRET", "")
YTA = "https://youtubeanalytics.googleapis.com/v2/reports?"


def yt_refrescar():
    """El access_token de Google dura 1 hora: lo renovamos antes de usarlo.

    Sin esto el panel fallaba con 401 cada vez que se corria mas de una hora
    despues de la vez anterior.
    """
    if not os.path.exists(YT_TOKEN):
        return None
    tk = json.load(open(YT_TOKEN))
    if not tk.get("refresh_token"):
        return tk.get("access_token")
    params = urllib.parse.urlencode({
        "client_id": YT_CLIENT_ID, "client_secret": YT_SECRET,
        "refresh_token": tk["refresh_token"], "grant_type": "refresh_token"}).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=params)
        with urllib.request.urlopen(req, timeout=25) as r:
            tk["access_token"] = json.loads(r.read())["access_token"]
        json.dump(tk, open(YT_TOKEN, "w"))
    except Exception:
        pass          # si falla el refresco probamos con el token que haya
    return tk.get("access_token")


def yt_analytics(cab, desde, hasta):
    """Retencion REAL por video (YouTube Analytics API).

    Es la metrica que ninguna API de Instagram entrega y que los paneles de
    demo inventan: aca sale del canal propio. `averageViewPercentage` es que
    porcentaje del video se mira en promedio.
    """
    def ga(url):
        try:
            req = urllib.request.Request(url, headers=cab)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            AVISOS.append(f"YouTube Analytics: {e}")
            return {}

    q = urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": desde.date().isoformat(),
        "endDate": hasta.date().isoformat(),
        "metrics": ("views,averageViewDuration,averageViewPercentage,"
                    "estimatedMinutesWatched,subscribersGained"),
        "dimensions": "video", "sort": "-views", "maxResults": 25})
    por_video = {f[0]: {"vistas_periodo": f[1], "seg_promedio": f[2],
                        "retencion": round(f[3], 1), "minutos": f[4],
                        "suscriptores": f[5]}
                 for f in ga(YTA + q).get("rows", [])}

    # Curvas de los videos mas vistos. Una consulta por video, asi que
    # limitamos a los 10 primeros: mas que eso no cambia ninguna decision.
    curvas = []
    orden = sorted(por_video, key=lambda v: -por_video[v]["vistas_periodo"])[:10]
    for vid in orden:
        q2 = urllib.parse.urlencode({
            "ids": "channel==MINE", "startDate": desde.date().isoformat(),
            "endDate": hasta.date().isoformat(),
            "metrics": "audienceWatchRatio", "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={vid}"})
        puntos = [{"pct": round(f[0] * 100), "ratio": round(f[1] * 100, 1)}
                  for f in ga(YTA + q2).get("rows", [])]
        if len(puntos) >= 5:
            curvas.append({"id": vid, "puntos": puntos,
                           "vistas": por_video[vid]["vistas_periodo"],
                           "retencion": por_video[vid]["retencion"]})
    top = orden[0] if orden else None
    return por_video, curvas, top


def yt_totales(cab, desde, hasta):
    """Totales del canal en un rango. Con esto se calculan los deltas reales."""
    q = urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": desde.date().isoformat(),
        "endDate": hasta.date().isoformat(),
        "metrics": ("views,estimatedMinutesWatched,subscribersGained,"
                    "averageViewPercentage,averageViewDuration")})
    try:
        req = urllib.request.Request(YTA + q, headers=cab)
        with urllib.request.urlopen(req, timeout=30) as resp:
            filas = json.loads(resp.read()).get("rows", [])
    except Exception:
        return {}
    if not filas:
        return {}
    v = filas[0]
    return {"vistas": v[0], "minutos": v[1], "suscriptores": v[2],
            "retencion": round(v[3], 1), "seg_promedio": v[4]}


def yt_serie(cab, desde, hasta):
    """Serie diaria del canal: vistas, minutos vistos y suscriptores por dia."""
    q = urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": desde.date().isoformat(),
        "endDate": hasta.date().isoformat(),
        "metrics": "views,estimatedMinutesWatched,subscribersGained",
        "dimensions": "day"})
    try:
        req = urllib.request.Request(YTA + q, headers=cab)
        with urllib.request.urlopen(req, timeout=30) as r:
            filas = json.loads(r.read()).get("rows", [])
    except Exception:
        return []
    return [{"fecha": f[0], "valor": f[1], "minutos": f[2], "seguidores": f[3]}
            for f in filas]


def youtube(desde, hasta=None):
    """Canal, últimos videos y sus metricas. Devuelve (datos, motivo_si_falla)."""
    if not os.path.exists(YT_TOKEN):
        return None, (f"YouTube no está autorizado todavía (falta {os.path.basename(YT_TOKEN)}). "
                      "Se consigue con: python3 yt_token.py auth")
    at = yt_refrescar()
    cab = {"Authorization": f"Bearer {at}"}

    def yget(url):
        try:
            req = urllib.request.Request(url, headers=cab)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                "El token de YouTube está vencido o revocado (la app OAuth "
                "sigue en modo Testing y Google los caduca cada ~7 días). "
                "Hay que reautorizar a mano." if e.code == 401 else f"HTTP {e.code}")
        except Exception as e:
            raise RuntimeError(str(e))

    try:
        canal = yget("https://www.googleapis.com/youtube/v3/channels"
                     "?part=snippet,statistics,contentDetails&mine=true")["items"][0]
        subidas = canal["contentDetails"]["relatedPlaylists"]["uploads"]
        items = yget("https://www.googleapis.com/youtube/v3/playlistItems"
                     f"?part=snippet,contentDetails&playlistId={subidas}&maxResults=25")["items"]
        ids = [i["contentDetails"]["videoId"] for i in items]
        detalle = yget("https://www.googleapis.com/youtube/v3/videos"
                       f"?part=snippet,statistics,contentDetails&id={','.join(ids)}")["items"]
    except RuntimeError as e:
        return None, str(e)

    hasta = hasta or datetime.datetime.now(datetime.timezone.utc)
    analitica, curva, top_id = yt_analytics(cab, desde, hasta)
    serie = yt_serie(cab, desde, hasta)
    # misma ventana corrida hacia atras: es la base de los deltas
    largo = hasta - desde
    tot = yt_totales(cab, desde, hasta)
    tot_previo = yt_totales(cab, desde - largo, desde)

    videos = []
    for v in detalle:
        pub = datetime.datetime.fromisoformat(
            v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        st = v.get("statistics", {})
        vistas = int(st.get("viewCount", 0))
        inter = int(st.get("likeCount", 0)) + int(st.get("commentCount", 0))
        dur = v["contentDetails"].get("duration", "")
        # PT1M30S -> segundos; sirve para separar shorts de videos largos
        mm = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
        seg = sum(int(x or 0) * f for x, f in zip(mm.groups(), (3600, 60, 1))) if mm else 0
        videos.append({
            "fecha": v["snippet"]["publishedAt"][:10],
            "reciente": pub >= desde,
            "tipo": "Short" if seg and seg <= 60 else "Video",
            "texto": v["snippet"]["title"][:110],
            "id_video": v["id"],
            "link": f"https://youtu.be/{v['id']}",
            "miniatura": v["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
            "alcance": vistas,          # en YouTube la vara comparable son las vistas
            "vistas": vistas,
            "likes": int(st.get("likeCount", 0)),
            "comentarios": int(st.get("commentCount", 0)),
            "interacciones": inter,
            "engagement": round(inter / vistas * 100, 1) if vistas else 0,
            "duracion_seg": seg,
        })
    # pegamos la retencion real de Analytics a cada video
    for v in videos:
        a = analitica.get(v["id_video"])
        if a:
            v.update({"retencion": a["retencion"], "seg_vistos": a["seg_promedio"],
                      "minutos": a["minutos"], "suscriptores": a["suscriptores"],
                      "vistas_periodo": a["vistas_periodo"]})
    return {"canal": canal, "videos": videos, "curva": curva, "top_id": top_id,
            "serie": serie, "analitica": analitica,
            "tot": tot, "tot_previo": tot_previo}, None


# ---------------------------------------------------------------- CALENDARIO
# La instancia de Postiz de cada uno. Postiz es autoalojado: la URL es distinta
# para cada instalación, así que no puede vivir en el código.
POSTIZ = entorno.valor("POSTIZ_URL", "").rstrip("/")
# Va en el .env, nunca en el código: es la llave del calendario de quien instala esto,
# y el código se publica. Estuvo escrito acá adentro y viajó al repositorio.
POSTIZ_TOKEN = entorno.valor("POSTIZ_TOKEN", "")


def limpiar_html(crudo):
    """Deja solo <p> y <br>: el contenido de Postiz entra al panel, no su markup."""
    if not crudo:
        return ""
    limpio = re.sub(r"<(?!/?(p|br)\b)[^>]*>", "", crudo)
    return limpio.replace("<br>", "<br/>")


def calendario(desde, hasta):
    """Lo programado en Postiz: publicado y por publicar."""
    # Sin URL o sin token no hay nada que pedir. Decirlo así evita el aviso críptico
    # que salía antes —"unknown url type: '/posts?...'"— cuando faltaba la URL y la
    # petición se armaba igual, sin servidor adelante.
    if not POSTIZ or not POSTIZ_TOKEN:
        if config.cargar().get("postiz", {}).get("activo"):
            AVISOS.append("Calendario: falta POSTIZ_URL o POSTIZ_TOKEN en el .env.")
        return []
    q = urllib.parse.urlencode({"startDate": desde.isoformat().replace("+00:00", "Z"),
                                "endDate": hasta.isoformat().replace("+00:00", "Z")})
    try:
        req = urllib.request.Request(f"{POSTIZ}/posts?{q}",
                                     headers={"Authorization": POSTIZ_TOKEN})
        with urllib.request.urlopen(req, timeout=25) as r:
            posts = json.loads(r.read()).get("posts", [])
    except Exception as e:
        AVISOS.append(f"Postiz: {e}")
        return []
    salida = []
    for p in posts:
        crudo = p.get("content", "")
        salida.append({
            "id": p.get("id", ""),
            "fecha": p["publishDate"][:10],
            "hora": p["publishDate"][11:16],
            "red": p.get("integration", {}).get("providerIdentifier", "?"),
            "estado": p.get("state", ""),
            "texto": re.sub("<[^>]+>", " ", crudo).strip()[:80],
            # el HTML completo: es lo que se lee al abrir la pieza en el calendario
            "html": limpiar_html(crudo),
            "link": p.get("releaseURL") or "",
        })
    return sorted(salida, key=lambda x: (x["fecha"], x["hora"]))


def suma(serie, metrica):
    return sum(d.get(metrica, 0) for d in serie.values())


def delta(actual, previo):
    """Variacion contra el período anterior: porcentaje Y cambio absoluto.

    Devuelve las dos cifras porque solas mienten. Con 65 de base, pasar a 1.436
    es "+2.109%", que se lee como un exito historico; el numero honesto al lado
    es "+1.371". El porcentaje dice la forma del cambio, el absoluto su tamaño.
    None si no hay base con que comparar (no se puede dividir por cero).
    """
    if not previo:
        return None
    return {"pct": round((actual - previo) / previo * 100, 1),
            "abs": actual - previo}


def fmt(x):
    """1234567 -> '1.234.567' (formato argentino), sin tocar el resto del texto."""
    return f"{x:,}".replace(",", ".")


def plural(tipo, n):
    """'Carrusel' -> 'carruseles'. Sin esto salia 'carrusels'."""
    t = tipo.lower()
    if n == 1:
        return t
    return t + ("es" if t.endswith(("l", "r", "d", "n")) else "s")


def atribuir_seguidores(posts, serie):
    """Cuántos seguidores trajo cada pieza. Devuelve la lista de piezas con dato.

    POR QUÉ ES NECESARIO ESTIMAR
    Instagram da `follows` por publicación, pero SOLO en feed: probado contra la API el
    2026-08-07, un reel devuelve
    "The Media Insights API does not support the profile_visits, follows metric for
    this media product type". Y los reels son justo donde entra la gente nueva.

    CÓMO SE ESTIMA, Y QUÉ TAN EN SERIO TOMARLO
    Se cruza el día de publicación con los seguidores ganados ese día y el siguiente
    (la mayor parte de las altas de una pieza caen en las primeras 48 h; una pieza
    publicada a la noche casi no suma en su propio día).

    La estimación se descarta si en esa ventana hay otra pieza: con dos piezas
    compitiendo no hay forma honesta de saber cuál trajo a quién. Preferimos no decir
    nada antes que repartir por la mitad e inventar precisión.

    Es correlación, no atribución. Sirve para ordenar piezas entre sí, no para
    afirmar "este reel me trajo exactamente 4 seguidores".
    """
    por_dia = {d["fecha"]: d.get("seguidores", 0) or 0 for d in serie}
    fechas_post = {}
    for p in posts:
        fechas_post.setdefault(p.get("fecha"), []).append(p)

    salida = []
    for p in posts:
        # El dato real le gana siempre a la estimación.
        if p.get("seguidores_ganados") is not None:
            p["seguidores_origen"] = "directo"
            salida.append(p)
            continue
        f = p.get("fecha")
        if not f or f not in por_dia:
            continue
        try:
            siguiente = (datetime.date.fromisoformat(f) + datetime.timedelta(days=1)).isoformat()
        except ValueError:
            continue
        ventana = [f] + ([siguiente] if siguiente in por_dia else [])
        # ¿Alguna otra pieza cae en la misma ventana? Entonces no se puede atribuir.
        if sum(len(fechas_post.get(d, [])) for d in ventana) > 1:
            continue
        p["seguidores_ganados"] = sum(por_dia.get(d, 0) for d in ventana)
        p["seguidores_origen"] = "estimado"
        salida.append(p)
    return salida


def insights(red, dias):
    """Lee las metricas y saca conclusiones accionables, en castellano.

    Cada regla se dispara SOLO si el dato existe y la muestra alcanza. Es la
    diferencia con un panel de demo: aca ninguna frase esta escrita de antemano,
    todas salen de los numeros de la cuenta.
    """
    fuera = []
    # YouTube devuelve los ultimos videos del canal aunque sean viejos, para
    # tener que mostrar. Para juzgar el RITMO hay que mirar solo el período.
    del_periodo = [p for p in red["posts"] if p.get("reciente", True)]
    posts = [p for p in red["posts"] if p.get("alcance") is not None]
    kpi = {k["nombre"]: k["valor"] for k in red["kpis"]}

    def agregar(nivel, titulo, detalle):
        fuera.append({"nivel": nivel, "titulo": titulo, "detalle": detalle})

    # --- que formato rinde, y donde estas poniendo el esfuerzo ---
    #
    # OJO: un formato no es "mejor" que otro, hace un TRABAJO distinto. Medirlos solo
    # por alcance es como decir que el delantero es mejor que el arquero porque hace mas
    # goles. Por eso cada formato se mide en dos ejes:
    #   ALCANCE  -> a cuanta gente llega (su trabajo de traer)
    #   ENGANCHE -> interacciones sobre alcance (su trabajo de convencer al que llego)
    #
    # Los datos de la industria (Socialinsider 2026) muestran que esos dos ejes van al
    # REVES entre si: los reels alcanzan 1,36x mas que los carruseles y 2,25x mas que
    # una imagen, pero el enganche por alcance es 6,90% en carrusel, 4,44% en imagen y
    # 3,31% en reel. Un panel que solo mire alcance te empuja a abandonar justo el
    # formato que mejor convierte.
    porf = {}
    for p in posts:
        g = porf.setdefault(p["tipo"], {"n": 0, "alc": 0, "eng": []})
        g["n"] += 1
        g["alc"] += p["alcance"]
        if p["alcance"]:
            inter = sum(p.get(c) or 0 for c in ("likes", "comentarios", "guardados", "compartidos"))
            g["eng"].append(inter / p["alcance"] * 100)
    prom = {t: g["alc"] / g["n"] for t, g in porf.items() if g["n"]}
    # Mediana y no promedio: una pieza viral corre el promedio y deja al resto de su
    # propio formato pareciendo un fracaso.
    engan = {t: statistics.median(g["eng"]) for t, g in porf.items() if len(g["eng"]) >= 2}
    if len(prom) >= 2:
        mejor = max(prom, key=prom.get)
        peor = min(prom, key=prom.get)
        veces = prom[mejor] / prom[peor] if prom[peor] else 0
        if veces >= 2:
            msg = (f"{mejor} alcanza {veces:.0f}x más que {peor} "
                   f"({prom[mejor]:.0f} contra {prom[peor]:.0f} de promedio).")
            # ¿El formato que menos alcanza es el que MEJOR engancha? Entonces no es
            # el formato equivocado: es el otro puesto del equipo.
            reparto = (peor in engan and mejor in engan and engan[mejor]
                       and engan[peor] / engan[mejor] >= 1.3)
            if reparto:
                agregar("bien", "Cada formato te hace un trabajo distinto",
                        msg + f" Pero al revés en enganche: {peor} tiene "
                              f"{engan[peor]:.1f}% de interacciones sobre alcance contra "
                              f"{engan[mejor]:.1f}% de {mejor}. "
                              f"{mejor.capitalize()} te trae gente nueva, {peor} convence "
                              f"a la que ya llegó. Necesitás los dos: sin el primero te "
                              f"quedás sin gente a quien convencer.")
            elif porf[peor]["n"] > porf[mejor]["n"]:
                agregar("alerta", "Estás apostando al formato equivocado",
                        msg + f" Y sin embargo publicaste {porf[peor]['n']} "
                              f"{plural(peor, porf[peor]['n'])} contra "
                              f"{porf[mejor]['n']} {plural(mejor, porf[mejor]['n'])}."
                        + (f" Tampoco compensa en enganche ({engan[peor]:.1f}% contra "
                           f"{engan[mejor]:.1f}%)." if peor in engan and mejor in engan else ""))
            else:
                agregar("bien", f"{mejor} es tu formato fuerte", msg)

    # --- te ven pero no te siguen ---
    alcance, seguidores = kpi.get("Alcance", 0), red.get("seguidores", 0)
    nuevos = red.get("seguidores_período")
    # Si tenemos el desglose por tipo de seguidor, la lectura de mas abajo dice esto
    # mismo pero sabiendo si la gente era nueva o no. Esta queda como respaldo para
    # las redes (o los períodos) donde ese desglose no existe.
    if alcance > 300 and nuevos is not None and red.get("pct_nuevos") is None:
        conv = nuevos / alcance * 100
        if conv < 0.5:
            agregar("alerta", "Te ven pero no te siguen",
                    f"{fmt(alcance)} cuentas te vieron y ganaste {nuevos} seguidores "
                    f"({conv:.2f}%). El contenido entretiene pero no da un motivo para quedarse.")

    # --- ¿entra gente nueva, o le hablás siempre al mismo círculo? ---
    #
    # Esta es la lectura que ningun numero suelto contesta. Un alcance de 900 puede ser
    # un negocio creciendo o un negocio agotando su propia lista de contactos, y son
    # situaciones opuestas que piden decisiones opuestas.
    #
    # SOBRE LOS UMBRALES, para que nadie los tome como ley:
    #   - NO existe un benchmark publicado y creible de "que % del alcance deberia ser
    #     de no seguidores". Cualquiera que te de un numero universal se lo invento.
    #     La unica referencia seria que encontramos: un estudio de +6M de perfiles
    #     (abril 2026) midio que ~55% de las vistas de Reels vienen de no seguidores.
    #     Sirve como orden de magnitud del formato, no como meta de tu cuenta.
    #   - Por eso el 30% de abajo es criterio nuestro, no un estandar: por debajo de
    #     ahi, 7 de cada 10 impresiones se las estas dando a gente que ya te conoce.
    #     El numero que de verdad importa es como se mueve ESTE numero contra vos
    #     mismo mes a mes (queda guardado en el historico desde hoy).
    pct_nuevos = red.get("pct_nuevos")
    audiencia_vista = red.get("audiencia_vista")
    if pct_nuevos is not None and alcance > 300:
        if pct_nuevos < 30:
            agregar("alerta", "Le estás hablando a los de siempre",
                    f"Solo el {pct_nuevos:.0f}% de tu alcance fue a cuentas que no te siguen. "
                    f"Tu contenido circula puertas adentro: sin gente nueva entrando, el "
                    f"crecimiento se termina cuando se agota tu propia lista.")
        elif pct_nuevos > 55:
            # Llega gente nueva. La pregunta pasa a ser si se queda.
            conv_nuevos = (nuevos / alcance * 100) if (nuevos is not None and alcance) else None
            if conv_nuevos is not None and conv_nuevos < 0.5:
                agregar("alerta", "Traés gente nueva pero no se queda",
                        f"{pct_nuevos:.0f}% de tu alcance fue a gente que no te sigue, y aun así "
                        f"solo {conv_nuevos:.2f}% terminó siguiéndote. El contenido funciona "
                        f"para que te descubran; el problema está en lo que encuentran "
                        f"después: el perfil, la bio y los primeros posts fijados.")
            else:
                agregar("bien", "Estás llegando a gente nueva",
                        f"{pct_nuevos:.0f}% de tu alcance fue a cuentas que no te seguían. "
                        f"Es el motor del crecimiento: esto es lo que hay que sostener.")

    # --- ¿QUE pieza te trae seguidores? ---
    #
    # Es la pregunta que abre la lectura de arriba: si llega gente nueva y no se queda,
    # lo unico accionable es saber cual de tus piezas SI la retuvo, para hacer mas de esa.
    # Sin esto el panel diagnostica y no receta.
    con_altas = [p for p in atribuir_seguidores(posts, red.get("serie") or [])
                 if (p.get("seguidores_ganados") or 0) > 0]
    if con_altas and nuevos:
        con_altas.sort(key=lambda p: -(p["seguidores_ganados"] or 0))
        top = con_altas[0]
        # DOS condiciones, y las dos hacen falta:
        #   - que la pieza explique una porcion real del período (30%), y
        #   - un minimo absoluto. "De 3 seguidores, 1 vino de este reel" pasa el 30% y
        #     no significa nada: a esa escala una persona te sigue porque te cruzo en
        #     otro lado. Mismo criterio que MINIMO_PARA_COMPARAR en senales.py:
        #     callarse es una respuesta valida.
        if top["seguidores_ganados"] >= 5 and top["seguidores_ganados"] / nuevos >= 0.3:
            estimado = top.get("seguidores_origen") == "estimado"
            resto = [p for p in con_altas[1:3]]
            n = top["seguidores_ganados"]
            detalle = (f"De los {nuevos} seguidores del período, {n} "
                       f"{'llegó' if n == 1 else 'llegaron'} con tu "
                       f"{top.get('tipo', 'pieza').lower()} del {top.get('fecha')}. ")
            if resto:
                detalle += ("Le siguen: " + ", ".join(
                    f"{p.get('tipo', '?').lower()} del {p.get('fecha')} ({p['seguidores_ganados']})"
                    for p in resto) + ". ")
            detalle += ("Ese es el contenido que no solo te hace ver, te hace seguir: "
                        "mirá qué tiene en común y repetilo.")
            if estimado:
                # Nunca presentar una estimacion como si fuera un dato medido.
                detalle += (" (Estimado: Instagram no informa seguidores por reel, así que "
                            "se cruza el día de publicación con las altas de ese día y el "
                            "siguiente. Sirve para ordenar piezas, no como número exacto.)")
            agregar("bien", "Esta pieza es la que te trae seguidores", detalle)

    # Tu propia audiencia no te esta viendo. Es un problema distinto al anterior y se
    # arregla distinto: no es que falte gente nueva, es que los que ya tenes no te ven.
    # El 30% es criterio nuestro, no un benchmark publicado: en un mes entero de
    # publicaciones, no llegar a un tercio de tu propia gente es señal de que Instagram
    # dejo de mostrarte a los tuyos.
    if audiencia_vista is not None and red.get("seguidores", 0) > 200 and audiencia_vista < 30:
        agregar("alerta", "Tus propios seguidores no te están viendo",
                f"Solo el {audiencia_vista:.0f}% de tus seguidores llegó a verte en "
                f"{dias} días. No es un problema de audiencia chica: es que la que ya "
                f"tenés no está recibiendo lo que publicás.")

    # --- el contenido no mueve al siguiente paso ---
    visitas = kpi.get("Visitas al perfil", 0)
    if alcance > 300:
        ctr = visitas / alcance * 100
        if ctr < 3:
            agregar("alerta", "El contenido no manda a nadie al perfil",
                    f"Solo {ctr:.1f}% de los que te vieron entraron al perfil "
                    f"({visitas} de {fmt(alcance)}). Falta un CTA que empuje.")
        elif ctr > 8:
            agregar("bien", "Tu contenido empuja al perfil",
                    f"{ctr:.1f}% de los alcanzados visitaron el perfil. Muy por encima de lo normal.")

    # --- retención: la señal #1, y la que se lee al revés de lo que todos creen ---
    #
    # El error clásico es mirar los segundos vistos: "34 segundos, bárbaro". Pero 34
    # segundos de un video de 2:23 es que se fueron a la cuarta parte. Lo que pesa es
    # el PORCENTAJE, y por eso un video más corto con la misma historia rinde más.
    rets = [(p.get("retencion"), p) for p in posts if p.get("retencion") is not None]
    if len(rets) >= 3:
        valores = sorted(r for r, _ in rets)
        mediana_ret = valores[len(valores) // 2]
        largos = [p for r, p in rets if p.get("duracion") and p["duracion"] > 60]
        # Un video que dura el doble que el resto y retiene menos: el problema no es
        # el tema, es el metraje. Es la recomendación más barata que existe.
        flojos = [p for p in largos if (p.get("retencion") or 0) < mediana_ret]
        if flojos:
            p = max(flojos, key=lambda x: x["duracion"])
            agregar("alerta", "Tus videos largos no se sostienen",
                    f"El del {p['fecha']} dura {p['duracion']:.0f} segundos y solo lo "
                    f"miraron un {p['retencion']:.0f}% ({p['seg_vistos']:.0f}s). Tu mediana "
                    f"es {mediana_ret:.0f}%. La misma historia contada en la mitad de "
                    f"tiempo termina con más gente adentro, y el tiempo de visualización "
                    f"es la señal que más pesa para que te muestren.")
        elif mediana_ret >= 50:
            agregar("bien", "La gente se queda a ver tus reels",
                    f"Mediana de retención del {mediana_ret:.0f}%: se miran más de la "
                    f"mitad de cada video. Es la señal más fuerte que existe y la tenés "
                    f"a favor.")

    # --- guardados y compartidos: señales de valor real ---
    guardados = sum(p.get("guardados", 0) or 0 for p in posts)
    compartidos = sum(p.get("compartidos", 0) or 0 for p in posts)
    if posts and alcance > 300:
        if guardados == 0:
            agregar("alerta", "Nadie guarda tu contenido",
                    "Cero guardados en el período. El guardado es la señal de "
                    "'esto me sirve después': sin él, no estás creando material de referencia.")
        if compartidos == 0:
            agregar("alerta", "Nadie comparte tu contenido",
                    "Cero compartidos. Lo que se comparte es lo que le sirve a alguien "
                    "para decir algo por vos. Sin eso no hay crecimiento orgánico.")

    # --- ritmo de publicación ---
    if del_periodo:
        cada = dias / len(del_periodo)
        if cada > 4:
            agregar("alerta", "Estás publicando poco",
                    f"{len(del_periodo)} piezas en {dias} días, una cada {cada:.1f} días. "
                    f"Con esa frecuencia el algoritmo no tiene con qué trabajar.")
        elif cada <= 1.5:
            agregar("bien", "Buen ritmo de publicación",
                    f"{len(del_periodo)} piezas en {dias} días.")
    elif red["posts"]:
        agregar("alerta", "No publicaste nada en el período",
                f"Las piezas que se ven abajo son las últimas del canal, pero ninguna "
                f"salió en los últimos {dias} días. Un canal sin piezas nuevas deja de "
                f"recibir distribución.")

    # --- la pieza que se despego ---
    if len(posts) >= 3:
        orden = sorted(posts, key=lambda p: -p["alcance"])
        top, resto = orden[0], orden[1:]
        media_resto = sum(p["alcance"] for p in resto) / len(resto)
        if media_resto and top["alcance"] / media_resto >= 3:
            agregar("bien", "Tenés una pieza que se despegó",
                    f'"{top["texto"][:70]}" hizo {fmt(top["alcance"])} de alcance, '
                    f"{top['alcance'] / media_resto:.0f}x el promedio del resto. "
                    f"Vale la pena estudiar por qué funcionó y repetir la fórmula.")

    return fuera


def brief(red):
    """Que conviene publicar en esta red, deducido de sus propias metricas.

    Lo consumen el panel (seccion Generador) y `generador.py`: una sola
    definicion, dos consumidores.
    """
    posts = [p for p in red["posts"] if p.get("alcance")]
    if not posts:
        return None

    porf = {}
    for p in posts:
        g = porf.setdefault(p["tipo"], {"n": 0, "alc": 0})
        g["n"] += 1
        g["alc"] += p["alcance"]
    prom = {t: g["alc"] / g["n"] for t, g in porf.items()}
    ganador = max(prom, key=prom.get)

    guardados = sum(p.get("guardados", 0) or 0 for p in posts)
    compartidos = sum(p.get("compartidos", 0) or 0 for p in posts)
    comentarios = sum(p.get("comentarios", 0) or 0 for p in posts)
    if guardados == 0:
        objetivo, pide = "Guardado", ("Nadie guardó nada en el período. Hacé una pieza de "
                                      "referencia: checklist, pasos numerados, comparativa. "
                                      "Algo que valga la pena volver a mirar.")
    elif compartidos == 0:
        objetivo, pide = "Compartido", ("Nadie compartió nada. Hacé una pieza que le sirva a "
                                        "alguien para decir algo por vos: una verdad incómoda "
                                        "del rubro.")
    elif comentarios <= 2:
        objetivo, pide = "Comentario", ("Casi no hay conversación. Cerrá con una pregunta "
                                        "concreta o pedí una palabra clave.")
    else:
        objetivo, pide = "Conversión", ("Las señales sociales están; ahora pedí la acción.")

    return {
        "formato": ganador,
        "alcance_formato": round(prom[ganador]),
        "objetivo": objetivo,
        "pide": pide,
        "ganchos": [{"texto": p["texto"].split(".")[0][:88], "alcance": p["alcance"]}
                    for p in sorted(posts, key=lambda x: -x["alcance"])[:3]],
    }


def horarios(red):
    """Cruza la hora de publicacion con el alcance que consiguio cada pieza.

    No es el 'horario en que tu audiencia esta online' (eso Meta lo devuelve
    vacio en cuentas chicas): es el horario en el que a VOS te funciono. Con
    pocas piezas dice poco, por eso viaja siempre con la cantidad de muestra.
    """
    piezas = [p for p in red["posts"] if p.get("hora") and p.get("alcance")]
    if len(piezas) < 3:
        return None

    # Instagram devuelve UTC; la cuenta es de Argentina (UTC-3)
    def local(h):
        return (int(h[:2]) - 3) % 24

    franjas = {}
    for p in piezas:
        h = local(p["hora"])
        # agrupamos de a 3 horas: con pocas piezas, franjas mas finas son ruido
        f = (h // 3) * 3
        g = franjas.setdefault(f, {"n": 0, "alc": 0, "piezas": []})
        g["n"] += 1
        g["alc"] += p["alcance"]
        g["piezas"].append(p["texto"][:52])

    filas = [{"franja": f"{f:02d}:00–{(f + 3) % 24:02d}:00",
              "desde": f, "n": g["n"], "promedio": round(g["alc"] / g["n"]),
              "ejemplos": g["piezas"][:2]}
             for f, g in sorted(franjas.items())]
    mejor = max(filas, key=lambda x: x["promedio"])
    return {"franjas": filas, "mejor": mejor["franja"],
            "muestra": len(piezas),
            "nota": (f"Sobre {len(piezas)} piezas. Con esta cantidad es una pista, "
                     f"no una ley: hacen falta unas 20 para hablar en serio.")}


def mix_engagement(red):
    """De que esta hecha la interaccion: likes, comentarios, guardados, compartidos."""
    posts = red["posts"]
    partes = [
        ("Likes", sum(p.get("likes", 0) or 0 for p in posts)),
        ("Comentarios", sum(p.get("comentarios", 0) or 0 for p in posts)),
        ("Guardados", sum(p.get("guardados", 0) or 0 for p in posts)),
        ("Compartidos", sum(p.get("compartidos", 0) or 0 for p in posts)),
    ]
    total = sum(v for _, v in partes)
    if not total:
        return []
    return [{"nombre": k, "valor": v, "pct": round(v / total * 100, 1)}
            for k, v in partes if v]


TODAS = ("instagram", "facebook", "youtube", "tiktok", "ads", "calendario")


def redes_pedidas():
    """Qué redes hay que volver a bajar. Por defecto, todas.

        python3 recolector.py --red instagram
        python3 recolector.py --red instagram,youtube
        python3 recolector.py --red ads         # sólo las campañas
        python3 recolector.py --red calendario  # sólo lo programado en Postiz

    Existe porque bajar todo son ~53 segundos y una sola red son ~18: si venís
    a mirar Instagram no tiene sentido esperar a que YouTube y Meta Ads terminen.
    Lo que no se pide NO queda vacío: se hereda del panel anterior.

    `ads` entra en la lista aunque no sea una red social: se baja aparte, con
    otra credencial, y cuesta ~12s que casi nunca hacen falta.

    `calendario` también, pero por el motivo opuesto: cuesta medio segundo, así
    que se baja SIEMPRE y nunca se hereda. Pedirlo solo (`--red calendario`) es
    la forma de ver en el panel algo que acabás de programar en Postiz sin
    esperar el minuto de las redes.
    """
    if "--red" not in sys.argv:
        return set(TODAS)
    i = sys.argv.index("--red")
    if i + 1 >= len(sys.argv):
        sys.exit("--red necesita un valor: --red instagram[,youtube]")
    pedidas = {r.strip().lower() for r in sys.argv[i + 1].split(",") if r.strip()}
    desconocidas = pedidas - set(TODAS)
    if desconocidas:
        sys.exit(f"No conozco esa red: {', '.join(sorted(desconocidas))}. "
                 f"Las que hay: {', '.join(TODAS)}")
    if not pedidas:
        sys.exit("--red necesita al menos una red")
    return pedidas


def del_panel_anterior(nombre):
    """Los datos de una red tal como quedaron en la última recolección.

    Devuelve None si no hay panel previo o si esa red nunca se bajó: en ese caso
    quien llama tiene que recolectarla igual, porque heredar la nada dejaría el
    panel mostrando una red vacía como si fuera un dato real.
    """
    if not os.path.exists(PANEL_SALIDA):
        return None
    try:
        m = re.search(r"const DATOS = (\{.*?\});\n",
                      open(PANEL_SALIDA, encoding="utf-8").read(), re.S)
        if not m:
            return None
        red = json.loads(m.group(1)).get("redes", {}).get(nombre)
        return limpiar_derivados(red) if red else None
    except (json.JSONDecodeError, OSError):
        return None


def del_panel_anterior_ads():
    """Las campañas tal como quedaron en la última recolección.

    Van por separado de las redes porque en el JSON viven en `ads`, no adentro
    de `redes`. Devuelve None si no hay panel previo (hay que bajarlas) y []
    si el panel existía y no tenía campañas — que es un dato, no una falta.
    """
    if not os.path.exists(PANEL_SALIDA):
        return None
    try:
        m = re.search(r"const DATOS = (\{.*?\});\n",
                      open(PANEL_SALIDA, encoding="utf-8").read(), re.S)
        return json.loads(m.group(1)).get("ads") if m else None
    except (json.JSONDecodeError, OSError):
        return None


def limpiar_derivados(red):
    """Saca de una red heredada lo que el post-proceso vuelve a calcular.

    Hace falta por un caso concreto y silencioso: `atribuir_seguidores` marca una
    pieza como "directo" cuando ya trae `seguidores_ganados`, porque asume que
    ese numero vino de la API. En una red heredada ese numero puede ser de la
    corrida anterior y haber sido ESTIMADO — al volver a pasar, la estimacion se
    promovia a dato duro y encima desaparecia el aviso de "esto es aproximado".
    Un numero inventado presentado como medicion es peor que no tener el numero.

    Solo se limpia lo estimado: si el origen era "directo", el dato salio de la
    API y sigue siendo tan valido como el dia que se bajo.
    """
    for p in red.get("posts", []):
        if p.get("seguidores_origen") == "estimado":
            p.pop("seguidores_ganados", None)
            p.pop("seguidores_origen", None)
    return red


_reloj = [None, None]   # [arranque del paso actual, nombre del paso actual]


def paso(nombre):
    """Anuncia un paso y, al empezar el siguiente, dice cuánto tardó el anterior.

    Sirve para saber DÓNDE se va el minuto y medio. Sin este dato, optimizar es
    adivinar: la intuición dice que las tres redes tardan parecido, y la medición
    suele decir que una se lleva casi todo.
    """
    if _reloj[0] is not None:
        print(f"      ({_reloj[1]}: {time.time() - _reloj[0]:.1f}s)")
    _reloj[0], _reloj[1] = time.time(), nombre
    print(nombre)


REPO_CONFIG = ("https://raw.githubusercontent.com/MartinOlivero/"
               "command-center/main/config.py")

# Redes que NO desaparecen del panel cuando están apagadas: se muestran pendientes de
# conectar. Instagram y Facebook salen del mismo token, así que apagarlas es una decisión
# ("no uso esa red") y mostrarlas vacías molestaría. Estas dos, en cambio, están apagadas
# porque falta un trámite —y lo que no se ve, no se pide.
POR_CONECTAR = {
    "youtube": ("Conectar YouTube pide una autorización propia con Google, aparte del "
                "token de Meta. Está explicado en el README, y si preferís que lo deje "
                "andando por vos, escribime: iamautom.com"),
    "tiktok": ("Conectar TikTok pide autorizar la cuenta desde el navegador, aparte del "
               "token de Meta. Está explicado en el README, y si preferís que lo deje "
               "andando por vos, escribime: iamautom.com"),
}


def _red_pendiente(red):
    """Una red apagada, mostrada como pendiente en vez de borrada del panel."""
    return {"nombre": {"youtube": "YouTube", "tiktok": "TikTok"}[red],
            "conectada": False, "cuenta": "sin conectar", "seguidores": 0, "foto": "",
            "kpis": [], "serie": [], "serie_etiqueta": "", "posts": [],
            "pais": [], "ciudad": [], "motivo": POR_CONECTAR[red]}


def version_publicada():
    """La última versión publicada, o None si no se pudo averiguar.

    Sin esto el panel tiene botón de actualizar y nadie lo aprieta nunca, porque no hay
    forma de enterarse de que hay algo nuevo.

    Se lee la VERSION del `config.py` del repositorio en vez de usar releases: así la
    versión vive en UN solo lugar y no hay dos números que se puedan contradecir.

    Nunca puede frenar la recolección: si no hay internet, si el repo es privado o si
    tarda, devuelve None y el panel simplemente no muestra el aviso. Cuatro segundos de
    espera es el techo — nadie va a esperar más por un cartel informativo.
    """
    try:
        with urllib.request.urlopen(REPO_CONFIG, timeout=4) as r:
            # El archivo entero (son 7 KB). Leer "los primeros N bytes" parecía más
            # prudente, pero deja una bomba: el día que el comentario de arriba de
            # VERSION crezca y la empuje más abajo, el aviso deja de aparecer y nadie
            # se entera. El tope es solo para no tragarse una respuesta absurda.
            texto = r.read(200_000).decode("utf-8", "replace")
        hallado = re.search(r'^VERSION\s*=\s*"([^"]+)"', texto, re.M)
        if not hallado or hallado.group(1) == config.VERSION:
            return None
        return hallado.group(1)
    except Exception:                      # noqa: BLE001 — un cartel no rompe la corrida
        return None


def estado_meta(cred):
    """Diagnostico del token de Meta: quien es, que puede hacer, cuando caduca.

    Es el 'panel de conexion': en vez de fallar en silencio, dice que falta.
    """
    tok = cred["IG_PAGE_TOKEN"]
    d = get(f"{GRAPH}/debug_token?input_token={tok}&access_token={tok}").get("data", {})
    exp = d.get("expires_at", 0)
    return {
        "app": d.get("application", "?"),
        "app_id": d.get("app_id", ""),
        "graph": GRAPH_VERSION,
        "valido": bool(d.get("is_valid")),
        "caduca": "nunca" if exp == 0 else datetime.datetime.fromtimestamp(exp).strftime("%d/%m/%Y"),
        "permisos": sorted(d.get("scopes", [])),
    }


def _facebook(cred, inicio, inicio_previo, ahora):
    """Los datos de la Página de Facebook, ya con la forma que usa el panel.

    Extraida de main() para poder SALTEARLA cuando se actualiza una sola red.
    Todo lo que necesita entra por parametro y todo lo que produce sale por el
    return: no toca `redes` ni ninguna variable de afuera.
    """
    fb_perfil, fb_serie, fb_posts = facebook(cred, inicio, ahora)
    _, fb_serie_prev, fb_posts_prev = facebook(cred, inicio_previo, inicio)
    fb_inter = sum(p["interacciones"] for p in fb_posts)
    fb_inter_prev = sum(p["interacciones"] for p in fb_posts_prev)
    return {
        "nombre": "Facebook",
        "conectada": bool(fb_perfil.get("name")),
        "cuenta": fb_perfil.get("name", "?"),
        "seguidores": fb_perfil.get("followers_count", 0),
        # Meta no entrega estadísticas de Páginas con menos de 100 likes: devuelve ceros
        # sin explicar nada. Decirlo acá evita la lectura equivocada —y cara— de que el
        # panel está roto. Cuando la Página cruce los 100, los números aparecen solos.
        "motivo": (
            f"Meta todavía no entrega estadísticas de esta Página: hacen falta 100 "
            f"seguidores y hoy tiene {fb_perfil.get('fan_count', 0)}. No es un error del "
            f"panel — los números van a aparecer solos cuando la Página cruce ese número."
            if fb_perfil.get("name") and fb_perfil.get("fan_count", 0) < 100 else None),
        "foto": "",
        "kpis": [
            {"nombre": "Seguidores", "valor": fb_perfil.get("followers_count", 0),
             "delta": None, "nota": "total de la Página"},
            {"nombre": "Visitas a la Página", "valor": suma(fb_serie, "page_views_total"),
             "delta": delta(suma(fb_serie, "page_views_total"),
                            suma(fb_serie_prev, "page_views_total")),
             "nota": "en el período"},
            {"nombre": "Interacciones", "valor": fb_inter,
             "delta": delta(fb_inter, fb_inter_prev),
             "nota": "reacciones + comentarios + compartidos"},
            {"nombre": "Publicaciones", "valor": len(fb_posts),
             "delta": delta(len(fb_posts), len(fb_posts_prev)),
             "nota": "en el período"},
        ],
        "serie": [{"fecha": f, "valor": v.get("page_views_total", 0)}
                  for f, v in sorted(fb_serie.items())],
        "serie_etiqueta": "Visitas a la Página por dia",
        "posts": sorted(fb_posts, key=lambda p: -p["interacciones"]),
        "pais": [], "ciudad": [],
        # Limite real de la plataforma, no del panel: que quede escrito.
        "limite": "Meta eliminó el alcance por publicación de la API en la v25. "
                  "Solo quedan interacciones y métricas a nivel Página.",
    }

def _youtube_red(inicio, ahora):
    """Los datos del canal, o el motivo por el que no se pudieron traer.

    Devuelve SIEMPRE un dict: la rama de error tambien, porque el panel
    necesita mostrar "no conectado y por que" en vez de un hueco.
    """
    yt, motivo = youtube(inicio, ahora)
    if yt:
        canal, videos = yt["canal"], yt["videos"]
        tot, prev = yt.get("tot", {}), yt.get("tot_previo", {})
        st = canal.get("statistics", {})
        recientes = [v for v in videos if v["reciente"]]
        return {
            "nombre": "YouTube",
            "conectada": True,
            "cuenta": canal["snippet"]["title"],
            "canal_id": canal.get("id", ""),
            "seguidores": int(st.get("subscriberCount", 0)),
            "foto": incrustar_miniatura(
                canal["snippet"]["thumbnails"].get("default", {}).get("url", "")),
            "kpis": [
                {"nombre": "Suscriptores", "valor": int(st.get("subscriberCount", 0)),
                 "delta": None, "nota": f"+{tot.get('suscriptores', 0)} en el período"},
                {"nombre": "Vistas del período", "valor": tot.get("vistas", 0),
                 "delta": delta(tot.get("vistas", 0), prev.get("vistas", 0)),
                 "nota": "reproducciones en la ventana"},
                {"nombre": "Minutos vistos", "valor": tot.get("minutos", 0),
                 "delta": delta(tot.get("minutos", 0), prev.get("minutos", 0)),
                 "nota": "el tiempo real que te regalaron"},
                {"nombre": "Retención promedio", "valor": tot.get("retencion", 0), "sufijo": "%",
                 "delta": delta(tot.get("retencion", 0), prev.get("retencion", 0)),
                 "nota": "cuánto del video se mira, de verdad"},
                {"nombre": "Duración vista", "valor": tot.get("seg_promedio", 0), "sufijo": "s",
                 "delta": delta(tot.get("seg_promedio", 0), prev.get("seg_promedio", 0)),
                 "nota": "segundos promedio por reproducción"},
                {"nombre": "Suscriptores ganados", "valor": tot.get("suscriptores", 0),
                 "delta": delta(tot.get("suscriptores", 0), prev.get("suscriptores", 0)),
                 "nota": "en el período"},
                {"nombre": "Vistas del canal", "valor": int(st.get("viewCount", 0)),
                 "delta": None, "nota": "históricas, desde que abriste"},
                {"nombre": "Videos publicados", "valor": int(st.get("videoCount", 0)),
                 "delta": None, "nota": "total del canal"},
            ],
            "serie": yt.get("serie", []),
            "serie_etiqueta": "Vistas por día",
            "curvas": yt.get("curva", []),
            "top_id": yt.get("top_id"),
            "posts": sorted(videos, key=lambda v: -v["vistas"]),
            "pais": [], "ciudad": [],
            "nota_periodo": f"{len(recientes)} publicados en los últimos {DIAS} días",
        }
    else:
        return {
            "nombre": "YouTube", "conectada": False, "cuenta": "sin conectar",
            "seguidores": 0, "foto": "", "kpis": [], "serie": [], "serie_etiqueta": "",
            "posts": [], "pais": [], "ciudad": [], "motivo": motivo,
        }


def _tiktok_red(inicio, ahora):
    """Los datos de TikTok, o el motivo por el que no se pudieron traer.

    OJO CON LAS EXPECTATIVAS: la Display API pública de TikTok da seguidores, likes,
    videos y, por video, vistas/likes/comentarios/shares. NO da alcance, impresiones,
    retención ni demografía — esos campos no existen en esa API, viven en la app.
    Por eso esta pantalla tiene menos KPIs que Instagram y no es un error.
    """
    # 20 es lo que TikTok devuelve por llamada; alcanza de sobra para una ventana de
    # 30 días y evita paginar de más en cuentas con mucho contenido.
    datos, motivo = tiktok.resumen(cantidad=20)
    if not datos:
        return {
            "nombre": "TikTok", "conectada": False, "cuenta": "sin conectar",
            "seguidores": 0, "foto": "", "kpis": [], "serie": [], "serie_etiqueta": "",
            "posts": [], "pais": [], "ciudad": [], "motivo": motivo,
        }

    p, vids = datos["perfil"], datos["videos"]
    desde = inicio.timestamp()
    posts = []
    for v in vids:
        vistas = v.get("view_count", 0) or 0
        inter = (v.get("like_count", 0) or 0) + (v.get("comment_count", 0) or 0) \
            + (v.get("share_count", 0) or 0)
        creado = v.get("create_time", 0) or 0
        posts.append({
            "fecha": datetime.datetime.fromtimestamp(
                creado, datetime.timezone.utc).strftime("%Y-%m-%d") if creado else "",
            "reciente": creado >= desde,
            "tipo": "TikTok",
            "texto": (v.get("title") or "")[:110],
            "id_video": v.get("id", ""),
            "link": v.get("share_url", ""),
            "miniatura": "",          # la Display API no devuelve miniatura
            "alcance": vistas,        # acá la vara comparable son las vistas, como en YT
            "vistas": vistas,
            "likes": v.get("like_count", 0) or 0,
            "comentarios": v.get("comment_count", 0) or 0,
            "compartidos": v.get("share_count", 0) or 0,
            "interacciones": inter,
            "engagement": round(inter / vistas * 100, 1) if vistas else 0,
        })

    recientes = [v for v in posts if v["reciente"]]
    vistas_periodo = sum(v["vistas"] for v in recientes)
    return {
        "nombre": "TikTok",
        "conectada": True,
        "cuenta": p.get("display_name", ""),
        "seguidores": p.get("follower_count", 0),
        "foto": "",
        "kpis": [
            {"nombre": "Seguidores", "valor": p.get("follower_count", 0),
             "delta": None, "nota": "total de la cuenta"},
            {"nombre": "Vistas del período", "valor": vistas_periodo, "delta": None,
             "nota": f"de lo publicado en los últimos {DIAS} días"},
            {"nombre": "Likes totales", "valor": p.get("likes_count", 0),
             "delta": None, "nota": "históricos, desde que abriste"},
            {"nombre": "Videos publicados", "valor": p.get("video_count", 0),
             "delta": None, "nota": "total de la cuenta"},
        ],
        "serie": [], "serie_etiqueta": "",
        "posts": sorted(posts, key=lambda v: -v["vistas"]),
        "pais": [], "ciudad": [],
        "nota_periodo": f"{len(recientes)} publicados en los últimos {DIAS} días",
        # `limite` ya lo pinta la plantilla como aviso. Sin esta línea, la pantalla
        # parece incompleta por un error nuestro y no por un límite de TikTok.
        "limite": "TikTok no presta alcance, retención ni demografía por su API pública: "
                  "esos números solo están dentro de la app.",
    }


def _instagram(cred, inicio, inicio_previo, ahora):
    """Perfil, metricas, piezas y conversacion de Instagram.

    Incluye la bajada de comentarios: es parte de la foto de la red y no
    tendria sentido heredar los numeros de Instagram con la conversacion
    de otra corrida.
    """
    perfil = get(f"{GRAPH}/{cred['IG_USER_ID']}?fields=username,name,followers_count,"
                 f"follows_count,media_count,profile_picture_url"
                 f"&access_token={cred['IG_PAGE_TOKEN']}")
    perfil["profile_picture_url"] = incrustar_miniatura(perfil.get("profile_picture_url"))
    serie = insights_diarios(cred, CON_SERIE_DIARIA, inicio, ahora)
    tot = insights_totales(cred, SOLO_TOTAL + ("reach",), inicio, ahora)
    tot_previo = insights_totales(cred, SOLO_TOTAL + ("reach",), inicio_previo, inicio)
    posts = publicaciones(cred, inicio)
    def kpi(nombre, clave, nota):
        return {"nombre": nombre, "valor": tot.get(clave, 0),
                "delta": delta(tot.get(clave, 0), tot_previo.get(clave, 0)), "nota": nota}
    alcance_ig = tot.get("reach", 0)
    nuevos_ig = suma(serie, "follower_count")
    # ratios derivados: dicen mas que los numeros crudos
    er = round(tot.get("total_interactions", 0) / alcance_ig * 100, 1) if alcance_ig else 0
    ctr_perfil = round(tot.get("profile_views", 0) / alcance_ig * 100, 1) if alcance_ig else 0
    frecuencia = round(tot.get("views", 0) / alcance_ig, 2) if alcance_ig else 0
    # Alcance partido entre gente que te sigue y gente que no. Es el unico dato del
    # panel que contesta "¿este contenido trae gente nueva o le habla a los de siempre?".
    reparto = insights_desglose(cred, "reach", "follow_type", inicio, ahora)
    fuera = reparto.get("NON_FOLLOWER", 0)
    dentro = reparto.get("FOLLOWER", 0)
    # UNKNOWN queda afuera del porcentaje a proposito: es alcance que Meta no supo
    # atribuir, y meterlo en cualquiera de los dos lados inventa precision que no hay.
    base_reparto = fuera + dentro
    pct_nuevos = round(fuera / base_reparto * 100, 1) if base_reparto else None
    # Que porcion de TU PROPIA audiencia llegaste a tocar. Es el numero que separa
    # "tengo pocos seguidores" de "tengo seguidores y no me estan viendo".
    #
    # OJO CON LA FORMULA. El benchmark que anda dando vueltas (12% para feed, Hootsuite)
    # divide el alcance TOTAL por los seguidores, y eso solo tiene sentido en cuentas
    # donde el alcance viene mayormente de seguidores. En una cuenta chica que distribuye
    # por Reels da numeros como 728%, que no significan nada: no alcanzaste 7 veces a tu
    # audiencia, alcanzaste a un monton de gente que no es tu audiencia.
    # Por eso dividimos el alcance de SEGUIDORES sobre los seguidores. Deja de ser
    # comparable con ese 12% publicado, y a cambio mide lo que dice medir.
    seguidores_ig = perfil.get("followers_count", 0)
    audiencia_vista = (round(dentro / seguidores_ig * 100, 1)
                       if seguidores_ig and dentro else None)
    red = {
        "nombre": "Instagram",
        "conectada": bool(perfil.get("username")),
        "cuenta": "@" + perfil.get("username", "?"),
        "seguidores": perfil.get("followers_count", 0),
        "seguidores_período": nuevos_ig,
        "foto": perfil.get("profile_picture_url", ""),
        "kpis": [
            {"nombre": "Seguidores", "valor": perfil.get("followers_count", 0),
             "delta": None, "nota": f"+{nuevos_ig} en el período"},
            kpi("Alcance", "reach", "cuentas distintas que te vieron"),
            kpi("Vistas", "views", "veces que se reprodujo tu contenido"),
            kpi("Interacciones", "total_interactions", "likes + comentarios + guardados + compartidos"),
            kpi("Visitas al perfil", "profile_views", "el contenido mueve al siguiente paso"),
            kpi("Cuentas que reaccionaron", "accounts_engaged", "personas distintas, no acciones"),
            kpi("Guardados", "saves", "señal de 'esto me sirve después'"),
            kpi("Compartidos", "shares", "señal de 'esto le sirve a otro'"),
            kpi("Comentarios", "comments", "la conversación que abriste"),
            kpi("Clics a la web", "website_clicks", "el link de la bio"),
            {"nombre": "Engagement rate", "valor": er, "delta": None, "sufijo": "%",
             "nota": "interacciones sobre alcance"},
            {"nombre": "Frecuencia", "valor": frecuencia, "delta": None, "sufijo": "x",
             "nota": "veces que te vio cada cuenta alcanzada"},
        ] + ([{"nombre": "Alcance en gente nueva", "valor": pct_nuevos, "delta": None,
               "sufijo": "%", "nota": "del alcance fue a cuentas que NO te siguen"}]
             if pct_nuevos is not None else [])
          + ([{"nombre": "Tu audiencia alcanzada", "valor": audiencia_vista, "delta": None,
               "sufijo": "%", "nota": "de tus seguidores llegó a verte en el período"}]
             if audiencia_vista is not None else []),
        "pct_nuevos": pct_nuevos,
        "audiencia_vista": audiencia_vista,
        "ctr_perfil": ctr_perfil,
        "serie": [{"fecha": f, "valor": v.get("reach", 0),
                   "seguidores": v.get("follower_count", 0)} for f, v in sorted(serie.items())],
        "serie_etiqueta": "Alcance por día",
        "posts": sorted(posts, key=lambda p: -(p["alcance"] or 0)),
        "pais": demografia(cred, "country"),
        "ciudad": demografia(cred, "city"),
    }
    # El texto de los comentarios: acá están los leads. Se guarda aparte (comentarios.json)
    # y NO se incrusta en el panel — el panel muestra el análisis, no la conversación cruda.
    # Si falla, el panel se genera igual: son datos extra, no el corazón del recolector.
    try:
        filas = comentarios.actualizar(
            get, GRAPH, cred["IG_PAGE_TOKEN"],
            red["posts"], red["cuenta"])
        red["conversacion"] = comentarios.resumen(
            [c for c in filas if c.get("red", "instagram") == "instagram"])
    except (urllib.error.URLError, OSError, KeyError) as e:
        AVISOS.append(f"No pude bajar los comentarios de Instagram ({e}).")
    return red

def main():
    cred = credenciales()
    PEDIDAS = redes_pedidas()
    if len(PEDIDAS) < len(TODAS):
        print(f"Actualizando solo: {', '.join(sorted(PEDIDAS))}. "
              f"El resto se hereda del panel anterior.\n")
    ahora = datetime.datetime.now(datetime.timezone.utc)
    inicio = ahora - datetime.timedelta(days=DIAS)
    inicio_previo = ahora - datetime.timedelta(days=DIAS * 2)
    redes = {}

    # ---- INSTAGRAM ----
    if "instagram" in PEDIDAS or del_panel_anterior("instagram") is None:
        paso(f"[1/7] Instagram ({DIAS} días)...")
        redes["instagram"] = _instagram(cred, inicio, inicio_previo, ahora)
    else:
        redes["instagram"] = del_panel_anterior("instagram")
        redes["instagram"]["heredada"] = True

    # ---- FACEBOOK ----
    if "facebook" in PEDIDAS or del_panel_anterior("facebook") is None:
        paso("[2/7] Facebook...")
        redes["facebook"] = _facebook(cred, inicio, inicio_previo, ahora)
    else:
        redes["facebook"] = del_panel_anterior("facebook")
        redes["facebook"]["heredada"] = True

    # ---- YOUTUBE ----
    if "youtube" in PEDIDAS or del_panel_anterior("youtube") is None:
        paso("[3/7] YouTube...")
        redes["youtube"] = _youtube_red(inicio, ahora)
    else:
        redes["youtube"] = del_panel_anterior("youtube")
        redes["youtube"]["heredada"] = True

    # ---- TIKTOK ----
    if config.red_activa(CFG, "tiktok"):
        if "tiktok" in PEDIDAS or del_panel_anterior("tiktok") is None:
            paso("[4/7] TikTok...")
            redes["tiktok"] = _tiktok_red(inicio, ahora)
        else:
            redes["tiktok"] = del_panel_anterior("tiktok")
            redes["tiktok"]["heredada"] = True

    # --- comentarios de YouTube ---
    # Van aparte de los de Instagram A PROPÓSITO. Mezclarlos daría un número más
    # lindo y una lectura falsa: en YouTube la gente escribe párrafos y hace
    # preguntas técnicas; en Instagram tira un emoji. Promediar las dos cosas
    # esconde justo lo que hay que ver.
    if redes.get("youtube", {}).get("conectada"):
        try:
            tok = yt_refrescar()
            canal_id = redes["youtube"].get("canal_id")
            if not (tok and canal_id):
                raise RuntimeError("falta el token o el id del canal")
            filas_yt = comentarios.actualizar_youtube(get, tok, canal_id)
            n_yt = len([c for c in filas_yt if c["red"] == "youtube"])
            print(f"  comentarios YT: {n_yt} bajados")
        except (RuntimeError, KeyError, OSError) as e:
            AVISOS.append(f"No pude bajar los comentarios de YouTube: {e}")

    # Cada red mide su propia conversación, con su propio corte de muestra.
    for red_k in ("instagram", "youtube"):
        if not redes.get(red_k, {}).get("conectada"):
            continue
        propias = comentarios.leer(red=red_k)
        if not propias:
            continue
        redes[red_k]["temas"] = leads.temas(propias, CFG.get("ctas", leads.CTAS))
        # Las dos lecturas que cambian decisiones, cada una sobre SU red: quién quedó
        # colgado esperando el CTA y quién escribió con intención de comprar.
        redes[red_k]["gap_cta"] = leads.gap(propias, CFG.get("ctas", leads.CTAS))
        redes[red_k]["leads"] = leads.calientes(propias, CFG.get("ctas", leads.CTAS))
        # Para el gráfico: una intención por comentario, así las barras suman 100%.
        redes[red_k]["reparto"] = leads.reparto(propias, CFG.get("ctas", leads.CTAS))
        # Y solo lo que pide una respuesta hoy. El resto se lee en la lista completa.
        redes[red_k]["accionables"] = leads.accionables(propias, CFG.get("ctas", leads.CTAS))
        # La conversación completa va al panel para poder leerla entera: hasta que
        # haya mucho volumen, leer los comentarios uno por uno sigue siendo la mejor
        # herramienta de análisis que existe.
        redes[red_k]["comentarios"] = [
            {k: c.get(k) for k in ("autor", "texto", "fecha", "likes", "media_id", "propio")}
            for c in sorted(propias, key=lambda x: x.get("fecha", ""), reverse=True)[:80]]

    # ---- COMPETENCIA ----
    # Lo que le funciona a otros. Va al final porque si falla no debe frenar nada:
    # es información para decidir, no el corazón del panel.
    comps = CFG.get("competencia") or {}
    if comps.get("instagram") or comps.get("youtube"):
        paso("[5/7] Competencia...")
        rivales = []
        for h in comps.get("instagram", []):
            c = competencia.instagram(get, GRAPH, cred["IG_PAGE_TOKEN"],
                                      cred["IG_USER_ID"], h)
            if c:
                rivales.append(competencia.analizar(c))
                print(f"  IG @{c['cuenta']}: {len(c['piezas'])} piezas")
            else:
                AVISOS.append(f"No pude leer @{h} en Instagram. "
                              "La API solo lee cuentas Business o Creator.")
        if comps.get("youtube"):
            tok_yt = yt_refrescar()
            for h in comps.get("youtube", []):
                c = competencia.youtube(get, tok_yt, h) if tok_yt else None
                if c:
                    an = competencia.analizar(c)
                    # Lo que su audiencia le pide: el mejor buscador de temas que hay.
                    # Solo YouTube lo entrega (Instagram no da el texto, ver competencia.py).
                    coms = competencia.comentarios_youtube(get, tok_yt, c["canal_id"])
                    if coms:
                        an["comentarios"] = coms[:80]
                        an["reparto_comentarios"] = leads.reparto(coms, [])
                        an["accionables"] = leads.accionables(coms, [], tope=8)
                    rivales.append(an)
                    print(f"  YT {c['cuenta']}: {len(c['piezas'])} piezas, "
                          f"{len(coms)} comentarios")
                else:
                    AVISOS.append(f"No pude leer @{h} en YouTube.")
        COMPETENCIA.extend(rivales)

    # ---- CALENDARIO ----
    paso("[6/7] Calendario (Postiz)...")
    agenda = calendario(inicio, ahora + datetime.timedelta(days=21))

    # Insights y mix por red: se calculan al final, sobre los datos ya armados.
    for r in redes.values():
        if r["conectada"]:
            r["insights"] = insights(r, DIAS)
            r["mix"] = mix_engagement(r)
            r["brief"] = brief(r)
            r["horarios"] = horarios(r)
        else:
            r["insights"], r["mix"], r["brief"] = [], [], None
            r["horarios"] = None

    # El analisis con IA se guarda aparte: no se regenera en cada refresco
    # del panel, solo cuando se pide expresamente (analista.py).
    try:
        import analista
        ia = analista.cargar()
    except Exception:
        ia = None

    # Las redes apagadas en config.json no llegan al panel. Se calculan igual (es más
    # barato que reescribir los bloques) pero no se muestran ni ensucian el análisis.
    for red in [r for r in redes if not config.red_activa(CFG, r)]:
        if red in POR_CONECTAR:
            print(f"  {red}: apagado, se muestra como pendiente de conectar.")
            redes[red] = _red_pendiente(red)
        else:
            print(f"  {red}: apagado en config.json, no se muestra.")
            del redes[red]

    # Y las que ni siquiera se calcularon en esta corrida. Pasa al actualizar una sola
    # red: las demás se heredan del panel anterior, y una red que nunca estuvo ahí no
    # se hereda de ningún lado. Sin esto, la invitación a conectar aparecía o no según
    # cómo se hubiera actualizado, que es peor que no tenerla.
    for red in POR_CONECTAR:
        if red not in redes:
            redes[red] = _red_pendiente(red)

    # ---- CAMPAÑAS DE META ADS (opcional) ----
    # Solo si hay META_ADS_TOKEN en el .env. Es una credencial DISTINTA de la del panel:
    # las cuentas publicitarias cuelgan del usuario, no de la Página. Sin la variable,
    # esta sección no existe y el panel no la muestra.
    ads = []
    # Las campañas cuestan ~12s y casi nunca son el motivo por el que actualizás.
    # Si pediste una red puntual, se heredan igual que las redes; sólo se vuelven
    # a bajar si las pediste explícitamente (`--red ads`) o si no hay nada previo.
    heredado_ads = del_panel_anterior_ads()
    if "ads" not in PEDIDAS and heredado_ads is not None:
        ads = heredado_ads
    elif cred.get("META_ADS_TOKEN"):
        paso("[7/7] Campañas de Meta Ads...")
        try:
            # campanas.py recibe el `get` como argumento para poder probarse sin red;
            # acá le damos uno que arma la query igual que el resto del recolector.
            def get_ads(url, **p):
                return get(f"{url}?{urllib.parse.urlencode(p)}") or {}
            ads = campanas.todo(get_ads, GRAPH, cred["META_ADS_TOKEN"], dias=DIAS)
        except (urllib.error.URLError, OSError, KeyError) as e:
            AVISOS.append(f"No pude leer las campañas de Meta Ads ({e}).")

    datos = {
        "ia": ia,
        "generado": datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
        "dias": DIAS,
        "redes": redes,
        "calendario": agenda,
        "marca": {**CFG.get("marca", {}), "producto": config.PRODUCTO,
                  "version": config.VERSION, "version_nueva": version_publicada()},
        "conexion": estado_meta(cred),
        "ads": ads,
        "avisos": sorted(set(AVISOS)),
        "competencia": COMPETENCIA,
        "config": {"competencia": CFG.get("competencia", {}),
                   "ctas": CFG.get("ctas", [])},
    }

    # Los ratios del algoritmo (compartidos/alcance, guardados/alcance, likes/alcance) y
    # la comparación de cada pieza contra tu propia mediana DE SU FORMATO. Un número mide
    # tamaño; un ratio mide calidad. Va acá, con las tres redes ya armadas, porque necesita
    # el conjunto de piezas para sacar las medianas.
    for red in redes.values():
        if red.get("posts"):
            red["senales"] = senales.enriquecer(red["posts"])

    # Foto de las métricas de hoy. Va ANTES de armar el HTML: si el panel falla por
    # cualquier motivo, el dato del día ya quedó guardado y no se pierde nunca más.
    # Y si falla el guardado, avisamos pero seguimos: el panel importa más.
    try:
        historico.guardar(datos)
    except OSError as e:
        AVISOS.append(f"No pude guardar el histórico ({e}). El panel se generó igual.")

    # dejamos cada pieza propuesta por la IA lista para renderizar
    fuentes = list((ia or {}).get("recomendaciones", []))
    if fuentes:
        carpeta = os.path.join(AQUI, "piezas-ia")
        os.makedirs(carpeta, exist_ok=True)
        for i, rec in enumerate(fuentes, 1):
            if not rec.get("slides"):
                continue
            pieza = {
                "formato": "carrusel" if rec.get("formato") in ("Carrusel", "Reel") else "ad",
                "titulo": re.sub(r"[^a-z0-9]+", "-",
                                 rec.get("titulo", f"pieza-{i}").lower()).strip("-")[:44],
                "acento": {"instagram": "#9333ea", "youtube": "#e0245e",
                           "facebook": "#0891b2"}.get(rec.get("red"), "#22d3ee"),
                "slides": rec["slides"],
            }
            with open(os.path.join(carpeta, f"{i}.json"), "w", encoding="utf-8") as f:
                json.dump(pieza, f, ensure_ascii=False, indent=1)

    paso("[escribiendo el panel]")
    plantilla = open(os.path.join(AQUI, "plantilla.html")).read()
    # Incrustamos el JSON en el HTML: un solo archivo, sin servidor, sin CORS.
    salida = plantilla.replace(
        "/*DATOS*/null",
        json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
    destino = PANEL_SALIDA
    with open(destino, "w") as f:
        f.write(salida)

    print(f"\nListo: {destino}")
    for k, r in redes.items():
        marca = "OK " if r["conectada"] else "-- "
        print(f"  [{marca}] {r['nombre']:10} {r['cuenta']:28} "
              f"{len(r['posts'])} piezas")
    print(f"  calendario: {len(agenda)} entradas")
    print(f"  histórico:  {len(historico.ultima_por_dia())} días guardados")
    conv = redes.get("instagram", {}).get("conversacion")
    if conv:
        print(f"  comentarios: {conv['reales']} reales de {conv['autores_unicos']} personas "
              f"(+{conv['propios']} respuestas tuyas)")
    ig = redes.get("instagram", {})
    for p in ig.get("gap_cta", {}).get("sin_respuesta_probable", []):
        print(f"  ATENCION: @{p['autor']} escribio el CTA {p['veces']} veces "
              f"-> revisa si le llego la guia")
    for l in ig.get("leads", [])[:3]:
        print(f"  LEAD [{l['puntos']}] @{l['autor']}: \"{l['cita'][:60]}\"")
    for a in ads:
        print(f"  campanas:   {a['nombre']} ({a['moneda']}) "
              f"{len(a['campanas'])} campanas, gasto historico {a['total']['gasto']:,.0f}")
    if datos["avisos"]:
        print("  Avisos:")
        for a in datos["avisos"]:
            print(f"    - {a[:130]}")


if __name__ == "__main__":
    main()
