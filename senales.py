#!/usr/bin/env python3
"""
senales.py — Las tres señales con las que el algoritmo de Instagram decide, y la
comparación de cada pieza contra tu propio historial.

POR QUÉ EXISTE
El panel mostraba números crudos: 963 de alcance, 14 likes, 0 compartidos. Con eso, la
pieza de mayor alcance parece la mejor. Los ratios dicen lo contrario: llegó lejos y no
movió a nadie.

Un número mide TAMAÑO. Un ratio mide CALIDAD. Es la diferencia entre "vinieron 900
personas al local" y "de las 900 que entraron, ninguna compró".

LAS TRES SEÑALES (confirmadas por Instagram)
  1. Tiempo de visualización  — la más fuerte. Cuánto te miran, no cuántos.
  2. Compartidos ÷ alcance    — la más fuerte para llegar a gente que NO te sigue.
                                Pesa 3-5 veces más que un like.
  3. Likes ÷ alcance          — la tercera. Importa menos de lo que todos creen.

LA REGLA QUE NO SE ROMPE
Instagram usa cuatro sistemas de ranking distintos (Feed, Reels, Stories, Explora) y cada
uno pondera diferente. Los reels rinden entre 80% y 120% más que un posteo de feed por
diseño. **Comparar un reel con un carrusel es comparar el consumo de una moto con el de un
camión.** Por eso acá las medianas se calculan SIEMPRE por formato, nunca todas juntas.

Autochequeo:
    python3 senales.py
"""

import statistics

# Con menos piezas que esto, la mediana de un formato es una anécdota, no una referencia.
# Preferimos no decir nada antes que decir "estás 300% arriba" comparando contra dos posts.
MINIMO_PARA_COMPARAR = 3

# Cuánto tiene que alejarse un ratio de tu mediana para que valga la pena mencionarlo.
# Por debajo de esto es ruido: la misma pieza publicada dos veces varía más que eso.
UMBRAL_DESTACADO = 1.5   # 50% arriba
UMBRAL_FLOJO = 0.5       # 50% abajo


def ratios(post):
    """Las tres señales de una pieza, en porcentaje sobre el alcance.

    Devuelve None en cada una que no se pueda calcular, en vez de 0: no es lo mismo
    "nadie lo compartió" que "esta red no informa compartidos".
    """
    alcance = post.get("alcance") or 0
    if not alcance:
        # La retención se devuelve igual: no se calcula sobre el alcance, así que
        # una pieza sin alcance informado puede tener retención perfectamente.
        return {"sends_reach": None, "saves_reach": None, "likes_reach": None,
                "retencion": post.get("retencion")}

    def pct(clave):
        v = post.get(clave)
        return round(v / alcance * 100, 2) if v is not None else None

    return {
        "sends_reach": pct("compartidos"),
        "saves_reach": pct("guardados"),
        "likes_reach": pct("likes"),
        # La señal #1 del algoritmo, y la unica que NO se mide sobre el alcance:
        # es que porcentaje del video miraron. Viene calculada del recolector
        # porque necesita la duracion real del archivo, que la API no publica.
        # Puede pasar de 100%: son reproducciones repetidas.
        "retencion": post.get("retencion"),
    }


def medianas_por_formato(posts, minimo=MINIMO_PARA_COMPARAR):
    """La mediana de cada señal, separada por formato (Reel / Carrusel / Post).

    Mediana y no promedio: un solo reel viral te corre el promedio y hace que todo lo
    demás parezca un fracaso. La mediana aguanta el outlier.

    Los formatos con menos de `minimo` piezas quedan afuera.
    """
    por_tipo = {}
    for p in posts:
        if not p.get("alcance"):
            continue
        por_tipo.setdefault(p.get("tipo", "?"), []).append(ratios(p))

    salida = {}
    for tipo, filas in por_tipo.items():
        if len(filas) < minimo:
            continue
        med = {}
        for señal in ("sends_reach", "saves_reach", "likes_reach", "retencion"):
            valores = [f[señal] for f in filas if f[señal] is not None]
            med[señal] = round(statistics.median(valores), 2) if valores else None
        med["piezas"] = len(filas)
        salida[tipo] = med
    return salida


def lectura(post, medianas):
    """Frase corta comparando esta pieza contra tu mediana de SU MISMO formato.

    Devuelve None cuando no hay con qué comparar. Callarse es una respuesta válida:
    inventar una comparación con dos piezas es peor que no decir nada.
    """
    med = medianas.get(post.get("tipo"))
    if not med:
        return None
    r = ratios(post)
    notas = []
    etiquetas = {"sends_reach": "compartidos", "saves_reach": "guardados",
                 "likes_reach": "likes", "retencion": "retención"}

    for señal, nombre in etiquetas.items():
        valor, base = r[señal], med.get(señal)
        if valor is None or base is None:
            continue
        if base == 0:
            # Tu mediana es cero: cualquier valor positivo es noticia, pero no hay
            # división posible. Se dice en palabras.
            if valor > 0:
                notas.append(f"{nombre}: los únicos del formato")
            continue
        veces = valor / base
        if veces >= UMBRAL_DESTACADO:
            notas.append(f"{nombre}: {veces:.1f}x tu mediana")
        elif veces <= UMBRAL_FLOJO:
            notas.append(f"{nombre}: la mitad de tu mediana")
    return notas or None


def diagnostico(posts):
    """La lectura de conjunto: qué señal está floja en toda la cuenta.

    Es la pregunta que un número suelto no contesta: ¿el problema es que no llegás,
    o que llegás y no pasa nada?
    """
    con_alcance = [p for p in posts if p.get("alcance")]
    if not con_alcance:
        return None

    todos = [ratios(p) for p in con_alcance]
    def med(señal):
        v = [t[señal] for t in todos if t[señal] is not None]
        return round(statistics.median(v), 2) if v else None

    sends, saves, likes = med("sends_reach"), med("saves_reach"), med("likes_reach")
    alerta = None
    # Sin compartidos no salís de tu propia audiencia, por más likes que tengas.
    # Es el caso "gusta mucho a quien lo ve, pero nadie lo reenvía".
    if sends is not None and sends < 0.2 and (likes or 0) >= 3:
        alerta = ("Tu contenido gusta a quien lo ve pero casi no se comparte: "
                  "está escrito para gustar, no para reenviar. Los compartidos son la "
                  "señal más fuerte para llegar a gente que no te sigue.")
    elif sends is not None and sends < 0.2:
        alerta = ("Casi no hay compartidos. Es la señal que más te expande: sin eso, "
                  "el alcance depende solo de a quién ya tenés.")

    return {"sends_reach": sends, "saves_reach": saves, "likes_reach": likes,
            "piezas": len(con_alcance), "alerta": alerta}


def enriquecer(posts):
    """Le agrega a cada pieza sus ratios y su lectura. Modifica la lista en el lugar
    (es la que después se incrusta en el panel) y devuelve el resumen de la cuenta."""
    medianas = medianas_por_formato(posts)
    for p in posts:
        p.update(ratios(p))
        p["lectura"] = lectura(p, medianas)
    return {"medianas": medianas, "cuenta": diagnostico(posts)}


def _autochequeo():
    def post(tipo, alcance, likes=0, compartidos=0, guardados=0):
        return {"tipo": tipo, "alcance": alcance, "likes": likes,
                "compartidos": compartidos, "guardados": guardados}

    # ── ratios ────────────────────────────────────────────────────────────
    r = ratios(post("Reel", 200, likes=10, compartidos=4, guardados=2))
    assert r == {"sends_reach": 2.0, "saves_reach": 1.0, "likes_reach": 5.0,
                 "retencion": None}, r
    # Alcance 0 no puede dividir: None, no 0 ni una excepción.
    assert ratios(post("Reel", 0, likes=5))["likes_reach"] is None
    # Un campo ausente (Facebook no informa compartidos) es None, no 0.
    assert ratios({"tipo": "Post", "alcance": 100, "likes": 5})["sends_reach"] is None

    # ── retención ─────────────────────────────────────────────────────────
    # No se mide sobre el alcance: una pieza sin alcance informado la conserva.
    p = {"tipo": "Reel", "alcance": 0, "retencion": 34.9}
    assert ratios(p)["retencion"] == 34.9, "perdió la retención sin alcance"
    # Arriba de 100% no es un error: el video se reprodujo más de una vez.
    assert ratios({"tipo": "Reel", "alcance": 50, "retencion": 128.0})["retencion"] == 128.0

    # ── medianas por formato ──────────────────────────────────────────────
    posts = [
        post("Reel", 100, likes=5, compartidos=1),
        post("Reel", 100, likes=5, compartidos=1),
        post("Reel", 100, likes=5, compartidos=1),
        post("Carrusel", 100, likes=9),   # solo 2 carruseles: no alcanza para mediana
        post("Carrusel", 100, likes=9),
    ]
    m = medianas_por_formato(posts)
    assert "Reel" in m and m["Reel"]["likes_reach"] == 5.0, m
    assert "Carrusel" not in m, "comparó un formato con menos de 3 piezas"
    # Y lo importante: los formatos no se mezclan entre sí.
    assert m["Reel"]["piezas"] == 3

    # La mediana aguanta un viral que arruinaría el promedio.
    virales = [post("Reel", 100, likes=5)] * 4 + [post("Reel", 100, likes=90)]
    assert medianas_por_formato(virales)["Reel"]["likes_reach"] == 5.0, \
        "un outlier corrió la mediana (¿se coló un promedio?)"

    # ── lectura ───────────────────────────────────────────────────────────
    destacado = post("Reel", 100, likes=15, compartidos=1)   # 3x la mediana de likes
    notas = lectura(destacado, m)
    assert notas and any("likes" in n and "3.0x" in n for n in notas), notas
    # Sin base de comparación, no inventa nada.
    assert lectura(post("Carrusel", 100, likes=50), m) is None, \
        "comparó contra un formato sin mediana"

    # ── diagnóstico de cuenta ─────────────────────────────────────────────
    # Gusta mucho (likes altos) pero nadie comparte: tiene que avisarlo.
    mudos = [post("Reel", 100, likes=8, compartidos=0) for _ in range(4)]
    d = diagnostico(mudos)
    assert d["alerta"] and "no se comparte" in d["alerta"], d
    sanos = [post("Reel", 100, likes=8, compartidos=2) for _ in range(4)]
    assert diagnostico(sanos)["alerta"] is None, "alertó sobre una cuenta que sí comparte"

    # ── enriquecer no rompe ni pierde piezas ──────────────────────────────
    lista = [post("Reel", 100, likes=5, compartidos=1) for _ in range(3)]
    resumen = enriquecer(lista)
    assert all("likes_reach" in p for p in lista), "no enriqueció todas las piezas"
    assert resumen["cuenta"]["piezas"] == 3

    print("senales.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
