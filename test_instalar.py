#!/usr/bin/env python3
"""Checks de la cadena de tokens de Meta, sin tocar la API real.

    python3 test_instalar.py

Lo que se prueba es la LOGICA, que es donde estan los errores caros: distinguir
un token que no vence de uno que vence, y no dar por buena una cadena que quedo
a medias. Las respuestas de Meta se simulan reemplazando `instalar.get`.
"""
import time
import instalar

AHORA = int(time.time())
llamadas = []


def falsa_api(respuestas):
    """Reemplaza instalar.get por una que devuelve respuestas preparadas.

    Guarda cada llamada en `llamadas` para poder afirmar TAMBIEN sobre como se
    pidio, no solo sobre lo que se devolvio.
    """
    def get(ruta, **params):
        llamadas.append((ruta, params))
        for clave, valor in respuestas.items():
            if clave in ruta:
                return valor
        return {"_error": f"sin respuesta preparada para {ruta}"}
    instalar.get = get


# ── estado_token: lo esencial es distinguir "no vence" de "vence" ────────────
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "PAGE",
                                    "expires_at": 0, "scopes": instalar.PERMISOS}}})
est = instalar.estado_token("tok", "id", "sec")
assert est["valido"]
assert est["vence_en_dias"] is None, "expires_at 0 significa que NO vence"

falsa_api({"debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": AHORA + 60 * 86400,
                                    "scopes": instalar.PERMISOS}}})
assert instalar.estado_token("tok", "id", "sec")["vence_en_dias"] == 60

# un token ya vencido no puede devolver dias negativos
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": AHORA - 10 * 86400, "scopes": []}}})
assert instalar.estado_token("tok")["vence_en_dias"] == 0

falsa_api({"debug_token": {"data": {"is_valid": False}}})
assert instalar.estado_token("tok")["valido"] is False

# el token de la app se arma como pide Meta, y solo si estan las dos partes
assert instalar.app_token("111", "abc") == "111|abc"
llamadas.clear()
falsa_api({"debug_token": {"data": {"is_valid": True, "expires_at": 0, "scopes": []}}})
instalar.estado_token("tok", "111", "abc")
assert llamadas[0][1]["access_token"] == "111|abc", "debe inspeccionar con el app token"
llamadas.clear()
instalar.estado_token("tok")            # sin app_id/secret cae al propio token
assert llamadas[0][1]["access_token"] == "tok"

# ── la cadena completa ──────────────────────────────────────────────────────
CADENA_OK = {
    "oauth/access_token": {"access_token": "USER_LARGO"},
    "me/accounts": {"data": [
        {"name": "Sin Instagram"},                       # se saltea: no tiene IG
        {"name": "La Página", "access_token": "PAGE_PERMANENTE",
         "instagram_business_account": {"id": "17841400", "username": "cliente"}},
    ]},
    "debug_token": {"data": {"is_valid": True, "type": "PAGE", "expires_at": 0,
                             "scopes": instalar.PERMISOS}},
}
falsa_api(CADENA_OK)
pag, err = instalar.volver_permanente("CORTO", "111", "abc")
assert err is None, err
assert pag["token"] == "PAGE_PERMANENTE"
assert pag["ig_id"] == "17841400"
assert pag["cuenta"] == "@cliente"

# ── y ahora lo que importa de verdad: que NO de por buena una cadena fallida ──
# Este es el caso del token de Pagina pegado por error: el canje "anda" pero lo
# que sale sigue venciendo. Sin este chequeo el cliente se entera en dos horas.
falsa_api({**CADENA_OK,
           "debug_token": {"data": {"is_valid": True, "type": "PAGE",
                                    "expires_at": AHORA + 3600,
                                    "scopes": instalar.PERMISOS}}})
pag, err = instalar.volver_permanente("CORTO", "111", "abc")
assert pag is None and "permanente" in err, f"tendria que rechazarlo, dijo: {err}"

# Meta rechaza el canje (secret mal copiado es el caso tipico)
falsa_api({"oauth/access_token": {"_error": "Invalid appsecret"}})
pag, err = instalar.volver_permanente("CORTO", "111", "malo")
assert pag is None and "Invalid appsecret" in err

# el usuario administra Paginas pero ninguna tiene Instagram vinculado
falsa_api({"oauth/access_token": {"access_token": "USER_LARGO"},
           "me/accounts": {"data": [{"name": "Solo Facebook"}]}})
pag, err = instalar.volver_permanente("CORTO", "111", "abc")
assert pag is None and "Instagram" in err

# no administra ninguna Pagina
falsa_api({"oauth/access_token": {"access_token": "USER_LARGO"},
           "me/accounts": {"data": []}})
pag, err = instalar.volver_permanente("CORTO", "111", "abc")
assert pag is None and "Página" in err

# el canje se pide con los parametros exactos que documenta Meta
llamadas.clear()
falsa_api(CADENA_OK)
instalar.intercambiar_por_largo("CORTO", "111", "abc")
ruta, params = llamadas[0]
assert ruta == "oauth/access_token"
assert params["grant_type"] == "fb_exchange_token"
assert params["client_id"] == "111" and params["client_secret"] == "abc"
assert params["fb_exchange_token"] == "CORTO"

# y el token de Pagina se deriva con el LARGO, no con el corto: es toda la
# diferencia entre uno permanente y uno de dos horas
llamadas.clear()
instalar.volver_permanente("CORTO", "111", "abc")
cuentas = [p for r, p in llamadas if r == "me/accounts"][0]
assert cuentas["access_token"] == "USER_LARGO", \
    "derivar la Pagina con el token corto devuelve uno que vence en 2 horas"

# ── verificar_token: el error de Meta no se puede tapar ─────────────────────
# Si la API contesta cualquier otra cosa (limite de uso, app en modo desarrollo, red
# caida) y el instalador dice "el token no es valido", la persona sale a regenerar un
# token que estaba bien. El mensaje de Meta ES el diagnostico.
falsa_api({"debug_token": {"_error": "Application request limit reached"}})
ig, motivo = instalar.verificar_token("tok")
assert ig is None and "limit reached" in motivo, f"tapo el error de Meta: {motivo}"

falsa_api({"debug_token": {"data": {"is_valid": True, "type": "PAGE", "expires_at": 0,
                                    "scopes": instalar.PERMISOS}},
           "me": {"_error": "Error validating access token"}})
ig, motivo = instalar.verificar_token("tok")
assert ig is None and "validating" in motivo, f"tapo el error de Meta: {motivo}"

# y un token que si sirve sigue devolviendo la cuenta
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "PAGE", "expires_at": 0,
                                    "scopes": instalar.PERMISOS}},
           "me": {"id": "152744", "name": "La Página",
                  "instagram_business_account": {"id": "17841400", "username": "cliente"}}})
assert instalar.verificar_token("tok") == ("17841400", "@cliente")


# ── el error de certificados se reconoce y se explica ───────────────────────
# El Python de python.org viene sin certificados raiz y corta TODA conexion segura.
# Si no se reconoce, la persona sale a buscar un token nuevo que no era el problema.
ssl_falso = Exception("<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate "
                      "verify failed: unable to get local issuer certificate>")
assert instalar.aviso_certificados(ssl_falso) is True
assert instalar.aviso_certificados(Exception("timed out")) is False, \
    "un problema de red comun no es de certificados"


# ── el paso 3 no pide lo que puede deducir ni lo que no necesita ────────────
PAGINA_CON_IG = {"id": "1", "name": "La Página",
                 "instagram_business_account": {"id": "17841400", "username": "cliente"}}
preguntas = []
original_preguntar, original_si_no = instalar.preguntar, instalar.si_no
instalar.preguntar = lambda t, defecto="": (preguntas.append(t.strip()), "TOKEN")[1]
instalar.si_no = lambda t, defecto=True: defecto

# a) token de Pagina que no vence: ya es el destino del canje. Pedir el App Secret
#    seria pedir una credencial para llegar a donde el token ya esta.
falsa_api({"app": {"id": "997"},
           "debug_token": {"data": {"is_valid": True, "type": "PAGE", "expires_at": 0,
                                    "scopes": instalar.PERMISOS}},
           "me": PAGINA_CON_IG})
cred = instalar.pedir_credenciales()
assert cred["IG_APP_ID"] == "997", "el App ID se deduce del token, no se pregunta"
assert cred["IG_PAGE_TOKEN"] == "TOKEN" and cred["IG_USER_ID"] == "17841400"
assert len(preguntas) == 1, f"con un token permanente alcanza con pedir el token: {preguntas}"

# b) token que vence: ahi si hace falta el App Secret, y el App ID sigue sin pedirse
preguntas.clear()
falsa_api({"app": {"id": "997"},
           "debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": AHORA + 3600,
                                    "scopes": instalar.PERMISOS}},
           "me/accounts": {"data": [{**PAGINA_CON_IG, "access_token": "PAGE_PERMANENTE"}]},
           "oauth/access_token": {"access_token": "USER_LARGO"}})
cred = instalar.pedir_credenciales()
assert "App Secret" in " ".join(preguntas), "un token que vence necesita el App Secret"
assert not any("App ID" in p for p in preguntas), "el App ID nunca se pregunta si se dedujo"

# c) si Meta no dice cual es el App ID, recien ahi se pregunta
preguntas.clear()
falsa_api({"app": {"_error": "vaya a saber"},
           "debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": AHORA + 3600,
                                    "scopes": instalar.PERMISOS}},
           "me/accounts": {"data": [{**PAGINA_CON_IG, "access_token": "PAGE_PERMANENTE"}]},
           "oauth/access_token": {"access_token": "USER_LARGO"}})
instalar.pedir_credenciales()
assert any("App ID" in p for p in preguntas), "sin deduccion hay que preguntarlo"

instalar.preguntar, instalar.si_no = original_preguntar, original_si_no

# ── el ID de la Pagina tambien se deduce, y su falta no puede reventar nada ──
# Sin FB_PAGE_ID el recolector se caia con KeyError en la primera corrida, despues
# de que la instalacion pareciera haber terminado bien.
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "PAGE", "expires_at": 0,
                                    "scopes": instalar.PERMISOS}},
           "me": {"id": "152744"}})
assert instalar.completar_page_id({"IG_PAGE_TOKEN": "tok"})["FB_PAGE_ID"] == "152744"

# con un token de Usuario hay que buscarla entre sus Paginas, y es la que tiene Instagram
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": AHORA + 3600, "scopes": []}},
           "me/accounts": {"data": [{"id": "sin-ig"},
                                    {"id": "152744", "instagram_business_account":
                                     {"id": "17841400"}}]}})
assert instalar.completar_page_id({"IG_PAGE_TOKEN": "tok"})["FB_PAGE_ID"] == "152744"

# y si ya venia cargado no se vuelve a preguntar a Meta
llamadas.clear()
assert instalar.completar_page_id({"IG_PAGE_TOKEN": "tok", "FB_PAGE_ID": "ya"})["FB_PAGE_ID"] == "ya"
assert not llamadas, "no hace falta ir a la API si el dato ya está"


# ── guardar_env no puede borrar credenciales buenas ─────────────────────────
# Reconfigurar salteando el App Secret no debe dejar al cliente sin el que tenia.
import os, tempfile
tmp = tempfile.mkdtemp()
instalar.ENV = os.path.join(tmp, ".env")
open(instalar.ENV, "w").write("IG_APP_SECRET=elbueno\nOTRA_COSA=intacta\n")
instalar.guardar_env({"IG_PAGE_TOKEN": "nuevo", "IG_APP_SECRET": "", "cuenta": "@x"})
guardado = dict(l.strip().split("=", 1) for l in open(instalar.ENV)
                if "=" in l and not l.startswith("#"))
assert guardado["IG_APP_SECRET"] == "elbueno", "un valor vacio no puede pisar uno bueno"
assert guardado["OTRA_COSA"] == "intacta", "no puede tocar credenciales de otras cosas"
assert guardado["IG_PAGE_TOKEN"] == "nuevo"
assert oct(os.stat(instalar.ENV).st_mode)[-3:] == "600", "el .env no puede quedar legible"

# ── el rescate cuando `me/accounts` viene vacio ─────────────────────────────
# Es el camino que salva una instalacion que si no terminaba en "no administras
# ninguna Pagina". Se prueba la funcion que hace el trabajo, no la conversacion.
PAGINA = {"name": "Quantum Coffee", "access_token": "PAGE_PERMANENTE",
          "instagram_business_account": {"id": "17841467", "username": "cliente"}}

falsa_api({"1287243731141950": PAGINA})
pag, err = instalar.pagina_por_id("USER_LARGO", "1287243731141950")
assert err is None and pag["token"] == "PAGE_PERMANENTE"
assert pag["ig_id"] == "17841467" and pag["cuenta"] == "@cliente"

# la URL de la Pagina tambien sirve: nadie tiene el ID a mano, pero si el link
falsa_api({"1287243731141950": PAGINA})
pag, err = instalar.pagina_por_id("USER_LARGO", "https://facebook.com/1287243731141950/")
assert err is None and pag["pagina"] == "Quantum Coffee"

# una Pagina sin Instagram vinculado NO puede darse por buena
falsa_api({"1287243731141950": {"name": "Pelada", "access_token": "T"}})
pag, err = instalar.pagina_por_id("USER_LARGO", "1287243731141950")
assert pag is None and "Instagram" in err

# si la cuenta no administra esa Pagina, Meta no devuelve token
falsa_api({"1287243731141950": {"name": "Ajena"}})
pag, err = instalar.pagina_por_id("USER_LARGO", "1287243731141950")
assert pag is None and "no la administra" in err

# un vanity name no sirve: `me/accounts` ya fallo, y por nombre no hay token
pag, err = instalar.pagina_por_id("USER_LARGO", "facebook.com/quantumcoffee")
assert pag is None and "solo números" in err

# el rescate solo se ofrece si el motivo es EXACTAMENTE ese: si alguien reescribe
# el texto de SIN_PAGINA sin tocar `pedir_credenciales`, esto lo caza.
falsa_api({"debug_token": {"data": {"is_valid": True, "type": "USER",
                                    "expires_at": 0, "scopes": instalar.PERMISOS}},
           "me/accounts": {"data": []}})
assert instalar.verificar_token("tok")[1] is instalar.SIN_PAGINA

# ── actualizar: lo que NO puede pasar es perder datos ───────────────────────
# El histórico es lo único irreversible del panel. Se arma un ZIP como el de GitHub
# (todo dentro de una carpeta) y se comprueba que el código se reemplace y los datos no.
import io, zipfile

destino = tempfile.mkdtemp()
instalar.AQUI = destino
open(os.path.join(destino, "historico.jsonl"), "w").write("MIS DATOS DE MESES")
open(os.path.join(destino, "recolector.py"), "w").write("version vieja")

crudo = io.BytesIO()
with zipfile.ZipFile(crudo, "w") as z:
    z.writestr("command-center-main/recolector.py", "version nueva")
    z.writestr("command-center-main/historico.jsonl", "BASURA QUE NO DEBE PISAR")
    z.writestr("command-center-main/piezas/logo.svg", "<svg/>")
crudo.seek(0)

instalar.urllib.request.urlopen = lambda *a, **k: io.BytesIO(crudo.getvalue())
assert instalar.actualizar() == 0

assert open(os.path.join(destino, "recolector.py")).read() == "version nueva", \
    "el codigo tiene que actualizarse"
assert open(os.path.join(destino, "historico.jsonl")).read() == "MIS DATOS DE MESES", \
    "el historico NO se puede pisar: esos dias no se pueden volver a pedir a la API"
assert os.path.exists(os.path.join(destino, "piezas", "logo.svg")), \
    "tiene que crear los subdirectorios que vengan en el zip"

# Un lanzador NUEVO tiene que llegar ejecutable: zipfile no restaura permisos y un
# .command sin el bit de ejecucion no hace nada al doble clic. Solo se nota con
# archivos nuevos, porque sobrescribir uno existente no le cambia el modo.
crudo2 = io.BytesIO()
with zipfile.ZipFile(crudo2, "w") as z:
    info = zipfile.ZipInfo("command-center-main/Lanzador.command")
    info.external_attr = 0o100755 << 16
    z.writestr(info, "#!/bin/bash\n")
crudo2.seek(0)
instalar.urllib.request.urlopen = lambda *a, **k: io.BytesIO(crudo2.getvalue())
assert instalar.actualizar() == 0
assert os.access(os.path.join(destino, "Lanzador.command"), os.X_OK), \
    "un .command nuevo tiene que quedar ejecutable"

# Y el caso que se escapo la primera vez: contenido YA correcto pero permisos rotos.
# Como no hay nada que reescribir, es el unico que no se arregla solo salvo que se
# revisen los permisos aunque el archivo no cambie.
os.chmod(os.path.join(destino, "Lanzador.command"), 0o644)
crudo2.seek(0)
instalar.urllib.request.urlopen = lambda *a, **k: io.BytesIO(crudo2.getvalue())
assert instalar.actualizar() == 0
assert os.access(os.path.join(destino, "Lanzador.command"), os.X_OK), \
    "un lanzador con permisos rotos tiene que repararse aunque su contenido este bien"

# una descarga fallida no puede dejar la instalacion a medias
def explota(*a, **k):
    raise instalar.urllib.error.URLError("sin internet")
instalar.urllib.request.urlopen = explota
assert instalar.actualizar() == 1
assert open(os.path.join(destino, "recolector.py")).read() == "version nueva", \
    "si falla la descarga, no se toca nada"

print("OK — todos los checks pasaron")
