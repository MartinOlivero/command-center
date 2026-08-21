#!/usr/bin/env python3
"""Check minimo del panel, sin tocar la red:  python3 test_panel.py

Cubre lo unico que puede romperse en silencio: que los datos entren de
verdad en el HTML, y las cuentas de los KPIs.
"""
import json
import os
import re

import recolector as panel

AQUI = os.path.dirname(os.path.abspath(__file__))

# --- variacion: porcentaje Y cambio absoluto ---
assert panel.delta(150, 100) == {"pct": 50.0, "abs": 50}
assert panel.delta(50, 100) == {"pct": -50.0, "abs": -50}
assert panel.delta(10, 0) is None, "sin base previa no se inventa un porcentaje"
assert panel.delta(0, 100) == {"pct": -100.0, "abs": -100}
# el caso que motivo el cambio: un porcentaje enorme sobre una base minuscula.
# "+2109.2%" y "+1371" describen lo mismo, pero solo el segundo dice el tamaño.
assert panel.delta(1436, 65) == {"pct": 2109.2, "abs": 1371}

# --- herencia al actualizar una sola red ---
# El bug que esto fija: al heredar, `atribuir_seguidores` veia que la pieza ya
# traia `seguidores_ganados` y la marcaba "directo". Pero ese numero podia venir
# ESTIMADO de la corrida anterior, asi que una aproximacion terminaba mostrandose
# como medicion, y sin el aviso de que era aproximada.
heredada = {"posts": [
    {"titulo": "estimado", "seguidores_ganados": 7, "seguidores_origen": "estimado"},
    {"titulo": "directo",  "seguidores_ganados": 3, "seguidores_origen": "directo"},
    {"titulo": "sin dato"},
]}
limpia = panel.limpiar_derivados(heredada)
est, dir_, sin = limpia["posts"]
assert "seguidores_ganados" not in est, "lo estimado no puede sobrevivir a la herencia"
assert "seguidores_origen" not in est
assert dir_["seguidores_ganados"] == 3, "lo que midio la API sigue siendo valido"
assert dir_["seguidores_origen"] == "directo"
assert sin == {"titulo": "sin dato"}, "no se inventa nada donde no habia"
assert panel.limpiar_derivados({}) == {}, "una red sin piezas no puede romper"

# --- que redes hay que bajar ---
import sys as _sys
_argv = _sys.argv
try:
    _sys.argv = ["recolector.py"]
    # Contra la constante, no contra una lista escrita a mano: así sumar una red al
    # panel no rompe este test (que es justo lo que pasó al enchufar TikTok).
    assert panel.redes_pedidas() == set(panel.TODAS), \
        "sin flag se baja todo, campañas y calendario incluidos"
    assert {"instagram", "facebook", "youtube", "tiktok"} <= set(panel.TODAS), \
        "alguna red se cayó de la lista de las que se pueden pedir"
    _sys.argv = ["recolector.py", "--red", "instagram"]
    assert panel.redes_pedidas() == {"instagram"}, "pedir una red NO arrastra las campañas"
    _sys.argv = ["recolector.py", "--red", "ads"]
    assert panel.redes_pedidas() == {"ads"}, "las campañas se pueden pedir solas"
    _sys.argv = ["recolector.py", "--red", "instagram,youtube"]
    assert panel.redes_pedidas() == {"instagram", "youtube"}
    _sys.argv = ["recolector.py", "--red", "INSTAGRAM"]
    assert panel.redes_pedidas() == {"instagram"}, "el nombre no distingue mayusculas"
    # una red mal escrita tiene que cortar, no bajar de menos en silencio
    for malo in (["--red", "twitter"], ["--red"], ["--red", ""]):
        _sys.argv = ["recolector.py"] + malo
        try:
            panel.redes_pedidas()
            raise AssertionError(f"deberia haber cortado con {malo}")
        except SystemExit:
            pass
finally:
    _sys.argv = _argv

# --- suma de la serie diaria ---
serie = {"2026-07-01": {"reach": 10}, "2026-07-02": {"reach": 5}, "2026-07-03": {}}
assert panel.suma(serie, "reach") == 15
assert panel.suma(serie, "inexistente") == 0

# --- las dos listas de metricas no pueden pisarse ---
assert not set(panel.CON_SERIE_DIARIA) & set(panel.SOLO_TOTAL), \
    "una metrica no puede estar en los dos modos de la API"

# --- el dato tiene que llegar al HTML ---
plantilla = open(os.path.join(AQUI, "plantilla.html"), encoding="utf-8").read()
assert plantilla.count("/*DATOS*/null") == 1, "falta (o sobra) el hueco donde se inyectan los datos"

falso = {"generado": "2026-08-02T17:00", "dias": 30, "perfil": {"username": "x"},
         "kpis": [{"nombre": "Alcance", "valor": 100, "delta": 5, "nota": "n"}],
         "serie": [{"fecha": "2026-07-01", "reach": 10}],
         "posts": [], "pais": [], "ciudad": [], "avisos": []}
html = plantilla.replace("/*DATOS*/null",
                         json.dumps(falso, ensure_ascii=False).replace("</", "<\\/"))
assert "/*DATOS*/" not in html, "el marcador quedo sin reemplazar"
assert "</script>" not in json.dumps(falso).replace("</", "<\\/"), \
    "un caption con </script> no debe poder cortar el bloque de JavaScript"

# el JSON incrustado tiene que volver a parsear tal cual salio
recuperado = json.loads(re.search(r"const DATOS = (\{.*?\});\n", html, re.S).group(1))
assert recuperado == falso, "los datos se deforman al incrustarse"

# ── aviso de version nueva ──────────────────────────────────────────────────
# Lo importante no es que avise: es que NUNCA pueda frenar la recoleccion. Un cartel
# informativo no puede ser el motivo por el que alguien se queda sin datos.
import io as _io

panel.urllib.request.urlopen = lambda *a, **k: _io.BytesIO(b'VERSION = "9.9.9"\n')
assert panel.version_publicada() == "9.9.9", "tiene que detectar una version mayor"

panel.urllib.request.urlopen = (
    lambda *a, **k: _io.BytesIO(f'VERSION = "{panel.config.VERSION}"\n'.encode()))
assert panel.version_publicada() is None, "si es la misma version, no se avisa nada"

def _sin_internet(*a, **k):
    raise OSError("sin internet")
panel.urllib.request.urlopen = _sin_internet
assert panel.version_publicada() is None, "sin internet no puede explotar"

panel.urllib.request.urlopen = lambda *a, **k: _io.BytesIO(b"<html>404</html>")
assert panel.version_publicada() is None, "una respuesta que no es config.py se ignora"

print("OK — todos los checks pasaron")
