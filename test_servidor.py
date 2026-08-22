#!/usr/bin/env python3
"""Check del arranque del servidor: que un puerto ocupado no frene el panel.

    python3 test_servidor.py

Es el caso real: alguien deja un panel abierto, cierra la tapa, y a la semana hace
doble clic en "Abrir panel". Si eso termina en una instruccion de terminal, para la
mayoria de la gente el panel simplemente no abre.
"""
import socket

import servidor

# Ocupamos un puerto a proposito y pedimos desde ahi: tiene que correrse al siguiente.
tomado = socket.socket()
tomado.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tomado.bind(("127.0.0.1", 0))
tomado.listen(1)
puerto_ocupado = tomado.getsockname()[1]

srv, puerto = servidor.abrir_puerto(puerto_ocupado, 20)
assert srv is not None, "con puertos libres al lado, tiene que abrir en alguno"
assert puerto > puerto_ocupado, f"eligio {puerto}, que es el que estaba ocupado"
srv.server_close()

# Y si se pide UN solo intento sobre el puerto ocupado, avisa en vez de reventar.
srv, puerto = servidor.abrir_puerto(puerto_ocupado, 1)
assert srv is None and puerto is None, "sin lugar tiene que devolver None, no explotar"

tomado.close()

# ── sin panel.html, la respuesta tiene que explicar que falta correr el recolector ──
import http.client
import os
import threading

hay_panel = os.path.exists(os.path.join(servidor.AQUI, "panel.html"))
srv, puerto = servidor.abrir_puerto(8900, 20)
threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
    c.request("GET", "/panel.html")
    r = c.getresponse()
    cuerpo = r.read().decode("utf-8", "replace")
finally:
    srv.shutdown()
    srv.server_close()

if hay_panel:
    assert r.status == 200 and "recolector.py" not in cuerpo[:200], \
        "con panel.html generado hay que servir el panel, no el aviso"
else:
    assert r.status == 200, f"tendria que responder una pagina, no {r.status}"
    assert "recolector.py" in cuerpo, "el aviso tiene que decir como generar el panel"
    assert "File not found" not in cuerpo, "eso es el 404 crudo de la biblioteca"

# ── el reloj de afuera no puede ser mas corto que el de adentro ────────────────
# El bug del 21/08/2026: el servidor esperaba 330s al analista y el analista le daba
# 300s al modelo. Cuando el modelo tardaba cerca de su techo, el padre lo mataba antes
# de que pudiera terminar ni explicarse. Si alguien vuelve a escribir un numero a mano
# en cualquiera de los dos lados, esto tiene que fallar.
import inspect
import re

import ia

fuente = inspect.getsource(servidor.reanalizar)
m = re.search(r"timeout=([^)]+)\)", fuente)
assert m, "reanalizar() ya no pasa un timeout al analista"
espera = eval(m.group(1), {"ia": ia})
assert espera > ia.TIMEOUT, (
    f"el servidor espera {espera}s y el modelo tiene techo {ia.TIMEOUT}s: "
    "el analisis se pierde justo cuando termina")

# ── /abrir no puede abrir cualquier carpeta de la maquina ─────────────────────
# El nombre llega por un POST y termina en una llamada al sistema operativo. Recortar
# con basename() NO alcanza: basename("../../..") devuelve "..", que se sale igual.
for intento in ("../../..", "..", "/etc", "no-existe", "../piezas-ia", ""):
    try:
        servidor.abrir_carpeta(intento)
        raise SystemExit(f"/abrir acepto {intento!r}: se sale de la carpeta de piezas")
    except RuntimeError:
        pass

# ── las miniaturas tambien tienen que pedirse bien desde Windows ──────────────
# Alla el separador de rutas es "\\", que en una URL no significa nada: si se cuela,
# el panel muestra cuatro imagenes rotas. Y el nombre de la carpeta sale del titulo de
# la pieza, asi que trae espacios y acentos.
assert servidor._url(r"piezas\Cafe Nandu", "a b_01.png", sep="\\") == \
    "/piezas/Cafe%20Nandu/a%20b_01.png", "una ruta de Windows no quedo pedible"
assert servidor._url("piezas/Café Ñandú", "a b_01.png", sep="/") == \
    "/piezas/Caf%C3%A9%20%C3%91and%C3%BA/a%20b_01.png", "se perdieron los acentos"

# ── el panel tiene que darse cuenta de que quedo viejo en memoria ─────────────
# Paso el 22/08/2026: el servidor arranco 02:38:51 y la actualizacion escribio ia.py
# 02:38:58. Siete segundos, y el panel quedo con el codigo anterior sin avisar nada.
import time

assert servidor.desfasado() == [], "no hay actualizacion en curso: no puede avisar nada"
prueba = os.path.join(servidor.AQUI, "config.py")
antes = os.path.getmtime(prueba)
try:
    os.utime(prueba, (time.time() + 5, time.time() + 5))   # como si lo acabara de escribir el instalador
    assert "config.py" in servidor.desfasado(), \
        "un archivo mas nuevo que el proceso tiene que detectarse"
finally:
    os.utime(prueba, (antes, antes))
# panel.html NO cuenta: lo reescribe cada recoleccion y el aviso saldria siempre.
assert not any(f == "panel.html" for f in servidor.desfasado()), "panel.html no se vigila"

print("OK — todos los checks pasaron")
