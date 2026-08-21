#!/usr/bin/env python3
"""
Generador de piezas: carruseles, stories y placas de anuncio.

No inventa ideas de la nada: lee `panel.html` (los datos reales que bajo el
recolector) y arma briefs concretos a partir de lo que de verdad funciono en
la cuenta. Despues renderiza la pieza a imagenes con Chrome headless, que ya
esta en la Mac: costo cero, sin API de imagenes, sin dependencias nuevas.

    python3 generador.py briefs                 # que conviene publicar y por que
    python3 generador.py ejemplo > pieza.json   # plantilla para editar
    python3 generador.py render pieza.json      # JSON -> PNG listos para subir

El JSON de la pieza lo escribe una persona (o yo, en la conversacion). El
script no simula creatividad: arma el brief con datos y hace el render.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(AQUI, "panel.html")
SALIDA = os.path.join(AQUI, "piezas")
# Chrome headless es el que convierte las piezas en PNG. La ruta NO es una sola, y
# antes acá había UNA cableada: la de macOS con Chrome en /Applications. En cualquier
# otra máquina el panel decía "No encuentro Chrome en /Applications/Google Chrome.app"
# —incluso en Windows, donde esa carpeta no existe— aunque el navegador estuviera
# instalado dos carpetas más allá. Se busca en los lugares reales y se acepta
# cualquier navegador con motor Chromium: Brave, Edge y Chromium entienden los
# mismos `--headless --screenshot` que Chrome, porque son el mismo motor.
NAVEGADORES_MAC = [
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Chromium.app/Contents/MacOS/Chromium",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
NAVEGADORES_WIN = [
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
]
# Linux, o cualquier instalación por gestor de paquetes: el binario está en el PATH.
NAVEGADORES_PATH = ["google-chrome", "google-chrome-stable", "chromium",
                    "chromium-browser", "brave-browser", "microsoft-edge"]


def _candidatos():
    """Las rutas donde puede estar el navegador, según la plataforma."""
    if sys.platform == "darwin":
        # /Applications es la instalación normal; ~/Applications es la de quien no
        # tiene permisos de administrador, que en una Mac de trabajo es lo habitual.
        return [os.path.join(base, app)
                for base in ("/Applications", os.path.expanduser("~/Applications"))
                for app in NAVEGADORES_MAC]
    if os.name == "nt":
        bases = [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")]
        return [os.path.join(b, sub) for b in bases if b for sub in NAVEGADORES_WIN]
    return []


def buscar_chrome(cfg=None):
    """El navegador con el que renderizar, o None si no hay ninguno.

    Se puede fijar a mano con `"chrome": "/ruta/al/navegador"` en config.json (o con
    la variable de entorno CHROME, para probar sin tocar el archivo). Esa es la
    salida para quien lo tenga en una carpeta que no adivinamos: sin ella, el único
    camino sería editar este archivo en cada actualización.
    """
    forzado = os.environ.get("CHROME") or (cfg or config.cargar()).get("chrome", "")
    if forzado:
        # Si alguien lo declaró y no está, se avisa de ESE y no se sigue buscando:
        # encontrar otro por atrás escondería el error de tipeo en la ruta.
        return os.path.expanduser(forzado) if os.path.exists(os.path.expanduser(forzado)) else None
    for ruta in _candidatos():
        if os.path.exists(ruta):
            return ruta
    return next((r for n in NAVEGADORES_PATH if (r := shutil.which(n))), None)

# Medidas reales de cada formato de Instagram.
FORMATOS = {
    "carrusel": (1080, 1350),   # 4:5, el que mas pantalla ocupa en el feed
    "story": (1080, 1920),      # 9:16
    "ad": (1080, 1080),         # 1:1
}


def datos_panel():
    """Lee los datos que el recolector incrusto en panel.html."""
    if not os.path.exists(PANEL):
        sys.exit("Falta panel.html. Corre primero: python3 recolector.py")
    m = re.search(r"const DATOS = (\{.*?\});\n", open(PANEL, encoding="utf-8").read(), re.S)
    if not m:
        sys.exit("No pude leer los datos de panel.html. Regeneralo con el recolector.")
    return json.loads(m.group(1))


def briefs():
    """Que conviene publicar. El calculo vive en recolector.brief(): aca solo se muestra."""
    d = datos_panel()
    print(f"\nBRIEFS basados en datos reales · ultimos {d['dias']} dias")
    print("=" * 72)
    for red in d["redes"].values():
        b = red.get("brief")
        if not b:
            continue
        print(f"\n### {red['nombre']} — {red['cuenta']}")
        print(f"Formato que mas alcanza: {b['formato']} ({b['alcance_formato']} de promedio)")
        print(f"Objetivo de la proxima pieza: {b['objetivo']} — {b['pide']}")
        print("\nTus mejores ganchos (para reciclar el angulo, no el texto):")
        for g in b["ganchos"]:
            print(f"  · [{g['alcance']:>5}] {g['texto']}")
    print("\nPara generar una pieza:")
    print("  python3 generador.py ejemplo > pieza.json   (editas los textos)")
    print("  python3 generador.py render pieza.json\n")


def ejemplo():
    """Plantilla de pieza para editar. Sale por stdout para redirigir a un archivo."""
    return {
        "formato": "carrusel",
        "titulo": "nombre-interno-de-la-pieza",
        "acento": "#22d3ee",
        "slides": [
            {"tipo": "portada", "sobre": "El error", "titulo": "El gancho va acá",
             "texto": "Una línea que promete lo que se resuelve adentro."},
            {"tipo": "cuerpo", "sobre": "Paso 1", "titulo": "Una idea por slide",
             "texto": "El desarrollo. Corto: en el celular se lee poco."},
            {"tipo": "cuerpo", "sobre": "Paso 2", "titulo": "Segunda idea",
             "texto": "Sumá un dato concreto, no adjetivos."},
            {"tipo": "cierre", "sobre": "Tu turno", "titulo": "El pedido claro",
             "texto": "Comentá PANEL y te mando el link."},
        ],
    }


def html_pieza(pieza):
    """Arma el HTML de la pieza. Un .slide por imagen, medidas exactas del formato."""
    an, al = FORMATOS.get(pieza.get("formato", "carrusel"), FORMATOS["carrusel"])
    acento = pieza.get("acento", "#22d3ee")
    partes = []
    total = len(pieza["slides"])
    for i, s in enumerate(pieza["slides"], 1):
        clase = s.get("tipo", "cuerpo")
        partes.append(f"""
  <div class="slide {clase}">
    <div class="grilla"></div>
    <div class="contenido">
      {f'<span class="sobre">{s["sobre"]}</span>' if s.get("sobre") else ''}
      <h1>{s.get('titulo', '')}</h1>
      {f'<p>{s["texto"]}</p>' if s.get("texto") else ''}
    </div>
    <div class="pie"><span>{config.cargar()["marca"]["cuenta"]}</span><span>{i}/{total}</span></div>
  </div>""")

    return f"""<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#000; }}
  .slide {{
    width:{an}px; height:{al}px; position:relative; overflow:hidden;
    background:radial-gradient(ellipse 90% 60% at 50% 0%, #101a24, #05070a 70%);
    color:#e8f4f8; font-family:"Helvetica Neue",Arial,sans-serif;
    padding:96px 84px; display:flex; flex-direction:column; justify-content:center;
  }}
  /* la rejilla y la barra de acento repiten el codigo visual del panel */
  .grilla {{ position:absolute; inset:0; opacity:.5;
    background:
      linear-gradient(rgba(34,211,238,.07) 1px, transparent 1px) 0 0 / 100% 58px,
      linear-gradient(90deg, rgba(34,211,238,.07) 1px, transparent 1px) 0 0 / 58px 100%; }}
  .slide::before {{ content:""; position:absolute; top:0; left:0; right:0; height:10px;
    background:linear-gradient(90deg, {acento}, transparent 75%); }}
  .contenido {{ position:relative; }}
  .sobre {{ display:inline-block; background:{acento}; color:#04222a; font-size:23px;
    font-weight:800; letter-spacing:.15em; text-transform:uppercase; padding:11px 20px;
    margin-bottom:38px; }}
  h1 {{ font-size:{86 if al >= 1900 else 78}px; line-height:1.02; font-weight:800;
    letter-spacing:-.02em; }}
  .portada h1 {{ font-size:{100 if al >= 1900 else 92}px; }}
  p {{ font-size:36px; line-height:1.45; color:#8fa3b3; margin-top:34px; }}
  .cierre h1 {{ color:{acento}; }}
  .pie {{ position:absolute; left:84px; right:84px; bottom:62px; display:flex;
    justify-content:space-between; font-size:24px; color:#5d7284;
    font-family:ui-monospace,Menlo,monospace; letter-spacing:.08em; }}
</style>
{''.join(partes)}
"""


def _nombre(pieza):
    return pieza.get("titulo", "pieza").replace(" ", "-")


def carpeta_de(ruta_json):
    """En qué carpeta caen los PNG de esta pieza.

    Existe para que el servidor pueda mostrar las imágenes en el panel sin tener que
    adivinar el nombre —que sale del título de la pieza— ni parsear lo que imprime
    el render. Una sola definición: si mañana el nombre se arma distinto, cambia acá
    y el panel sigue encontrando las imágenes.
    """
    with open(ruta_json, encoding="utf-8") as f:
        return os.path.join(SALIDA, _nombre(json.load(f)))


def render(ruta_json):
    """JSON -> HTML -> PNG por slide, con Chrome headless."""
    pieza = json.load(open(ruta_json, encoding="utf-8"))
    formato = pieza.get("formato", "carrusel")
    if formato not in FORMATOS:
        sys.exit(f"Formato desconocido: {formato}. Usa uno de {list(FORMATOS)}")
    chrome = buscar_chrome()
    if not chrome:
        forzado = os.environ.get("CHROME") or config.cargar().get("chrome", "")
        sys.exit(f"No encuentro el navegador declarado en {forzado}" if forzado else
                 "No encuentro Google Chrome, ni ningún navegador con su mismo motor "
                 "(Chromium, Brave, Edge). Las piezas se convierten en imágenes con "
                 "Chrome, que es gratis: instalalo desde google.com/chrome y volvé a "
                 'probar. Si ya lo tenés en otra carpeta, poné "chrome": "/ruta/al/'
                 'navegador" en config.json.')

    an, al = FORMATOS[formato]
    nombre = _nombre(pieza)
    destino = os.path.join(SALIDA, nombre)
    os.makedirs(destino, exist_ok=True)

    html = html_pieza(pieza)
    ruta_html = os.path.join(destino, "slides.html")
    open(ruta_html, "w", encoding="utf-8").write(html)

    # Chrome captura la ventana completa, asi que renderizamos UN slide por vez
    # ocultando los demas: es la forma mas simple de obtener el recorte exacto.
    for i in range(len(pieza["slides"])):
        solo = html.replace(
            "</style>",
            f"  .slide {{ display:none }}\n"
            f"  .slide:nth-of-type({i + 1}) {{ display:flex }}\n</style>")
        tmp = os.path.join(destino, f"_tmp{i}.html")
        open(tmp, "w", encoding="utf-8").write(solo)
        png = os.path.join(destino, f"{nombre}_{i + 1:02d}.png")
        subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                        f"--screenshot={png}", f"--window-size={an},{al}",
                        f"file://{tmp}"],
                       check=True, capture_output=True)
        os.remove(tmp)
        print(f"  {os.path.basename(png)}")

    print(f"\n{len(pieza['slides'])} imagenes de {an}x{al} en:\n  {destino}")


def demo():
    """Autocomprobacion: el HTML sale bien armado y con las medidas correctas."""
    p = ejemplo()
    h = html_pieza(p)
    assert h.count('class="slide') == len(p["slides"]), "falta algun slide"
    assert "width:1080px; height:1350px" in h, "medida de carrusel incorrecta"
    assert "1/4" in h and "4/4" in h, "numeracion de slides mal"
    p9 = dict(p, formato="story")
    assert "height:1920px" in html_pieza(p9), "medida de story incorrecta"
    # el texto del usuario tiene que llegar intacto, acentos incluidos
    assert "Comentá PANEL" in h, "se perdio el texto del slide"
    # El buscador de navegador: lo que se declara gana, y una ruta declarada que no
    # existe tiene que devolver None y no seguir buscando por atras.
    assert buscar_chrome({"chrome": __file__}) == __file__, "ignoro el navegador declarado"
    assert buscar_chrome({"chrome": "/no/existe/chrome"}) is None, "tapo una ruta mal escrita"
    print("OK — el generador arma el HTML correctamente")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "briefs"
    if cmd == "briefs":
        briefs()
    elif cmd == "ejemplo":
        print(json.dumps(ejemplo(), ensure_ascii=False, indent=2))
    elif cmd == "render":
        if len(sys.argv) < 3:
            sys.exit("Uso: generador.py render pieza.json")
        render(sys.argv[2])
    elif cmd == "test":
        demo()
    else:
        sys.exit(__doc__)
