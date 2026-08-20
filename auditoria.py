#!/usr/bin/env python3
"""
auditoria.py — Revisa las campañas y dice qué está mal, qué falta y qué está funcionando.

SOLO LECTURA. No toca nada en Meta. Escribir en la cuenta publicitaria de alguien es
mover su plata, y eso no lo decide un script.

POR QUÉ LOS CHEQUEOS SON REGLAS Y NO IA
Son determinísticos: la misma cuenta da siempre el mismo resultado, sale gratis, y cada
hallazgo viene con el número que lo justifica para que se lo puedas discutir. La IA entra
después, para la lectura estratégica — pero sobre hallazgos que ya están verificados, no
inventando cuáles son.

EL CHEQUEO QUE SEPARA UN BUEN AUDITOR DE UNO MALO
En la cuenta de prueba hay una campaña con el PEOR CTR (0,95%) que consigue conversaciones
a 15 ARS, contra 1.425 de la que tiene "buen" CTR. Un auditor que mire CTR te haría pausar
la campaña 95 veces más eficiente que tenés.

Por eso acá una métrica de vidriera (CTR, CPM) nunca dispara sola: si el costo por
resultado está bien, no hay problema que reportar por más feo que se vea el CTR.

Autochequeo:
    python3 auditoria.py
"""

import statistics

# Arriba de esto le estás mostrando lo mismo a la misma gente: el CPM sube y el
# rendimiento cae. No es mala creatividad, es saturación.
FRECUENCIA_QUEMA = 3.0
# Un CTR por debajo de esto es señal de que el anuncio no engancha... salvo que el costo
# por resultado diga lo contrario.
CTR_FLOJO = 1.0
# Cuántas veces la mediana de la cuenta tiene que costar algo para llamarlo caro.
VECES_CARA = 2.0
# Con menos campañas que esto no hay mediana que valga: comparar contra dos es una anécdota.
MINIMO_PARA_MEDIANA = 3
# Debajo de esto, un costo por resultado es una anécdota, no un dato. Una campaña que
# gastó 300 pesos y trajo 25 conversaciones puede ser un hallazgo o puede ser suerte.
IMPRESIONES_MINIMAS = 1000
# Objetivos que optimizan interacción, no negocio. Para quien vende un servicio, Meta
# sale a buscar gente que da likes, no gente que compra.
OBJETIVOS_DE_VITRINA = {"OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT", "OUTCOME_AWARENESS",
                        "BRAND_AWARENESS", "REACH"}

ALTA, MEDIA, BAJA = "alta", "media", "baja"


def _hallazgo(gravedad, ambito, titulo, detalle, que_hacer):
    return {"gravedad": gravedad, "ambito": ambito, "titulo": titulo,
            "detalle": detalle, "que_hacer": que_hacer}


def mediana_costo(campanas):
    """El costo por resultado típico de esta cuenta, o None si no hay con qué compararlo.
    Mediana y no promedio: una campaña carísima corre el promedio y hace que todas las
    demás parezcan buenas."""
    costos = [c["costo_resultado"] for c in campanas if c.get("costo_resultado")]
    return statistics.median(costos) if len(costos) >= MINIMO_PARA_MEDIANA else None


def revisar_cuenta(cuenta):
    """Los hallazgos de una cuenta publicitaria. Lista ordenada por gravedad."""
    hallazgos = []
    nombre, moneda = cuenta.get("nombre", "?"), cuenta.get("moneda", "")
    campanas = cuenta.get("campanas", [])
    med = mediana_costo(campanas)

    # ── a nivel cuenta ────────────────────────────────────────────────────
    if not cuenta.get("activa"):
        hallazgos.append(_hallazgo(
            ALTA, nombre, "La cuenta no está activa",
            "Meta la marcó como inactiva o con saldo pendiente. Mientras esté así, "
            "cualquier cambio que intentes hacer va a fallar sin explicar bien por qué.",
            "Entrá al Administrador de Anuncios y revisá el estado de la cuenta y el "
            "medio de pago antes de tocar cualquier otra cosa."))

    total = cuenta.get("total") or {}
    freq = total.get("frecuencia")
    if freq and freq >= FRECUENCIA_QUEMA:
        hallazgos.append(_hallazgo(
            ALTA, nombre, f"Frecuencia {freq:.1f} en toda la cuenta",
            "Cada persona vio tus anuncios más de tres veces. A partir de ahí el "
            "rendimiento cae y el costo sube solo, aunque no cambies nada.",
            "Ampliá la segmentación o renová las creatividades. No es un problema de "
            "presupuesto: es que se te acabó el público."))

    # El hallazgo que no sale de ninguna métrica: si TODAS las campañas persiguen
    # interacción, Meta te va a traer gente que reacciona, no gente que compra. Es como
    # pagarle a alguien para que junte gente en la vereda de tu local sin invitarla a entrar.
    con_gasto = [c for c in campanas if c.get("gasto")]
    if con_gasto and all(c.get("objetivo") in OBJETIVOS_DE_VITRINA for c in con_gasto):
        hallazgos.append(_hallazgo(
            ALTA, nombre, "Todas las campañas persiguen interacción, no clientes",
            f"Las {len(con_gasto)} campañas con gasto usan un objetivo de interacción. "
            "Meta optimiza literalmente por lo que le pedís: si le pedís reacciones, sale a "
            "buscar gente que reacciona. Para vender un servicio, eso trae público barato "
            "que no compra.",
            "Si el negocio es vender (no dar a conocer), probá una campaña con objetivo de "
            "clientes potenciales o de ventas contra el mismo público, y compará el costo "
            "por cliente real, no por conversación."))

    # ── campaña por campaña ───────────────────────────────────────────────
    for c in campanas:
        n, gasto = c.get("nombre", "?"), c.get("gasto") or 0
        costo, res = c.get("costo_resultado"), c.get("resultados")
        etiqueta = c.get("etiqueta_resultado", "resultados")
        singular = c.get("singular_resultado") or "resultado"

        if not gasto:
            hallazgos.append(_hallazgo(
                BAJA, n, "Nunca gastó",
                "La campaña existe pero no llegó a invertir nada.",
                "O la activás con presupuesto, o la archivás para no seguir mirándola."))
            continue

        if res is None:
            hallazgos.append(_hallazgo(
                ALTA, n, f"Gastó {gasto:,.0f} {moneda} sin registrar ningún resultado",
                f"Meta no reporta ni un solo {singular} "
                "para el objetivo de esta campaña. Casi siempre significa que el evento "
                "no está configurado, no que nadie haya respondido.",
                "Revisá que el objetivo y el evento de conversión estén bien puestos. "
                "Plata gastada sin poder medir el resultado es plata que no sabés si sirvió."))
            continue

        # Un costo espectacular sobre una muestra chica no es un hallazgo, es ruido.
        # Decirlo evita escalar un número lindo que después no se sostiene.
        impresiones = c.get("impresiones") or 0
        dias = c.get("ventana_dias")
        if med and costo and costo <= med / VECES_CARA and impresiones < IMPRESIONES_MINIMAS:
            hallazgos.append(_hallazgo(
                MEDIA, n, "El mejor costo de la cuenta, pero sobre muy poca muestra",
                f"Consiguió {res:,.0f} {etiqueta} con solo {impresiones:,.0f} impresiones"
                + (f", sobre una ventana de {dias} días. " if dias else ". ") +
                "Con tan poco volumen, el costo puede ser un hallazgo real o puede ser suerte.",
                "Antes de mover presupuesto, dejala correr hasta juntar volumen y mirá si "
                "el costo se sostiene. Escalar sobre una muestra chica es la forma más "
                "común de quemar plata persiguiendo un número que no era."))

        # El chequeo cruzado: una métrica de vidriera NO alarma sola.
        ctr = c.get("ctr")
        costo_ok = med is not None and costo is not None and costo <= med
        if ctr is not None and ctr < CTR_FLOJO and not costo_ok:
            hallazgos.append(_hallazgo(
                MEDIA, n, f"CTR {ctr:.2f}% y el costo no lo compensa",
                "Poca gente hace clic, y el costo por resultado tampoco está mejor que "
                "el resto de tus campañas. Acá el problema sí es el anuncio.",
                "Probá otro gancho en la primera línea o cambiá la imagen. El CTR bajo "
                "solo importa cuando el resultado también sale caro."))

        f = c.get("frecuencia")
        if f and f >= FRECUENCIA_QUEMA:
            hallazgos.append(_hallazgo(
                MEDIA, n, f"Frecuencia {f:.1f}",
                "Le estás mostrando lo mismo a la misma gente una y otra vez.",
                "Ampliá el público o rotá la creatividad."))

        if med and costo and costo >= med * VECES_CARA:
            hallazgos.append(_hallazgo(
                ALTA, n, f"Cada {singular} te cuesta {costo:,.0f} {moneda}",
                f"Es {costo/med:.1f} veces la mediana de esta cuenta ({med:,.0f} {moneda}). "
                "Estás pagando de más por lo mismo.",
                "Antes de subirle presupuesto, mirá qué hace distinto la campaña que "
                "consigue lo mismo más barato y copiá eso."))

        # Lo bueno también es un hallazgo: una campaña pausada que rendía es la plata
        # más barata que existe, porque ya sabés que funciona.
        if med and costo and costo <= med / VECES_CARA and c.get("estado") == "PAUSED":
            hallazgos.append(_hallazgo(
                MEDIA, n, "Pausada, y era la más eficiente",
                f"Conseguía cada {singular} a "
                f"{costo:,.0f} {moneda}, contra una mediana de {med:,.0f}. Está apagada.",
                "Revisá por qué se pausó. Si no hubo un motivo de fondo, es lo primero "
                "que volvería a encender."))

    orden = {ALTA: 0, MEDIA: 1, BAJA: 2}
    hallazgos.sort(key=lambda h: orden[h["gravedad"]])
    return hallazgos


def lo_que_funciona(cuenta):
    """Lo que SÍ está andando. Un informe que solo trae problemas se lee como un reto,
    y a los dos días nadie lo abre más."""
    bien = []
    campanas = [c for c in cuenta.get("campanas", []) if c.get("costo_resultado")]
    if not campanas:
        return bien
    moneda = cuenta.get("moneda", "")
    mejor = min(campanas, key=lambda c: c["costo_resultado"])
    singular = mejor.get("singular_resultado") or "resultado"
    bien.append(f"«{mejor['nombre']}» es tu campaña más eficiente: cada {singular} "
                f"te costó {mejor['costo_resultado']:,.0f} {moneda}.")
    med = mediana_costo(campanas)
    if med and mejor["costo_resultado"] < med / VECES_CARA:
        bien.append(f"Y no por poco: cuesta {med/mejor['costo_resultado']:.0f} veces menos "
                    "que la mediana de la cuenta. Ahí hay algo que vale la pena repetir.")
    return bien


def auditar(cuentas):
    """El informe completo de todas las cuentas."""
    salida = []
    for c in cuentas:
        hallazgos = revisar_cuenta(c)
        salida.append({
            "cuenta": c.get("nombre", "?"),
            "moneda": c.get("moneda", ""),
            "hallazgos": hallazgos,
            "funciona": lo_que_funciona(c),
            "graves": sum(1 for h in hallazgos if h["gravedad"] == ALTA),
        })
    return salida


def _autochequeo():
    def camp(nombre, gasto=1000, costo=100, res=10, ctr=2.0, freq=1.5, estado="ACTIVE"):
        return {"nombre": nombre, "gasto": gasto, "costo_resultado": costo,
                "resultados": res, "ctr": ctr, "frecuencia": freq, "estado": estado,
                "etiqueta_resultado": "conversaciones",
                "singular_resultado": "conversación",
                "objetivo": "OUTCOME_SALES", "impresiones": 50000}

    def cuenta(campanas, activa=True, freq=1.5):
        return {"nombre": "Test", "moneda": "ARS", "activa": activa,
                "total": {"frecuencia": freq}, "campanas": campanas}

    titulos = lambda hs: [h["titulo"] for h in hs]

    # ── EL chequeo que importa: CTR feo pero costo excelente NO es un problema ──
    base = [camp("a", costo=100), camp("b", costo=100), camp("c", costo=100)]
    barata = camp("eficiente", costo=10, ctr=0.5)   # CTR horrible, costo 10x mejor
    hs = revisar_cuenta(cuenta(base + [barata]))
    assert not any("CTR" in t for t in titulos(hs)), \
        "alarmó por CTR en la campaña más barata de la cuenta"
    # Pero si el costo TAMBIÉN es malo, ahí sí se avisa.
    cara = camp("cara", costo=300, ctr=0.5)
    assert any("CTR" in t for t in titulos(revisar_cuenta(cuenta(base + [cara])))), \
        "no avisó de un CTR bajo que además sale caro"

    # ── gastó sin resultados ──────────────────────────────────────────────
    muda = camp("muda", gasto=5000, costo=None, res=None)
    hs = revisar_cuenta(cuenta([muda]))
    assert any("sin registrar" in t for t in titulos(hs)), titulos(hs)
    assert hs[0]["gravedad"] == ALTA, "no le dio gravedad alta a plata sin medir"

    # ── nunca gastó ───────────────────────────────────────────────────────
    hs = revisar_cuenta(cuenta([camp("vacia", gasto=0, costo=None, res=None)]))
    assert titulos(hs) == ["Nunca gastó"], titulos(hs)

    # ── cuenta inactiva y frecuencia de cuenta ────────────────────────────
    hs = revisar_cuenta(cuenta(base, activa=False, freq=4.5))
    assert any("no está activa" in t for t in titulos(hs))
    assert any("Frecuencia 4.5" in t for t in titulos(hs))
    assert hs[0]["gravedad"] == ALTA, "los problemas graves tienen que ir primero"

    # ── cara vs mediana ───────────────────────────────────────────────────
    hs = revisar_cuenta(cuenta(base + [camp("carisima", costo=500)]))
    assert any("te cuesta 500" in t for t in titulos(hs)), titulos(hs)

    # ── pausada y eficiente = oportunidad ─────────────────────────────────
    hs = revisar_cuenta(cuenta(base + [camp("dormida", costo=20, estado="PAUSED")]))
    assert any("era la más eficiente" in t for t in titulos(hs)), titulos(hs)

    # ── sin mediana no se inventan comparaciones ──────────────────────────
    hs = revisar_cuenta(cuenta([camp("sola", costo=9999)]))
    assert not any("te cuesta" in t for t in titulos(hs)), \
        "comparó contra una mediana que no existe (1 sola campaña)"

    # ── objetivo de vitrina en toda la cuenta ─────────────────────────────
    vitrina = [dict(camp(f"v{i}"), objetivo="OUTCOME_ENGAGEMENT") for i in range(3)]
    hs = revisar_cuenta(cuenta(vitrina))
    assert any("no clientes" in x for x in titulos(hs)), titulos(hs)
    # Si hay al menos una de ventas, ya no aplica.
    mixto = vitrina + [dict(camp("ventas"), objetivo="OUTCOME_SALES")]
    assert not any("no clientes" in x for x in titulos(revisar_cuenta(cuenta(mixto)))), \
        "alarmó por objetivo aunque había una campaña de ventas"

    # ── muestra chica ─────────────────────────────────────────────────────
    chica = dict(camp("prueba", costo=10), impresiones=105, ventana_dias=2)
    hs = revisar_cuenta(cuenta(base + [chica]))
    assert any("poca muestra" in x for x in titulos(hs)), titulos(hs)
    grande = dict(camp("solida", costo=10), impresiones=50000)
    assert not any("poca muestra" in x for x in titulos(revisar_cuenta(cuenta(base + [grande])))), \
        "avisó de muestra chica sobre 50.000 impresiones"

    # ── lo que funciona ───────────────────────────────────────────────────
    bien = lo_que_funciona(cuenta(base + [barata]))
    assert bien and "eficiente" in bien[0], bien
    assert "conversacione " not in bien[0], "cortó la s en vez de usar el singular"

    # ── informe completo ──────────────────────────────────────────────────
    inf = auditar([cuenta([muda])])
    assert inf[0]["graves"] == 1 and inf[0]["cuenta"] == "Test"

    print("auditoria.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
