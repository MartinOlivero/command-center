#!/usr/bin/env python3
"""
leads.py — Las dos lecturas de los comentarios que cambian decisiones de plata.

1) GAP OPERATIVO: quién disparó tu CTA y probablemente quedó sin respuesta.
2) LEADS CALIENTES: quién escribió algo con intención comercial, con la cita textual.

POR QUÉ SOLO ESTAS DOS
El resto del análisis (sentimiento, patrones, ideas de contenido) necesita volumen para
decir algo. Un gráfico de sentimiento sobre siete comentarios es un adorno. Estas dos, en
cambio, sirven desde el primer comentario: una persona que preguntó "¿cuánto sale?" y no
recibió respuesta es plata que se cae, tengas 7 comentarios o 7.000.

SIN IA, A PROPÓSITO
Todo acá son reglas: contar repeticiones y buscar señales en el texto. Es determinístico,
gratis, y explicable — cada lead viene con QUÉ señal lo marcó, así podés discutirle.
Cuando haya volumen, `analista.py` puede tomar estos candidatos y afinar el ranking con IA.
La regla filtra la paja; la IA ordena el grano. En ese orden, no al revés.

USO
    import comentarios, leads
    filas = comentarios.leer()
    leads.gap(filas, ["PANEL"])     # quién repitió el CTA
    leads.calientes(filas)          # candidatos ordenados por temperatura

Autochequeo:
    python3 leads.py
"""

import re
import unicodedata

# Las palabras clave de los CTAs salen de config.json ("ctas"), no de acá: las carga
# el instalador y se editan ahí. Esto es solo el valor de respaldo, y tiene que quedar
# vacío porque este archivo se publica: un default con las palabras de alguien le
# aparecería a todos los demás en su panel.
CTAS = []

# Señales de intención comercial. Cada grupo suma puntos: cuantos más grupos toca un
# comentario, más caliente. Se buscan sobre el texto SIN acentos y en minúscula, así
# "cuánto" y "cuanto" pesan igual (en un comentario nadie cuida la ortografía).
SENALES = {
    "precio": (
        3,
        "pregunta por plata",
        r"\b(precio|cuanto (sale|cuesta|vale|es)|cuanto sale|que precio|"
        r"presupuesto|cotiza|cotizar|arancel|valor|pagar|cobras|cobra)\b",
    ),
    "compra": (
        3,
        "quiere contratar",
        r"\b(contratar|comprar|adquirir|quiero uno|lo quiero|me interesa|"
        r"como accedo|donde compro|inscribir|anotarme|sumarme)\b",
    ),
    "negocio_propio": (
        3,
        "tiene un negocio",
        r"\b(tengo (un|una|mi)|mi (negocio|empresa|local|distribuidora|pyme|tienda|"
        r"comercio|emprendimiento)|trabajo en|somos una|nuestra empresa)\b",
    ),
    "reventa": (
        4,
        "quiere revender (B2B)",
        r"\b(a mis clientes|para mis clientes|revender|ofrecerlo|vender(lo|selo)?|"
        r"para clientes|mis clientes)\b",
    ),
    "factibilidad": (
        2,
        "evalúa si le sirve",
        r"\b(se puede|sirve para|funciona (con|para|en)|me sirve|aplica para|"
        r"anda con|es posible)\b",
    ),
    "como_hacer": (
        1,
        "quiere aprender a hacerlo",
        r"\b(como (lo )?(hago|hiciste|se hace|arma|armo)|tutorial|ensenar|"
        r"como funciona|paso a paso)\b",
    ),
}

# Un signo de pregunta solo no es un lead, pero suma: alguien que pregunta espera respuesta.
PUNTOS_PREGUNTA = 1


def normalizar(texto):
    """Minúscula y sin acentos, para que las reglas no dependan de la ortografía.
    'CUÁNTO' y 'cuanto' tienen que dar lo mismo."""
    plano = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn")


def es_solo_cta(texto, palabras):
    """True si el comentario es únicamente la palabra clave del CTA (ej: 'PANEL').
    Esa gente ya está contada en el gap: no son leads calientes, son disparos del embudo."""
    limpio = re.sub(r"[^\w]", "", normalizar(texto))
    return any(limpio == re.sub(r"[^\w]", "", normalizar(p)) for p in palabras)


def gap(filas, palabras, minimo_repeticiones=2):
    """Quién disparó el CTA y cuántas veces.

    LA HEURÍSTICA, dicha en voz alta: si alguien escribió la palabra clave DOS veces,
    lo más probable es que la primera no le haya respondido nadie. La gente no repite
    un código porque sí; repite cuando no pasó nada.

    NO es una certeza. Para el gap exacto (disparos vs. respuestas efectivamente
    enviadas) hay que cruzar con el log del workflow de n8n, que es quien manda los DM.
    Esto detecta el síntoma desde afuera, sin acceso a ese log.
    """
    por_persona = {}
    for c in filas:
        if c["propio"] or not es_solo_cta(c["texto"], palabras):
            continue
        p = por_persona.setdefault(c["autor"], {"autor": c["autor"], "veces": 0,
                                                "primera": c["fecha"], "ultima": c["fecha"]})
        p["veces"] += 1
        p["primera"] = min(p["primera"], c["fecha"])
        p["ultima"] = max(p["ultima"], c["fecha"])

    disparos = sorted(por_persona.values(), key=lambda p: -p["veces"])
    sospechosos = [p for p in disparos if p["veces"] >= minimo_repeticiones]
    return {
        "personas": len(disparos),
        "disparos": sum(p["veces"] for p in disparos),
        # Los que insistieron: revisá si les llegó la guía o quedaron colgados.
        "sin_respuesta_probable": sospechosos,
        "detalle": disparos,
    }


def temperatura(texto):
    """Puntaje de intención comercial + los motivos que lo justifican.
    Devolver los motivos no es adorno: es lo que te deja discutir el ranking."""
    plano = normalizar(texto)
    puntos, motivos = 0, []
    for _, (peso, motivo, patron) in SENALES.items():
        if re.search(patron, plano):
            puntos += peso
            motivos.append(motivo)
    if "?" in texto or "¿" in texto:
        puntos += PUNTOS_PREGUNTA
        motivos.append("hace una pregunta")
    return puntos, motivos


def calientes(filas, palabras_cta=(), minimo=2):
    """Comentarios con intención comercial, del más caliente al menos.

    Se excluyen: los tuyos y los que son solo la palabra del CTA (esos ya están en el gap).
    `minimo` es el corte de puntaje: con 2 entra alguien que solo pregunta si le sirve;
    subilo a 4-5 cuando tengas volumen y quieras solo los que hablan de plata.
    """
    salida = []
    for c in filas:
        if c["propio"] or es_solo_cta(c["texto"], palabras_cta):
            continue
        puntos, motivos = temperatura(c["texto"])
        if puntos < minimo:
            continue
        salida.append({
            "autor": c["autor"],
            "fecha": c["fecha"][:10],
            "cita": c["texto"],          # textual: es lo que le vas a contestar
            "puntos": puntos,
            "por_que": motivos,
            "media_id": c["media_id"],
        })
    # Más caliente primero; a igual puntaje, el más reciente: un lead de ayer está
    # más tibio que uno de marzo. La fecha va negada para invertir solo ese criterio.
    return sorted(salida, key=lambda l: (-l["puntos"], _fecha_desc(l["fecha"])))


def _fecha_desc(f):
    """Convierte '2026-08-05' en una clave que ordena de más nueva a más vieja."""
    return tuple(-int(x) for x in f.split("-"))


# Debajo de esto, cualquier proporción sobre los comentarios es ruido con forma de dato.
# El número no es arbitrario: con 7 comentarios, UNO SOLO mueve el 14% de la muestra;
# con 30 mueve el 3,3%; con 50, el 2%. Recién ahí "el 20% pregunta precios" significa
# algo distinto de "una persona preguntó precios".
MINIMO_PARA_TEMAS = 30
MUESTRA_COMODA = 50

# Qué se le puede preguntar a un comentario sin opinar. Cada categoría es una regla
# sobre el texto, no una interpretación: si aparece, aparece.
TEMAS = {
    "pregunta": ("Preguntas", r"[?¿]"),
    "precio": ("Preguntan precio", SENALES["precio"][2]),
    "quiere": ("Quieren contratar", SENALES["compra"][2]),
    "negocio": ("Cuentan su negocio", SENALES["negocio_propio"][2]),
    "pide_contenido": ("Piden contenido", r"\b(pod(e|é)s hacer|hac(e|é) un|"
                       r"me gustaria ver|podrias (hacer|explicar)|explica|"
                       r"tutorial de|video de|como se hace|segunda parte|parte 2)\b"),
    "duda": ("No entendieron algo", r"\b(no entiendo|no me queda claro|no funciona|"
             r"me da error|no me anda|no puedo|se traba|falla)\b"),
}


# Una intención por comentario, no varias. Las categorías de `temas` se solapan (el
# mismo comentario "tengo una pyme, ¿cuánto sale?" cuenta en tres), y eso sirve para
# buscar pero no para graficar: las barras suman más de 100% y el mismo texto aparece
# tres veces. Acá cada comentario cae en UNA sola, la de más arriba que le toque.
#
# El orden es por qué tan cerca está de la plata: si alguien cuenta su negocio Y
# quiere contratar, lo que importa es que quiere contratar.
#
# SOBRE LOS COLORES (validados con los seis chequeos en modo oscuro):
#   - Los tres del medio (#0e9fbd, #9333ea, #c2820c) pasan todos los pares.
#   - Verde y rojo NO se distinguen entre sí con daltonismo rojo-verde (ΔE 3.7).
#     Se dejan igual a propósito porque acá NO son identidad, son ESTADO: uno es
#     "hay plata esperando" y el otro "hay alguien trabado". El requisito que eso
#     impone es que el color nunca sea el único dato — por eso cada barra lleva
#     su nombre y su número al lado, que es lo que las hace distinguibles.
#   - El gris de "solo aliento" lee como gris a propósito: es la categoría que no
#     genera ninguna acción y no tiene que competir por atención con las otras.
INTENCIONES = [
    ("contratar", "Quieren contratarte", "#16a34a",
     # `contratar\w*` y no `contratar`: en rioplatense casi nunca aparece suelto,
     # viene pegado al pronombre — "contratarte", "contratarlos". Con \b al final
     # esas tres formas no matcheaban y el lead más caliente se perdía.
     r"\b(contratar\w*|te contrato|trabajar con vos|"
     r"me interesa (la|el|tu)|quiero (uno|eso|el)|como (accedo|compro|contrato)|"
     r"presupuesto|cuanto (sale|cuesta|vale)|precio)\b"),
    ("trabado", "Están trabados", "#ef4444",
     r"\b(no (me )?(funciona|anda|puedo|sale|deja|carga)|me (da|tira|salta) (un )?error|"
     r"error|falla|se traba|no coincide|no encuentro|no aparece|no me queda claro|"
     r"no entiendo|no accede|no está vigente|no vigente)\b"),
    ("negocio", "Cuentan su negocio", "#0e9fbd",
     r"\b(tengo (un|una|mi)|mi (negocio|empresa|local|distribuidora|pyme|tienda|"
     r"comercio|emprendimiento)|trabajo en|somos una|nuestra empresa|para mi negocio|"
     r"mi emprendimiento)\b"),
    ("pide", "Piden más contenido", "#9333ea",
     r"\b(pod(e|é)s hacer|hac(e|é) un|me gustaria ver|podrias (hacer|explicar)|"
     r"espero (los|el)|proxim[oa]s? (video|capitulo|parte)|segunda parte|parte 2|"
     r"tutorial de|video de|mas videos)\b"),
    ("consulta", "Consultan cómo hacerlo", "#c2820c",
     r"[?¿]|\b(como (se |lo |puedo )?(hago|hace|monto|instalo|configuro)|"
     r"se puede|recomendas|conviene|sirve para)\b"),
]


def intencion(texto):
    """La intención principal de un comentario. Devuelve la clave o 'aliento'.

    'aliento' es el fondo del embudo al revés: felicitaciones, emojis y gracias.
    No es basura — que la gente aplauda está bien — pero no genera ninguna acción,
    y mezclarlo con lo demás infla los porcentajes de lo que sí importa.
    """
    plano = normalizar(texto)
    for clave, _, _, patron in INTENCIONES:
        if re.search(patron, plano):
            return clave
    return "aliento"


def reparto(filas, palabras_cta=()):
    """Cómo se reparte la conversación entre intenciones. Para graficar.

    Suma 100% porque cada comentario entra en una sola categoría: eso es lo que
    hace que un gráfico de esto se pueda leer sin hacer cuentas raras.
    """
    conversacion = [c for c in filas
                    if not c["propio"] and not es_solo_cta(c["texto"], palabras_cta)]
    n = len(conversacion)
    cuenta = {}
    for c in conversacion:
        cuenta[intencion(c["texto"])] = cuenta.get(intencion(c["texto"]), 0) + 1

    orden = [(k, et, col) for k, et, col, _ in INTENCIONES] + \
            [("aliento", "Solo aliento", "#5d7284")]
    return {
        "total": n,
        "barras": [{"clave": k, "etiqueta": et, "color": col,
                    "cuantos": cuenta.get(k, 0),
                    "pct": round(cuenta.get(k, 0) / n * 100, 1) if n else 0}
                   for k, et, col in orden if cuenta.get(k)],
    }


def accionables(filas, palabras_cta=(), tope=6):
    """SOLO lo que pide una respuesta tuya hoy: quiere contratar o está trabado.

    El resto de la conversación se lee en la lista completa. Traer las 13 preguntas
    acá no ayuda a decidir nada: si hay 100, la lista es tan inútil como no tenerla.
    """
    salida = []
    for c in filas:
        if c["propio"] or es_solo_cta(c["texto"], palabras_cta):
            continue
        i = intencion(c["texto"])
        if i not in ("contratar", "trabado"):
            continue
        salida.append({
            "autor": c["autor"],
            "fecha": c["fecha"][:10],
            "cita": c["texto"][:260],
            "tipo": i,
            "etiqueta": "Quiere contratarte" if i == "contratar" else "Está trabado",
        })
    # Lo comercial primero; dentro de cada grupo, lo más reciente.
    return sorted(salida, key=lambda x: (x["tipo"] != "contratar",
                                         _fecha_desc(x["fecha"])))[:tope]


def temas(filas, palabras_cta=()):
    """Cuántos comentarios toca cada tema, y si la muestra da para leerlo.

    Devuelve SIEMPRE el estado de la muestra, aunque no alcance. Un panel que
    esconde que midió sobre siete comentarios miente por omisión: el número se
    ve igual de contundente con 7 que con 700, y no es lo mismo.
    """
    reales = [c for c in filas if not c["propio"]]
    # Los disparos del CTA no son conversación: son gente ejecutando una consigna.
    # Contarlos como "participación" infla el número y no dice nada del contenido.
    conversacion = [c for c in reales if not es_solo_cta(c["texto"], palabras_cta)]

    conteo = {}
    for clave, (etiqueta, patron) in TEMAS.items():
        hits = [c for c in conversacion if re.search(patron, normalizar(c["texto"]))]
        if hits:
            conteo[clave] = {
                "etiqueta": etiqueta,
                "cuantos": len(hits),
                # La cita textual es lo que convierte un número en algo accionable.
                "ejemplos": [{"autor": h["autor"], "texto": h["texto"][:180]}
                             for h in hits[:3]],
            }

    n = len(conversacion)
    return {
        "total": len(reales),
        "conversacion": n,
        "solo_cta": len(reales) - n,
        "temas": dict(sorted(conteo.items(), key=lambda x: -x[1]["cuantos"])),
        "suficiente": n >= MINIMO_PARA_TEMAS,
        "minimo": MINIMO_PARA_TEMAS,
        "comoda": MUESTRA_COMODA,
        "faltan": max(0, MINIMO_PARA_TEMAS - n),
    }


def _autochequeo():
    def com(texto, autor="alguien", propio=False, fecha="2026-08-05T12:00:00+0000"):
        return {"texto": texto, "autor": autor, "propio": propio, "fecha": fecha,
                "media_id": "m1", "responde_a": None, "id": texto[:6] + autor}

    # ── GAP ──────────────────────────────────────────────────────────────
    filas = [
        com("2140", "danitejeiro", fecha="2026-08-05T12:00:00+0000"),
        com("2140", "danitejeiro", fecha="2026-08-05T19:59:00+0000"),   # repitió: sospechoso
        com("2140", "miloniahome"),
        com(" 2140 ", "conespacios"),          # con espacios sigue siendo el CTA
        com("2140", "vos", propio=True),       # tuyo: no cuenta
        com("me sirve 2140 para mi local", "otro"),  # no es SOLO el CTA
    ]
    g = gap(filas, ["2140"])
    assert g["personas"] == 3, f"personas mal: {g['personas']}"
    assert g["disparos"] == 4, f"disparos mal: {g['disparos']}"
    assert [p["autor"] for p in g["sin_respuesta_probable"]] == ["danitejeiro"], \
        "no detectó a quien repitió el CTA"

    # ── TEMPERATURA ──────────────────────────────────────────────────────
    assert temperatura("¿Cuánto sale?")[0] > temperatura("Muy bueno!")[0], \
        "una pregunta de precio tiene que pesar más que un halago"
    # Sin acentos tiene que puntuar igual que con acentos.
    assert temperatura("cuanto sale")[0] == temperatura("cuánto sale")[0], \
        "la falta de acento cambió el puntaje"

    # ── LEADS CALIENTES ──────────────────────────────────────────────────
    filas = [
        com("2140", "solo_cta"),
        com("🔥🔥", "emoji"),
        com("Muy cierto, es tener un negocio abierto 24 horas", "opinion"),
        com("¿cuánto sale? tengo una distribuidora", "caliente"),
        com("se puede hacer para mis clientes? quiero revenderlo", "b2b"),
        com("¿cuánto sale?", "tibio", fecha="2026-03-01T12:00:00+0000"),
        com("¿cuánto sale?", "reciente", fecha="2026-08-01T12:00:00+0000"),
    ]
    l = calientes(filas, ["2140"])
    autores = [x["autor"] for x in l]
    assert "solo_cta" not in autores, "el disparo del CTA se coló como lead"
    assert "emoji" not in autores, "un emoji se coló como lead"
    assert autores[0] in ("b2b", "caliente"), f"el más caliente no quedó primero: {autores}"
    assert autores.index("reciente") < autores.index("tibio"), \
        "a igual puntaje, el más reciente va primero"
    assert l[0]["cita"], "perdió la cita textual"
    assert l[0]["por_que"], "no explicó por qué es un lead"

    # ── temas ─────────────────────────────────────────────────────────────
    def com(texto, autor="x", propio=False):
        return {"texto": texto, "autor": autor, "propio": propio,
                "fecha": "2026-08-01", "media_id": "1"}

    t = temas([com("¿cuánto sale?"), com("me encantó 🔥"),
               com("2140"), com("respondo yo", propio=True),
               com("podés hacer un video de n8n?")], ["2140"])
    assert t["total"] == 4, "contó tus propios comentarios como ajenos"
    assert t["conversacion"] == 3, "el disparo del CTA no es conversación"
    assert t["solo_cta"] == 1
    assert t["temas"]["precio"]["cuantos"] == 1
    assert t["temas"]["pide_contenido"]["cuantos"] == 1
    # Con 3 comentarios NO puede decir que la muestra alcanza.
    assert t["suficiente"] is False and t["faltan"] == MINIMO_PARA_TEMAS - 3
    # Y tiene que traer la cita, que es lo único accionable.
    assert t["temas"]["precio"]["ejemplos"][0]["texto"] == "¿cuánto sale?"

    # Con volumen suficiente, deja de avisar.
    grande = temas([com(f"¿pregunta {i}?") for i in range(MINIMO_PARA_TEMAS)], [])
    assert grande["suficiente"] is True and grande["faltan"] == 0

    # ── intención única y reparto ─────────────────────────────────────────
    # Un comentario que toca tres categorías tiene que caer en UNA: la de más
    # arriba. Si no, el gráfico suma más de 100% y el texto se repite tres veces.
    assert intencion("Tengo una pyme, ¿cuánto sale?") == "contratar"
    assert intencion("me tira un error al levantar el contenedor") == "trabado"
    assert intencion("tengo una distribuidora de bebidas") == "negocio"
    assert intencion("espero los próximos capítulos") == "pide"
    assert intencion("¿se puede hacer con Twilio?") == "consulta"
    assert intencion("crack, genio total 🔥") == "aliento"

    r = reparto([com("¿cuánto sale?"), com("me da error"), com("genio!"),
                 com("2140"), com("mío", propio=True)], ["2140"])
    assert r["total"] == 3, "contó el CTA o tu propio comentario"
    assert sum(b["cuantos"] for b in r["barras"]) == 3, "un comentario cayó en dos barras"
    assert abs(sum(b["pct"] for b in r["barras"]) - 100) < 0.5, "las barras no suman 100%"

    # Accionables: solo lo que pide respuesta, y lo comercial primero.
    acc = accionables([com("me da error", "ana"), com("quiero contratarte", "beto"),
                       com("¿se puede con twilio?", "caro")], [])
    assert [a["autor"] for a in acc] == ["beto", "ana"], acc
    assert all(a["tipo"] in ("contratar", "trabado") for a in acc)

    print("leads.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
