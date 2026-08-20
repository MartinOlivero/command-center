#!/usr/bin/env python3
"""
historico.py — Guarda una foto de las métricas en cada corrida del recolector.

POR QUÉ EXISTE
El panel te dice "826 guardados". Eso es un número, no una señal. Recién sirve cuando
podés decir "826 guardados, 40% arriba de tu promedio". La diferencia es la misma que
entre "tenés 38 de fiebre" y "tenés 38, y ayer tenías 36,5".

Hasta ahora el recolector pisaba panel.html en cada corrida y el dato de ayer se perdía
para siempre. Esto arregla eso: cada corrida agrega UNA línea a historico.jsonl y nunca
se borra nada.

QUÉ SE GUARDA Y QUÉ NO
Los datos del panel llevan fotos de perfil y miniaturas en base64: son el 95% del peso y
no se comparan con nada. Se podan. Queda solo lo numérico: medido sobre la cuenta real,
~50 KB por corrida (unos 18 MB al año corriéndolo a diario). La mayor parte son las
curvas de retención de YouTube, que son 100 puntos por video — pesadas, pero es
justamente el dato que ningún otro lado guarda.

USO
    import historico
    historico.guardar(datos)                  # en el recolector, al final
    corridas = historico.leer()               # todas, ordenadas de vieja a nueva
    dia_a_dia = historico.ultima_por_dia()    # una por día (la última si corriste varias)

Autochequeo:
    python3 historico.py
"""

import datetime
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(AQUI, "historico.jsonl")

# Claves que se van a la basura antes de guardar: son imágenes incrustadas en base64.
# Si mañana aparece otra (ej. "portada"), sumala acá y listo.
PESADAS = {"foto", "miniatura", "profile_picture_url", "avatar"}


def podar(valor):
    """Devuelve una copia sin las claves pesadas, a cualquier profundidad.
    No toca el original: el recolector sigue usando los datos completos para el HTML."""
    if isinstance(valor, dict):
        return {k: podar(v) for k, v in valor.items() if k not in PESADAS}
    if isinstance(valor, list):
        return [podar(v) for v in valor]
    return valor


def guardar(datos, ruta=RUTA):
    """Agrega una línea al histórico con las métricas de esta corrida.

    Nunca reescribe el archivo: solo agrega al final. Si corrés el recolector tres veces
    el mismo día quedan tres líneas, y ultima_por_dia() se queda con la última.
    Preferimos eso antes que borrar: un archivo que solo crece no se corrompe a la mitad.
    """
    fila = {
        # Si el recolector no puso fecha (no debería pasar), la ponemos igual: una
        # corrida sin fecha es una corrida que después no se puede ordenar.
        "fecha": datos.get("generado")
        or datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
        "dias": datos.get("dias"),
        "redes": podar(datos.get("redes", {})),
    }
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila


def leer(ruta=RUTA):
    """Todas las corridas, de la más vieja a la más nueva.

    Una línea rota (corte de luz a mitad de escritura) se saltea en vez de reventar:
    perder una corrida es molesto, perder el histórico entero es grave.
    """
    if not os.path.exists(ruta):
        return []
    corridas = []
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.strip()
        if not linea:
            continue
        try:
            corridas.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return sorted(corridas, key=lambda c: c.get("fecha", ""))


def ultima_por_dia(ruta=RUTA):
    """Una corrida por día calendario, quedándose con la última de cada uno.
    Es lo que querés para graficar una curva o calcular un delta contra ayer."""
    por_dia = {}
    for c in leer(ruta):  # ya viene ordenada: la última de cada día pisa a las previas
        por_dia[c.get("fecha", "")[:10]] = c
    return [por_dia[d] for d in sorted(por_dia)]


def _autochequeo():
    """Chequeo mínimo: que pode las imágenes, que ordene, y que deduplique por día."""
    import tempfile

    tmp = os.path.join(tempfile.mkdtemp(), "h.jsonl")

    datos = {
        "generado": "2026-08-06T10:00-03:00",
        "dias": 30,
        "redes": {
            "instagram": {
                "cuenta": "@x", "seguidores": 181,
                "foto": "data:image/jpeg;base64," + "A" * 5000,
                "posts": [{"alcance": 100, "miniatura": "data:..." + "B" * 5000}],
            }
        },
        "ia": {"titular": "no se guarda"},
    }
    guardar(datos, tmp)

    (fila,) = leer(tmp)
    red = fila["redes"]["instagram"]
    assert "foto" not in red, "no podó la foto de perfil"
    assert "miniatura" not in red["posts"][0], "no podó la miniatura del post"
    assert red["seguidores"] == 181 and red["posts"][0]["alcance"] == 100, "perdió métricas"
    assert "ia" not in fila, "guardó el análisis de IA (es texto, no métrica)"
    assert "foto" in datos["redes"]["instagram"], "mutó los datos originales del panel"

    # Dos corridas el mismo día + una al día siguiente -> 2 días, y del primero gana la última.
    guardar({**datos, "generado": "2026-08-06T20:00-03:00",
             "redes": {"instagram": {"seguidores": 190}}}, tmp)
    guardar({**datos, "generado": "2026-08-07T10:00-03:00",
             "redes": {"instagram": {"seguidores": 195}}}, tmp)

    dias = ultima_por_dia(tmp)
    assert len(dias) == 2, f"esperaba 2 días, hay {len(dias)}"
    assert dias[0]["redes"]["instagram"]["seguidores"] == 190, "no se quedó con la última del día"
    assert dias[1]["redes"]["instagram"]["seguidores"] == 195, "ordenó mal los días"

    # Una línea corrupta no debe tumbar la lectura.
    with open(tmp, "a", encoding="utf-8") as f:
        f.write("{esto no es json\n")
    assert len(leer(tmp)) == 3, "una línea rota se comió el histórico"

    print("historico.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
