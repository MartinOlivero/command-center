#!/usr/bin/env python3
"""
competencia.py — Qué le funciona a otros, medido con lo único que las APIs dejan ver.

POR QUÉ EXISTE
Tu panel te dice qué te funciona A VOS. Eso alcanza para mejorar, no para descubrir:
si un tema no lo tocaste nunca, tus números no tienen forma de decirte que existe.
Los competidores son el único lugar donde ver demanda que todavía no atendiste.

QUÉ SE PUEDE VER Y QUÉ NO (probado contra las APIs el 2026-08-07)
  SE VE:     seguidores, cada pieza con su caption/título, likes, comentarios,
             formato, fecha y —en YouTube— la duración.
  NO SE VE:  alcance, impresiones, guardados, compartidos, retención, CTR.
             Son privados del dueño de la cuenta. Nadie los tiene: cualquier
             herramienta que te los muestre los está estimando.

LA CONSECUENCIA, Y CÓMO LA ESQUIVAMOS
Sin alcance no hay engagement rate real, así que comparar tu 7,2% contra "el de
ellos" sería comparar dos cosas distintas. Por eso acá NO se compara cuenta contra
cuenta: se mide cuánto se despegó cada pieza de la MEDIANA DE SU PROPIA CUENTA.
Un video con 10x la mediana del canal es una señal de tema ganador tenga ese canal
2.000 o 900.000 suscriptores, y no necesita un solo dato privado.

IG solo funciona con cuentas Business o Creator: una cuenta personal devuelve
"Invalid user id" y no hay vuelta que darle.

Autochequeo (no toca la red):
    python3 competencia.py
"""

import re
import statistics

# Cuánto tiene que despegarse una pieza de la mediana de su propia cuenta para
# que valga la pena mirarla. Con menos que esto es variación normal: la misma
# pieza publicada dos veces rinde distinto sin que nadie haya hecho nada mejor.
UMBRAL_OUTLIER = 2.0

# Debajo de esto, la mediana de una cuenta es una anécdota y marcar "outliers"
# contra ella sería inventar una referencia.
MINIMO_PIEZAS = 5

CAMPOS_IG = ("business_discovery.username({handle})"
             "{{username,name,followers_count,media_count,"
             "media.limit(50){{caption,like_count,comments_count,"
             "media_product_type,media_type,timestamp,permalink}}}}")


def _limpiar(texto, tope=150):
    return re.sub(r"\s+", " ", (texto or "")).strip()[:tope]


def instagram(get, graph, token, uid, handle):
    """Perfil y piezas de un competidor de Instagram. None si no se puede leer."""
    handle = handle.lstrip("@").split("/")[-1] or handle
    url = (f"{graph}/{uid}?fields={CAMPOS_IG.format(handle=handle)}"
           f"&access_token={token}")
    bd = (get(url) or {}).get("business_discovery")
    if not bd:
        return None
    piezas = []
    for m in bd.get("media", {}).get("data", []):
        piezas.append({
            "texto": _limpiar(m.get("caption")),
            "tipo": "Reel" if m.get("media_product_type") == "REELS"
                    else ("Carrusel" if m.get("media_type") == "CAROUSEL_ALBUM" else "Post"),
            "likes": m.get("like_count", 0),
            "comentarios": m.get("comments_count", 0),
            "fecha": (m.get("timestamp") or "")[:10],
            "link": m.get("permalink", ""),
        })
    return {"red": "instagram", "cuenta": bd.get("username", handle),
            "link": f"https://www.instagram.com/{bd.get('username', handle)}/",
            "nombre": bd.get("name", ""), "seguidores": bd.get("followers_count", 0),
            "piezas_totales": bd.get("media_count", 0), "piezas": piezas}


def youtube(pedir, token, handle):
    """Canal y videos de un competidor de YouTube. None si no se encuentra."""
    handle = handle.lstrip("@").split("/")[-1] or handle
    base = "https://www.googleapis.com/youtube/v3"
    ch = pedir(f"{base}/channels?part=snippet,statistics,contentDetails"
               f"&forHandle=@{handle}&access_token={token}")
    items = (ch or {}).get("items") or []
    if not items:
        return None
    c = items[0]
    subidas = c["contentDetails"]["relatedPlaylists"]["uploads"]
    lista = pedir(f"{base}/playlistItems?part=contentDetails&playlistId={subidas}"
                  f"&maxResults=50&access_token={token}")
    ids = [i["contentDetails"]["videoId"] for i in (lista or {}).get("items", [])]
    piezas = []
    # La API acepta hasta 50 ids por llamada: con una alcanza y cuesta 1 de cuota.
    if ids:
        det = pedir(f"{base}/videos?part=snippet,statistics,contentDetails"
                    f"&id={','.join(ids[:50])}&access_token={token}")
        for v in (det or {}).get("items", []):
            st, sn = v.get("statistics", {}), v.get("snippet", {})
            seg = _duracion(v.get("contentDetails", {}).get("duration", ""))
            piezas.append({
                "texto": _limpiar(sn.get("title")),
                # Un video de menos de 3 minutos en vertical es un short; la API no
                # lo dice, pero la duración lo delata y cambia con qué compararlo.
                "tipo": "Short" if seg and seg <= 180 else "Video",
                "likes": int(st.get("likeCount", 0) or 0),
                "comentarios": int(st.get("commentCount", 0) or 0),
                "vistas": int(st.get("viewCount", 0) or 0),
                "duracion": seg,
                "fecha": (sn.get("publishedAt") or "")[:10],
                "link": f"https://youtu.be/{v['id']}",
            })
    st = c.get("statistics", {})
    return {"red": "youtube", "cuenta": c["snippet"]["title"],
            "canal_id": c["id"],
            "nombre": c["snippet"].get("customUrl", ""),
            "link": f"https://www.youtube.com/channel/{c['id']}",
            "seguidores": int(st.get("subscriberCount", 0) or 0),
            "piezas_totales": int(st.get("videoCount", 0) or 0), "piezas": piezas}


def comentarios_youtube(pedir, token, canal_id, tope=200):
    """Lo que la gente le escribe A ÉL. Solo YouTube.

    POR QUÉ SOLO YOUTUBE
    Instagram no lo permite: `business_discovery` entrega `comments_count` pero no el
    texto, y pedir el campo `comments` devuelve "(#100) Please read documentation for
    supported fields". Probado el 2026-08-07. No es que falte programarlo.

    PARA QUÉ SIRVE
    Es el mejor buscador de temas que existe: lo que su audiencia le pregunta y él no
    respondió es un video que podés hacer mañana, con demanda ya demostrada y sin
    tener que adivinar.
    """
    base = "https://www.googleapis.com/youtube/v3"
    salida, pagina = [], None
    while len(salida) < tope:
        url = (f"{base}/commentThreads?part=snippet&allThreadsRelatedToChannelId={canal_id}"
               f"&maxResults=100&textFormat=plainText&access_token={token}"
               + (f"&pageToken={pagina}" if pagina else ""))
        d = pedir(url) or {}
        if "error" in d or not d.get("items"):
            break
        for hilo in d["items"]:
            s = hilo.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            salida.append({
                "texto": (s.get("textOriginal") or "").strip(),
                "autor": (s.get("authorDisplayName") or "").lstrip("@"),
                "fecha": (s.get("publishedAt") or "")[:10],
                "likes": s.get("likeCount", 0),
                # Marca de que NO es del dueño de la cuenta que corre el panel: acá
                # todos los comentarios son "de otros" por definición.
                "propio": False,
                "link": f"https://youtu.be/{hilo['snippet'].get('videoId', '')}",
            })
        pagina = d.get("nextPageToken")
        if not pagina:
            break
    return salida


def _duracion(iso):
    """'PT16M56S' -> 1016 segundos. 0 si no se entiende."""
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def analizar(comp):
    """Le agrega a cada pieza su múltiplo contra la mediana de SU PROPIA cuenta.

    La métrica es vistas en YouTube y likes en Instagram, porque es lo que cada
    API entrega. No son comparables entre sí y por eso nunca se mezclan.
    """
    piezas = comp.get("piezas") or []
    clave = "vistas" if comp["red"] == "youtube" else "likes"
    # Por formato, igual que con las piezas propias: un short y un video largo no
    # compiten en el mismo sistema de ranking.
    por_tipo = {}
    for p in piezas:
        por_tipo.setdefault(p["tipo"], []).append(p.get(clave, 0) or 0)
    medianas = {t: statistics.median(v) for t, v in por_tipo.items()
                if len(v) >= 3 and statistics.median(v) > 0}

    for p in piezas:
        base = medianas.get(p["tipo"])
        p["veces"] = round((p.get(clave, 0) or 0) / base, 1) if base else None
        p["metrica"] = clave

    outliers = sorted([p for p in piezas if (p.get("veces") or 0) >= UMBRAL_OUTLIER],
                      key=lambda p: -(p["veces"] or 0))
    return {
        **comp,
        "medianas": {t: round(v) for t, v in medianas.items()},
        "metrica": clave,
        "suficiente": len(piezas) >= MINIMO_PIEZAS,
        "minimo": MINIMO_PIEZAS,
        "outliers": outliers[:6],
        "ritmo": _ritmo(piezas),
        "formatos": {t: len(v) for t, v in por_tipo.items()},
    }


def _ritmo(piezas):
    """Cada cuántos días publican, en mediana. None si no hay con qué."""
    fechas = sorted({p["fecha"] for p in piezas if p.get("fecha")})
    if len(fechas) < 3:
        return None
    import datetime
    dias = [(datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
            for a, b in zip(fechas, fechas[1:])]
    return round(statistics.median(dias), 1) if dias else None


def _autochequeo():
    # ── duración ISO ──────────────────────────────────────────────────────
    assert _duracion("PT16M56S") == 1016
    assert _duracion("PT30S") == 30 and _duracion("PT1H2M3S") == 3723
    assert _duracion("") == 0 and _duracion("basura") == 0

    # ── outliers contra la mediana propia ─────────────────────────────────
    def v(vistas, fecha="2026-08-01", tipo="Video"):
        return {"vistas": vistas, "likes": 0, "tipo": tipo, "fecha": fecha, "texto": "x"}

    r = analizar({"red": "youtube", "piezas": [
        v(100), v(100), v(100), v(1000), v(50)]})
    assert r["medianas"]["Video"] == 100
    # 1000 sobre una mediana de 100 son 10x: eso es un outlier.
    assert r["outliers"] and r["outliers"][0]["veces"] == 10.0, r["outliers"]
    # Y el que rindió menos que la mediana no puede aparecer como hallazgo.
    assert all(p["veces"] >= UMBRAL_OUTLIER for p in r["outliers"])

    # Con menos de 3 piezas de un formato no hay mediana, y sin mediana no se
    # inventa un múltiplo: es None, no 0.
    r2 = analizar({"red": "youtube", "piezas": [v(100), v(9000)]})
    assert r2["medianas"] == {} and r2["outliers"] == []
    assert all(p["veces"] is None for p in r2["piezas"])

    # Instagram mide likes, no vistas: si se mezclaran las métricas, un reel de
    # YouTube parecería 1000x mejor que un post de Instagram por definición.
    r3 = analizar({"red": "instagram", "piezas": [
        {"likes": 10, "tipo": "Reel", "fecha": "2026-08-01", "texto": "a"},
        {"likes": 10, "tipo": "Reel", "fecha": "2026-08-02", "texto": "b"},
        {"likes": 10, "tipo": "Reel", "fecha": "2026-08-03", "texto": "c"},
        {"likes": 90, "tipo": "Reel", "fecha": "2026-08-04", "texto": "d"}]})
    assert r3["metrica"] == "likes" and r3["outliers"][0]["veces"] == 9.0

    # ── ritmo ─────────────────────────────────────────────────────────────
    assert _ritmo([{"fecha": f} for f in
                   ("2026-08-01", "2026-08-03", "2026-08-05", "2026-08-07")]) == 2.0
    assert _ritmo([{"fecha": "2026-08-01"}]) is None

    print("competencia.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
