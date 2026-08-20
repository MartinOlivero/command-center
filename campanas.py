#!/usr/bin/env python3
"""
campanas.py — Campañas de Meta Ads en el panel.

POR QUÉ EXISTE (y por qué no alcanza con el Administrador de Anuncios)
Meta ya te muestra gasto, CTR y CPM. Lo que NO te muestra es el costo por el resultado que
te importa a vos, ni cómo se compara tu plata contra lo que conseguís gratis. Eso es lo
único que justifica traer esto acá.

EL NÚMERO QUE IMPORTA
El CTR no paga sueldos. Si la campaña es de mensajes, lo que importa es cuánto te costó
cada conversación; si es de ventas, cada venta. Por eso acá el "resultado" se elige según
el OBJETIVO de la campaña, no se muestra siempre lo mismo.

Es la diferencia entre "vinieron 19.000 personas al local" y "de todas esas, 81 se
acercaron a preguntar, y cada una te costó tanto".

MULTI-CUENTA
No hay nada que configurar más allá del token: se listan todas las cuentas que ese token
puede ver. Pensado para agencia — las cuentas de clientes aparecen con su nombre, así
nunca se confunden con las propias.

CONFIGURACIÓN
En el `.env` de la raíz del repo:

    META_ADS_TOKEN=EAAxxxx     # System User con ads_read (no vence)

Sin esa variable, el módulo no hace nada y el panel simplemente no muestra la sección.

Autochequeo (no toca la red):
    python3 campanas.py
"""

import datetime
import json

import segmentos

# La acción que cuenta como "resultado", según qué se propuso la campaña. Meta devuelve
# decenas de tipos de acción; casi todos son ruido. Estos son los que significan algo.
# El orden importa: se usa el primero que exista.
# Cada entrada guarda (acciones, plural, singular): el singular es para "cuesta X por
# conversación" — sin él la frase queda "por cada uno de los conversaciones".
# Meta NO elige el resultado por el objetivo de la campaña, sino por lo que OPTIMIZA el
# conjunto de anuncios. Dos campañas de "Tráfico" pueden reportar cosas distintas: una
# cuenta clics en el enlace y la otra visitas a la pagina que llegaron a cargar.
# Medido el 18/08/2026: el panel mostraba 387 clics y el telefono 490 visitas, porque los
# conjuntos optimizan LANDING_PAGE_VIEWS y el panel tenia link_click fijo.
RESULTADO_POR_OPTIMIZACION = {
    "LANDING_PAGE_VIEWS": (["landing_page_view"], "visitas al sitio", "visita"),
    "LINK_CLICKS": (["link_click"], "clics al sitio", "clic"),
    "OFFSITE_CONVERSIONS": (["offsite_conversion.fb_pixel_purchase", "purchase", "lead"],
                            "conversiones", "conversión"),
    "LEAD_GENERATION": (["lead", "onsite_conversion.lead_grouped"], "leads", "lead"),
    "QUALITY_LEAD": (["lead", "onsite_conversion.lead_grouped"], "leads", "lead"),
    "CONVERSATIONS": (["onsite_conversion.total_messaging_connection",
                       "onsite_conversion.messaging_first_reply"], "conversaciones", "conversación"),
    "REACH": ([], "alcance", "persona alcanzada"),
    "IMPRESSIONS": ([], "alcance", "persona alcanzada"),
    "THRUPLAY": (["video_view"], "reproducciones", "reproducción"),
    "APP_INSTALLS": (["app_install"], "instalaciones", "instalación"),
}

RESULTADO_POR_OBJETIVO = {
    "OUTCOME_ENGAGEMENT": (
        ["onsite_conversion.total_messaging_connection", "onsite_conversion.messaging_first_reply",
         "post_engagement"],
        "conversaciones", "conversación",
    ),
    "OUTCOME_LEADS": (["lead", "onsite_conversion.lead_grouped"], "leads", "lead"),
    "OUTCOME_SALES": (["purchase", "offsite_conversion.fb_pixel_purchase"], "ventas", "venta"),
    "OUTCOME_TRAFFIC": (["link_click"], "clics al sitio", "clic"),
    "OUTCOME_APP_PROMOTION": (["app_install"], "instalaciones", "instalación"),
    "OUTCOME_AWARENESS": ([], "alcance", "persona alcanzada"),
}
# Para campañas viejas con los objetivos anteriores a 2023.
RESULTADO_POR_OBJETIVO.update({
    "MESSAGES": RESULTADO_POR_OBJETIVO["OUTCOME_ENGAGEMENT"],
    "LEAD_GENERATION": RESULTADO_POR_OBJETIVO["OUTCOME_LEADS"],
    "CONVERSIONS": RESULTADO_POR_OBJETIVO["OUTCOME_SALES"],
    "LINK_CLICKS": RESULTADO_POR_OBJETIVO["OUTCOME_TRAFFIC"],
    "POST_ENGAGEMENT": RESULTADO_POR_OBJETIVO["OUTCOME_ENGAGEMENT"],
})

CAMPOS_INSIGHTS = ("spend,impressions,reach,clicks,ctr,cpm,cpc,frequency,"
                   "actions,cost_per_action_type,date_start,date_stop")

# Arriba de esta frecuencia le estás mostrando lo mismo a la misma gente una y otra vez.
# El CPM sube solo y el rendimiento cae: es saturación, no mala creatividad.
FRECUENCIA_QUEMA = 3.0


def ventana(preset="maximum"):
    """Los parametros de fecha para pedirle datos a Meta.

    `date_preset=maximum` de la API **deja afuera el dia en curso**: devuelve hasta ayer.
    La app de Meta en el telefono SI cuenta el dia de hoy, asi que el panel mostraba
    numeros mas chicos que el celular y parecia roto. Medido el 18/08/2026: la API daba
    15,29 USD y el telefono 19,41 — la diferencia era exactamente el dia de hoy.

    Con `time_range` explicito hasta hoy, los dos numeros coinciden. Ojo: el dia en curso
    es PARCIAL y Meta lo sigue ajustando por algunas horas, que es probablemente el motivo
    por el que su preset lo excluye.
    """
    if preset != "maximum":
        return {"date_preset": preset}
    hoy = datetime.date.today()
    # Meta rechaza rangos que arranquen a mas de 37 meses: devuelve el aviso #3018 y
    # descarta la consulta. Se pide 36 para tener margen; es "todo el historico" en la
    # practica, porque una cuenta publicitaria de 3 años ya es vieja.
    desde = hoy - datetime.timedelta(days=int(36 * 30.4))
    return {"time_range": json.dumps({"since": desde.isoformat(), "until": hoy.isoformat()})}


def _dias_entre(desde, hasta):
    """Cuántos días cubre un rango de Meta (ambos inclusive). None si falta alguno."""
    if not desde or not hasta:
        return None
    try:
        d = datetime.date.fromisoformat(desde)
        h = datetime.date.fromisoformat(hasta)
        return (h - d).days + 1
    except ValueError:
        return None


def _num(v):
    """Meta manda casi todo como texto. Devuelve float o None, nunca revienta."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resultado(fila, objetivo, optimiza=None):
    """Cuántos resultados consiguió y cuánto costó cada uno.

    `optimiza` es el `optimization_goal` del conjunto de anuncios y MANDA sobre el objetivo
    de la campaña: es lo que usa Meta para decidir qué llama "resultado", y sin eso el panel
    reportaba una métrica distinta a la que el usuario ve en su celular.

    Devuelve (cantidad, costo_unitario, plural, singular). La cantidad y el costo pueden
    ser None: es mejor mostrar un guion que inventar una conversión que Meta no reportó.
    """
    claves, etiqueta, singular = (
        RESULTADO_POR_OPTIMIZACION.get(optimiza)
        or RESULTADO_POR_OBJETIVO.get(objetivo, ([], "resultados", "resultado")))
    acciones = {a.get("action_type"): _num(a.get("value")) for a in (fila.get("actions") or [])}
    costos = {a.get("action_type"): _num(a.get("value"))
              for a in (fila.get("cost_per_action_type") or [])}

    for k in claves:
        if acciones.get(k):
            return acciones[k], costos.get(k), etiqueta, singular

    # Campañas de reconocimiento: el "resultado" es la gente alcanzada.
    if objetivo in ("OUTCOME_AWARENESS", "REACH", "BRAND_AWARENESS") or optimiza in ("REACH", "IMPRESSIONS"):
        alcance, gasto = _num(fila.get("reach")), _num(fila.get("spend"))
        if alcance:
            return alcance, (gasto / alcance if gasto else None), etiqueta, singular
    return None, None, etiqueta, singular


def lectura(fila, objetivo, moneda=""):
    """SOLO los problemas. Lista de frases cortas, o vacía si no hay nada que decir.

    El costo por resultado NO va acá aunque sea el número más importante: ya se devuelve
    como `costo_resultado` y el panel lo muestra en su propia columna. Repetirlo como
    "nota" llenaba la pantalla de la misma cifra dos veces, y una alarma que aparece
    siempre deja de leerse como alarma.
    """
    notas = []
    freq = _num(fila.get("frequency"))
    ctr = _num(fila.get("ctr"))
    cant, _costo, _, _singular = resultado(fila, objetivo)

    if freq and freq >= FRECUENCIA_QUEMA:
        notas.append(f"frecuencia {freq:.1f}: le estás mostrando lo mismo a la misma gente")
    if ctr is not None and ctr < 1:
        notas.append(f"CTR {ctr:.2f}%: el anuncio no engancha a quien lo ve")
    if cant is None and _num(fila.get("spend")):
        # Gastó y Meta no reporta ninguna acción del objetivo: o está mal configurada,
        # o el objetivo no genera acciones medibles. Vale avisarlo.
        notas.append("gastó sin registrar ningún resultado del objetivo")
    return notas


def resumen_cuenta(fila):
    """Los números de la cuenta entera, ya convertidos a número."""
    if not fila:
        return None
    return {
        "gasto": _num(fila.get("spend")),
        "impresiones": _num(fila.get("impressions")),
        "alcance": _num(fila.get("reach")),
        "clics": _num(fila.get("clicks")),
        "ctr": _num(fila.get("ctr")),
        "cpm": _num(fila.get("cpm")),
        "cpc": _num(fila.get("cpc")),
        "frecuencia": _num(fila.get("frequency")),
    }


def comparar_con_organico(gasto, alcance_pago, alcance_organico, moneda="ARS"):
    """Cuánto te costó cada persona alcanzada con plata, contra las que llegaste gratis.

    Es la comparación que ninguna herramienta de ads te hace, porque las herramientas de
    ads no saben qué pasa en tu contenido orgánico. Si pagar sale caro y tu contenido
    gratis llega a más gente, la plata está tapando un problema en vez de resolverlo.

    ⚠️ LOS DOS ALCANCES TIENEN QUE SER DEL MISMO PERÍODO. Comparar el gasto histórico de
    dos años contra el alcance orgánico de 30 días da un resultado que parece profundo y
    no significa nada. Por eso quien llama tiene que pasar el alcance pago DEL MISMO RANGO
    que usa el panel, no el total de la cuenta.
    """
    if not gasto or not alcance_pago:
        return None
    costo = gasto / alcance_pago
    texto = f"Cada persona alcanzada con plata te costó {costo:,.0f} {moneda}."
    if alcance_organico:
        veces = alcance_organico / alcance_pago
        if veces >= 1.5:
            texto += (f" Tu contenido orgánico llegó a {veces:.1f} veces más gente sin pagar: "
                      "antes de subir el presupuesto, mirá qué está haciendo bien lo que no pagás.")
        elif veces <= 0.5:
            texto += " La pauta te está llevando más lejos que tu contenido orgánico."
    return {"costo_por_persona": round(costo, 2), "texto": texto}


CAMPOS_VIDEO = ("video_p25_watched_actions,video_p50_watched_actions,"
                "video_p75_watched_actions,video_p100_watched_actions")

# Una posicion que se lleva mucha menos plata de la que merece por rendimiento.
# 1.5 = trae un 50% mas de clics de los que le tocarian por lo que costo; abajo de
# eso puede ser ruido y no vale la pena avisar.
POSICION_DESAPROVECHADA = 1.5


def _accion(fila, campo):
    """Los campos de video vienen como lista de acciones, no como numero suelto."""
    v = (fila.get(campo) or [{}])[0].get("value")
    return _num(v)


def retencion_video(fila):
    """Cuantos llegaron al 25/50/75/100% del video, y que parte del arranque es.

    Es la MISMA lectura que el panel ya muestra para YouTube. Separa dos problemas que
    se confunden: que el video no enganche (se cae del 25 al 50) o que aburra promediando
    (llega al 50 y no termina).
    """
    p25 = _accion(fila, "video_p25_watched_actions")
    if not p25:
        return None
    etapas = [("25%", p25), ("50%", _accion(fila, "video_p50_watched_actions")),
              ("75%", _accion(fila, "video_p75_watched_actions")),
              ("100%", _accion(fila, "video_p100_watched_actions"))]
    # Sobre los que llegaron al 25%, NO sobre las impresiones: una impresion puede ser
    # medio segundo de scroll, y dividir por eso da porcentajes que no significan nada.
    return {"etapas": [{"hito": h, "gente": int(v or 0),
                        "parte": round((v or 0) / p25, 4)} for h, v in etapas],
            "termina": round((_accion(fila, "video_p100_watched_actions") or 0) / p25, 4)}


def creativo(ad):
    """La imagen/video y el texto del aviso, para poder VER que se publico.

    Sin esto la lista es de nombres internos ("C · imagen · la cuenta") y no hay forma
    de saber que pieza fue la que rindio.
    """
    c = ad.get("creative") or {}
    return {
        "miniatura": c.get("thumbnail_url") or c.get("image_url") or "",
        "es_video": bool(c.get("video_id")),
        "texto": (c.get("body") or "").strip(),
        "titular": (c.get("title") or "").strip(),
        "preview": ad.get("preview_shareable_link") or "",
    }


# Que significa que cada metrica suba. None = ni bueno ni malo, solo informa.
# Esta tabla es todo el criterio: sin ella un CPM que baja se pintaba de rojo
# ("bajo") cuando en realidad es la mejor noticia del dia.
DIRECCION = {
    "ctr":        ("CTR", True,  "de cada 100 que lo vieron, más lo tocaron"),
    "cpm":        ("CPM", False, "te sale más barato que mil personas lo vean"),
    "cpc":        ("costo por clic", False, "cada clic te cuesta menos"),
    "frecuencia": ("frecuencia", False, "le estás mostrando lo mismo a la misma gente"),
    "clics":      ("clics", True, "más gente entró"),
    "alcance":    ("alcance", True, "le llegó a más gente distinta"),
    "gasto":      ("gasto", None, "cuánto se invirtió ese día"),
}

# Abajo de esto es ruido: un CTR que pasa de 6,00% a 6,15% no es una mejora, es el
# mismo dia con otra gente. Marcarlo de verde entrena a no creerle a los colores.
CAMBIO_MINIMO = 8.0


def tendencias(serie, hoy=None):
    """Compara el ultimo dia CERRADO contra el promedio de los anteriores.

    Dos decisiones que hacen la diferencia entre un indicador util y uno que miente:

    1. **El dia de hoy se excluye.** Esta a medio correr: compararlo contra dias
       completos siempre da peor y el panel avisaria de una caida que no existe.
    2. **Contra el promedio de los previos**, no contra el dia anterior suelto. Un
       martes flojo no significa que la campaña se cayo.

    Devuelve [] cuando no hay al menos dos dias cerrados: es preferible no decir nada
    a dibujar una flecha con un dato.
    """
    hoy = hoy or datetime.date.today().isoformat()
    cerrados = [d for d in serie if d.get("dia") and d["dia"] < hoy and (d.get("gasto") or 0) > 0]
    if len(cerrados) < 2:
        return []
    ultimo, previos = cerrados[-1], cerrados[:-1][-7:]      # hasta una semana de contexto
    salida = []
    for clave, (etiqueta, subir_es_bueno, porque) in DIRECCION.items():
        actual = ultimo.get(clave)
        base = [d[clave] for d in previos if d.get(clave) is not None]
        if actual is None or not base:
            continue
        promedio = sum(base) / len(base)
        if not promedio:
            continue
        pct = (actual - promedio) / promedio * 100
        subio = pct > 0
        if abs(pct) < CAMBIO_MINIMO or subir_es_bueno is None:
            estado = "neutro"
        else:
            estado = "bien" if subio == subir_es_bueno else "mal"
        salida.append({
            "metrica": clave, "etiqueta": etiqueta,
            "valor": round(actual, 4), "antes": round(promedio, 4),
            "pct": round(pct, 1), "estado": estado,
            "dia": ultimo["dia"], "dias_base": len(base),
            "porque": porque,
        })
    return salida


def posiciones(get, graph, token, act_id, preset="maximum"):
    """Donde se mostro cada peso: feed, stories o reels, en Facebook o Instagram.

    Meta reparte solo cuando la campaña esta en automatico, y no siempre acierta: es
    normal que la posicion que mejor convierte reciba una fraccion del presupuesto.
    `rinde` es la relacion entre la parte de los clics y la parte del gasto: arriba de
    1 trae mas clics de los que le corresponderian por lo que costo.
    """
    filas = get(f"{graph}/{act_id}/insights", fields="spend,impressions,clicks,ctr,reach",
                breakdowns="publisher_platform,platform_position",
                **ventana(preset), limit=50, access_token=token)
    datos = filas.get("data", [])
    gasto_total = sum(_num(f.get("spend")) or 0 for f in datos)
    clics_total = sum(_num(f.get("clicks")) or 0 for f in datos)
    salida = []
    for f in datos:
        gasto = _num(f.get("spend")) or 0
        clics = _num(f.get("clicks")) or 0
        parte_gasto = (gasto / gasto_total) if gasto_total else 0
        parte_clics = (clics / clics_total) if clics_total else 0
        salida.append({
            "plataforma": f.get("publisher_platform", ""),
            "posicion": f.get("platform_position", ""),
            "gasto": round(gasto, 2),
            "clics": int(clics),
            "ctr": _num(f.get("ctr")),
            "impresiones": _num(f.get("impressions")),
            "parte_gasto": round(parte_gasto, 4),
            "parte_clics": round(parte_clics, 4),
            "rinde": round(parte_clics / parte_gasto, 2) if parte_gasto else None,
        })
    salida.sort(key=lambda x: -x["gasto"])
    return salida


def por_dia(get, graph, token, act_id, preset="maximum"):
    """Gasto, clics y CTR dia por dia. Con dos dias no dice nada; a las dos semanas
    muestra si la campaña se esta quemando o mejorando."""
    filas = get(f"{graph}/{act_id}/insights",
                fields="spend,clicks,ctr,cpm,cpc,frequency,impressions,reach",
                time_increment=1, **ventana(preset), limit=200, access_token=token)
    return [{"dia": f.get("date_start", ""),
             "gasto": round(_num(f.get("spend")) or 0, 2),
             "clics": int(_num(f.get("clicks")) or 0),
             "ctr": _num(f.get("ctr")),
             "cpm": _num(f.get("cpm")),
             "cpc": _num(f.get("cpc")),
             "frecuencia": _num(f.get("frequency")),
             "alcance": _num(f.get("reach"))} for f in filas.get("data", [])]


def bajar(get, graph, token, act_id, preset="maximum", moneda=""):
    """Todo lo de una cuenta: totales, campañas y sus lecturas.

    `moneda` se arrastra hasta las lecturas: sin eso, una cuenta en dólares mostraba
    sus costos en pesos. `get` se pasa como argumento para poder probar sin red.
    """
    cuenta = get(f"{graph}/{act_id}/insights",
                 fields=CAMPOS_INSIGHTS, **ventana(preset), access_token=token)
    total = resumen_cuenta((cuenta.get("data") or [None])[0])

    # El objetivo NO viene en insights: hay que traerlo de la campaña y cruzarlo por id.
    objetivos = {}
    camps = get(f"{graph}/{act_id}/campaigns",
                fields="id,name,status,objective,created_time,start_time,stop_time",
                limit=100, access_token=token)
    for c in camps.get("data", []):
        objetivos[c["id"]] = {
            "objetivo": c.get("objective", ""), "estado": c.get("status", ""),
            # Cuándo existió: sin esto no se puede saber si una prueba corrió dos días
            # o dos meses, y eso cambia por completo cuánto confiar en su costo.
            "creada": (c.get("created_time") or "")[:10],
            "arranco": (c.get("start_time") or "")[:10],
            "paro": (c.get("stop_time") or "")[:10],
        }

    # Que optimiza cada conjunto: es lo que define el "resultado" que reporta Meta.
    # Una campaña puede tener conjuntos con optimizaciones distintas; se guarda el de
    # cada conjunto y, para el total de la campaña, el que mas se repite.
    opt_por_conjunto, opt_por_campana = {}, {}
    sets = get(f"{graph}/{act_id}/adsets", fields="id,name,optimization_goal,campaign_id",
               limit=200, access_token=token)
    for s in sets.get("data", []):
        meta_opt = s.get("optimization_goal")
        if not (s.get("id") and meta_opt):
            continue           # un conjunto sin id ni optimizacion no aporta nada
        opt_por_conjunto[s["id"]] = meta_opt
        opt_por_campana.setdefault(s.get("campaign_id"), []).append(meta_opt)
    opt_campana = {c: max(set(v), key=v.count) for c, v in opt_por_campana.items() if v}

    filas = get(f"{graph}/{act_id}/insights", level="campaign",
                fields="campaign_id,campaign_name," + CAMPOS_INSIGHTS,
                **ventana(preset), limit=100, access_token=token)

    campanas = []
    for f in filas.get("data", []):
        meta = objetivos.get(f.get("campaign_id"), {})
        obj = meta.get("objetivo", "")
        cant, costo, etiqueta, singular = resultado(
            f, obj, opt_campana.get(f.get("campaign_id")))
        campanas.append({
            "id": f.get("campaign_id", ""),
            "nombre": f.get("campaign_name", "?"),
            "estado": meta.get("estado", "?"),
            "objetivo": obj,
            "creada": meta.get("creada", ""),
            "arranco": meta.get("arranco", ""),
            "paro": meta.get("paro", ""),
            # OJO: esto es la ventana CONSULTADA, no los días que la campaña estuvo
            # corriendo. Con date_preset=maximum devuelve todo el historial de la cuenta,
            # así que una campaña que gastó 3 días igual reporta 368. Para saber cuánto
            # corrió de verdad están `arranco` y `paro`, que sí son de la campaña.
            "ventana_desde": f.get("date_start", ""),
            "ventana_hasta": f.get("date_stop", ""),
            "ventana_dias": _dias_entre(f.get("date_start"), f.get("date_stop")),
            **resumen_cuenta(f),
            "resultados": cant,
            "costo_resultado": costo,
            "etiqueta_resultado": etiqueta,
            # El singular viaja con el dato: "cada conversación", no "cada
            # conversacione". Sacar la "s" final funciona en inglés, no acá.
            "singular_resultado": singular,
            "optimiza": opt_campana.get(f.get("campaign_id")) or "",
            "lectura": lectura(f, obj, moneda),
        })
    # La que más gastó primero: es donde está la plata y donde primero hay que mirar.
    campanas.sort(key=lambda c: -(c.get("gasto") or 0))

    # ---- Nivel anuncio -------------------------------------------------------
    # La campaña dice CUANTA plata se fue; el anuncio dice CUAL de las piezas la
    # hizo rendir. Sin esto no se puede saber si conviene el video o la imagen,
    # que es la unica decision que la persona puede tomar el lunes a la mañana.
    # Los campos de video viajan en la MISMA llamada: pedirlos aparte seria otra
    # ida a la API para datos de las mismas filas.
    filas_ads = get(f"{graph}/{act_id}/insights", level="ad",
                    fields="ad_id,ad_name,adset_id,adset_name,campaign_id," + CAMPOS_INSIGHTS
                           + "," + CAMPOS_VIDEO,
                    **ventana(preset), limit=200, access_token=token)
    con_datos = {}
    for f in filas_ads.get("data", []):
        obj = objetivos.get(f.get("campaign_id"), {}).get("objetivo", "")
        cant, costo, etiqueta, singular = resultado(
            f, obj, opt_por_conjunto.get(f.get("adset_id")))
        con_datos[f.get("ad_id")] = {
            "id": f.get("ad_id", ""),
            "campana_id": f.get("campaign_id", ""),
            "nombre": f.get("ad_name", "?"),
            "conjunto": f.get("adset_name", ""),
            **resumen_cuenta(f),
            "resultados": cant,
            "costo_resultado": costo,
            "etiqueta_resultado": etiqueta,
            "singular_resultado": singular,
            "optimiza": opt_por_conjunto.get(f.get("adset_id")) or "",
            "video": retencion_video(f),
        }

    # Los anuncios que todavia no gastaron NO vuelven en insights. Si solo mostraramos
    # esos, alguien con 5 anuncios ve 3 y cree que el panel se comio dos. Los pedimos
    # aparte y los marcamos como "sin datos", que es distinto de "no existe".
    lista = get(f"{graph}/{act_id}/ads",
                fields="id,name,status,campaign_id,adset{name},preview_shareable_link,"
                       "creative{thumbnail_url,image_url,video_id,body,title}",
                limit=200, access_token=token)
    anuncios = []
    for a in lista.get("data", []):
        fila = con_datos.get(a.get("id"))
        if fila:
            fila["estado"] = a.get("status", "")
            fila.update(creativo(a))
            anuncios.append(fila)
        else:
            anuncios.append({
                "id": a.get("id", ""),
                "campana_id": a.get("campaign_id", ""),
                "nombre": a.get("name", "?"),
                "conjunto": (a.get("adset") or {}).get("name", ""),
                "estado": a.get("status", ""),
                "sin_datos": True,
                **creativo(a),
            })
    anuncios.sort(key=lambda a: -(a.get("gasto") or 0))
    for c in campanas:
        c["anuncios"] = [a for a in anuncios if a.get("campana_id") == c.get("id")]

    serie = por_dia(get, graph, token, act_id, preset)
    return {
        "total": total,
        "campanas": campanas,
        "anuncios": anuncios,
        "posiciones": posiciones(get, graph, token, act_id, preset),
        "por_dia": serie,
        "tendencias": tendencias(serie),
    }


def todo(get, graph, token, preset="maximum", dias=30):
    """Todas las cuentas que este token puede ver, con sus campañas.

    Se descubren solas: no hay que configurar ids. Las cuentas sin gasto se saltean —
    Meta crea cuentas vacías por su cuenta y llenarían el panel de ceros.

    Se bajan DOS ventanas por cuenta:
      - `preset` (por defecto el histórico completo): el panorama de la cuenta.
      - los últimos `dias`: la única que se puede comparar contra el alcance orgánico
        del panel, que también son esos días.
    Una cuenta pausada hace meses tiene histórico y no tiene período: es esperable, y
    por eso el bloque de comparación simplemente no aparece.
    """
    cuentas = get(f"{graph}/me/adaccounts",
                  fields="name,account_id,account_status,currency,amount_spent",
                  limit=50, access_token=token)
    salida = []
    for c in cuentas.get("data", []):
        if not _num(c.get("amount_spent")):
            continue
        act = f"act_{c['account_id']}"
        moneda = c.get("currency", "")
        datos = bajar(get, graph, token, act, preset, moneda)
        if not datos["total"] or not datos["total"].get("gasto"):
            continue
        # Meta a veces no devuelve `name` y quedaba el id crudo como título. Un número de
        # 16 dígitos no le dice nada a nadie.
        nombre = (c.get("name") or "").strip()
        if not nombre or nombre.isdigit():
            nombre = f"Cuenta {c['account_id'][-6:]}"
        # La misma ventana que usa el resto del panel, para poder comparar sin mentir.
        del_periodo = get(f"{graph}/{act}/insights", fields=CAMPOS_INSIGHTS,
                          date_preset=f"last_{dias}d", access_token=token)
        # A quién le funciona: el total de una cuenta es un promedio, y un promedio
        # esconde que un segmento rinde 5 veces mejor que otro con la misma plata.
        # Se usa el objetivo de la campaña que más gastó: es el que define qué se cuenta
        # como resultado en toda la cuenta.
        principal = datos["campanas"][0].get("objetivo", "") if datos["campanas"] else ""
        try:
            cortes = segmentos.bajar(get, graph, token, act, principal, preset)
        except Exception:
            cortes = {}
        salida.append({
            "id": act,
            "nombre": nombre,
            "segmentos": cortes,
            "hallazgos_segmentos": segmentos.analizar_todo(cortes, moneda) if cortes else [],
            "moneda": moneda,
            "activa": c.get("account_status") == 1,
            "periodo": resumen_cuenta((del_periodo.get("data") or [None])[0]),
            "dias": dias,
            **datos,
        })
    salida.sort(key=lambda c: -(c["total"].get("gasto") or 0))
    return salida


def _autochequeo():
    FILA = {
        "spend": "120853.75", "impressions": "19126", "reach": "11961", "clicks": "301",
        "ctr": "1.573774", "cpm": "6318.82", "cpc": "401.5", "frequency": "1.599",
        "date_start": "2026-01-01", "date_stop": "2026-01-03",
        "actions": [
            {"action_type": "link_click", "value": "71"},
            {"action_type": "post_engagement", "value": "4678"},
            {"action_type": "onsite_conversion.total_messaging_connection", "value": "81"},
        ],
        "cost_per_action_type": [
            {"action_type": "onsite_conversion.total_messaging_connection", "value": "1492.02"},
            {"action_type": "post_engagement", "value": "25.83"},
        ],
    }

    # ── el resultado se elige por objetivo, no siempre el mismo ────────────
    cant, costo, etiq, sing = resultado(FILA, "OUTCOME_ENGAGEMENT")
    assert (cant, etiq, sing) == (81.0, "conversaciones", "conversación"), (cant, etiq, sing)
    assert costo == 1492.02, "perdió el costo por resultado que ya calcula Meta"
    # Mismo dato, otro objetivo: el resultado tiene que ser otro.
    assert resultado(FILA, "OUTCOME_TRAFFIC")[0] == 71.0, "no usó link_click para tráfico"
    # Objetivo sin acción reportada: None, no un cero inventado.
    assert resultado({"spend": "100"}, "OUTCOME_SALES")[0] is None

    # ── lecturas ──────────────────────────────────────────────────────────
    # Una campaña sana no tiene nada que decir: la lectura son PROBLEMAS, no un resumen.
    assert lectura(FILA, "OUTCOME_ENGAGEMENT", "ARS") == [], \
        "avisó algo sobre una campaña que anda bien (¿volvió la nota del costo?)"

    quemada = dict(FILA, frequency="4.2", ctr="0.4")
    notas = lectura(quemada, "OUTCOME_ENGAGEMENT")
    assert any("frecuencia 4.2" in n for n in notas), "no avisó la saturación"
    assert any("CTR 0.40%" in n for n in notas), notas

    # Gastó y no registró nada del objetivo: hay que decirlo.
    muda = {"spend": "5000", "actions": []}
    assert any("sin registrar" in n for n in lectura(muda, "OUTCOME_SALES")), "se comió el aviso"

    # ── orgánico vs pago ──────────────────────────────────────────────────
    c = comparar_con_organico(120853.75, 11961, 30000)
    assert c and "2.5 veces más gente sin pagar" in c["texto"], c
    assert comparar_con_organico(120853.75, 11961, 2000)["texto"].endswith(
        "más lejos que tu contenido orgánico."), "no detectó que la pauta rinde mejor"
    assert comparar_con_organico(0, 100, 100) is None, "dividió por un gasto en cero"

    # ── bajar(): cruza el objetivo de campaigns con las filas de insights ──
    def get_falso(url, **p):
        if "/campaigns" in url:
            return {"data": [{"id": "c1", "name": "Mensajes", "status": "PAUSED",
                              "objective": "OUTCOME_ENGAGEMENT",
                              "created_time": "2025-09-20T10:00:00+0000",
                              "start_time": "2025-10-01T10:00:00+0000"}]}
        if p.get("level") == "campaign":
            return {"data": [dict(FILA, campaign_id="c1", campaign_name="Mensajes")]}
        return {"data": [FILA]}

    d = bajar(get_falso, "G", "T", "act_1")
    assert d["total"]["gasto"] == 120853.75, d["total"]
    (c1,) = d["campanas"]
    assert c1["resultados"] == 81.0 and c1["etiqueta_resultado"] == "conversaciones", c1
    assert c1["singular_resultado"] == "conversación", "no arrastró el singular"
    assert c1["ventana_dias"] == 3, f"mal el rango consultado: {c1['ventana_dias']}"
    assert c1["arranco"] == "2025-10-01", "no trajo la fecha de arranque de la campaña"
    assert _dias_entre(None, "2026-01-02") is None, "inventó días sin fecha de inicio"
    assert c1["estado"] == "PAUSED", "no cruzó el estado desde campaigns"

    # ── todo(): saltea cuentas vacías ─────────────────────────────────────
    def get_cuentas(url, **p):
        if "/adaccounts" in url:
            return {"data": [
                {"name": "Con datos", "account_id": "1", "currency": "ARS",
                 "account_status": 1, "amount_spent": "120853"},
                {"name": "Vacía", "account_id": "2", "currency": "USD",
                 "account_status": 1, "amount_spent": "0"},
            ]}
        return get_falso(url, **p)

    cuentas = todo(get_cuentas, "G", "T")
    assert len(cuentas) == 1 and cuentas[0]["nombre"] == "Con datos", \
        "mostró una cuenta publicitaria vacía"
    assert cuentas[0]["periodo"] is not None, "no bajó la ventana comparable del panel"

    # Sin nombre, no puede quedar el id crudo de 16 dígitos como título.
    def get_sin_nombre(url, **p):
        if "/adaccounts" in url:
            return {"data": [{"name": "1484035319439021", "account_id": "1484035319439021", "currency": "ARS",
                              "account_status": 1, "amount_spent": "120853"}]}
        return get_falso(url, **p)

    assert todo(get_sin_nombre, "G", "T")[0]["nombre"] == "Cuenta 439021", \
        "dejó el id crudo como nombre de la cuenta (Meta a veces manda el id como name)"

    # --- tendencias: lo unico con criterio propio, y lo mas facil de romper ---
    serie = [
        {"dia": "2026-08-14", "gasto": 5, "ctr": 4.0, "cpm": 1.20, "frecuencia": 1.05,
         "clics": 100, "alcance": 900, "cpc": 0.05},
        {"dia": "2026-08-15", "gasto": 5, "ctr": 4.0, "cpm": 1.20, "frecuencia": 1.05,
         "clics": 100, "alcance": 900, "cpc": 0.05},
        {"dia": "2026-08-16", "gasto": 5, "ctr": 6.0, "cpm": 0.80, "frecuencia": 1.40,
         "clics": 160, "alcance": 900, "cpc": 0.03},
        # El dia en curso, con numeros absurdos: si se colara en la comparacion,
        # los asserts de abajo fallarian.
        {"dia": "2026-08-17", "gasto": 9, "ctr": 9.9, "cpm": 0.10, "frecuencia": 9.0,
         "clics": 999, "alcance": 10, "cpc": 0.9},
    ]
    d = {x["metrica"]: x for x in tendencias(serie, hoy="2026-08-17")}
    assert d["ctr"]["estado"] == "bien", "un CTR que sube tiene que ser buena noticia"
    assert d["cpm"]["estado"] == "bien", "un CPM que BAJA es buena noticia, no mala"
    assert d["frecuencia"]["estado"] == "mal", "la frecuencia que sube es saturacion"
    assert d["gasto"]["estado"] == "neutro", "gastar mas no es bueno ni malo"
    assert all(x["dia"] == "2026-08-16" for x in d.values()), "no excluyo el dia en curso"
    assert tendencias(serie[:1]) == [], "con un solo dia cerrado no puede opinar"
    # Un cambio chico es ruido, no una mejora.
    plano = [dict(x, ctr=4.0, cpm=1.2, frecuencia=1.05) for x in serie[:3]]
    plano[-1]["ctr"] = 4.2                      # +5%, abajo del umbral
    assert {x["metrica"]: x for x in tendencias(plano, hoy="2026-08-17")}["ctr"]["estado"] == "neutro"

    print("campanas.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
