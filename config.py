#!/usr/bin/env python3
"""
config.py — La configuración de esta instalación del panel.

POR QUÉ EXISTE
Hasta ahora el panel estaba cableado a una cuenta: el nombre en el header, el handle en
las piezas, las palabras clave de los CTAs, y el supuesto de que existen tres redes y un
Postiz. Para instalarlo en un cliente había que ir a buscar esas cosas por cinco archivos.

Ahora todo eso vive en `config.json`, al lado del panel. Si el archivo no existe, se usan
los valores de abajo y el panel funciona igual que siempre: no hay que crear nada para que
ande, solo para que sea de otro.

QUÉ NO VA ACÁ
Ningún secreto. Los tokens siguen en el `.env` (que no se versiona) o en el archivo al que
ese `.env` apunte. `config.json` es lo que se puede leer sin peligro: nombres, colores, qué
redes mostrar.

USO
    import config
    cfg = config.cargar()
    cfg["marca"]["organizacion"]     # "MI MARCA"
    config.red_activa(cfg, "facebook")
    cfg["ctas"]                      # ["PANEL", "INFO"]

Autochequeo:
    python3 config.py
"""

import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(AQUI, "config.json")

# El nombre del producto, separado del nombre del negocio. En la barra van uno
# arriba del otro y con jerarquía distinta: el negocio es de quién es, esto es qué es.
# Juntos y del mismo tamaño se leían como un solo nombre raro.
PRODUCTO = "COMMAND CENTER"

# Versión del paquete. Se muestra en el panel y en el instalador: es lo primero que hay
# que preguntar cuando alguien reporta un problema, y lo que compara `--actualizar`.
VERSION = "1.0.0"

# Lo que se usa cuando no hay config.json (o cuando le falta una clave). Es también la
# documentación de qué se puede configurar: si algo no está acá, no es configurable.
DEFECTOS = {
    "marca": {
        "organizacion": "MI MARCA",     # lo grande del header
        "cuenta": "@micuenta",          # el handle chico, y el pie de las piezas
        "acento": "#22d3ee",
        # De qué se trata el negocio y para quién. Va dentro de los prompts de IA:
        # sin esto el análisis habla de "tu cuenta" en abstracto y las ideas de
        # contenido salen genéricas. Es el dato que más cambia la calidad de lo
        # que devuelve el modelo, y el único que no se puede deducir de la API.
        "descripcion": "una marca que hace contenido en redes sociales",
    },
    # Una red en false desaparece del panel. NO se muestra vacía ni con un error:
    # un panel que dice "Facebook: 0" cuando el cliente no tiene Facebook parece roto.
    # TikTok arranca APAGADO: necesita una autorización por navegador que el resto
    # no necesita, y un panel ya instalado no puede estrenar una tarjeta rota.
    "redes": {"instagram": True, "facebook": True, "youtube": True, "tiktok": False},
    # Calendario editorial. La mayoría de los clientes no va a tener Postiz.
    "postiz": {"activo": True},
    # Las palabras clave de tus CTAs ("comentá X y te lo mando"). Si falta una, esos
    # comentarios se cuentan como leads calientes en vez de como gente esperando.
    # Las carga el instalador; vacío es un valor válido (no todos usan CTAs).
    "ctas": [],
    # A quién mirar. Conviene gente de tu tamaño o un escalón arriba: una cuenta
    # de 900k juega otro juego y su "mediana" no dice nada sobre la tuya.
    # Instagram SOLO lee cuentas Business o Creator (una personal da "Invalid user id").
    # Se agregan desde el panel, en la pantalla de Competencia.
    "competencia": {
        "instagram": [],
        "youtube": [],
    },
    "dias": 30,
}


def _fusionar(base, encima):
    """Mezcla dos niveles de diccionario. Lo que falte en `encima` se toma de `base`,
    así un config.json a medio escribir no rompe nada."""
    salida = {}
    for k, v in base.items():
        if isinstance(v, dict) and isinstance(encima.get(k), dict):
            salida[k] = {**v, **encima[k]}
        else:
            salida[k] = encima.get(k, v)
    # Claves que agregó el usuario y no conocemos: se respetan igual.
    for k, v in encima.items():
        salida.setdefault(k, v)
    return salida


def cargar(ruta=RUTA):
    """La configuración efectiva. Nunca falla: si el archivo está roto, avisa y sigue
    con los valores por defecto — quedarse sin panel por una coma de más sería peor."""
    if not os.path.exists(ruta):
        return dict(DEFECTOS)
    try:
        with open(ruta, encoding="utf-8") as f:
            return _fusionar(DEFECTOS, json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  aviso: {os.path.basename(ruta)} no se pudo leer ({e}). Uso los valores por defecto.")
        return dict(DEFECTOS)


def red_activa(cfg, red):
    """¿Hay que mostrar esta red? Una red que no está declarada se considera activa,
    para que un config viejo no haga desaparecer datos sin avisar."""
    return bool(cfg.get("redes", {}).get(red, True))


def marca_para_prompt(cfg=None):
    """Quién es el dueño de estas cuentas, en una frase, para meter en los prompts.

    Los tres prompts de IA del panel arrancaban nombrando a una marca concreta
    escrita a mano. Eso hacía dos cosas malas a la vez: ataba el código a una
    cuenta, y —más caro— hacía que el modelo analizara los datos de cualquiera
    creyendo que eran de otro negocio, con lo cual las recomendaciones salían del
    nicho equivocado.
    """
    cfg = cfg or cargar()
    m = cfg.get("marca", {})
    nombre = m.get("organizacion") or "esta marca"
    cuenta = m.get("cuenta") or ""
    desc = m.get("descripcion") or ""
    quien = f"{nombre} ({cuenta})" if cuenta else nombre
    return f"{quien}, {desc}" if desc else quien


def guardar(cfg, ruta=RUTA):
    """Escribe la configuración. Lo usa el instalador."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return ruta


def _autochequeo():
    import tempfile

    tmp = os.path.join(tempfile.mkdtemp(), "c.json")

    # Sin archivo, todo por defecto y el panel anda igual que siempre.
    c = cargar(tmp)
    assert c["marca"]["organizacion"] == "MI MARCA" and c["dias"] == 30
    assert red_activa(c, "facebook") is True
    # Los defectos no pueden traer datos de nadie: es código que se publica.
    assert c["ctas"] == [] and c["competencia"]["instagram"] == []

    # Un config parcial no puede borrar lo que no menciona.
    guardar({"marca": {"organizacion": "PANADERÍA LA ESQUINA"},
             "redes": {"facebook": False}}, tmp)
    c = cargar(tmp)
    assert c["marca"]["organizacion"] == "PANADERÍA LA ESQUINA"
    assert c["marca"]["acento"] == "#22d3ee", "perdió el acento al fusionar"
    assert c["dias"] == 30, "perdió una clave que el config no mencionaba"
    assert red_activa(c, "facebook") is False, "no respetó la red apagada"
    assert red_activa(c, "instagram") is True, "apagó una red que no se pidió apagar"
    # Una red que el config no nombra sigue activa: no hacemos desaparecer datos solos.
    assert red_activa({"redes": {}}, "youtube") is True

    # Un JSON roto no puede dejar sin panel a nadie.
    with open(tmp, "w") as f:
        f.write("{esto no es json")
    assert cargar(tmp)["dias"] == 30, "un config roto tiró abajo la configuración entera"

    print("config.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
