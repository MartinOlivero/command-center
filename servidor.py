#!/usr/bin/env python3
"""
Servidor local del Panel de Métricas.

El panel solo es un archivo: no puede llamar a la IA cuando apretas un boton.
Este servidor le da esa mano y nada mas. Sirve el panel y expone dos rutas:

    POST /generar    {fuente, formato, objetivo, filo}  -> una pieza, en el momento
    POST /render     {archivo}                          -> los PNG de esa pieza
    POST /actualizar (sin cuerpo)                       -> corre el recolector y rehace el panel
    POST /auditar    (sin cuerpo)                       -> informe de las campañas (solo lectura)
    POST /conexiones (sin cuerpo)                       -> si las credenciales viven, AHORA
    POST /comentarios(sin cuerpo)                       -> comentarios nuevos de IG, sin bajar todo
    POST /analizar   (sin cuerpo)                       -> otra lectura de la IA, sin bajar todo

Se levanta con:

    python3 servidor.py
    PUERTO=8761 python3 servidor.py      # si ya tenés uno abierto

y abre el panel solo en http://127.0.0.1:8760

Nada sale de la maquina: la IA corre sobre el CLI de Claude ya instalado y las
piezas se guardan en `piezas-ia/`. El panel abierto con doble click sigue
funcionando para todo lo demas; solo el boton Generar necesita esto prendido.
"""
import errno
import glob
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import urllib.parse
import threading
import time
import webbrowser

import auditoria
import config
import generador
import entorno
import ia

AQUI = os.path.dirname(os.path.abspath(__file__))
# Se puede pisar con PUERTO=8761 python3 servidor.py, por si ya tenés uno abierto.
PUERTO = int(os.environ.get("PUERTO", 8760))
PIEZAS = os.path.join(AQUI, "piezas-ia")

FORMATOS_VISUALES = {"Carrusel", "Story", "Ad", "Reel", "Short"}


def datos_cuenta():
    """Los datos reales del panel, para que la pieza se apoye en algo."""
    ruta = os.path.join(AQUI, "panel.html")
    if not os.path.exists(ruta):
        return {}
    m = re.search(r"const DATOS = (\{.*?\});\n", open(ruta, encoding="utf-8").read(), re.S)
    if not m:
        return {}
    d = json.loads(m.group(1))
    fuera = {"dias": d.get("dias")}
    for k, r in (d.get("redes") or {}).items():
        if not r.get("conectada"):
            continue
        fuera[k] = {
            "seguidores": r["seguidores"],
            "kpis": {x["nombre"]: x["valor"] for x in r["kpis"]},
            "piezas": [{"tipo": p["tipo"], "texto": p["texto"], "alcance": p.get("alcance"),
                        "engagement": p.get("engagement"), "guardados": p.get("guardados")}
                       for p in r["posts"][:12]],
        }
    return fuera


TONOS = {
    1: "didáctico y calmo, explicando como a alguien que recién empieza",
    2: "directo pero amable",
    3: "directo, sin vueltas",
    4: "filoso: nombra el error de frente",
    5: "sin anestesia: incomoda al que lo escucha, sin insultar ni exagerar",
}


def generar(pedido):
    """Una sola pieza, escrita en el momento con los datos de la cuenta."""
    fuente = pedido.get("fuente", "instagram")
    formato = pedido.get("formato", "Reel")
    objetivo = pedido.get("objetivo", "DM")
    filo = int(pedido.get("filo", 3))
    extra = (pedido.get("tema") or "").strip()

    visual = formato in FORMATOS_VISUALES
    bloque_slides = """,
  "slides": [
    {"tipo": "portada", "sobre": "etiqueta corta", "titulo": "max 6 palabras", "texto": "max 15 palabras"},
    {"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "max 6 palabras", "texto": "max 15 palabras"},
    {"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "max 6 palabras", "texto": "max 15 palabras"},
    {"tipo": "cierre", "sobre": "Tu turno", "titulo": "max 6 palabras", "texto": "el CTA"}
  ]""" if visual else ""

    prompt = f"""Sos analista senior de redes y guionista de contenido.
Trabajas con {config.marca_para_prompt()}.

Datos REALES de sus cuentas:
{json.dumps(datos_cuenta(), ensure_ascii=False)}

Escribi UNA sola pieza con estas condiciones:
- Se apoya en lo que funciono en: {fuente}
- Formato: {formato}
- Objetivo: {objetivo}
- Tono: {TONOS.get(filo, TONOS[3])}
{f"- Tema pedido por el usuario: {extra}" if extra else ""}

Respondé UNICAMENTE con este JSON:

{{
  "titulo": "titulo interno corto",
  "gancho": "el primer renglon o la primera frase hablada, textual",
  "angulo": "en una frase, desde donde se cuenta",
  "porque": "en que dato concreto de la cuenta se apoya, citando el numero",
  "guion": [
    {{"paso": "Hook", "texto": "..."}},
    {{"paso": "Diagnóstico", "texto": "..."}},
    {{"paso": "Reframe", "texto": "..."}},
    {{"paso": "Prueba", "texto": "..."}},
    {{"paso": "CTA", "texto": "..."}}
  ],
  "cta": "que se le pide exactamente a la persona",
  "duracion": "cuanto deberia durar o cuantos slides lleva"{bloque_slides}
}}

Reglas:
- Español rioplatense con acentos correctos.
- El "porque" cita un numero real de los datos de arriba. Si no hay dato que la
  sostenga, elegi otro angulo que si lo tenga.
- Nicho pyme argentino: turnos perdidos, WhatsApp sin contestar, facturas a mano,
  stock descontrolado, empleados que se van. Nada de "descubri el secreto".
- Nada de texto fuera del JSON."""

    pieza = ia.preguntar_json(prompt, timeout=300)
    pieza.update({"fuente": fuente, "formato": formato, "objetivo": objetivo, "filo": filo})

    # se guarda para poder renderizarla despues sin volver a pedirsela a la IA
    os.makedirs(PIEZAS, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", pieza.get("titulo", "pieza").lower()).strip("-")[:44]
    archivo = f"{slug or 'pieza'}.json"
    guardable = {
        "formato": "story" if formato == "Story" else ("ad" if formato == "Ad" else "carrusel"),
        "titulo": slug or "pieza",
        "acento": {"instagram": "#9333ea", "youtube": "#e0245e",
                   "facebook": "#0891b2"}.get(fuente, "#22d3ee"),
        "slides": pieza.get("slides", []),
        "meta": {k: pieza.get(k) for k in ("gancho", "angulo", "porque", "cta", "guion")},
    }
    with open(os.path.join(PIEZAS, archivo), "w", encoding="utf-8") as f:
        json.dump(guardable, f, ensure_ascii=False, indent=1)
    pieza["archivo"] = archivo
    return pieza


# Una sola actualización a la vez. Sin esto, dos clicks seguidos lanzan dos recolectores
# que escriben panel.html al mismo tiempo y te dejan un archivo a medio hacer.
_actualizando = threading.Lock()
# Lo mismo para el análisis: dos clicks son dos corridas de IA pagadas escribiendo
# el mismo analisis.json, y la segunda pisa a la primera a mitad de camino.
_analizando = threading.Lock()


# "ads" no es una red social pero se pide igual que una: se baja aparte, con
# otra credencial, y es lo que más tarda después de Instagram y YouTube.
REDES_VALIDAS = ("instagram", "facebook", "youtube", "ads", "calendario")


def actualizar(red=None):
    """Vuelve a bajar los datos y reescribe panel.html.

    Es el mismo `recolector.py` de siempre, disparado desde el botón en vez de la
    terminal. Casi todo el tiempo es esperar a las APIs, no cálculo nuestro.

    Con `red`, baja SOLO esa y hereda las otras del panel anterior. Medido: las
    tres son ~53s y una sola ~20s de recolección. Sirve cuando venís a mirar una
    red concreta y no querés esperar a las otras dos.
    """
    orden = [sys.executable, os.path.join(AQUI, "recolector.py")]
    if red:
        # Validar acá y no confiar en el recolector: esto viene de un POST, y lo
        # que llega por la red no se mete en una línea de comandos sin revisar.
        if red not in REDES_VALIDAS:
            raise RuntimeError(f"no conozco la red '{red}'")
        orden += ["--red", red]
    if not _actualizando.acquire(blocking=False):
        raise RuntimeError("ya hay una actualización en curso")
    try:
        r = subprocess.run(orden, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        if r.returncode != 0:
            # El recolector avisa los problemas por stderr; mostramos el final, que es
            # donde está el error real y no el rastro de llamadas.
            raise RuntimeError(r.stderr.strip()[-300:] or "falló el recolector")
        # Le devolvemos al panel el resumen que el recolector imprime, así el botón
        # puede mostrar qué pasó en vez de un "listo" a ciegas.
        return {"salida": r.stdout.strip()[-800:]}
    finally:
        _actualizando.release()


def auditar():
    """Informe de las campañas: qué está mal, qué falta y qué está funcionando.

    Dos capas, y el orden importa:
      1. `auditoria.py` encuentra los hallazgos con REGLAS. Determinista, gratis, y cada
         uno viene con el número que lo respalda.
      2. La IA los ordena, los prioriza y escribe el plan. Trabaja sobre hallazgos ya
         verificados: no decide cuáles son, así no puede inventar un problema.

    NO escribe nada en Meta. Es un informe.
    """
    d = datos_panel_completo()
    cuentas = d.get("ads") or []
    if not cuentas:
        raise RuntimeError("no hay campañas para auditar (¿falta META_ADS_TOKEN en el .env?)")

    informe = auditoria.auditar(cuentas)
    # A la IA le pasamos los hallazgos Y los números, para que pueda priorizar con
    # criterio en vez de repetir la lista en otro orden.
    crudo = json.dumps({"informe": informe, "cuentas": [
        {"nombre": c["nombre"], "moneda": c["moneda"], "activa": c["activa"],
         "total": c["total"], "periodo": c.get("periodo"),
         "campanas": [{k: v for k, v in x.items() if k != "lectura"} for x in c["campanas"]],
         # A quién le funciona, no solo cuánto se gastó: es donde están los hallazgos
         # que un total esconde (un país que cuesta 6 veces más, un dispositivo que rinde
         # el doble, un público que rinde y se lleva el 4% del presupuesto).
         "segmentos": c.get("segmentos"),
         "hallazgos_segmentos": c.get("hallazgos_segmentos")}
        for c in cuentas]}, ensure_ascii=False)

    prompt = f"""Sos un especialista en Meta Ads que audita cuentas de clientes hace 15 años.
No vendes humo: mirás los numeros y decis lo que hay que hacer el lunes a la mañana.

Ya se corrieron chequeos automaticos sobre esta cuenta. Estos son los hallazgos
verificados y los numeros crudos:

{crudo}

Escribi el informe. Respondé UNICAMENTE con un JSON valido con esta forma:

{{
  "titular": "una frase que resuma el estado de la inversion publicitaria",
  "analogia": "explicá el problema principal con una analogia de la vida real",
  "prioridad": [
    {{"que": "la accion concreta", "por_que": "el dato que la sostiene, con el numero",
      "impacto": "que cambia si lo hacés", "esfuerzo": "bajo|medio|alto"}}
  ],
  "quien": [
    {{"segmento": "el publico, pais o dispositivo", "que_pasa": "el numero que lo define",
      "que_hacer": "subir presupuesto | sacarlo | probarlo aparte"}}
  ],
  "mal_configurado": ["cosas que estan mal puestas y hay que arreglar"],
  "falta": ["cosas que directamente no estan configuradas y deberian"],
  "funciona": ["lo que esta andando bien y hay que sostener o repetir"],
  "kpis": [
    {{"kpi": "nombre del indicador", "hoy": "el valor actual con su unidad",
      "mes_1": "meta realista a 30 dias", "mes_3": "meta a 90 dias",
      "como": "que hay que hacer para llegar"}}
  ]
}}

Reglas:
- Español rioplatense (vos, tenés, mirá), con acentos correctos.
- Maximo 4 items en "prioridad", ordenados por lo que mas mueve la aguja.
- Cada "por_que" cita un numero REAL de los datos de arriba. Sin numero, no va.
- El CTR y el CPM son metricas de vidriera: NO recomiendes nada basado solo en eso.
  Lo que manda es el costo por el resultado del OBJETIVO de cada campaña.
- NUNCA propongas pausar la campaña con el mejor costo por resultado, por feo que
  tenga el CTR. Es el error clasico y es caro.
- Si una cuenta esta inactiva, eso va primero: bloquea cualquier otro cambio.
- No inventes metricas que no esten en los datos.
- En "quien" van 3 a 6 items sacados de los SEGMENTOS: publico, pais y dispositivo.
  Es la parte mas accionable del informe: un promedio esconde que un segmento rinde
  cinco veces mejor que otro con la misma plata. Cita el numero de cada uno (costo por
  resultado, CTR, o que porcentaje del presupuesto se lleva).
- En "kpis" van 4 a 6 indicadores con metas REALISTAS, partiendo del valor de hoy.
  Nada de metas redondas inventadas: si el costo por conversacion hoy es 1.425, una meta
  de mes 1 es 1.000, no 100. Incluí siempre el costo por resultado y el CTR.
- Nada de texto fuera del JSON."""

    return {"ia": ia.preguntar_json(prompt, timeout=300), "chequeos": informe}


def datos_panel_completo():
    """El JSON entero incrustado en panel.html (no el recorte que usa `generar`)."""
    ruta = os.path.join(AQUI, "panel.html")
    if not os.path.exists(ruta):
        raise RuntimeError("todavía no hay panel.html: corré el recolector primero")
    m = re.search(r"const DATOS = (\{.*?\});\n", open(ruta, encoding="utf-8").read(), re.S)
    if not m:
        raise RuntimeError("no pude leer los datos del panel")
    return json.loads(m.group(1))


def sumar_competidor(pedido):
    """Agrega un competidor, lo baja al momento y devuelve su análisis.

    POR QUÉ ACÁ Y NO EN EL RECOLECTOR
    El recolector corre entero y tarda un minuto y medio. Sumar un competidor tiene
    que ser instantáneo: escribís el @, apretás, y en dos segundos ves si esa cuenta
    se puede leer o no. Además queda guardado en config.json, así que la próxima
    corrida del recolector ya lo trae solo.
    """
    import urllib.request
    import competencia, config

    red = (pedido.get("red") or "").strip()
    handle = (pedido.get("handle") or "").strip().lstrip("@")
    # Aceptar una URL pegada entera: nadie recorta el handle a mano.
    handle = re.sub(r"^https?://(www\.)?(instagram|youtube)\.com/(@)?", "", handle)
    handle = handle.split("/")[0].split("?")[0]
    if not handle or red not in ("instagram", "youtube"):
        return {"error": "Falta el usuario o la red."}

    def pedir(url):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            cuerpo = getattr(e, "read", lambda: b"")()
            try:
                return json.loads(cuerpo)
            except Exception:
                return {"error": {"message": str(e)}}

    cred = _credenciales()
    if red == "instagram":
        c = competencia.instagram(pedir, "https://graph.facebook.com/v26.0",
                                  cred["IG_PAGE_TOKEN"], cred["IG_USER_ID"], handle)
        if not c:
            return {"error": f"No pude leer @{handle}. La API de Instagram solo lee "
                             "cuentas Business o Creator, no personales."}
    else:
        tok = _token_youtube()
        if not tok:
            return {"error": "No hay token de YouTube. Corré: python3 yt_token.py auth"}
        c = competencia.youtube(pedir, tok, handle)
        if not c:
            return {"error": f"No encontré el canal @{handle} en YouTube."}

    analizado = competencia.analizar(c)

    # Los comentarios de SUS videos: solo YouTube los entrega (ver competencia.py).
    if red == "youtube" and pedido.get("comentarios"):
        import leads
        cid = c.get("canal_id") or ""
        if cid:
            coms = competencia.comentarios_youtube(pedir, tok, cid)
            analizado["comentarios"] = coms[:80]
            analizado["reparto_comentarios"] = leads.reparto(coms, [])
            analizado["accionables"] = leads.accionables(coms, [], tope=8)

    # Queda guardado para la próxima corrida del recolector.
    cfg = config.cargar()
    comps = cfg.setdefault("competencia", {})
    lista = comps.setdefault(red, [])
    if handle not in lista:
        lista.append(handle)
        config.guardar(cfg)
    # La lista vuelve con la respuesta: el panel es un archivo estático y su copia
    # de la config quedó vieja en cuanto se guardó la nueva. Sin esto, el chip del
    # competidor recién agregado no aparece hasta regenerar el panel entero.
    analizado["guardados"] = cfg["competencia"]
    return analizado


def quitar_competidor(pedido):
    """Saca un competidor de la lista guardada."""
    import config
    red, handle = pedido.get("red"), (pedido.get("handle") or "").lstrip("@")
    cfg = config.cargar()
    lista = (cfg.get("competencia") or {}).get(red) or []
    cfg.setdefault("competencia", {})[red] = [h for h in lista if h.lower() != handle.lower()]
    config.guardar(cfg)
    return {"ok": True, "quedan": cfg["competencia"][red]}


def _credenciales():
    datos = {}
    ruta = os.path.join(AQUI, ".env")
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.strip().split("=", 1)
                datos[k] = v.strip().strip('"').strip("'")
    return datos


def _token_youtube():
    """Refresca y devuelve el access_token de YouTube. None si no hay."""
    import urllib.parse
    _env = entorno.leer()
    ruta = os.path.expanduser(
        _env.get("YT_TOKEN_FILE") or os.path.join(AQUI, "youtube_token.json"))
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as f:
        tk = json.load(f)
    if not tk.get("refresh_token"):
        return tk.get("access_token")
    # Nunca del código: si estuvieran acá se publicarían con el repo. Y por la misma
    # puerta que `yt_token.py auth`, que acepta el .env o el JSON de Google Cloud:
    # dos lecturas distintas de lo mismo es como YouTube se caía a la hora.
    import yt_token
    cid, secreto = yt_token.credenciales(obligatorias=False)
    if not (cid and secreto):
        return tk.get("access_token")
    datos = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secreto,
        "refresh_token": tk["refresh_token"], "grant_type": "refresh_token"})
    # curl y no urllib: en esta Mac el handshake TLS contra Google falla con urllib.
    r = subprocess.run(["curl", "-s", "-X", "POST", "https://oauth2.googleapis.com/token",
                        "-d", datos], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=40)
    try:
        return json.loads(r.stdout).get("access_token") or tk.get("access_token")
    except json.JSONDecodeError:
        return tk.get("access_token")


def reanalizar():
    """Otra lectura de la IA sobre los datos que YA están, sin volver a bajar nada.

    Ojo con lo que ahorra y lo que no: medido, tarda entre 3 y 6 minutos, MÁS que el
    botón Actualizar. No es un atajo por tiempo. Lo que ahorra es cuota de las
    APIs de Meta y de YouTube, que son limitadas y no se recuperan; el tiempo del
    modelo, no. Sirve para pedir una segunda lectura de los mismos números o
    cuando el análisis quedó viejo respecto de los datos.

    Va por subproceso y no importando `analista`: sus errores son `sys.exit()`,
    que dentro del servidor matarían el hilo y dejarían al navegador esperando
    para siempre. Como proceso aparte, un fallo es un código de salida.
    """
    if not _analizando.acquire(blocking=False):
        raise RuntimeError("ya hay un análisis en curso")
    try:
        r = subprocess.run([sys.executable, os.path.join(AQUI, "analista.py")],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           # Derivado y no un número acá: si esta espera queda por
                           # debajo del techo del modelo, matamos al analista con el
                           # análisis ya pago y sin poder explicar por qué.
                           timeout=ia.TIMEOUT + ia.MARGEN)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:] or r.stdout.strip()[-300:]
                               or "falló el analista")
        with open(os.path.join(AQUI, "analisis.json"), encoding="utf-8") as f:
            return {"analisis": json.load(f)}
    finally:
        _analizando.release()


# La hora en que arrancó ESTE proceso. Con eso alcanza para saber si el panel se
# actualizó por abajo mientras corría.
ARRANQUE = time.time()

# panel.html queda afuera a propósito: lo reescribe cada recolección, así que siempre
# sería más nuevo y el aviso saldría siempre.
VIGILADOS = os.path.join(AQUI, "*.py"), os.path.join(AQUI, "plantilla.html")


def desfasado():
    """Los archivos del panel que son más nuevos que este proceso.

    Un programa no se reemplaza a sí mismo mientras corre: después de actualizar, en el
    disco está el código nuevo y acá adentro sigue el viejo, hasta que se cierra y se
    vuelve a abrir. También pasa si el panel arranca EN MEDIO de una actualización, que
    es peor porque queda con una mezcla: medido el 22/08/2026, un servidor levantado a
    las 02:38:51 con ia.py escrito a las 02:38:58 — siete segundos después.

    Sin esto, cada síntoma aparece por su lado y ninguno se parece al otro: una ruta que
    "no existe", una IA que "no está instalada" en una máquina que la tiene. Ninguno
    dice lo único que hay que hacer.
    """
    nuevos = []
    for patron in VIGILADOS:
        for f in glob.glob(patron):
            try:
                if os.path.getmtime(f) > ARRANQUE:
                    nuevos.append(os.path.basename(f))
            except OSError:                 # se lo llevaron mientras mirábamos
                pass
    return sorted(nuevos)


def actualizar_panel():
    """Trae la versión nueva del panel, sin que la persona vaya hasta la carpeta.

    Es el mismo `instalar.py --actualizar` del doble clic, disparado desde el cartel.
    Va por subproceso y no importando `instalar`: esa función termina en `sys.exit()`,
    que adentro del servidor mataría el hilo.

    Lo que NO puede hacer es dejar el panel corriendo con el código nuevo. Un programa
    no se reemplaza a sí mismo mientras corre: este proceso ya tiene sus módulos en
    memoria y sigue con los viejos hasta que se lo cierra y se lo vuelve a abrir. Por
    eso devuelve el aviso además del resultado — prometer menos es lo único honesto.

    Tampoco se actualiza con una recolección o un análisis a medio correr: esos
    procesos leen los .py del disco al arrancar, y cambiárselos abajo mientras trabajan
    es pedir un error que después no se puede reproducir.
    """
    if not _actualizando.acquire(blocking=False):
        raise RuntimeError("esperá a que termine de bajar los datos")
    if not _analizando.acquire(blocking=False):
        _actualizando.release()
        raise RuntimeError("esperá a que termine el análisis")
    try:
        r = subprocess.run([sys.executable, os.path.join(AQUI, "instalar.py"),
                            "--actualizar"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        if r.returncode != 0:
            # El instalador cuenta sus problemas por stdout (que el repo no contesta,
            # que no hay internet); stderr queda para lo que ni él vio venir.
            raise RuntimeError(r.stdout.strip()[-300:] or r.stderr.strip()[-300:]
                               or "no se pudo actualizar")
        return {"salida": r.stdout.strip()[-600:]}
    finally:
        _analizando.release()
        _actualizando.release()


def comentarios_nuevos():
    """Los comentarios nuevos de Instagram, sin rehacer toda la recolección.

    La diferencia de costo es todo el punto de este botón. El recolector, para
    llegar hasta acá, pide los insights de CADA post y encima descarga los reels
    para medirles la duración: un minuto y medio. Esto hace UNA llamada para
    saber qué posts tienen comentarios, y después baja solo los de esos.

    Devuelve lo accionable, que no es el total: quién escribió algo y todavía no
    tiene respuesta tuya.
    """
    import config
    import comentarios as com
    import recolector as rec

    cred = _credenciales()
    handle = config.cargar()["marca"]["cuenta"]
    antes = {c["id"] for c in com.leer()}

    url = (f"{rec.GRAPH}/{cred['IG_USER_ID']}/media"
           f"?fields=id,permalink,caption,comments_count&limit=50"
           f"&access_token={cred['IG_PAGE_TOKEN']}")
    medios = rec.get(url).get("data", [])
    if not medios:
        return {"nuevos": 0, "esperando": [],
                "detalle": "Instagram no devolvió publicaciones. ¿El token sigue vivo?"}

    # Cuántos tenemos guardados de cada post. Si la API dice que ese post tiene
    # los mismos que ya tengo, no hay nada nuevo ahí y me ahorro la llamada.
    # Es la diferencia entre 22 segundos y casi nada cuando no cambió nada, que
    # es justamente el caso de apretar el botón dos veces seguidas.
    guardados_por_post = {}
    for c in com.leer(red="instagram"):
        guardados_por_post[c["media_id"]] = guardados_por_post.get(c["media_id"], 0) + 1

    posts, de_donde, salteados = [], {}, 0
    for m in medios:
        cuantos = m.get("comments_count", 0)
        de_donde[m["id"]] = {
            "permalink": m.get("permalink", ""),
            "pieza": re.sub(r"\s+", " ", (m.get("caption") or "")).strip()[:60]}
        if cuantos and guardados_por_post.get(m["id"], 0) >= cuantos:
            salteados += 1
            continue
        posts.append({"media_id": m["id"], "comentarios": cuantos})

    filas = com.actualizar(rec.get, rec.GRAPH, cred["IG_PAGE_TOKEN"], posts, handle)
    ig = [c for c in filas if c.get("red", "instagram") == "instagram"]

    # Un comentario ajeno está respondido si cuelga de él una respuesta TUYA.
    respondidos = {c["responde_a"] for c in ig if c["propio"] and c["responde_a"]}
    esperando = [c for c in ig if not c["propio"] and c["id"] not in respondidos]
    esperando.sort(key=lambda c: c.get("fecha", ""), reverse=True)

    return {
        "nuevos": len([c for c in ig if c["id"] not in antes]),
        "ajenos": len([c for c in ig if not c["propio"]]),
        "sin_responder": len(esperando),
        "consultados": len(posts), "sin_cambios": salteados,
        # 25 alcanza para trabajar una tanda; más es una lista que nadie termina.
        "esperando": [{
            "autor": c["autor"], "texto": c["texto"], "fecha": (c.get("fecha") or "")[:10],
            "nuevo": c["id"] not in antes,
            **de_donde.get(c["media_id"], {"permalink": "", "pieza": ""}),
        } for c in esperando[:25]],
    }


def uso_de_cuota(token):
    """Cuánta cuota de la Graph API llevás gastada en la última hora.

    Meta lo devuelve en el header `X-App-Usage` de CUALQUIER llamada: son tres
    porcentajes (0-100) sobre una ventana móvil de una hora. Al llegar a 100 te
    corta. Se pide con una llamada mínima (`/me?fields=id`), que es la más barata
    que existe: lo que interesa es el header, no la respuesta.

    Devuelve None si no se pudo leer — el header no viene siempre, y preferimos
    no mostrar nada antes que mostrar un cero que parezca "no gastaste nada".
    """
    import urllib.error
    import urllib.request
    url = f"https://graph.facebook.com/v26.0/me?fields=id&access_token={token}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            cabeceras = r.headers
    except urllib.error.HTTPError as e:
        cabeceras = e.headers          # el límite también viaja en el error
    except Exception:
        return None

    # Meta manda uno u otro según con qué token preguntes, y NO tienen la misma
    # forma. Con un token de Página (el que usa el panel) llega el de business
    # use case: un diccionario por Página, con una entrada por tipo de uso.
    espera = 0
    crudo = cabeceras.get("X-Business-Use-Case-Usage")
    if crudo:
        try:
            entradas = [e for lista in json.loads(crudo).values() for e in lista]
        except (json.JSONDecodeError, AttributeError):
            return None
        if not entradas:
            return None
        espera = max(e.get("estimated_time_to_regain_access", 0) for e in entradas)
    else:
        crudo = cabeceras.get("X-App-Usage")
        if not crudo:
            return None
        try:
            entradas = [json.loads(crudo)]
        except json.JSONDecodeError:
            return None

    # De todos los porcentajes manda el más alto: es el que te va a frenar primero.
    peor = max(max(e.get("call_count", 0), e.get("total_cputime", 0),
                   e.get("total_time", 0)) for e in entradas)
    return {"usado_pct": peor, "espera_min": espera, "ventana": "1 hora móvil",
            "detalle": max(entradas, key=lambda e: max(e.get("call_count", 0),
                                                       e.get("total_cputime", 0),
                                                       e.get("total_time", 0)))}


def conexiones():
    """Estado de las credenciales AHORA, no cuando se recolectó.

    El panel ya mostraba un estado de conexión, pero era una foto del momento en
    que se bajaron los datos: si el token se caía después, seguía diciendo
    "vigente" hasta la próxima recolección. Esto lo pregunta en el momento.

    El diagnóstico de Meta es el de `instalar.py`, no una copia: si cambia el
    criterio de "esto está por vencerse", cambia en un solo lugar.
    """
    import instalar
    cred = _credenciales()
    fuera = {}

    tok = cred.get("IG_PAGE_TOKEN")
    if not tok:
        fuera["meta"] = {"estado": "sin_configurar",
                         "detalle": "no hay token en el .env. Corré `python3 instalar.py`"}
    else:
        est = instalar.estado_token(tok, cred.get("IG_APP_ID"), cred.get("IG_APP_SECRET"))
        if not est["valido"]:
            fuera["meta"] = {"estado": "caido", "detalle": est["motivo"]}
        else:
            dias = est["vence_en_dias"]
            faltan = [p for p in instalar.PERMISOS if p not in est["scopes"]]
            if faltan:
                fuera["meta"] = {"estado": "atencion", "dias": dias,
                                 "detalle": "faltan permisos: " + ", ".join(faltan)}
            elif dias is None:
                fuera["meta"] = {"estado": "ok", "dias": None,
                                 "detalle": "token permanente, no vence"}
            else:
                # Catorce días es el umbral para que avisar sirva de algo: da tiempo
                # a coordinar con el cliente antes de que el panel quede mudo.
                fuera["meta"] = {"estado": "atencion" if dias <= 14 else "ok", "dias": dias,
                                 "detalle": f"vence en {dias} días. Conviene volverlo "
                                            "permanente con `python3 instalar.py`"
                                            if dias <= 14 else f"vence en {dias} días"}

    # YouTube se renueva solo con su refresh_token: alcanza con ver si el canje sale.
    try:
        fuera["youtube"] = ({"estado": "ok", "detalle": "renovado con refresh_token"}
                            if _token_youtube()
                            else {"estado": "sin_configurar",
                                  "detalle": "YouTube no está autorizado. Se hace una vez "
                                             "con: python3 yt_token.py auth"})
    except Exception as e:
        fuera["youtube"] = {"estado": "caido", "detalle": str(e)[:200]}

    # ---- cuota ----
    # Meta la publica en un header; YouTube NO tiene forma de consultarla por API
    # (su doc manda a la consola de Google). Se dice cuál es cuál en vez de
    # inventar un número para que las dos filas se vean parejas.
    cuota = {}
    if tok:
        u = uso_de_cuota(tok)
        if u:
            p, d = u["usado_pct"], u["detalle"]
            cuota["meta"] = {
                "estado": "caido" if p >= 95 else "atencion" if p >= 75 else "ok",
                "detalle": f"{p}% usado, queda {100 - p}% "
                           f"(llamadas {d.get('call_count', 0)}%, CPU "
                           f"{d.get('total_cputime', 0)}%, tiempo {d.get('total_time', 0)}%). "
                           + (f"Bloqueado: vuelve en {u['espera_min']} min."
                              if u["espera_min"] else
                              f"Se repone solo, ventana de {u['ventana']}.")}
        else:
            cuota["meta"] = {"estado": "sin_configurar",
                             "detalle": "Meta no devolvió el header de uso esta vez"}
    cuota["youtube"] = {
        "estado": "info",
        "detalle": "10.000 unidades por día, pero la API no permite consultar cuánto "
                   "queda: sólo se ve en console.cloud.google.com. Una recolección "
                   "gasta muy poco (los comentarios cuestan 1 unidad por llamada)."}
    fuera["cuota"] = cuota

    return fuera


def render(archivo):
    """Convierte una pieza ya generada en PNG, con el generador de siempre."""
    ruta = os.path.join(PIEZAS, os.path.basename(archivo))
    if not os.path.exists(ruta):
        raise RuntimeError("no encuentro esa pieza")
    r = subprocess.run([sys.executable, os.path.join(AQUI, "generador.py"), "render", ruta],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300] or "falló el render")
    # Las imágenes se muestran EN el panel. No hace falta nada nuevo para servirlas:
    # este servidor ya publica la carpeta del panel, así que alcanza con decirle al
    # navegador por qué URL pedirlas. Antes se devolvía sólo la ruta en el disco, que
    # obligaba a copiarla a mano e ir a buscarla al Finder.
    carpeta = generador.carpeta_de(ruta)
    return {"salida": r.stdout.strip(), "carpeta": os.path.basename(carpeta),
            "imagenes": _urls_de(carpeta)}


def _urls_de(carpeta):
    """Las URLs con las que el navegador puede pedir los PNG de esa carpeta.

    Se arma con relpath y no escribiendo "piezas/" a mano: si el generador cambia
    dónde deja las imágenes, esto sigue apuntando bien. quote() por segmento porque
    el nombre sale del título de la pieza y trae espacios, acentos y ñ.
    """
    try:
        rel = os.path.relpath(carpeta, AQUI)
    except ValueError:      # en Windows, si quedara en otra unidad
        return []
    return [_url(rel, f) for f in sorted(os.listdir(carpeta))
            if f.lower().endswith(".png")]


def _url(rel, archivo, sep=os.sep):
    """La ruta en disco `rel/archivo`, como URL.

    `sep` se puede pasar para probar el caso de Windows desde cualquier máquina: allá
    el separador es "\\" y una URL con eso adentro no la sirve nadie. Es la única
    parte de esto que cambia según el sistema, así que es la que tiene test.
    """
    return "/" + "/".join(urllib.parse.quote(t) for t in rel.split(sep) + [archivo])


def abrir_carpeta(nombre):
    """Abre la carpeta de una pieza en el Finder / Explorador de archivos.

    Por qué lo hace el servidor y no un link: un `file://` clickeado desde una página
    servida por http:// está bloqueado en Chrome y Edge, no pasa nada y no hay forma
    de habilitarlo. Como este servidor corre en la misma máquina que el navegador,
    abrirla es cosa suya.
    """
    # Esto entra por un POST y termina en una llamada al sistema operativo, así que
    # no alcanza con recortar el nombre: `basename("../../..")` devuelve "..", que se
    # sale igual de la carpeta de piezas. Lo que decide es dónde quedó parada la ruta
    # una vez resuelta — tiene que estar ADENTRO de la carpeta de piezas y no ser la
    # carpeta misma.
    raiz = os.path.realpath(generador.SALIDA)
    carpeta = os.path.realpath(os.path.join(raiz, os.path.basename(nombre)))
    if os.path.dirname(carpeta) != raiz or not os.path.isdir(carpeta):
        raise RuntimeError("esa carpeta todavía no existe")
    if hasattr(os, "startfile"):
        # La forma de Windows. `explorer.exe` sirve igual pero devuelve código 1
        # aunque haya funcionado, y eso se vería en el panel como un error falso.
        os.startfile(carpeta)
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", carpeta],
                       check=True)
    return {"abierta": os.path.basename(carpeta)}


class Manejador(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=AQUI, **kw)

    def log_message(self, formato, *args):
        # solo interesan los POST; el resto es ruido de archivos estaticos.
        # args puede traer un HTTPStatus, asi que se compara sobre texto.
        if args and "POST" in str(args[0]):
            super().log_message(formato, *args)

    def end_headers(self):
        # El panel se REGENERA con cada actualización, pero el navegador se queda con la
        # copia vieja y te muestra datos de hace una hora sin avisar. Peor: después de
        # tocar el diseño, ves el diseño anterior y creés que no funcionó.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        marcar_actividad()
        # El latido de la pestaña abierta: dice "todavía hay alguien mirando" y, ya que
        # el viaje se hace igual una vez por minuto, trae de vuelta lo que el HTML no
        # puede saber por sí solo — qué versión está instalada y corriendo ahora.
        if self.path.split("?")[0] == "/latido":
            # Aprovecha el viaje que ya se hace igual: si el panel quedó viejo en
            # memoria, la pestaña se entera sola en el próximo minuto en vez de
            # descubrirlo cuando algo falla raro.
            # La versión va SIEMPRE, y es el dato vivo: la que quedó grabada en
            # panel.html es de cuando se generó, y después de actualizar sigue
            # anunciando una versión nueva que ya está instalada.
            return self.responder(200, {"v": config.VERSION,
                                        "desfasado": bool(desfasado())})

        # panel.html no viene en el paquete: lo escribe el recolector con los datos.
        # Si todavía no corrió, la biblioteca contesta un "404 File not found" que no
        # explica nada. analista.py y generador.py ya avisan bien en este caso; el
        # servidor era el único que dejaba a la persona mirando un error en inglés.
        if self.path.split("?")[0] in ("/", "/panel.html") and \
                not os.path.exists(os.path.join(AQUI, "panel.html")):
            return self.falta_panel()
        # Con el panel ya escrito, entrar a la raiz mostraba el LISTADO DE ARCHIVOS de
        # la carpeta -- el codigo .py y los .json con los datos, a la vista -- en vez
        # del panel, y parecia que estaba roto. Paso el 18/08/2026.
        if self.path.split("?")[0] in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/panel.html")
            self.end_headers()
            return
        return super().do_GET()

    def falta_panel(self):
        cuerpo = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>Todavía no hay datos</title>
<style>
 body{font:16px/1.6 system-ui,sans-serif;max-width:34rem;margin:12vh auto;padding:0 1.5rem;
      color:#e7e7ea;background:#15151a}
 code{background:#26262e;padding:.2em .45em;border-radius:.3em;font-size:.95em}
 pre{background:#26262e;padding:1rem;border-radius:.5em;overflow-x:auto}
 h1{font-size:1.4rem;margin-bottom:.2em} p{color:#b9b9c3}
</style>
<h1>Todavía no hay datos</h1>
<p>El panel se arma con tus números, así que hasta que no se bajen por primera vez
no hay nada que mostrar. Es cuestión de un minuto:</p>
<pre>python3 recolector.py</pre>
<p>Cuando termine, recargá esta página.</p>
<p>Si eso falla, el instalador te dice qué falta:</p>
<pre>python3 instalar.py --estado</pre>
</html>"""
        crudo = cuerpo.encode("utf-8")
        self.send_response(200)         # 200 y no 404: la página se muestra, no es un error del navegador
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def responder(self, codigo, cuerpo):
        crudo = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def do_POST(self):
        marcar_actividad()
        largo = int(self.headers.get("Content-Length", 0))
        try:
            pedido = json.loads(self.rfile.read(largo) or b"{}")
        except json.JSONDecodeError:
            return self.responder(400, {"error": "JSON inválido"})
        try:
            if self.path == "/generar":
                print(f"  generando {pedido.get('formato')} para {pedido.get('fuente')}...")
                return self.responder(200, generar(pedido))
            if self.path == "/render":
                return self.responder(200, render(pedido.get("archivo", "")))
            if self.path == "/actualizar-panel":
                print("  trayendo la versión nueva del panel...")
                return self.responder(200, actualizar_panel())
            if self.path == "/abrir":
                return self.responder(200, abrir_carpeta(pedido.get("carpeta", "")))
            if self.path == "/auditar":
                print("  auditando campañas...")
                return self.responder(200, auditar())
            if self.path == "/conexiones":
                print("  revisando credenciales...")
                return self.responder(200, conexiones())
            if self.path == "/comentarios":
                print("  trayendo comentarios nuevos...")
                return self.responder(200, comentarios_nuevos())
            if self.path == "/analizar":
                print("  releyendo los datos con la IA...")
                return self.responder(200, reanalizar())
            if self.path == "/competencia":
                print(f"  buscando @{pedido.get('handle')} en {pedido.get('red')}...")
                return self.responder(200, sumar_competidor(pedido))
            if self.path == "/competencia/quitar":
                return self.responder(200, quitar_competidor(pedido))
            if self.path == "/actualizar":
                red = pedido.get("red")
                print(f"  actualizando {red or 'las tres redes'}...")
                return self.responder(200, actualizar(red))
        except subprocess.TimeoutExpired:
            # Con la espera derivada de ia.TIMEOUT esto ya no debería pasar por una
            # corrida lenta: si pasa, el proceso quedó colgado de verdad.
            return self.responder(504, {"error": "la IA no contestó nunca. Probá de "
                                        "nuevo; si se repite, revisá que `claude` "
                                        "funcione a mano en una terminal"})
        except Exception as e:
            return self.responder(500, {"error": str(e)[:300]})
        self.responder(404, {"error": "ruta desconocida"})


# ── apagado automático ──────────────────────────────────────────────────────
# Corriendo en segundo plano no hay ventana que cerrar, así que el panel tiene que
# saber apagarse solo. La pestaña abierta manda un latido cada minuto; cuando dejan de
# llegar es que ya nadie está mirando. Sin esto, cada doble clic dejaría un proceso
# vivo para siempre y a la semana habría diez.
ULTIMA_SEÑAL = time.time()
# 5 minutos sin latidos ni pedidos. Se puede bajar por entorno para probarlo sin
# esperar: SIN_NADIE=3 python3 servidor.py
SIN_NADIE = int(os.environ.get("SIN_NADIE", 300))


def marcar_actividad():
    global ULTIMA_SEÑAL
    ULTIMA_SEÑAL = time.time()


# Cuando el panel ya se actualizó, este proceso es código viejo que ocupa el puerto: no
# se puede reemplazar a sí mismo, y mientras siga vivo el ícono del Escritorio se le
# engancha —"si ya hay un servidor, no levanto otro"— y devuelve la versión anterior una
# y otra vez. Pasó de verdad el 22/08/2026: seis horas de cerrar la pestaña y reabrir
# siempre contra el mismo proceso de las 02:38, con el disco ya en 1.1.4.
#
# Cerrada la pestaña, entonces, hay que irse rápido y dejarle el lugar al nuevo. Pero no
# antes de 90s: la pestaña abierta late una vez por minuto, y un umbral más corto lo
# apagaría en la cara de alguien que lo está mirando.
SIN_NADIE_VIEJO = 90


def limite_apagado():
    """Cuánto silencio se tolera antes de apagarse. Menos, si este proceso quedó viejo."""
    return min(SIN_NADIE, SIN_NADIE_VIEJO) if desfasado() else SIN_NADIE


def vigilar(srv):
    """Apaga el servidor cuando nadie lo usa. Corre en su propio hilo."""
    while True:
        time.sleep(min(30, max(1, SIN_NADIE // 3)))
        if time.time() - ULTIMA_SEÑAL > limite_apagado():
            threading.Thread(target=srv.shutdown, daemon=True).start()
            return


class Servidor(socketserver.ThreadingTCPServer):
    """Un hilo por pedido.

    Con el servidor de un solo hilo (TCPServer), mientras el recolector tarda su minuto
    y medio el panel quedaba TILDADO: ni el reloj andaba, porque el navegador no podía
    pedir ni una imagen. Lo mismo pasaba con el botón Generar, que puede tardar 300s.
    Es la diferencia entre un mostrador con un empleado y uno con varios.
    """
    allow_reuse_address = True
    daemon_threads = True  # que Ctrl+C corte de una, sin esperar pedidos colgados


def abrir_puerto(desde, intentos):
    """El primer puerto libre a partir de `desde`. Devuelve (servidor, puerto).

    Cualquier cosa escuchando en 8760 —otro panel que quedó abierto, un servidor de
    desarrollo olvidado— frenaba el arranque con una instrucción para escribir en la
    terminal. Quien hace doble clic en "Abrir panel" no tiene por qué resolver eso:
    probamos el siguiente y le avisamos dónde quedó.
    """
    for puerto in range(desde, desde + intentos):
        try:
            return Servidor(("127.0.0.1", puerto), Manejador), puerto
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
    return None, None


def panel_ya_abierto():
    """El puerto donde ya hay un panel de estos escuchando, o None.

    Evita que el segundo doble clic levante un servidor más. Se pregunta por /latido
    y no por el panel: cualquier cosa puede estar sirviendo un HTML en ese puerto,
    pero /latido lo contesta este servidor y nadie más.
    """
    import urllib.request
    for puerto in range(PUERTO, PUERTO + 20):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto}/latido", timeout=1) as r:
                if r.status == 204:
                    return puerto
        except Exception:                  # noqa: BLE001 — cerrado o ajeno: sigo
            continue
    return None


def al_fondo():
    """Se desprende de quien lo lanzó y sigue vivo por su cuenta.

    En macOS `nohup ... &` no alcanza: cuando la app que hizo el doble clic termina,
    LaunchServices se lleva puestos los procesos que quedaron colgando de ella, y el
    panel moría antes de atender el primer pedido. El doble fork con `setsid` en el
    medio es la receta de siempre: el primer fork devuelve el control enseguida,
    `setsid` abre una sesión nueva sin terminal de la que depender, y el segundo evita
    volver a agarrar una.

    En Windows no hay fork ni setsid, y tampoco hacen falta: el acceso directo llama a
    `pythonw.exe`, que es el mismo Python pero sin consola. Ahí lo único que hay que
    resolver es que la salida no se pierda en el aire.
    """
    if os.name != "nt":
        if os.fork() > 0:
            os._exit(0)
        os.setsid()
        if os.fork() > 0:
            os._exit(0)

    # Sin consola, lo que se imprima se pierde: si algo falla, el log es la única
    # pista que le queda a la persona. Se escribe por descriptor y además se cambian
    # sys.stdout/sys.stderr, porque bajo pythonw.exe pueden venir en None.
    log = open(os.path.join(AQUI, "panel.log"), "a", buffering=1, encoding="utf-8")
    for fd in (1, 2):
        try:
            os.dup2(log.fileno(), fd)
        except OSError:
            pass
    sys.stdout = sys.stderr = log


def main():
    if "--fondo" in sys.argv:
        # Dos doble clics seguidos no pueden dejar dos servidores. Se chequea acá y no
        # en el lanzador para que valga igual en las dos plataformas: en Windows el
        # acceso directo llama a pythonw.exe directo, sin script en el medio donde
        # poner esta lógica.
        ya = panel_ya_abierto()
        if ya:
            webbrowser.open(f"http://127.0.0.1:{ya}/panel.html")
            return
        al_fondo()
    # Si la persona eligió el puerto a mano, se respeta y no se busca otro: pidió ESE.
    elegido_a_mano = bool(os.environ.get("PUERTO"))
    srv, puerto = abrir_puerto(PUERTO, 1 if elegido_a_mano else 20)
    if not srv:
        sys.exit(f"El puerto {PUERTO} está ocupado.\n"
                 + ("Cerrá el otro servidor, o probá con otro:\n"
                    f"    PUERTO={PUERTO + 1} python3 servidor.py"
                    if elegido_a_mano else
                    f"Probé hasta el {PUERTO + 19} y estaban todos ocupados, que es raro.\n"
                    "Reiniciar la computadora los libera."))
    if puerto != PUERTO:
        print(f"El puerto {PUERTO} estaba ocupado, así que abrí el panel en el {puerto}.")
    with srv:
        url = f"http://127.0.0.1:{puerto}/panel.html"
        print(f"Command Center en {url}")
        print("Los botones Actualizar y Generar del panel ya funcionan. Ctrl+C para cortar.\n")
        if not os.environ.get("SIN_NAVEGADOR"):
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        # En segundo plano no hay ventana para cortar con Ctrl+C, así que el servidor
        # tiene que saber irse solo cuando ya nadie tiene el panel abierto.
        threading.Thread(target=vigilar, args=(srv,), daemon=True).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nlisto.")


if __name__ == "__main__":
    main()
