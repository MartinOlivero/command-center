#!/usr/bin/env python3
"""
instalar.py — Deja el Panel de Métricas andando en una máquina nueva.

PARA QUÉ
Instalar esto en un cliente son cuatro cosas: tener las dependencias, crear una app de
Meta, conseguir un token, y decirle al panel de quién es. Las tres primeras son donde se
traba todo el mundo; la cuarta es un archivo de texto.

Este asistente hace las preguntas, VERIFICA el token contra la API antes de guardarlo, y
corre la primera recolección. El paso de verificar es el que evita el 90% del soporte
posterior: un token mal generado se ve acá, no tres días después cuando el panel aparece
vacío y nadie sabe por qué.

    python3 instalar.py

No pisa nada sin preguntar. Se puede correr de nuevo para cambiar la configuración.
"""

import glob
import io
import json
import locale
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import config
import ia

AQUI = os.path.dirname(os.path.abspath(__file__))
# El .env vive DENTRO de esta carpeta, al lado de los scripts. Antes vivía un nivel
# más arriba (compartido con otros proyectos), pero eso rompe cuando la carpeta se
# distribuye sola: el instalador escribiría las credenciales fuera del directorio
# que la persona descargó, en cualquier lugar de su disco.
RAIZ = AQUI
ENV = os.path.join(RAIZ, ".env")
GRAPH = "https://graph.facebook.com/v26.0"

# Sin estos permisos el panel queda mudo en alguna parte. `instagram_manage_comments` es
# el que más se olvida: desde 2024 hace falta hasta para leer el @ de quien comenta.
PERMISOS = ["instagram_basic", "instagram_manage_insights", "instagram_manage_comments",
            "pages_read_engagement", "pages_show_list"]

# Este error tiene un rescate propio (ver `rescate_por_id`), así que se compara por
# identidad en vez de leerse a ojo: si el texto cambia, el rescate deja de ofrecerse.
SIN_PAGINA = ("el token no ve ninguna Página, aunque la administres")

ARREGLO_DE_RAIZ = """
  Para arreglarlo de raíz: entrá a facebook.com/settings?tab=business_tools, suprimí
  la app de la lista y volvé a generar el token. Mientras la autorización siga viva,
  Meta no vuelve a preguntarte qué Página querés darle, y el token nace ciego."""


# ── utilidades de consola ───────────────────────────────────────────────────
def titulo(t):
    print(f"\n\033[1m{t}\033[0m\n" + "─" * len(t))


def preguntar(texto, defecto=""):
    sufijo = f" [{defecto}]" if defecto else ""
    r = input(f"  {texto}{sufijo}: ").strip()
    return r or defecto


def si_no(texto, defecto=True):
    d = "S/n" if defecto else "s/N"
    r = input(f"  {texto} [{d}]: ").strip().lower()
    return defecto if not r else r.startswith("s")


# ── 1. dependencias ─────────────────────────────────────────────────────────
def revisar_dependencias():
    """Avisa qué falta y cómo instalarlo. NO instala nada solo: en la máquina de otro,
    un script que instala cosas por su cuenta es una forma rápida de romper algo.

    Devuelve qué encontró, para que los pasos siguientes no vuelvan a preguntárselo
    al disco (el paso de IA necesita saber si existe `claude`).
    """
    titulo("1. Dependencias")
    hallado = {}
    faltan = []
    # Solo python3 es imprescindible: el panel entero usa la biblioteca estándar,
    # sin un solo paquete de terceros. Lo demás enciende funciones sueltas.
    for cmd, para_que, como in [
        ("python3", "el panel entero", "viene con macOS; en Windows: python.org"),
        ("claude", "el análisis con IA (usa tu suscripción de Claude)",
         "npm i -g @anthropic-ai/claude-code"),
        ("ffmpeg", "solo si vas a generar piezas en video", "brew install ffmpeg"),
    ]:
        # Para `claude` se usa la misma búsqueda que el panel, no `which` a secas: si
        # acá dijera "ok" mirando el PATH del shell y el panel después no lo encontrara
        # con su PATH de app, la persona tendría dos respuestas opuestas sobre lo mismo.
        hay = bool(ia.buscar_cli()) if cmd == "claude" else bool(shutil.which(cmd))
        hallado[cmd] = hay
        print(f"  [{'ok' if hay else '--'}] {cmd:9} {para_que}")
        if not hay:
            faltan.append((cmd, como))
    for cmd, como in faltan:
        print(f"\n  Falta {cmd}. Se instala con:\n      {como}")
    if not hallado["python3"]:
        sys.exit("\n  Sin python3 no se puede seguir.")
    if faltan:
        print("\n  Nada de esto bloquea el panel: solo apaga esa función.")

    # Que exista python3 no alcanza: el Python que se baja de python.org viene SIN los
    # certificados raíz, y entonces no puede verificar con quién está hablando. Todo el
    # panel se cae en la primera llamada a Meta con un error de OpenSSL que no le dice
    # nada a nadie. Se detecta acá, en un paso, y no tres pantallas más adelante.
    try:
        urllib.request.urlopen(GRAPH + "/", timeout=20)
    except urllib.error.HTTPError:
        pass                            # contestó: el canal seguro funciona, que es lo que se prueba
    except Exception as e:
        print("  [--] conexión segura con Meta")
        if aviso_certificados(e):
            sys.exit(1)
        print(f"\n  No pude llegar a graph.facebook.com: {e}\n"
              "  Revisá tu conexión y volvé a correr el instalador.")
        sys.exit(1)
    print("  [ok] conexión segura con Meta")
    return hallado


def aviso_certificados(error):
    """Si el error es de certificados, explica cómo arreglarlo. Devuelve si lo era.

    Es EL tropiezo de macOS con el Python de python.org, y el mensaje que tira OpenSSL
    ("unable to get local issuer certificate") no le sugiere a nadie que la solución es
    hacer doble clic en un archivo que ya tiene instalado. Buscamos ese archivo y lo
    nombramos con su ruta real.
    """
    if "CERTIFICATE_VERIFY_FAILED" not in str(error):
        return False
    print("""
  Tu Python no tiene instalados los certificados raíz, así que no puede verificar
  con quién está hablando y corta toda conexión segura. No es tu token ni tu
  conexión: es el Python que bajaste de python.org, que los trae aparte.

  Es como tener el teléfono andando pero sin la agenda para saber si quien atiende
  del otro lado es de verdad tu banco. El teléfono funciona; falta la agenda.""")
    guiones = sorted(glob.glob("/Applications/Python 3.*/Install Certificates.command"))
    if guiones:
        print(f"""
  Se arregla en diez segundos, con el archivo que ya tenés:

      abrí el Finder en   {os.path.dirname(guiones[-1])}
      doble clic en       Install Certificates.command

  O pegá esto en la Terminal:

      "{guiones[-1]}"
""")
    else:
        print("""
  En macOS: buscá la carpeta de tu versión de Python en /Applications y hacé doble
  clic en "Install Certificates.command".
  En Windows: reinstalá Python desde python.org dejando marcadas las opciones por
  defecto.
""")
    print("  Después volvé a correr el instalador.")
    return True


# ── 2. la app de Meta ───────────────────────────────────────────────────────
def guia_meta():
    titulo("2. La app de Meta")
    print("""  Esto se hace UNA vez y no se vuelve a tocar. Va con el cliente adelante,
  porque la app tiene que quedar a nombre de él.

  Por qué no hace falta la revisión de Meta: la App Review se exige cuando una app
  toca datos de TERCEROS. Si la app es del cliente y el cliente es admin de su propia
  app, no hace falta. Es como cocinar en tu casa: no necesitás habilitación municipal,
  la necesitás para venderle comida a desconocidos.

  Pasos:
    1. Entrar a developers.facebook.com CON LA CUENTA DEL CLIENTE
    2. Crear una app tipo "Business"
    3. Agregarle el producto "Instagram Graph API"
    4. Su Instagram tiene que ser cuenta PROFESIONAL vinculada a una Página de Facebook
    5. En el Explorador de la API (developers.facebook.com/tools/explorer):
       - elegir la app
       - en "Usuario o página" elegir **Token de acceso de usuario** (NO la página)
       - agregar estos permisos:""")
    for p in PERMISOS:
        print(f"           {p}")
    print("""       - Generar token y copiarlo

  Ojo con el punto del usuario: tiene que ser token de USUARIO, aunque el panel
  después use uno de Página. El de usuario es el único que se puede canjear por
  uno de larga duración, y recién de ese se deriva el de Página, que ya no vence.
  Si pegás directamente el de Página, arrancás con dos horas y no hay canje posible.

  El token que copiás ahora dura un par de horas: es normal. El instalador lo
  cambia por el permanente en el paso siguiente.

  El App ID no me lo tenés que buscar: viaja adentro del token y lo leo solo. El
  App Secret (Configuración > Información básica de la app) te lo voy a pedir sólo
  si el token que pegues vence; si ya es uno permanente, no hace falta.""")
    input("\n  Enter cuando tengas el token a mano... ")


# ── 3. verificar el token ───────────────────────────────────────────────────
def get(ruta, **params):
    url = f"{GRAPH}/{ruta}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {"_error": json.loads(e.read())["error"]["message"]}
        except Exception:
            return {"_error": f"HTTP {e.code}"}
    except Exception as e:
        return {"_error": str(e)}


def app_token(app_id, app_secret):
    """El "carnet" de la app. Meta recomienda usarlo para inspeccionar tokens ajenos."""
    return f"{app_id}|{app_secret}"


def estado_token(token, app_id=None, app_secret=None):
    """Qué es este token y cuándo se muere.

    `vence_en_dias = None` significa QUE NO VENCE, que es adonde queremos llegar.
    Meta lo marca con `expires_at: 0`.
    """
    verificador = app_token(app_id, app_secret) if (app_id and app_secret) else token
    d = get("debug_token", input_token=token, access_token=verificador).get("data", {})
    if not d or not d.get("is_valid"):
        motivo = (d.get("error") or {}).get("message") or "el token no es válido o ya venció"
        return {"valido": False, "motivo": motivo}
    exp = d.get("expires_at") or 0
    return {"valido": True, "tipo": d.get("type"), "scopes": d.get("scopes", []),
            "vence_en_dias": None if not exp else max(0, round((exp - time.time()) / 86400))}


def intercambiar_por_largo(token, app_id, app_secret):
    """Token corto de USUARIO -> token largo de usuario (~60 días).

    Es el primer eslabón: por sí solo no resuelve nada duradero, pero es el único
    que habilita el segundo, que sí.
    """
    r = get("oauth/access_token", grant_type="fb_exchange_token",
            client_id=app_id, client_secret=app_secret, fb_exchange_token=token)
    if r.get("_error"):
        return None, r["_error"]
    if not r.get("access_token"):
        return None, "Meta no devolvió ningún token en el intercambio"
    return r["access_token"], None


def token_permanente_de_pagina(user_token_largo):
    """Segundo eslabón, y el que realmente importa.

    Los tokens de Página derivados de un user token de LARGA duración NO tienen
    fecha de vencimiento (doc oficial de Meta: "Long-lived Page access token do
    not have an expiration date"). Derivados de uno corto, heredan las 2 horas.
    Misma llamada, resultado completamente distinto según con qué token la hagas.
    """
    r = get("me/accounts", fields="name,access_token,instagram_business_account{id,username}",
            access_token=user_token_largo)
    if r.get("_error"):
        return None, r["_error"]
    for p in r.get("data", []):
        ig = p.get("instagram_business_account")
        if ig and p.get("access_token"):
            return {"token": p["access_token"], "pagina": p.get("name", "?"),
                    "ig_id": ig["id"], "cuenta": "@" + ig.get("username", "?")}, None
    if r.get("data"):
        return None, ("ninguna de las Páginas tiene una cuenta de Instagram profesional "
                      "vinculada (se vincula en la Página, en 'Cuentas conectadas')")
    return None, "este usuario no administra ninguna Página"


def volver_permanente(token_corto, app_id, app_secret):
    """Encadena los dos pasos y CONFIRMA contra la API que quedó sin vencimiento.

    Confirmar es el punto: sin este chequeo uno se entera de que la cadena falló
    dos horas después, con el cliente mirando un panel vacío.
    """
    largo, err = intercambiar_por_largo(token_corto, app_id, app_secret)
    if err:
        return None, f"no se pudo canjear por uno de larga duración: {err}"
    pag, err = token_permanente_de_pagina(largo)
    if err:
        return None, err
    est = estado_token(pag["token"], app_id, app_secret)
    if not est["valido"]:
        return None, f"el token derivado no valida: {est['motivo']}"
    if est["vence_en_dias"] is not None:
        return None, (f"quedó con vencimiento a {est['vence_en_dias']} días en vez de "
                      "permanente. Suele pasar si el token que pegaste era de Página "
                      "y no de Usuario")
    return pag, None


def verificar_token(token):
    """Confirma contra la API que el token sirve, y de paso descubre el IG_USER_ID.

    Devuelve (ig_user_id, nombre_de_cuenta) o (None, motivo). Preguntarle el ID a la
    persona sería pedirle un dato que no tiene por qué saber, y que se puede averiguar.
    """
    # Si la API contestó un error, ese mensaje ES el diagnóstico: decir siempre "no es
    # válido" cuando en realidad hubo un límite de uso, la app quedó en modo desarrollo
    # o se cayó la red manda a la persona a regenerar un token que estaba perfecto.
    r = get("debug_token", input_token=token, access_token=token)
    if r.get("_error"):
        return None, f"la API de Meta contestó: {r['_error']}"
    d = r.get("data", {})
    if not d:
        return None, "el token no es válido o ya venció"
    faltantes = [p for p in PERMISOS if p not in d.get("scopes", [])]
    if faltantes:
        return None, "le faltan permisos: " + ", ".join(faltantes)

    # La cuenta de Instagram cuelga de la PÁGINA de Facebook, pero hay dos formas de
    # llegar según qué eligió la persona en el Explorador, y las dos son válidas:
    #   - token de PÁGINA  -> `me` YA ES la página, se le pide el instagram directo
    #   - token de USUARIO -> hay que listar sus páginas primero
    # Aceptamos las dos en vez de exigir una: nadie se acuerda cuál eligió.
    if d.get("type") == "PAGE":
        pag = get("me", fields="name,instagram_business_account{id,username}",
                  access_token=token)
        if pag.get("_error"):
            return None, f"la API de Meta contestó: {pag['_error']}"
        candidatas = [pag] if pag.get("id") or pag.get("name") else []
    else:
        cuentas = get("me/accounts",
                      fields="name,instagram_business_account{id,username}",
                      access_token=token)
        if cuentas.get("_error"):
            return None, f"la API de Meta contestó: {cuentas['_error']}"
        candidatas = cuentas.get("data", [])

    for p in candidatas:
        ig = p.get("instagram_business_account")
        if ig:
            return ig["id"], "@" + ig.get("username", "?")
    if candidatas:
        return None, (f"la Página '{candidatas[0].get('name', '?')}' no tiene una cuenta de "
                      "Instagram profesional vinculada. Se vincula desde la configuración "
                      "de la Página, en Cuentas conectadas")
    return None, SIN_PAGINA


def pagina_por_id(token, referencia):
    """Busca la Página por su ID, sin pasar por `me/accounts`.

    `me/accounts` a veces devuelve una lista VACÍA aunque la persona sí administre la
    Página. Pasa cuando Meta emitió el token sin activos adentro: se ve en `debug_token`,
    donde los `granular_scopes` vienen sin `target_ids`. Preguntando por la Página
    directa, en cambio, devuelve su token igual. Sin esta puerta de atrás, la
    instalación termina acá y no hay nada en pantalla que explique por qué.

    El token tiene que ser de USUARIO y de larga duración: el token de Página hereda el
    vencimiento del que lo pidió, así que uno derivado del corto dura dos horas.
    """
    pid = referencia.strip().rstrip("/").split("/")[-1].split("?")[0]
    if not pid.isdigit():
        return None, f"'{pid}' no parece un ID de Página: son solo números"

    d = get(pid, fields="name,access_token,instagram_business_account{id,username}",
            access_token=token)
    if d.get("_error"):
        return None, d["_error"]
    if not d.get("access_token"):
        return None, ("esa Página no devolvió token: la cuenta con la que autorizaste "
                      "no la administra")
    ig = d.get("instagram_business_account")
    if not ig:
        return None, (f"la Página '{d.get('name', '?')}' existe, pero no tiene una cuenta "
                      "de Instagram profesional vinculada")
    return {"token": d["access_token"], "pagina": d.get("name", "?"),
            "ig_id": ig["id"], "cuenta": "@" + ig.get("username", "?")}, None


def rescate_por_id(token, app_id):
    """Segunda oportunidad cuando Meta dice que no administrás ninguna Página.

    Devuelve (datos_de_la_pagina, app_secret). El App Secret se pide acá y no después
    porque el orden importa: hay que canjear el token de usuario por el de 60 días
    ANTES de pedir la Página, o el token que sale dura dos horas y el panel se apaga
    a media tarde.
    """
    print("""
  Esto pasa incluso administrando la Página: Meta a veces emite el token sin ningún
  activo adentro y no lo avisa. Se puede esquivar entrando por el ID de la Página.

  Para eso necesito el App Secret: developers.facebook.com > tu app > Configuración >
  Información básica.""")
    app_secret = preguntar("  App Secret (Enter para saltear)").strip()
    if not app_secret:
        print(ARREGLO_DE_RAIZ)
        return None, ""

    largo, err = intercambiar_por_largo(token, app_id, app_secret)
    if err:
        print(f"  No pude canjear el token: {err}")
        return None, app_secret

    print("""
  Ahora el ID de la Página. Está en Meta Business Suite > Configuración > Páginas.
  También sirve pegar la URL de la Página.""")
    while True:
        ref = preguntar("  ID o URL de la Página (Enter para saltear)").strip()
        if not ref:
            print(ARREGLO_DE_RAIZ)
            return None, app_secret
        pag, err = pagina_por_id(largo, ref)
        if pag:
            return pag, app_secret
        print(f"  No salió: {err}")


def app_id_del_token(token):
    """El App ID que emitió el token, preguntándoselo a Meta.

    Pedírselo a la persona es mandarla a developers.facebook.com a copiar un número
    que el token ya lleva encima. Devuelve None si no se pudo averiguar, y ahí sí se
    pregunta.
    """
    return get("app", access_token=token).get("id")


def completar_page_id(cred):
    """Agrega el ID de la Página de Facebook, que el panel necesita para sus métricas.

    Se averigua con el mismo token que ya validamos, así que preguntarlo sería pedir un
    dato que está a una llamada de distancia. Antes no se guardaba y la recolección se
    caía con KeyError recién en el paso 6, cuando todo parecía haber salido bien.
    """
    token = cred.get("IG_PAGE_TOKEN")
    if not token or cred.get("FB_PAGE_ID"):
        return cred

    if estado_token(token).get("tipo") == "PAGE":
        cred["FB_PAGE_ID"] = get("me", fields="id", access_token=token).get("id", "")
    else:
        for p in get("me/accounts", fields="id,instagram_business_account",
                     access_token=token).get("data", []):
            if p.get("instagram_business_account"):
                cred["FB_PAGE_ID"] = p.get("id", "")
                break

    print(f"  Página de Facebook: {cred['FB_PAGE_ID']} (también salió del token)"
          if cred.get("FB_PAGE_ID") else
          "  No pude averiguar el ID de la Página: Facebook va a quedar sin datos.")
    return cred


def pedir_credenciales():
    titulo("3. Conectar la cuenta")
    print("""  Pegá el token que copiaste del Explorador. El App ID lo saco de ahí adentro,
  y el App Secret te lo pido sólo si el token vence.""")

    rescatado = ""   # App Secret, si hubo que usar el rescate por ID de Página
    while True:
        token = preguntar("\n  Pegá el token").strip()
        if not token:
            if si_no("¿Salteo esto y lo configuro después?", False):
                return None
            continue

        print("  Verificando contra la API de Meta...")
        ig_id, detalle = verificar_token(token)
        if not ig_id:
            print(f"  NO SIRVE: {detalle}")
            if detalle is SIN_PAGINA:
                pag, rescatado = rescate_por_id(token, app_id_del_token(token))
                if pag:
                    token, ig_id, detalle = pag["token"], pag["ig_id"], pag["cuenta"]
                    print(f"  OK: conectado a {detalle}, por la Página '{pag['pagina']}'")
                    break
            if not si_no("¿Probás con otro token?"):
                return None
            continue
        print(f"  OK: conectado a {detalle}")
        break

    app_id = app_id_del_token(token)
    print(f"  App ID: {app_id} (lo leí del token)" if app_id else
          "  No pude leer el App ID del token.")

    cred = {"IG_PAGE_TOKEN": token, "IG_USER_ID": ig_id, "cuenta": detalle,
            "IG_APP_ID": app_id or "", "IG_APP_SECRET": rescatado}

    # Un token de Página que no vence YA ES el resultado del canje. Pedir el App Secret
    # acá sería exigir una credencial para llegar a donde el token ya está: el canje
    # fallaría además con un error críptico, porque `me/accounts` no existe para una
    # Página.
    est = estado_token(token)
    if est.get("tipo") == "PAGE" and est.get("vence_en_dias") is None:
        print("  Este token es de Página y no vence: no hay nada que convertir.")
        return cred

    print("""
  Este token vence, así que hay que canjearlo por uno permanente. Para eso Meta pide
  el App Secret: developers.facebook.com > tu app > Configuración > Información básica.""")
    app_secret = preguntar("  App Secret").strip()
    if not app_id:
        app_id = preguntar("  App ID").strip()
        cred["IG_APP_ID"] = app_id
    cred["IG_APP_SECRET"] = app_secret

    if not (app_id and app_secret):
        dias = est.get("vence_en_dias")
        print(f"""
  ATENCIÓN: sin App Secret guardo el token tal cual vino{f', y vence en {dias} días' if dias else ''}.
  Después el panel queda mudo. Volvé a correr `python3 instalar.py` cuando lo tengas.""")
        return cred

    print("  Convirtiéndolo en permanente...")
    pag, err = volver_permanente(token, app_id, app_secret)
    if err:
        print(f"  No se pudo: {err}")
        dias = estado_token(token, app_id, app_secret).get("vence_en_dias")
        print(f"  Guardo el token como está (vence en {dias} días)." if dias
              else "  Guardo el token como está.")
        if not si_no("¿Seguir igual?", True):
            return None
        return cred

    print(f"  LISTO: token de la Página '{pag['pagina']}' — sin vencimiento.")
    cred.update({"IG_PAGE_TOKEN": pag["token"], "IG_USER_ID": pag["ig_id"],
                 "cuenta": pag["cuenta"]})
    return cred


def guardar_env(cred):
    """Escribe el .env. Si ya existe, hace una copia antes de tocarlo: perder las
    credenciales de otra cosa por sobreescribir un archivo es un mal día entero."""
    if os.path.exists(ENV):
        shutil.copy(ENV, ENV + ".backup")
        print(f"  (copia de seguridad en {os.path.basename(ENV)}.backup)")
        previas = {}
        for linea in open(ENV, encoding="utf-8", errors="replace"):
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.strip().split("=", 1)
                previas[k] = v
        # Un valor vacio NO pisa a uno bueno: si alguien reconfigura y saltea el
        # App Secret, sin este filtro le borrabamos el que ya andaba.
        previas.update({k: v for k, v in cred.items() if k != "cuenta" and v})
    else:
        previas = {k: v for k, v in cred.items() if k != "cuenta" and v}

    # encoding explicito: sin esto Windows escribia el archivo en cp1252 y el acento
    # de "Metricas" dejaba el panel entero sin poder leer sus credenciales.
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("# Credenciales del Panel de Métricas. NO se versiona ni se comparte.\n")
        for k, v in previas.items():
            f.write(f"{k}={v}\n")
    os.chmod(ENV, 0o600)  # solo el dueño puede leerlo
    print(f"  Guardado en {ENV} (permisos 600)")


# ── 4. la configuración del panel ───────────────────────────────────────────
def aviso_youtube():
    """YouTube no entra por el mismo camino que Meta, y hay que decirlo acá.

    Meta se resuelve pegando un token; Google exige un ida y vuelta por el navegador
    que no entra en una pregunta del instalador. El agujero no era técnico —yt_token.py
    hace todo— sino que nadie te avisaba que ese paso existía: activabas YouTube, el
    panel salía vacío y no había forma de saber por qué.
    """
    import yt_token
    if os.path.exists(yt_token.TOKEN):
        print("  YouTube ya está autorizado en esta instalación.")
        return
    tiene_credenciales = (os.path.exists(yt_token.CLIENT)
                          or leer_env().get("YT_CLIENT_ID"))
    print("""
  OJO con YouTube: falta un paso más, y no lo puedo hacer solo. Google no acepta
  un token pegado como Meta: hay que autorizar desde el navegador y volver con el
  código. Sin eso, la pantalla de YouTube va a estar vacía (el resto del panel
  funciona igual).""")
    if tiene_credenciales:
        print("""
  Ya tenés las credenciales de Google acá, así que son dos comandos:

      python3 yt_token.py auth          # te da la URL para autorizar
      python3 yt_token.py code "<url>"  # pegás la URL entera a la que te devuelve""")
    else:
        print(f"""
  Primero hacen falta las credenciales de Google (una vez, gratis):

    1. console.cloud.google.com > crear proyecto
    2. Habilitar "YouTube Data API v3" y "YouTube Analytics API"
    3. Credenciales > Crear credenciales > ID de cliente de OAuth > Aplicación de
       escritorio > descargar el JSON
    4. Dejar ese archivo acá como:
           {yt_token.CLIENT}
       (o poner YT_CLIENT_ID y YT_CLIENT_SECRET en el .env)

  Y después:

      python3 yt_token.py auth
      python3 yt_token.py code "<url>" """)
    input("\n  Enter para seguir... ")


def aviso_tiktok():
    """TikTok tiene el mismo problema que YouTube (autorizar por navegador) y uno más.

    Hay que crear una app en el portal de TikTok. Suena a trámite pesado y no lo es:
    la parte que TikTok rechaza —y por la que todo el mundo abandona— es el permiso
    para PUBLICAR. Leer tus propios datos es otro permiso y no necesita revisión.
    Decirlo acá evita que el cliente se frene en un paso que no le corresponde.
    """
    import tiktok
    if os.path.exists(tiktok.TOKENS):
        print("  TikTok ya está autorizado en esta instalación.")
        return
    env = leer_env()
    tiene_credenciales = env.get("TIKTOK_CLIENT_KEY") and env.get("TIKTOK_CLIENT_SECRET")
    print("""
  OJO con TikTok, dos cosas:

  1. Trae MENOS datos que las demás, y no es un error del panel. Su API pública da
     seguidores, likes, videos y —por video— vistas, likes, comentarios y shares.
     NO da alcance, retención ni demografía: esos números viven solo en la app.

  2. Falta un paso que no puedo hacer solo: autorizar desde el navegador, igual
     que YouTube. Sin eso la pantalla queda vacía (el resto del panel anda igual).""")
    if not tiene_credenciales:
        print("""
  Primero hay que crear la app (una vez, gratis, con la cuenta del cliente):

    1. developers.tiktok.com > Manage apps > crear una app
    2. Agregarle el producto "Login Kit"
    3. Pedir SOLO estos permisos de lectura:
           user.info.basic, user.info.stats, video.list
       (NO pidas los de publicar: son los que TikTok rechaza, y pedirlos de más
        es lo que hace fallar la revisión. Para leer no hace falta revisión.)
    4. En Login Kit > Redirect URI poner una página tuya cualquiera: solo recibe
       el código en la URL. NO uses una que canjee el código (como la de Postiz),
       porque un código es de un solo uso y te lo quema.
    5. Copiar Client key y Client secret al .env:
           TIKTOK_CLIENT_KEY=...
           TIKTOK_CLIENT_SECRET=...
           TIKTOK_REDIRECT=<la misma URL del paso 4>""")
    print("""
  Y después, los dos comandos:

      python3 tiktok.py auth          # te da la URL para autorizar
      python3 tiktok.py code "<url>"  # pegás la URL entera a la que te devuelve""")
    input("\n  Enter para seguir... ")


def armar_config(cuenta):
    titulo("4. De quién es este panel")
    cfg = config.cargar()
    cfg["marca"]["organizacion"] = preguntar(
        "Nombre que va grande en el panel", cfg["marca"]["organizacion"]).upper()
    cfg["marca"]["cuenta"] = preguntar("Handle de la cuenta", cuenta or cfg["marca"]["cuenta"])

    print("""
  En una línea: de qué se trata el negocio y para quién. Esto va dentro de los
  prompts de IA. Es lo que separa un análisis que dice "subí el engagement" de
  uno que dice "tus reels de casos reales rinden 3x, hacé más de esos".
    ejemplo: software de gestión para consultorios médicos en Argentina""")
    cfg["marca"]["descripcion"] = preguntar("El negocio en una línea",
                                            cfg["marca"].get("descripcion", ""))

    print("\n  Qué redes tiene. Una red apagada no se muestra (no aparece vacía).")
    # El nombre va escrito a mano: "tiktok".capitalize() da "Tiktok", que está mal.
    # TikTok arranca en False porque necesita un paso extra (ver aviso_tiktok).
    for red, nombre in (("instagram", "Instagram"), ("facebook", "Facebook"),
                        ("youtube", "YouTube"), ("tiktok", "TikTok")):
        defecto = cfg["redes"].get(red, red != "tiktok")
        cfg["redes"][red] = si_no(f"¿Usa {nombre}?", defecto)
    if cfg["redes"]["youtube"]:
        aviso_youtube()
    if cfg["redes"]["tiktok"]:
        aviso_tiktok()

    cfg["postiz"]["activo"] = si_no(
        "¿Usa Postiz para programar? (el calendario editorial)", False)

    print("""
  Palabras clave de tus CTAs: la palabra que pedís comentar ("comentá PANEL y te
  lo mando"). Sirven para separar dos cosas que en la bandeja de comentarios se ven
  iguales: el que comentó la palabra y quedó esperando que le mandes algo, y el que
  preguntó "¿cuánto sale?". Lo primero es una entrega pendiente, lo segundo un lead.

  Son pocas: una por campaña, no una por video. Si en cien videos pedís siempre la
  misma palabra, es una sola. Si no usás CTAs dejalo vacío (Enter): el panel anda
  igual. Se cambian cuando quieras, en config.json o corriendo esto de nuevo.
    ejemplo (separadas por coma): PANEL, INFO, GUIA""")
    ctas = preguntar("Palabras clave", ", ".join(cfg.get("ctas", [])))
    cfg["ctas"] = [c.strip().upper() for c in ctas.split(",") if c.strip()]

    cfg["dias"] = int(preguntar("Días de historia a mostrar", str(cfg.get("dias", 30))))
    ruta = config.guardar(cfg)
    print(f"\n  Guardado en {ruta}")
    return cfg


# ── 5. la inteligencia artificial ───────────────────────────────────────────
def configurar_ia(hay_claude):
    """Deja andando el análisis con IA por el camino que corresponda.

    Son dos caminos y conviene entender la diferencia antes de elegir, porque uno
    es gratis y el otro no:

      - Claude Code ya instalado: el panel lo usa y no cuesta nada extra, porque
        corre sobre la suscripción de Claude que la persona ya paga.
      - Sin Claude Code: hace falta una API key, que se paga por uso (centavos por
        análisis) pero no obliga a instalar nada.

    Si ya hay Claude Code no preguntamos nada: ofrecerle a alguien pagar por algo
    que ya tiene resuelto es la clase de pregunta que hace dudar de un instalador.
    """
    titulo("5. El análisis con IA")
    if hay_claude:
        print("""  Encontré Claude Code instalado, así que el panel va a usarlo.
  No cuesta nada extra: corre sobre tu suscripción de Claude.""")
        return None

    print("""  El panel funciona sin esto: los números, los gráficos y la competencia
  no necesitan IA. Lo que se apaga son el análisis escrito y el botón Generar.

  Hay dos formas de encenderlo:

    a) Instalar Claude Code (gratis si ya pagás Claude):
           npm i -g @anthropic-ai/claude-code
       Después volvé a correr este instalador.

    b) Pegar una API key acá abajo. Se paga por uso: alrededor de 4 dólares al
       mes con un análisis por día. Se saca en console.anthropic.com > API Keys.""")
    key = preguntar("\n  API key (Enter para saltear)").strip()
    if not key:
        print("  Salteado. El panel arranca igual, sin las funciones de IA.")
        return None
    if not key.startswith("sk-ant-"):
        print("""
  Ojo: las API keys de Anthropic empiezan con 'sk-ant-' y esta no. La guardo igual
  por si es de otro proveedor compatible (Kimi, DeepSeek), pero en ese caso falta
  un paso: hay que poner también ANTHROPIC_BASE_URL en el .env, y la key va en
  ANTHROPIC_AUTH_TOKEN en vez de ANTHROPIC_API_KEY. Está explicado en .env.example.
  Si era una key de Anthropic, revisala: seguro se cortó al copiar.""")
    return {"ANTHROPIC_API_KEY": key}


# ── 6. primera corrida ──────────────────────────────────────────────────────
def primera_corrida():
    titulo("6. Primera recolección")
    print("  Bajando datos... tarda entre uno y dos minutos.\n")
    r = subprocess.run([sys.executable, os.path.join(AQUI, "recolector.py")], cwd=AQUI)
    if r.returncode != 0:
        print("\n  Falló. Revisá el mensaje de arriba y volvé a correr:")
        print(f"      python3 {os.path.join(AQUI, 'recolector.py')}")
        return False
    print(f"\n  Listo: {os.path.join(AQUI, 'panel.html')}")
    return True


def abrir_panel():
    """Levanta el servidor, que a su vez abre el navegador solo.

    Termina acá a propósito: el objetivo del instalador es que la persona VEA su
    panel, no que lea instrucciones sobre cómo abrirlo. El proceso queda corriendo
    en esta misma ventana y se corta con Ctrl+C.
    """
    titulo("Abriendo el panel")
    print("  Se abre solo en el navegador. Esta ventana tiene que quedar abierta.")
    print("  Para cerrarlo: Ctrl+C acá.\n")
    try:
        subprocess.run([sys.executable, os.path.join(AQUI, "servidor.py")], cwd=AQUI)
    except KeyboardInterrupt:
        print("\n  Panel cerrado.")


ACCESO = "IamAutom Command Center"

# El .app de macOS es una carpeta con esta pinta adentro. CFBundleIconFile es lo único
# que hace falta para que el Finder muestre el ícono propio en vez del genérico.
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{nombre}</string>
  <key>CFBundleDisplayName</key><string>{nombre}</string>
  <key>CFBundleExecutable</key><string>lanzar</string>
  <key>CFBundleIconFile</key><string>icono</string>
  <key>CFBundleIdentifier</key><string>com.iamautom.commandcenter</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>NSHumanReadableCopyright</key><string>{sello}</string>
</dict></plist>
"""

# Firma de autoría. Un solo lugar para cambiarla: se usa en el .app, en el instalador
# y —vía plantilla.html— en el panel.
SELLO = "IamAutom Command Center · by @tincho.olivero · iamautom.com"

# De dónde baja `--actualizar`. Es el ZIP de la rama publicada: no contiene datos de
# nadie, porque el .gitignore los deja afuera del repositorio.
REPO_ZIP = "https://github.com/MartinOlivero/command-center/archive/refs/heads/main.zip"

# Aunque el ZIP no debería traerlos, si alguno se cuela por error no se pisa: perder el
# histórico es lo único irreversible del panel — esos días ya no se le pueden volver a
# pedir a la API.
INTOCABLES = {".env", ".env.backup", ".env.local", "config.json", "panel.html",
              "historico.jsonl", "comentarios.json", "analisis.json", "ideas.json",
              "duraciones.json"}


def _acceso_mac(escritorio):
    """Un .app de verdad, que es la única forma de que macOS muestre un ícono propio.

    El .app no abre ventana por sí solo, y el panel necesita una: es donde se avisa que
    hay que dejarla abierta y donde se corta con Ctrl+C. Por eso adentro no corre el
    servidor, sino que le pide a la Terminal que abra el lanzador de siempre.
    """
    app = os.path.join(escritorio, f"{ACCESO}.app")
    shutil.rmtree(app, ignore_errors=True)
    macos = os.path.join(app, "Contents", "MacOS")
    recursos = os.path.join(app, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(recursos)

    ejecutable = os.path.join(macos, "lanzar")
    with open(ejecutable, "w", encoding="utf-8") as f:
        # Sin ventana de Terminal: el panel es una app, no un script. Si ya hay un
        # servidor vivo se abre el navegador y listo — dos doble clics no levantan dos
        # servidores. El de adentro se apaga solo cuando se cierra la pestaña.
        f.write(f'''#!/bin/bash
# Si la carpeta se movió, o macOS todavía no dio permiso para entrar a ella, hay que
# decirlo: morir en silencio deja a la persona haciendo doble clic sin entender nada.
if ! cd "{AQUI}"; then
  osascript -e 'display alert "No encuentro la carpeta del panel" message "Estaba en:\\n\\n{AQUI}\\n\\nSi la moviste, volvé a correr el instalador desde su nueva ubicación. Si macOS te pidió permiso para acceder a esa carpeta, dale Permitir."'
  exit 1
fi

# Acá se buscaba a mano, con curl, el primer puerto del rango que contestara, y se
# abría ESE. Pero en una máquina puede haber más de un panel —dos instalaciones, o el
# de otra persona— y todos contestan igual: el 22/08/2026 el ícono abrió el panel de
# otra cuenta, con sus datos. Ahora decide `servidor.py --fondo`, que es el único que
# sabe cuál es el suyo: si ya está abierto abre esa pestaña, y si no, lo levanta.
# Además vale para las dos plataformas — en Windows el acceso directo llama a
# pythonw.exe sin script en el medio donde poner esta lógica.
if ! python3 servidor.py --fondo >> panel.log 2>&1; then
  osascript -e 'display alert "No pude abrir el panel" message "Mirá el archivo panel.log en la carpeta del panel."'
  exit 1
fi
''')
    os.chmod(ejecutable, 0o755)  # sin esto el doble clic no hace nada

    icono = os.path.join(AQUI, "icono.icns")
    if os.path.exists(icono):
        shutil.copy(icono, os.path.join(recursos, "icono.icns"))
    with open(os.path.join(app, "Contents", "Info.plist"), "w",
              encoding="utf-8") as f:
        f.write(PLIST.format(nombre=ACCESO, sello=SELLO))
    return app


def pythonw():
    """El Python sin consola de Windows, si está. Es el equivalente a no abrir Terminal.

    `python.exe` abre una ventana negra que hay que dejar abierta; `pythonw.exe` es el
    mismo intérprete sin esa ventana, y viene al lado en toda instalación normal.
    """
    if os.name != "nt":
        return None
    candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidato if os.path.exists(candidato) else None


def _acceso_windows(escritorio):
    """Un .lnk, que es lo único que admite ícono en Windows (un .bat no).

    Apunta a pythonw.exe para que no quede una consola abierta. Si no aparece —una
    instalación rara, o Python desde la Microsoft Store— cae al .bat de siempre: con
    ventana, pero funcionando. Y si la política de PowerShell bloquea la creación del
    acceso —pasa en equipos corporativos— cae a un .bat en el Escritorio: sin ícono,
    pero abre el panel igual. Mejor eso que nada.
    """
    destino = os.path.join(escritorio, f"{ACCESO}.lnk")
    sin_consola = pythonw()
    if sin_consola:
        blanco, args = sin_consola, '$s.Arguments="servidor.py --fondo";'
    else:
        blanco, args = os.path.join(AQUI, "Abrir panel.bat"), ""
    ps = (f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{destino}");'
          f'$s.TargetPath="{blanco}";{args}'
          f'$s.WorkingDirectory="{AQUI}";'
          f'$s.IconLocation="{os.path.join(AQUI, "icono.ico")}";$s.Save()')
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.exists(destino):
        return destino

    destino = os.path.join(escritorio, f"{ACCESO}.bat")
    # ponytail: este va en la codepage de la consola, NO en UTF-8. Un .bat lo lee
    # cmd.exe, que no habla UTF-8: si el usuario se llama "Martin" da igual, pero si
    # se llama "Jose" la ruta con acento tiene que salir como cmd espera leerla.
    with open(destino, "w",
              encoding=locale.getpreferredencoding(False)) as f:
        f.write(f'@echo off\r\ncd /d "{AQUI}"\r\ncall "Abrir panel.bat"\r\n')
    return destino


def _apunta_aca(ruta):
    """¿Ese acceso del Escritorio es de ESTA instalación?

    Un .app es una carpeta: lo que lleva la ruta adentro es su script. El .lnk de
    Windows la guarda en UTF-16, no en UTF-8, así que se buscan las dos formas.
    """
    objetivo = (os.path.join(ruta, "Contents", "MacOS", "lanzar")
                if ruta.endswith(".app") else ruta)
    try:
        with open(objetivo, "rb") as f:
            crudo = f.read()
    except OSError:
        return False                       # no se puede saber: no se toca
    return AQUI.encode("utf-8") in crudo or AQUI.encode("utf-16-le") in crudo


def _rehacer_acceso(escritorio=None):
    """Rehace el acceso del Escritorio si ya había uno DE ESTA instalación.

    Las dos condiciones importan. Si no hay acceso, no se crea: que no esté puede ser
    una decisión. Y si el que hay apunta a otra carpeta, no se toca — con dos paneles
    instalados, actualizar uno no puede robarle el ícono al otro.

    Eso último no es hipotético: el 22/08/2026 los tests de este archivo, que corren
    `actualizar()` sobre una carpeta temporal, reescribieron el acceso de verdad. Quedó
    apuntando a /var/folders/…/T/tmp… y sin su logo. Un test no puede salir de su caja,
    y la forma de garantizarlo es que la función mire de quién es lo que va a pisar.
    """
    escritorio = escritorio or os.path.join(os.path.expanduser("~"), "Desktop")
    hay = [n for n in (f"{ACCESO}.app", f"{ACCESO}.lnk", f"{ACCESO}.bat")
           if _apunta_aca(os.path.join(escritorio, n))]
    if not hay:
        return None
    try:
        destino = (_acceso_windows(escritorio) if sys.platform == "win32"
                   else _acceso_mac(escritorio))
        return os.path.basename(destino) + " (acceso del Escritorio)"
    except Exception:                      # noqa: BLE001
        # Cualquier cosa que pase acá es cosmética: el panel YA se actualizó bien. Que
        # un ícono que no se pudo rehacer haga fallar toda la actualización sería
        # cambiar algo importante por algo accesorio.
        return None


def actualizar(escritorio=None):
    # `escritorio` existe para los tests: sin él, probar esta función toca el Escritorio
    # de verdad de quien corre los tests. Que la protección de `_apunta_aca` alcance no
    # es excusa para no aislarlo — una prueba no puede depender de que el código que
    # está probando esté bien.
    """Trae la última versión del panel sin tocar nada de la persona.

    Descomprimir un ZIP encima de la carpeta parece equivalente, pero no lo es: el Finder
    de macOS no fusiona carpetas, crea una al lado. La persona termina con dos
    instalaciones y actualizando la que no usa. Acá no hay nada que descomprimir.

    Lo que hace seguro reemplazar todo lo que venga en el ZIP es que el repositorio NO
    contiene datos: el .gitignore deja afuera el .env, el config.json, el histórico y el
    panel. Igual se ignoran por nombre, por si alguna vez se cuela uno por error — una
    actualización que borra el histórico no tiene vuelta atrás.
    """
    titulo(f"Actualizar el panel (tenés la {config.VERSION})")
    print(f"  Bajando la última versión desde:\n      {REPO_ZIP}\n")
    try:
        with urllib.request.urlopen(REPO_ZIP, timeout=60) as r:
            crudo = io.BytesIO(r.read())
    except urllib.error.HTTPError as e:
        # GitHub contesta 404 —no 403— cuando el repositorio es privado: no revela que
        # existe. Decir "revisá tu conexión" acá manda a la persona a buscar donde no es.
        print(f"  El servidor respondió {e.code}.")
        print("  Si el repositorio todavía es privado, la descarga automática no funciona:"
              "\n  pedí el ZIP a quien te pasó el panel." if e.code == 404 else
              "  Probá de nuevo en un rato.")
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"  No pude descargarla ({e}).")
        print("  Revisá tu conexión, o bajá el ZIP a mano desde el repositorio.")
        return 1

    cambiados, saltados = [], []
    try:
        with zipfile.ZipFile(crudo) as z:
            for miembro in z.infolist():
                if miembro.is_dir():
                    continue
                # El ZIP de GitHub mete todo dentro de una carpeta con el nombre del repo.
                relativo = miembro.filename.split("/", 1)[-1]
                if not relativo:
                    continue
                if os.path.basename(relativo) in INTOCABLES:
                    saltados.append(relativo)
                    continue
                destino = os.path.join(AQUI, relativo)
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                nuevo = z.read(miembro)
                # zipfile NO restaura permisos: un lanzador que llega sin el bit de
                # ejecución no hace nada al doble clic. Se revisa SIEMPRE, aunque el
                # contenido no cambie: un archivo correcto con permisos rotos es
                # justamente el que nunca se arreglaría solo.
                ejecutable = bool((miembro.external_attr >> 16) & 0o111)
                if os.path.exists(destino) and open(destino, "rb").read() == nuevo:
                    if ejecutable and not os.access(destino, os.X_OK):
                        os.chmod(destino, 0o755)
                        cambiados.append(f"{relativo} (permisos)")
                    continue
                with open(destino, "wb") as f:
                    f.write(nuevo)
                if ejecutable:
                    os.chmod(destino, 0o755)
                cambiados.append(relativo)
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  El archivo bajado no se pudo abrir ({e}). No toqué nada.")
        return 1

    if not cambiados:
        print("  Ya tenías la última versión: no cambió ningún archivo.")
        return 0

    # El acceso del Escritorio NO viaja en el ZIP: se genera en la instalación y se
    # queda con el lanzador de ese día. Si no se rehace, un arreglo del lanzador no
    # llega nunca a quien ya lo tiene — que es justo el que lo necesita. Sólo se
    # rehace si ya existe: si lo borraron, fue a propósito.
    rehecho = _rehacer_acceso(escritorio)
    if rehecho:
        cambiados.append(rehecho)
    print(f"  Actualizados {len(cambiados)} archivos:")
    for c in sorted(cambiados)[:12]:
        print(f"      {c}")
    if len(cambiados) > 12:
        print(f"      … y {len(cambiados) - 12} más")
    if saltados:
        print(f"  Intactos tus datos ({', '.join(sorted(set(saltados)))}).")
    print("\n  Listo. Abrí el panel y apretá ↻ para bajar los datos con la versión nueva.")
    return 0


def carpeta_protegida(ruta):
    """Si el panel quedó en una carpeta que macOS protege.

    Escritorio, Documentos y Descargas están detrás de TCC: una app sin firma de
    desarrollador registrado no puede LEER ahí, y macOS ni siquiera pregunta — deniega
    y listo. El acceso del Escritorio abre igual, pero el servidor no puede abrir sus
    propios archivos y el panel no arranca nunca.

    Y es justo donde termina el ZIP que baja cualquiera: Descargas.
    """
    if sys.platform != "darwin":
        return False
    casa = os.path.realpath(os.path.expanduser("~"))
    aqui = os.path.realpath(ruta)
    return any(aqui == os.path.join(casa, c) or aqui.startswith(os.path.join(casa, c) + os.sep)
               for c in ("Desktop", "Documents", "Downloads",
                         "Escritorio", "Documentos", "Descargas"))


def mudarse():
    """Mueve el panel fuera de las carpetas protegidas. Devuelve el destino, o None.

    No se mueve solo mientras corre: se mueve y se pide volver a empezar desde el nuevo
    lugar. Reescribir la carpeta que uno mismo está ejecutando es la clase de atajo que
    funciona nueve de cada diez veces.
    """
    destino = os.path.join(os.path.expanduser("~"), "Command Center")
    print(f"""
  ATENCIÓN: el panel está en una carpeta que macOS protege.

      {AQUI}

  Desde ahí el acceso del Escritorio no va a poder abrirlo: macOS no deja que una
  aplicación lea dentro de Escritorio, Documentos ni Descargas, y ni siquiera avisa.
  Se resuelve moviéndolo una vez, a:

      {destino}""")
    if not si_no("\n¿Lo muevo ahí?"):
        print("  Lo dejo donde está. Vas a tener que abrirlo con 'Abrir panel.command'.")
        return None
    if os.path.exists(destino):
        print(f"  Ya existe {destino}. Movelo o borralo y volvé a correr esto.")
        return None
    try:
        shutil.move(AQUI, destino)
    except OSError as e:
        print(f"  No pude moverlo ({e}). Hacelo a mano y volvé a correr el instalador.")
        return None
    print(f"""
  Listo, ahora vive en:
      {destino}

  Abrí esa carpeta y hacé doble clic en 'Instalar.command' para terminar.""")
    return destino


def crear_acceso_directo():
    """Deja el panel a un doble clic en el Escritorio.

    Sin esto hay que acordarse de en qué carpeta quedó el ZIP descomprimido — casi
    siempre Descargas, entre otras cincuenta cosas. El acceso NO es un alias: los
    lanzadores hacen `cd` al directorio del archivo, y con un alias ese directorio
    sería el Escritorio, así que el panel no encontraría ni el .env ni los scripts.
    Entra a la carpeta real y desde ahí llama al lanzador de siempre.

    Si la carpeta se mueve, el acceso deja de servir: se rehace corriendo el instalador.
    """
    escritorio = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(escritorio):
        return
    if not si_no(f"\n¿Te dejo '{ACCESO}' en el Escritorio?"):
        return
    try:
        destino = (_acceso_windows(escritorio) if sys.platform == "win32"
                   else _acceso_mac(escritorio))
        print(f"  Listo: doble clic en '{os.path.basename(destino)}' desde el Escritorio.")
    except OSError as e:
        print(f"  No pude crearlo ({e}). Igual podés abrirlo desde la carpeta del panel.")


def main():
    print("\n\033[1m  C O M M A N D   C E N T E R\033[0m — instalación")
    print(f"  \033[2m{SELLO} · v{config.VERSION}\033[0m\n")
    print("  Seis pasos. Se puede cortar en cualquier momento con Ctrl+C y retomar:")
    print("  nada queda a medias.")

    # Antes que nada: si está en una carpeta protegida, moverlo. Todo lo que venga
    # después (credenciales, config, datos) tendría que rehacerse en la ruta nueva.
    if carpeta_protegida(AQUI) and mudarse():
        return 0

    hallado = revisar_dependencias()

    cred = None
    if not os.path.exists(ENV) or si_no("\n¿Reconfigurar la cuenta conectada?", False):
        guia_meta()
        cred = pedir_credenciales()
        if cred:
            guardar_env(completar_page_id(cred))
    else:
        print("\n  Ya hay un .env: dejo las credenciales como están.")

    armar_config((cred or {}).get("cuenta"))

    if not leer_env().get("ANTHROPIC_API_KEY"):
        key = configurar_ia(hallado.get("claude"))
        if key:
            guardar_env(key)

    crear_acceso_directo()

    if si_no("\n¿Bajo los datos ahora?") and primera_corrida():
        if si_no("\n¿Abro el panel?"):
            abrir_panel()
            return
    print(f"""
  Terminado.

  Para abrir el panel más adelante, doble clic en el acceso del Escritorio, o en:
      {"Abrir panel.command" if sys.platform == "darwin" else "Abrir panel.bat"}

  Para actualizar los datos: el botón ↻ arriba a la derecha del panel.
  Para entender qué significa cada número: la pantalla "Cómo leer este panel".
""")


def leer_env():
    """El .env como diccionario. Vacío si no existe."""
    if not os.path.exists(ENV):
        return {}
    fuera = {}
    for linea in open(ENV, encoding="utf-8", errors="replace"):
        linea = linea.strip()
        if "=" in linea and not linea.startswith("#"):
            k, v = linea.split("=", 1)
            fuera[k.strip()] = v.strip()
    return fuera


def diagnostico():
    """`python3 instalar.py --estado`: en qué anda la conexión de Meta, hoy.

    Existe para no tener que descubrir un token vencido por el sintoma (un panel
    vacio) sino por la causa. Es tambien lo que va a leer la vista de Ajustes.
    """
    titulo("Estado de la conexión con Meta")
    env = leer_env()
    token = env.get("IG_PAGE_TOKEN")
    if not token:
        print("  No hay IG_PAGE_TOKEN en el .env. Corré `python3 instalar.py`.")
        return 1

    est = estado_token(token, env.get("IG_APP_ID"), env.get("IG_APP_SECRET"))
    if not est["valido"]:
        print(f"  CAÍDO: {est['motivo']}")
        print("  Se arregla corriendo `python3 instalar.py` y pegando un token nuevo.")
        return 1

    dias = est["vence_en_dias"]
    print(f"  Token de tipo {est.get('tipo', '?')}")
    if dias is None:
        print("  Vencimiento: NO VENCE. Es lo que corresponde.")
    else:
        print(f"  Vencimiento: en {dias} días.")
        print("  Conviene volverlo permanente: `python3 instalar.py` y reconfigurar"
              "\n  la cuenta, pegando un token de USUARIO.")
    faltantes = [p for p in PERMISOS if p not in est["scopes"]]
    print("  Permisos: completos." if not faltantes
          else f"  Permisos que faltan: {', '.join(faltantes)}")
    if not env.get("IG_APP_SECRET"):
        print("  Falta IG_APP_SECRET en el .env: sin él no se puede renovar solo.")
    return 0 if (dias is None and not faltantes) else 1


if __name__ == "__main__":
    try:
        if "--estado" in sys.argv:
            sys.exit(diagnostico())
        elif "--actualizar" in sys.argv:
            sys.exit(actualizar())
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  Cortado. Nada quedó a medias: corré `python3 instalar.py` cuando quieras.")
