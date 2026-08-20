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


def _elegir_modo(env, hay_cli=None):
    """Qué camino usar, y por qué. Devuelve 'claude' o 'api', o revienta explicando.

    `hay_cli` se puede forzar para poder probar esta decisión en cualquier máquina:
    si mirara siempre el disco, el resultado del test dependería de si quien lo corre
    tiene Claude Code instalado, que es justo lo que la función tiene que abstraer.
    """
    modo = (env.get("IA_MODO") or "auto").lower()
    if hay_cli is None:
        hay_cli = bool(shutil.which("claude"))
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


def _por_cli(prompt, timeout):
    r = subprocess.run(["claude", "-p", prompt],
                       capture_output=True, text=True, timeout=timeout)
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


def preguntar(prompt, timeout=300):
    """Le pasa el prompt al modelo y devuelve su texto. Lanza RuntimeError si algo falla."""
    env = _env()
    modo = _elegir_modo(env)
    return _por_cli(prompt, timeout) if modo == "claude" else _por_api(prompt, timeout, env)


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


def preguntar_json(prompt, timeout=300):
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

    print("ia.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
