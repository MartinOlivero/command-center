#!/usr/bin/env python3
"""
ia.py — El único lugar del panel que le habla a un modelo.

POR QUÉ EXISTE
Había cuatro `subprocess.run(["claude", "-p", ...])` sueltos (dos en analista.py, dos
en servidor.py). Cada uno repetía el manejo de errores y todos daban por sentado que
en esa máquina existe el comando `claude`. En la tuya existe; en la de quien descargue
esto, no necesariamente.

LOS DOS CAMINOS
  1. `claude -p`  — usa Claude Code, que la persona ya tiene instalado y logueado con
     SU suscripción. No cuesta un centavo extra. Es el camino por defecto.
  2. API key      — si en el .env hay ANTHROPIC_API_KEY, se le pega directo a la API.
     Se paga por uso (centavos por análisis) pero no requiere Claude Code y sirve para
     dejarlo corriendo solo, sin nadie sentado en la máquina.

Se elige con IA_MODO en el .env:
    IA_MODO=auto     (por defecto) usa `claude` si está instalado; si no, la API key
    IA_MODO=claude   forzar Claude Code
    IA_MODO=api      forzar API key

OTRO PROVEEDOR QUE NO SEA ANTHROPIC
Con ANTHROPIC_BASE_URL en el .env se apunta a cualquier proveedor que hable el mismo
formato de pedido. Kimi (Moonshot) es el caso probado:

    ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic
    ANTHROPIC_AUTH_TOKEN=<tu key de Moonshot>
    ANTHROPIC_MODEL=kimi-k2.7-code

Dos advertencias, porque acá no hay garantías de nadie:
  - OpenAI NO entra por esta puerta. Habla otro idioma (otro formato de pedido y de
    respuesta), no alcanza con cambiar la dirección.
  - Moonshot no publica el contrato de ese endpoint, así que puede cambiar sin aviso.
    Con Anthropic, que sí lo publica, esto no pasa.

SIN LIBRERÍAS
Todo el panel es Python de la biblioteca estándar: se descarga y anda, sin instalar
nada. Por eso la llamada HTTP va con urllib y no con el SDK de Anthropic — meter una
dependencia obligaría a resolver paquetes en la máquina de un desconocido, que es
exactamente el paso donde se traba una instalación.

USO
    import ia
    texto = ia.preguntar(prompt)          # devuelve el texto del modelo
    datos = ia.preguntar_json(prompt)     # además le saca el JSON de adentro

Autochequeo:
    python3 ia.py
"""

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(AQUI, ".env")

# Se puede cambiar en el .env con ANTHROPIC_MODEL. El default es el Opus más nuevo:
# estos prompts son de análisis y criterio, no de completar texto, y ahí la diferencia
# entre modelos se nota en la calidad de lo que devuelve.
MODELO_DEFECTO = "claude-opus-5"

# A dónde se le habla. Se puede apuntar a otro proveedor con ANTHROPIC_BASE_URL en el
# .env — es la MISMA variable que usan el SDK y el CLI oficiales de Anthropic, así que
# quien ya la tenga puesta para otra cosa no tiene que aprender un nombre nuevo.
# Sirve para cualquier proveedor que hable el formato de Anthropic (Moonshot/Kimi
# publica https://api.moonshot.ai/anthropic; DeepSeek tiene el suyo). NO sirve para
# OpenAI, que usa otro formato de pedido y de respuesta.
BASE_DEFECTO = "https://api.anthropic.com"


def _url(env):
    """El endpoint de mensajes, con la base que corresponda.

    Se le saca la barra final porque una URL con doble barra (`.../anthropic//v1/...`)
    da 404 en algunos proveedores, y es un error carísimo de diagnosticar.
    """
    return (env.get("ANTHROPIC_BASE_URL") or BASE_DEFECTO).rstrip("/") + "/v1/messages"


def _env():
    """El .env como diccionario, con el entorno real pisando al archivo.

    Que el entorno gane permite probar una credencial suelta sin tocar el archivo:
        ANTHROPIC_API_KEY=sk-ant-... python3 analista.py
    """
    datos = {}
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if "=" in linea and not linea.startswith("#"):
                    k, v = linea.split("=", 1)
                    datos[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
              "ANTHROPIC_MODEL", "IA_MODO"):
        if os.environ.get(k):
            datos[k] = os.environ[k]
    return datos


# Dónde puede estar `claude` además del PATH. Sale de la documentación oficial
# (code.claude.com/docs/en/setup): el instalador nativo lo deja en ~/.local/bin, npm y
# Homebrew lo enlazan en su carpeta de binarios, y los paquetes de Linux en /usr/bin.
#
# Por qué no alcanza con el PATH: un panel abierto con doble clic en el ícono NO pasa
# por la terminal, y macOS le da a esa app un PATH mínimo —/usr/bin:/bin:/usr/sbin:
# /sbin— sin nada de lo que agrega el .zshrc. Medido el 21/08/2026 en la máquina de
# Tincho: `claude` en ~/.local/bin, el panel con ese PATH pelado, y el resultado era
# "no encontré Claude Code" en una máquina que lo tiene instalado y funcionando.
# El binario anda igual con ese PATH (es nativo, no necesita node): solo hay que
# encontrarlo.
_CASA = os.path.expanduser("~")
CANDIDATOS_CLI = ([
    # Windows: instalador nativo, y el .cmd que deja npm.
    os.path.join(_CASA, ".local", "bin", "claude.exe"),
    os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
] if os.name == "nt" else [
    os.path.join(_CASA, ".local", "bin", "claude"),      # instalador nativo
    os.path.join(_CASA, ".claude", "local", "claude"),   # instalación local vieja
    os.path.join(_CASA, ".npm-global", "bin", "claude"),
    "/opt/homebrew/bin/claude",                          # Homebrew en Apple Silicon
    "/usr/local/bin/claude",                             # Homebrew Intel, y npm global
    "/usr/bin/claude",                                   # apt / dnf / apk
])


def buscar_cli(env=None):
    """La ruta del comando `claude`, o None si no está en ningún lado conocido.

    Se puede fijar con CLAUDE_BIN en el .env, para una instalación en un lugar que no
    adivinamos. Devolver la RUTA y no un sí/no es lo que arregla el problema: con el
    PATH pelado, invocar "claude" a secas falla aunque lo hayamos encontrado.
    """
    forzado = (env or {}).get("CLAUDE_BIN") or os.environ.get("CLAUDE_BIN")
    if forzado:
        forzado = os.path.expanduser(forzado)
        return forzado if os.path.exists(forzado) else None
    return shutil.which("claude") or next(
        (r for r in CANDIDATOS_CLI if r and os.path.exists(r) and os.access(r, os.X_OK)),
        None)


def _elegir_modo(env, hay_cli=None):
    """Qué camino usar, y por qué. Devuelve 'claude' o 'api', o revienta explicando.

    `hay_cli` se puede forzar para poder probar esta decisión en cualquier máquina:
    si mirara siempre el disco, el resultado del test dependería de si quien lo corre
    tiene Claude Code instalado, que es justo lo que la función tiene que abstraer.
    """
    modo = (env.get("IA_MODO") or "auto").lower()
    if hay_cli is None:
        hay_cli = bool(buscar_cli(env))
    # Dos nombres para lo mismo, igual que en el SDK oficial: los proveedores
    # compatibles suelen autenticar con un token Bearer en vez de una API key.
    hay_key = bool(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"))

    if modo == "claude":
        if not hay_cli:
            raise RuntimeError(
                "IA_MODO=claude pero no encuentro el comando `claude`.\n"
                "  Instalalo con:  npm i -g @anthropic-ai/claude-code\n"
                "  (o sacá IA_MODO del .env para que use la API key)")
        return "claude"

    if modo == "api":
        if not hay_key:
            raise RuntimeError(
                "IA_MODO=api pero no hay ANTHROPIC_API_KEY en el .env.\n"
                "  Sacá una en console.anthropic.com > API Keys")
        return "api"

    # auto: lo gratis primero.
    if hay_cli:
        return "claude"
    if hay_key:
        return "api"
    raise RuntimeError(
        "Las funciones con IA necesitan una de estas dos cosas, y no encontré ninguna:\n"
        "  a) Claude Code instalado:  npm i -g @anthropic-ai/claude-code\n"
        "     (usa tu suscripción de Claude, no cuesta nada extra)\n"
        "  b) Una API key en el .env:  ANTHROPIC_API_KEY=sk-ant-...\n"
        "     (se paga por uso, unos centavos por análisis)\n"
        "El resto del panel funciona igual sin esto.")


# Lo único que va como argumento de la línea de comandos. El prompt entero —que lleva
# los datos del panel adentro— viaja por la entrada estándar, donde no hay límite de
# tamaño. `claude -p` pide una consigna como argumento y lee lo pipeado como contexto:
# está documentado (code.claude.com/docs/en/cli-reference, `cat archivo | claude -p`) y
# probado contra el CLI el 21/08/2026.
CONSIGNA = "Segui al pie de la letra las instrucciones que vienen en la entrada."


def _por_cli(prompt, timeout, binario=None):
    """El prompt por stdin, y en Windows sin abrir una ventana.

    Las dos cosas son por Windows, y ninguna se ve en macOS:

    - La línea de comandos de Windows se corta en 8191 caracteres. Estos prompts
      llevan los datos del panel adentro: el de una cuenta con historia pasa los
      20.000. Como argumento se romperían; por stdin no hay límite.
    - Un proceso de consola lanzado desde el panel —que corre sin consola, con
      pythonw.exe— abre una ventana negra por cada llamada al modelo. Peor que fea:
      como no dice nada, la persona la cierra, y al cerrarla se lleva puesto el
      análisis que estaba corriendo ahí adentro.
    """
    extra = {}
    if os.name == "nt":
        # Una consola PROPIA pero OCULTA, y no "ninguna consola".
        #
        # Probado con un cliente en Windows el 21/08/2026: `claude -p` contesta al
        # instante desde una terminal y se cuelga para siempre —sin error, sin salida—
        # lanzado desde el panel. La diferencia entre los dos casos no es el prompt ni
        # la version del CLI (se descarto actualizando a 2.1.238): es que el panel corre
        # con pythonw.exe, que no tiene consola, y `claude` es Node, que si la busca.
        #
        # CREATE_NO_WINDOW deja al hijo sin ninguna. CREATE_NEW_CONSOLE le da una suya,
        # y SW_HIDE hace que no se vea: tiene donde apoyarse y la persona no ve nada.
        # La salida sigue viniendo por los pipes de capture_output, no por esa consola.
        oculta = subprocess.STARTUPINFO()
        oculta.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        oculta.wShowWindow = subprocess.SW_HIDE
        extra["startupinfo"] = oculta
        extra["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    try:
        # La RUTA, no el nombre: con el PATH pelado de una app de escritorio,
        # "claude" a secas no se resuelve aunque el binario exista.
        r = subprocess.run([binario or "claude", "-p", CONSIGNA], input=prompt,
                           capture_output=True, text=True,
                           # Sin esto Windows decodifica la respuesta con la codepage
                           # local, y todo lo que devuelve el modelo viene en español.
                           encoding="utf-8", errors="replace",
                           timeout=timeout, **extra)
    except subprocess.TimeoutExpired:
        # Se traduce acá y no se deja subir: `TimeoutExpired` no es RuntimeError, así
        # que se escapaba de quien atrapa los errores y la persona terminaba viendo
        # media línea del `subprocess.py` de Python en la pantalla del panel.
        raise RuntimeError(
            f"Claude Code no contestó en {timeout} segundos. No es que tardó: no "
            "contestó nunca. Abrí una terminal en esta carpeta y probá "
            '`claude -p "hola"` a mano — si ahí también se queda colgado, el '
            "problema es del CLI y no del panel.") from None
    except FileNotFoundError:
        raise RuntimeError(
            "No encontré el comando `claude`. Instalalo con "
            "`npm i -g @anthropic-ai/claude-code`, o poné una ANTHROPIC_API_KEY "
            "en el .env para no depender de él.") from None
    if r.returncode != 0:
        raise RuntimeError(f"el CLI de Claude falló: {(r.stderr or '').strip()[:300]}")
    return r.stdout.strip()


def _cabeceras(env):
    """Los headers del pedido, con la credencial que haya.

    Anthropic autentica con `x-api-key`; los proveedores compatibles (Moonshot/Kimi,
    DeepSeek) usan `Authorization: Bearer`. Se manda UNA sola: mandar las dos hace que
    la API de Anthropic rechace el pedido. `anthropic-version` va siempre — Anthropic
    lo exige y los compatibles lo ignoran.
    """
    cab = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if env.get("ANTHROPIC_AUTH_TOKEN"):
        cab["authorization"] = "Bearer " + env["ANTHROPIC_AUTH_TOKEN"]
    else:
        cab["x-api-key"] = env["ANTHROPIC_API_KEY"]
    return cab


def _por_api(prompt, timeout, env):
    cuerpo = json.dumps({
        "model": env.get("ANTHROPIC_MODEL", MODELO_DEFECTO),
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    pedido = urllib.request.Request(_url(env), data=cuerpo, headers=_cabeceras(env))
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            datos = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            pass
        if e.code == 401:
            raise RuntimeError("la ANTHROPIC_API_KEY del .env no es válida") from None
        if e.code == 429:
            raise RuntimeError("la API está limitando por uso. Probá en un rato") from None
        raise RuntimeError(f"la API devolvió HTTP {e.code}: {detalle[:200]}") from None

    # Un rechazo por políticas vuelve con HTTP 200 y el contenido vacío: si no se
    # chequea acá, más adelante explota con un "no devolvió JSON" que no explica nada.
    if datos.get("stop_reason") == "refusal":
        raise RuntimeError("el modelo rechazó el pedido por sus políticas de uso")

    # Si se quedó sin presupuesto de salida, el texto viene cortado a la mitad y el JSON
    # que sigue queda inválido. Sin este aviso, el error que ve la persona es "la IA no
    # devolvió JSON", que manda a buscar el problema al lado equivocado.
    if datos.get("stop_reason") == "max_tokens":
        raise RuntimeError(
            "la respuesta se cortó por largo (max_tokens). Suele pasar con prompts muy "
            "grandes: probá con menos días de historia, o subí max_tokens en ia.py")

    # El contenido puede traer bloques de razonamiento además del texto; nos quedamos
    # solo con el texto.
    partes = [b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text"]
    if not partes:
        raise RuntimeError("la API no devolvió texto")
    return "".join(partes).strip()


# Cuánto se le da al modelo para contestar, y cuánto tiene que esperarlo quien lanza
# al analista como subproceso. La relación entre los dos es lo importante: el de
# afuera SIEMPRE mayor que el de adentro.
#
# Medido en la instalación de un cliente el 21/08/2026: el análisis tardó 333s de
# punta a punta (panel escrito 13:51:05, análisis 13:56:38). El servidor esperaba
# 330 y el modelo tenía techo 300, así que la carrera se perdía por segundos: el
# padre mataba al analista justo antes de que terminara, se tiraba a la basura el
# trabajo del modelo ya hecho y encima ganaba el mensaje genérico del servidor
# ("la IA tardó demasiado") en vez del que explica qué pasó.
#
# 420 porque 300 no alcanzaba en una cuenta real, y MARGEN porque el hijo no es solo
# la llamada al modelo: antes arranca Python, lee panel.html y levanta el CLI (Node),
# y después escribe el JSON. Ese tiempo también hay que esperarlo.
TIMEOUT = 420
MARGEN = 60


def preguntar(prompt, timeout=TIMEOUT):
    """Le pasa el prompt al modelo y devuelve su texto. Lanza RuntimeError si algo falla."""
    env = _env()
    modo = _elegir_modo(env)
    return (_por_cli(prompt, timeout, buscar_cli(env)) if modo == "claude"
            else _por_api(prompt, timeout, env))


def extraer_json(texto):
    """Saca el objeto JSON de una respuesta, aunque venga envuelto en ```json.

    Los modelos a veces explican antes del JSON y a veces lo encierran en un bloque de
    código. Las dos cosas son respuestas correctas; el que tiene que adaptarse es el
    que lee, no el que escribe.
    """
    m = (re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
         or re.search(r"(\{.*\})", texto, re.S))
    if not m:
        raise RuntimeError(f"la IA no devolvió JSON. Respuesta:\n{texto[:400]}")
    return json.loads(m.group(1))


def preguntar_json(prompt, timeout=TIMEOUT):
    """`preguntar` + `extraer_json`, que es lo que hacen los cuatro llamadores."""
    return extraer_json(preguntar(prompt, timeout))


def disponible():
    """¿Se puede usar IA en esta máquina? Para apagar botones en vez de que fallen."""
    try:
        _elegir_modo(_env())
        return True
    except RuntimeError:
        return False


def _autochequeo():
    # El JSON se encuentra venga como venga.
    assert extraer_json('```json\n{"a": 1}\n```')["a"] == 1
    assert extraer_json('Acá va:\n{"a": 2}\nlisto')["a"] == 2
    assert extraer_json('{"a": {"b": 3}}')["a"]["b"] == 3
    try:
        extraer_json("no hay json acá")
        raise AssertionError("tendría que haber fallado sin JSON")
    except RuntimeError:
        pass

    # La elección de camino, probada sin depender de qué haya instalado en ESTA máquina.
    con_cli, sin_cli = True, False
    assert _elegir_modo({}, con_cli) == "claude", "con Claude Code tiene que usar lo gratis"
    assert _elegir_modo({"ANTHROPIC_API_KEY": "sk-x"}, con_cli) == "claude", \
        "teniendo las dos, primero lo que no cuesta"
    assert _elegir_modo({"ANTHROPIC_API_KEY": "sk-x"}, sin_cli) == "api"
    assert _elegir_modo({"IA_MODO": "api", "ANTHROPIC_API_KEY": "sk-x"}, con_cli) == "api", \
        "IA_MODO=api tiene que ganarle al default"
    assert _elegir_modo({"IA_MODO": "claude"}, con_cli) == "claude"
    assert _elegir_modo({"ANTHROPIC_AUTH_TOKEN": "tok"}, sin_cli) == "api", \
        "un token Bearer también es credencial válida"

    # El prompt viaja por stdin, NUNCA como argumento: la línea de comandos de Windows
    # se corta en 8191 caracteres y estos prompts la pasan largo apenas la cuenta tiene
    # algo de historia. Se prueba sin llamar al CLI de verdad.
    visto = {}
    real = subprocess.run

    def espia(cmd, **kw):
        visto.update(cmd=cmd, kw=kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    subprocess.run = espia
    try:
        _por_cli("x" * 30000, 5)
    finally:
        subprocess.run = real
    assert max(len(a) for a in visto["cmd"]) < 200, \
        "el prompt no puede ir como argumento: Windows lo corta en 8191"
    assert visto["kw"]["input"] == "x" * 30000, "el prompt tiene que ir por stdin"
    assert visto["kw"]["encoding"] == "utf-8", "la respuesta del modelo viene en español"

    # Un CLI que no contesta y uno que no está tienen que salir por la misma puerta que
    # el resto de los errores: quien llama atrapa RuntimeError. Antes se escapaban, y
    # la persona veía media línea del subprocess.py de Python en el panel.
    for explota, pista in ((subprocess.TimeoutExpired("claude", 1), "no contestó"),
                           (FileNotFoundError(), "npm i -g")):
        def revienta(cmd, **kw):
            raise explota

        subprocess.run = revienta
        try:
            _por_cli("hola", 1)
            raise AssertionError(f"tendría que haber fallado con {type(explota).__name__}")
        except RuntimeError as e:
            assert pista in str(e), f"el error no dice qué hacer: {e}"
        finally:
            subprocess.run = real

    # La dirección: por defecto Anthropic, y sin barras dobles al apuntar a otro lado.
    assert _url({}) == "https://api.anthropic.com/v1/messages"
    assert _url({"ANTHROPIC_BASE_URL": "https://api.moonshot.ai/anthropic"}) == \
        "https://api.moonshot.ai/anthropic/v1/messages"
    assert _url({"ANTHROPIC_BASE_URL": "https://api.moonshot.ai/anthropic/"}) == \
        "https://api.moonshot.ai/anthropic/v1/messages", "la barra final no puede duplicarse"

    # La credencial: una sola, nunca las dos (mandar ambas hace que Anthropic rechace).
    solo_key = _cabeceras({"ANTHROPIC_API_KEY": "sk-ant-x"})
    assert solo_key["x-api-key"] == "sk-ant-x" and "authorization" not in solo_key
    solo_tok = _cabeceras({"ANTHROPIC_AUTH_TOKEN": "tok"})
    assert solo_tok["authorization"] == "Bearer tok" and "x-api-key" not in solo_tok
    ambas = _cabeceras({"ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_AUTH_TOKEN": "tok"})
    assert "x-api-key" not in ambas, "con las dos, gana el token y se manda una sola"
    assert all(c["anthropic-version"] == "2023-06-01" for c in (solo_key, solo_tok))

    # Y los tres callejones sin salida avisan qué hacer, no explotan con un stacktrace.
    for malo, cli, pista in (({"IA_MODO": "api"}, con_cli, "console.anthropic.com"),
                             ({"IA_MODO": "claude"}, sin_cli, "claude-code"),
                             ({}, sin_cli, "ANTHROPIC_API_KEY")):
        try:
            _elegir_modo(malo, cli)
            raise AssertionError(f"tendría que haber fallado con {malo}")
        except RuntimeError as e:
            assert pista in str(e), f"el error no dice cómo arreglarlo: {e}"

    # El PATH pelado de una app de escritorio no puede dejar sin IA a una máquina que
    # tiene el CLI instalado. Se simula con un binario propio en una carpeta candidata.
    import tempfile
    falso = os.path.join(tempfile.mkdtemp(), "claude")
    open(falso, "w", encoding="utf-8").close()
    os.chmod(falso, 0o755)
    guardados = (CANDIDATOS_CLI[:], os.environ.get("PATH"), os.environ.pop("CLAUDE_BIN", None))
    try:
        CANDIDATOS_CLI[:] = [falso]
        os.environ["PATH"] = "/usr/bin:/bin"          # el que da macOS al abrir por ícono
        assert shutil.which("claude") is None, "el PATH de prueba no quedó pelado"
        assert buscar_cli() == falso, "con el PATH pelado hay que ir a buscarlo igual"
        assert _elegir_modo({}) == "claude", "una máquina con el CLI se quedó sin IA"
        # Y lo que se declara a mano gana, aunque no exista nada mas.
        CANDIDATOS_CLI[:] = []
        assert buscar_cli({"CLAUDE_BIN": falso}) == falso, "ignoró CLAUDE_BIN del .env"
        assert buscar_cli({"CLAUDE_BIN": "/no/existe"}) is None, "acepto una ruta que no existe"
    finally:
        CANDIDATOS_CLI[:], os.environ["PATH"] = guardados[0], guardados[1]
        if guardados[2]:
            os.environ["CLAUDE_BIN"] = guardados[2]
        os.remove(falso)

    print("ia.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
