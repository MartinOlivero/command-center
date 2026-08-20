#!/usr/bin/env python3
"""
comentarios.py — Baja el TEXTO de los comentarios de Instagram, no solo cuántos hay.

POR QUÉ EXISTE
Hasta ahora el recolector pedía `comments.summary(total_count)`: sabía que un reel tenía
2.034 comentarios, pero no qué decía ninguno. Es como saber que sonó el teléfono 2.034
veces y no haber atendido nunca.

Acá están los leads. Alguien que comenta "¿cuánto sale?" o "yo tengo una distribuidora"
vale infinitamente más que un like, y hoy se pierde entre el ruido.

QUÉ HACE Y QUÉ NO
Trae, clasifica mecánicamente y guarda. NO interpreta: decidir cuál es un lead caliente
o medir el sentimiento es trabajo de la capa de análisis. Acá solo se separa lo que se
puede separar sin opinar:
  - tuyo vs. de otro     (por el @ del autor)
  - respuesta vs. suelto (si cuelga de otro comentario)

Eso ya arregla una mentira: si respondés todo, la mitad de "tus" comentarios son tuyos.
Erik tenía 2.034 comentarios que en realidad eran 1.066 reales + 968 respuestas propias.

DOC OFICIAL (verificada, no supuesta)
https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/comments/
  - Máximo 50 por página, con cursor.
  - Las respuestas NO vienen por defecto: hay que pedirlas con `replies{...}`.
  - Desde 2024-08-27, hasta leer el `username` exige el permiso instagram_manage_comments.

USO
    import comentarios
    comentarios.actualizar(cred, posts, "@micuenta")   # baja y fusiona con lo guardado
    todos = comentarios.leer()                               # lista plana de comentarios

Autochequeo (no toca la red):
    python3 comentarios.py
"""

import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(AQUI, "comentarios.json")

# Campos verificados contra la doc del nodo IG Comment. `replies` es field expansion:
# sin pedirla explícitamente, las respuestas no vienen y contás la mitad de la conversación.
CAMPOS = ("id,text,timestamp,username,like_count,hidden,parent_id,"
          "replies{id,text,timestamp,username,like_count,hidden}")


def _fila(c, media_id, responde_a, mi_handle):
    """Un comentario de la API convertido a nuestra forma."""
    autor = (c.get("username") or "").lower()
    return {
        "id": c["id"],
        "red": "instagram",
        "media_id": media_id,
        "texto": (c.get("text") or "").strip(),
        "autor": autor,
        "fecha": c.get("timestamp", ""),
        "likes": c.get("like_count", 0),
        "oculto": bool(c.get("hidden")),
        # None = comentario suelto; con valor = es respuesta a ese comentario
        "responde_a": responde_a,
        # Tuyo o de otro. Es la separación que hace que el total deje de mentir.
        "propio": autor == mi_handle,
    }


def bajar(get, graph, token, media_id, mi_handle):
    """Todos los comentarios de un post, con sus respuestas aplanadas en la misma lista.

    `get` y `graph` se pasan como argumento (no se importan) para que este módulo se
    pueda probar sin red y sin arrastrar el recolector entero.
    """
    url = (f"{graph}/{media_id}/comments?fields={CAMPOS}&limit=50"
           f"&access_token={token}")
    salida = []
    while url:
        pagina = get(url) or {}
        for c in pagina.get("data", []):
            salida.append(_fila(c, media_id, None, mi_handle))
            # Las respuestas vienen anidadas adentro del padre; las estiramos a la misma
            # lista con `responde_a` apuntando al padre. Una lista plana es mucho más
            # fácil de contar, filtrar y analizar que un árbol de dos niveles.
            for r in (c.get("replies") or {}).get("data", []):
                salida.append(_fila(r, media_id, c["id"], mi_handle))
        url = pagina.get("paging", {}).get("next")
    return salida


def actualizar(get, graph, token, posts, mi_handle, ruta=RUTA):
    """Baja los comentarios de cada post y los fusiona con lo ya guardado.

    Fusiona en vez de pisar: si alguien borra un comentario, la API deja de devolverlo,
    pero nosotros ya lo tenemos. Un lead que se arrepintió de escribir sigue siendo un
    lead que existió, y para el análisis eso importa.

    `posts` son los del recolector; solo se consultan los que tienen comentarios, para
    no gastar llamadas en los que están en cero.
    """
    mi_handle = mi_handle.lstrip("@").lower()
    guardados = {c["id"]: c for c in leer(ruta)}

    for p in posts:
        media_id = p.get("media_id") or p.get("id")
        if not media_id or not p.get("comentarios"):
            continue
        for c in bajar(get, graph, token, media_id, mi_handle):
            guardados[c["id"]] = c  # el más nuevo gana: el texto pudo editarse

    filas = sorted(guardados.values(), key=lambda c: c.get("fecha", ""))
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)
    return filas


# ─────────────────────────── YouTube ───────────────────────────
# Otra API, otro token, otra forma de nombrar todo. Lo único que comparte con
# Instagram es el resultado: una fila con la misma forma y el campo `red` puesto,
# para que el análisis de más arriba funcione igual sobre las dos.
#
# DOC OFICIAL (verificada el 2026-08-07, no supuesta):
# https://developers.google.com/youtube/v3/docs/commentThreads/list
#   - `allThreadsRelatedToChannelId` trae los de TODO el canal de una: 42 videos en
#     unas pocas llamadas, en vez de una llamada por video.
#   - maxResults tope 100. Cuesta 1 unidad de cuota por llamada (el tope diario es
#     10.000, así que esto es gratis en la práctica).
#   - Requiere el permiso youtube.force-ssl. Con solo `youtube` devuelve
#     ACCESS_TOKEN_SCOPE_INSUFFICIENT: es lo que nos bloqueó hasta hoy.
YT_API = "https://www.googleapis.com/youtube/v3/commentThreads"


def _fila_yt(c, cid, video_id, responde_a, mi_canal):
    s = c.get("snippet", {})
    return {
        "id": c.get("id", cid),
        "red": "youtube",
        "media_id": video_id,
        "texto": (s.get("textOriginal") or "").strip(),
        # El @ de YouTube ya viene con arroba; se lo sacamos para que sea igual que IG.
        "autor": (s.get("authorDisplayName") or "").lstrip("@").lower(),
        "fecha": s.get("publishedAt", ""),
        "likes": s.get("likeCount", 0),
        "oculto": False,
        "responde_a": responde_a,
        # En YouTube el autor se identifica por el id del canal, no por el nombre:
        # dos personas pueden mostrarse con el mismo nombre, el id es único.
        "propio": (s.get("authorChannelId") or {}).get("value") == mi_canal,
    }


def bajar_youtube(pedir, token, canal_id, tope=600):
    """Comentarios de todo el canal, con sus respuestas en la misma lista plana.

    `pedir(url)` se inyecta para poder probar sin red. `tope` corta la paginación:
    con un canal chico nunca se llega, y evita quedarse dando vueltas si algún día
    hay miles.
    """
    salida, pagina = [], None
    while len(salida) < tope:
        url = (f"{YT_API}?part=snippet,replies&allThreadsRelatedToChannelId={canal_id}"
               f"&maxResults=100&textFormat=plainText&access_token={token}"
               + (f"&pageToken={pagina}" if pagina else ""))
        d = pedir(url) or {}
        if "error" in d:
            # No reventamos el panel entero por esto: se avisa y se sigue con lo demás.
            raise RuntimeError(d["error"].get("message", "error de YouTube"))
        for hilo in d.get("items", []):
            s = hilo.get("snippet", {})
            video = s.get("videoId", "")
            top = s.get("topLevelComment", {})
            salida.append(_fila_yt(top, hilo["id"], video, None, canal_id))
            for r in (hilo.get("replies") or {}).get("comments", []):
                salida.append(_fila_yt(r, r.get("id"), video, hilo["id"], canal_id))
        pagina = d.get("nextPageToken")
        if not pagina:
            break
    return salida


def actualizar_youtube(pedir, token, canal_id, ruta=RUTA):
    """Baja los de YouTube y los fusiona con lo guardado, sin tocar los de Instagram."""
    guardados = {c["id"]: c for c in leer(ruta)}
    for c in bajar_youtube(pedir, token, canal_id):
        guardados[c["id"]] = c
    filas = sorted(guardados.values(), key=lambda c: c.get("fecha", ""))
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)
    return filas


def leer(ruta=RUTA, red=None):
    """Comentarios guardados, del más viejo al más nuevo. `red` filtra por plataforma.

    Los de antes de que existiera el campo se cuentan como de Instagram, que es de
    donde salieron: sin ese arreglo, al separar por red desaparecerían del panel.
    """
    if not os.path.exists(ruta):
        return []
    try:
        filas = json.load(open(ruta, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for c in filas:
        c.setdefault("red", "instagram")
    return [c for c in filas if red is None or c["red"] == red]


def resumen(filas):
    """Los números que hoy el panel no puede dar. Cuentas, no interpretación."""
    ajenos = [c for c in filas if not c["propio"]]
    return {
        "total": len(filas),
        "reales": len(ajenos),                                    # los que no son tuyos
        "propios": len(filas) - len(ajenos),                      # tus respuestas
        "respuestas": sum(1 for c in ajenos if c["responde_a"]),  # conversación, no comentario suelto
        "autores_unicos": len({c["autor"] for c in ajenos}),      # personas, no mensajes
    }


def _autochequeo():
    """Prueba con una API falsa: verifica el aplanado de respuestas, la paginación,
    la separación tuyo/ajeno y que fusionar no pierda un comentario borrado."""
    import tempfile

    ruta = os.path.join(tempfile.mkdtemp(), "c.json")

    pag1 = {
        "data": [
            {"id": "c1", "text": "2140", "timestamp": "2026-08-05T12:00:00+0000",
             "username": "danitejeiro", "like_count": 0, "hidden": False,
             "replies": {"data": [
                 {"id": "r1", "text": "¡Ya te lo mando!", "timestamp": "2026-08-05T12:05:00+0000",
                  "username": "Tincho.Olivero", "like_count": 1, "hidden": False},
             ]}},
        ],
        "paging": {"next": "PAGINA2"},
    }
    pag2 = {"data": [
        {"id": "c2", "text": "¿cuánto sale?", "timestamp": "2026-08-05T13:00:00+0000",
         "username": "unlead", "like_count": 0, "hidden": False},
    ]}
    falsa = {"PAGINA2": pag2}

    def get(url):
        return falsa.get(url, pag1)

    filas = actualizar(get, "G", "T", [{"id": "m1", "comentarios": 3}],
                       "@micuenta", ruta)

    assert len(filas) == 3, f"esperaba 3 comentarios (2 páginas + 1 respuesta), hay {len(filas)}"
    por_id = {c["id"]: c for c in filas}
    assert por_id["r1"]["responde_a"] == "c1", "no aplanó la respuesta colgándola del padre"
    assert por_id["c1"]["responde_a"] is None, "marcó un comentario suelto como respuesta"
    # El handle vino con mayúsculas y con @: igual tiene que reconocerse como propio.
    assert por_id["r1"]["propio"] is True, "no reconoció tu propia respuesta"
    assert por_id["c2"]["propio"] is False, "marcó como tuyo el comentario de otro"
    assert por_id["c2"]["texto"] == "¿cuánto sale?", "perdió el texto o los acentos"

    r = resumen(filas)
    assert r == {"total": 3, "reales": 2, "propios": 1, "respuestas": 0,
                 "autores_unicos": 2}, f"resumen mal: {r}"

    # Segunda corrida: la API ya no devuelve c2 (lo borraron). No se puede perder.
    falsa["PAGINA2"] = {"data": []}
    filas = actualizar(get, "G", "T", [{"id": "m1", "comentarios": 3}],
                       "@micuenta", ruta)
    assert "c2" in {c["id"] for c in filas}, "perdió un comentario borrado al fusionar"

    # Sin comentarios no se consulta el post (no gastar llamadas al pedo).
    def explota(url):
        raise AssertionError("consultó un post con 0 comentarios")

    actualizar(explota, "G", "T", [{"id": "m9", "comentarios": 0}], "@micuenta", ruta)

    print("comentarios.py: todo OK")


if __name__ == "__main__":
    _autochequeo()
