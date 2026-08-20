#!/usr/bin/env python3
"""
segmentos.py — A QUIÉN le está funcionando la publicidad, no solo cuánto gastó.

POR QUÉ EXISTE
El total de una campaña es un promedio, y un promedio esconde. "CTR 1,57%" puede ser un
segmento con 3,98% y otro con 0,72% mezclados en la misma bolsa. La plata se va a los dos
por igual y solo uno la devuelve.

Es la diferencia entre "el restaurante factura bien" y "el salón factura y el delivery
pierde plata, pero como está todo junto nadie se dio cuenta".

Este módulo abre esa bolsa en tres cortes: edad y género, país, y plataforma con
dispositivo. Con eso se pueden ver las cuatro cosas que un total nunca muestra:

  - El segmento que rinde y está subexplotado (el hallazgo que más plata devuelve).
  - El que se come el presupuesto rindiendo peor que el promedio.
  - Geografía que no debería estar ahí (una campaña para LATAM gastando en Estados Unidos).
  - Diferencias de dispositivo que revelan el perfil real de quien te compra.

COMBINACIONES VÁLIDAS (verificadas en la doc, no se pueden mezclar a gusto)
https://developers.facebook.com/docs/marketing-api/insights/breakdowns/
Meta solo permite ciertas permutaciones: `age,gender` juntos, `country` solo,
`publisher_platform,impression_device` juntos. Por eso son tres llamadas y no una.

Autochequeo:
    python3 segmentos.py
"""

import campanas

# (nombre interno, breakdown de Meta, cómo se lee en castellano)
CORTES = [
    ("edad_genero", "age,gender", "edad y género"),
    ("pais", "country", "país"),
    ("plataforma", "publisher_platform,impression_device", "plataforma y dispositivo"),
]

CAMPOS = ("spend,impressions,reach,clicks,ctr,cpm,frequency,actions,cost_per_action_type")

# Un segmento con menos gasto que esta parte del total es ruido: no alcanza para concluir
# nada y llenaría el informe de hallazgos sobre 200 pesos.
PARTE_MINIMA = 0.02          # 2% del gasto de la cuenta
# Cuánto mejor tiene que ser un segmento para llamarlo "subexplotado" o "caro".
VECES_MEJOR = 1.5
VECES_PEOR = 1.8
# Un segmento que rinde bien pero se lleva menos de esto del presupuesto está desaprovechado.
PARTE_DESAPROVECHADA = 0.15  # 15%
# Desde cuánto del presupuesto vale la pena marcar un segmento como caro. Un 10% de una
# cuenta chica ya es plata real: el corte anterior en 20% se comía casos evidentes.
PARTE_PARA_CARO = 0.10

TRADUCCION = {
    "female": "mujeres", "male": "hombres", "unknown": "sin identificar",
    "iphone": "iPhone", "ipad": "iPad", "android_smartphone": "Android",
    "android_tablet": "tablet Android", "desktop": "computadora",
    "facebook": "Facebook", "instagram": "Instagram", "messenger": "Messenger",
    "audience_network": "Audience Network", "threads": "Threads",
}


def plata(v, moneda=""):
    """Formatea un monto sin perder la diferencia. Con valores chicos (una campaña en
    dólares donde todo cuesta 1,38) redondear a entero convierte 1,38 y 0,52 en '1' y '1'."""
    if v is None:
        return "—"
    dec = 2 if abs(v) < 10 else 0
    return f"{v:,.{dec}f} {moneda}".strip()


def _etiqueta(fila, breakdown):
    """El nombre legible de un segmento: '25-34 · mujeres' en vez de '25-34/female'."""
    partes = []
    for k in breakdown.split(","):
        v = fila.get(k)
        if v:
            partes.append(TRADUCCION.get(str(v), str(v)))
    return " · ".join(partes) or "?"


def filas(datos, breakdown, objetivo, gasto_total):
    """Convierte la respuesta cruda de Meta en segmentos comparables."""
    salida = []
    for f in datos:
        gasto = campanas._num(f.get("spend")) or 0
        cant, costo, etiqueta, singular = campanas.resultado(f, objetivo)
        salida.append({
            "segmento": _etiqueta(f, breakdown),
            "gasto": gasto,
            # Qué porcentaje del presupuesto se lleva. Es la mitad de la historia:
            # sin esto no se puede decir "rinde bien pero le das el 3% de la plata".
            "parte_gasto": (gasto / gasto_total) if gasto_total else 0,
            "impresiones": campanas._num(f.get("impressions")),
            "ctr": campanas._num(f.get("ctr")),
            "cpm": campanas._num(f.get("cpm")),
            "resultados": cant,
            "costo_resultado": costo,
            "etiqueta_resultado": etiqueta,
            "singular_resultado": singular,
        })
    salida.sort(key=lambda s: -s["gasto"])
    return salida


def bajar(get, graph, token, act_id, objetivo, preset="maximum"):
    """Los tres cortes de una cuenta. Tres llamadas porque Meta no deja combinarlos."""
    total = get(f"{graph}/{act_id}/insights", fields="spend",
                date_preset=preset, access_token=token)
    gasto_total = campanas._num((total.get("data") or [{}])[0].get("spend")) or 0

    salida = {}
    for nombre, breakdown, _ in CORTES:
        d = get(f"{graph}/{act_id}/insights", fields=CAMPOS, breakdowns=breakdown,
                date_preset=preset, limit=100, access_token=token)
        salida[nombre] = filas(d.get("data", []), breakdown, objetivo, gasto_total)
    return salida


def _relevantes(segs):
    """Los segmentos con gasto suficiente como para decir algo de ellos."""
    return [s for s in segs
            if s["parte_gasto"] >= PARTE_MINIMA and (s["costo_resultado"] or 0) > 0]


def analizar(segs, moneda="", como_se_lee=""):
    """Los hallazgos de un corte. Cada uno con el número que lo justifica.

    Devuelve lista de dicts {tipo, segmento, texto}. Vacía si no hay nada que decir:
    un informe que siempre encuentra algo deja de ser creíble.
    """
    utiles = _relevantes(segs)
    if len(utiles) < 2:
        return []

    hallazgos = []
    costos = sorted(utiles, key=lambda s: s["costo_resultado"])
    mejor, peor = costos[0], costos[-1]
    # Mediana simple sobre los que tienen costo, para comparar contra "lo normal".
    medio = costos[len(costos) // 2]["costo_resultado"]
    etiq = mejor["singular_resultado"]

    # 1. El que rinde y no recibe plata. Es el hallazgo que más devuelve.
    if (mejor["costo_resultado"] <= medio / VECES_MEJOR
            and mejor["parte_gasto"] < PARTE_DESAPROVECHADA):
        hallazgos.append({
            "tipo": "subexplotado", "segmento": mejor["segmento"],
            "texto": (f"«{mejor['segmento']}» consigue cada {etiq} a "
                      f"{plata(mejor['costo_resultado'], moneda)} y solo se lleva el "
                      f"{mejor['parte_gasto']*100:.0f}% del presupuesto. Es el mejor de "
                      f"todo el corte por {como_se_lee} y está desaprovechado."),
        })

    # 2. El que se come el presupuesto rindiendo peor.
    if peor["costo_resultado"] >= medio * VECES_PEOR and peor["parte_gasto"] >= PARTE_PARA_CARO:
        hallazgos.append({
            "tipo": "caro", "segmento": peor["segmento"],
            "texto": (f"«{peor['segmento']}» se lleva el {peor['parte_gasto']*100:.0f}% del "
                      f"presupuesto y cada {etiq} le sale {plata(peor['costo_resultado'], moneda)}, "
                      f"contra {plata(mejor['costo_resultado'], moneda)} del mejor. "
                      "Es la plata más fácil de recuperar."),
        })

    # 3. Gasto que no devuelve NADA. Suele ser geografía o público mal puesto.
    for s in segs:
        if s["gasto"] and not s["resultados"] and s["parte_gasto"] >= PARTE_MINIMA:
            hallazgos.append({
                "tipo": "desperdicio", "segmento": s["segmento"],
                "texto": (f"«{s['segmento']}» consumió {plata(s['gasto'], moneda)} "
                          f"({s['parte_gasto']*100:.0f}% del total) sin un solo resultado. "
                          "Revisá si ese público tiene que estar en la campaña."),
            })

    # 4. Diferencia grande de CTR entre segmentos: dice quién te presta atención.
    con_ctr = [s for s in utiles if s["ctr"]]
    if len(con_ctr) >= 2:
        alto = max(con_ctr, key=lambda s: s["ctr"])
        bajo = min(con_ctr, key=lambda s: s["ctr"])
        if bajo["ctr"] and alto["ctr"] >= bajo["ctr"] * VECES_MEJOR:
            hallazgos.append({
                "tipo": "atencion", "segmento": alto["segmento"],
                "texto": (f"«{alto['segmento']}» tiene CTR {alto['ctr']:.2f}% contra "
                          f"{bajo['ctr']:.2f}% de «{bajo['segmento']}»: "
                          f"{alto['ctr']/bajo['ctr']:.0f} veces más atención por el mismo anuncio."),
            })
    return hallazgos


def analizar_todo(cortes, moneda=""):
    """Los hallazgos de los tres cortes juntos."""
    salida = []
    for nombre, _, como_se_lee in CORTES:
        for h in analizar(cortes.get(nombre, []), moneda, como_se_lee):
            salida.append({**h, "corte": como_se_lee})
    return salida


def _autochequeo():
    def fila(gasto, conv, ctr=2.0, **bd):
        f = {"spend": str(gasto), "impressions": "10000", "ctr": str(ctr),
             "actions": [], "cost_per_action_type": []}
        if conv:
            f["actions"] = [{"action_type": "onsite_conversion.total_messaging_connection",
                             "value": str(conv)}]
            f["cost_per_action_type"] = [
                {"action_type": "onsite_conversion.total_messaging_connection",
                 "value": str(gasto / conv)}]
        f.update(bd)
        return f

    OBJ = "OUTCOME_ENGAGEMENT"

    # ── etiquetas legibles ────────────────────────────────────────────────
    assert _etiqueta({"age": "45-54", "gender": "female"}, "age,gender") == "45-54 · mujeres"
    assert _etiqueta({"publisher_platform": "instagram", "impression_device": "iphone"},
                     "publisher_platform,impression_device") == "Instagram · iPhone"

    # ── subexplotado: rinde 5x mejor y se lleva el 4% ─────────────────────
    datos = [
        fila(9000, 5, gender="male"),       # 90% del gasto, 1.800/conv <- el caro
        fila(400, 20, gender="female"),     #  4% del gasto,     20/conv <- el bueno
        fila(600, 1, gender="unknown"),     #  6% del gasto,    600/conv (la mediana)
    ]
    segs = filas(datos, "gender", OBJ, 10000)
    hs = analizar(segs, "ARS", "género")
    tipos = {h["tipo"] for h in hs}
    assert "subexplotado" in tipos, hs
    sub = next(h for h in hs if h["tipo"] == "subexplotado")
    assert "mujeres" in sub["texto"] and "4%" in sub["texto"], sub["texto"]

    # ── caro: se lleva el 90% y rinde peor que la mediana ─────────────────
    assert "caro" in tipos, hs

    # ── desperdicio: gastó y no trajo nada ────────────────────────────────
    datos = [fila(5000, 10, country="AR"), fila(3000, 5, country="UY"),
             fila(2000, 0, country="US")]
    hs = analizar(filas(datos, "country", OBJ, 10000), "ARS", "país")
    desp = [h for h in hs if h["tipo"] == "desperdicio"]
    assert desp and "US" in desp[0]["texto"], hs

    # ── un segmento chico NO genera hallazgos (evita ruido) ───────────────
    datos = [fila(9900, 10, country="AR"), fila(100, 0, country="US")]  # US = 1% del gasto
    hs = analizar(filas(datos, "country", OBJ, 10000), "ARS", "país")
    assert not any(h["tipo"] == "desperdicio" for h in hs), \
        "alarmó por un segmento que gastó el 1% del total"

    # ── un costo de 0 no es "el mejor": es un dato que Meta no reportó ────
    datos = [fila(5000, 10, country="AR"), fila(400, 0, country="UY"), fila(4600, 5, country="MX")]
    segs = filas(datos, "country", OBJ, 10000)
    segs[1]["costo_resultado"] = 0        # como si Meta hubiera devuelto 0
    segs[1]["resultados"] = 1
    hs = analizar(segs, "USD", "país")
    assert not any(h["tipo"] == "subexplotado" and "UY" in h["texto"] for h in hs), \
        "reportó un costo de 0 como el mejor segmento"

    # ── montos chicos no se redondean a cero ──────────────────────────────
    assert plata(1.38, "USD") == "1.38 USD", plata(1.38, "USD")
    assert plata(1425, "ARS") == "1,425 ARS", plata(1425, "ARS")
    assert plata(None) == "—"

    # ── con un solo segmento no se compara nada ───────────────────────────
    assert analizar(filas([fila(10000, 5, country="AR")], "country", OBJ, 10000)) == []

    # ── CTR: detecta la diferencia de atención ────────────────────────────
    datos = [fila(5000, 10, ctr=1.0, gender="male"), fila(5000, 10, ctr=4.0, gender="female")]
    hs = analizar(filas(datos, "gender", OBJ, 10000), "ARS", "género")
    at = [h for h in hs if h["tipo"] == "atencion"]
    assert at and "mujeres" in at[0]["texto"], hs

    # ── bajar(): tres llamadas, una por corte ─────────────────────────────
    llamadas = []

    def get(url, **p):
        llamadas.append(p.get("breakdowns"))
        if p.get("fields") == "spend":
            return {"data": [{"spend": "10000"}]}
        return {"data": [fila(6000, 10, age="25-34", gender="male",
                              country="AR", publisher_platform="instagram",
                              impression_device="iphone")]}

    cortes = bajar(get, "G", "T", "act_1", OBJ)
    assert set(cortes) == {"edad_genero", "pais", "plataforma"}, cortes
    assert llamadas.count("age,gender") == 1 and llamadas.count("country") == 1, llamadas
    assert cortes["pais"][0]["parte_gasto"] == 0.6, "mal la parte del presupuesto"

    print("segmentos.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
