#!/usr/bin/env python3
"""
entorno.py — Leer el `.env`. Un solo lugar, una sola vez.

POR QUÉ EXISTE
Cuatro archivos del panel abrían el `.env` por su cuenta, cada uno con su propia
versión de "sacale las comillas" y "el entorno pisa al archivo". Mientras el panel
corría en una sola máquina eso no molestaba. Cuando el panel se distribuye, sí:
cada copia es un lugar donde puede faltar un caso (una comilla simple, una línea
comentada, un espacio antes del =) y donde una credencial puede terminar leída a
medias sin que nadie se entere hasta que la API contesta 401.

QUÉ NO HACE
No valida ni exige nada. Devolver el archivo tal como está es su único trabajo;
quién necesita qué variable lo decide cada módulo, porque cada uno enciende una
función distinta y ninguna es obligatoria para todas.

USO
    import entorno
    entorno.leer()["IG_PAGE_TOKEN"]
    entorno.valor("ANTHROPIC_MODEL", "claude-opus-5")

Autochequeo:
    python3 entorno.py
"""

import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(AQUI, ".env")


def leer(ruta=RUTA):
    """El `.env` como diccionario. Vacío si no existe: la ausencia de credenciales
    apaga funciones, no rompe el panel.

    Lo que esté en el entorno real le gana al archivo. Sirve para probar una
    credencial suelta sin editar nada:
        IG_PAGE_TOKEN=EAA... python3 recolector.py
    """
    datos = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, v = linea.split("=", 1)
                datos[k.strip()] = v.strip().strip('"').strip("'")
    # Solo las claves que ya conocemos: copiar el entorno entero metería PATH y
    # medio sistema en un diccionario que después se imprime en los diagnósticos.
    for k in list(datos) + CONOCIDAS:
        if os.environ.get(k):
            datos[k] = os.environ[k]
    return datos


# Las variables que el panel entiende. Están acá para que `leer()` las tome del
# entorno aunque no estén en el archivo, y para que .env.example y esta lista se
# puedan comparar de un vistazo.
CONOCIDAS = [
    "IG_PAGE_TOKEN", "IG_USER_ID", "IG_APP_ID", "IG_APP_SECRET",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL", "IA_MODO",
    "META_ADS_TOKEN", "META_ADS_TOKEN_FILE", "META_ADS_TOKEN_KEY",
    "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT",
    "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_TOKEN_FILE",
    "POSTIZ_URL", "POSTIZ_TOKEN",
    "PUERTO",
]


def valor(clave, defecto=""):
    """Una sola variable, con valor por defecto."""
    return leer().get(clave) or defecto


def _autochequeo():
    import tempfile

    tmp = os.path.join(tempfile.mkdtemp(), ".env")

    # Un .env que no existe no puede tirar abajo nada.
    assert leer(tmp) == {}

    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# un comentario\n"
                "SIMPLE=valor\n"
                'CON_COMILLAS="entre comillas"\n'
                "CON_SIMPLES='simples'\n"
                "  ESPACIADA  =  con espacios  \n"
                "\n"
                "CON_IGUAL=a=b=c\n"
                "SIN_IGUAL\n")
    d = leer(tmp)
    assert d["SIMPLE"] == "valor"
    assert d["CON_COMILLAS"] == "entre comillas", "no sacó las comillas dobles"
    assert d["CON_SIMPLES"] == "simples", "no sacó las comillas simples"
    assert d["ESPACIADA"] == "con espacios", "no limpió los espacios alrededor del ="
    assert d["CON_IGUAL"] == "a=b=c", "cortó en el primer = en vez del último valor"
    assert "SIN_IGUAL" not in d and "# un comentario" not in d

    # El entorno real le gana al archivo (probar una credencial sin editar nada).
    os.environ["SIMPLE"] = "del entorno"
    try:
        assert leer(tmp)["SIMPLE"] == "del entorno", "el archivo le ganó al entorno"
    finally:
        del os.environ["SIMPLE"]

    print("entorno.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
