#!/usr/bin/env python3
"""
Analista con IA: lee los datos reales de las tres redes y devuelve un
diagnostico y recomendaciones de contenido basadas en lo que YA funciono.

Corre sobre el CLI de Claude que ya esta instalado y logueado, asi que no
hace falta ninguna API key nueva ni se paga por analisis aparte.

    python3 analista.py            # analiza y guarda analisis.json
    python3 analista.py --ver      # muestra el ultimo analisis

El recolector lo llama solo si `analisis.json` no existe o quedo viejo, para
no gastar una corrida de IA cada vez que se refresca el panel.
"""
import json
import os
import re
import sys

import config
import ia

AQUI = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(AQUI, "panel.html")
CACHE = os.path.join(AQUI, "analisis.json")


def datos_panel():
    if not os.path.exists(PANEL):
        sys.exit("Falta panel.html. Corre primero: python3 recolector.py")
    m = re.search(r"const DATOS = (\{.*?\});\n", open(PANEL, encoding="utf-8").read(), re.S)
    if not m:
        sys.exit("No pude leer los datos de panel.html.")
    return json.loads(m.group(1))


def resumen(d):
    """Compacta los datos para el prompt: solo lo que sirve para decidir."""
    fuera = {"dias": d["dias"], "redes": {}}
    for k, r in d["redes"].items():
        if not r["conectada"]:
            continue
        fuera["redes"][k] = {
            "cuenta": r["cuenta"],
            "seguidores": r["seguidores"],
            "kpis": {x["nombre"]: x["valor"] for x in r["kpis"]},
            "piezas": [{
                "fecha": p["fecha"], "tipo": p["tipo"], "texto": p["texto"],
                "alcance": p.get("alcance"), "interacciones": p.get("interacciones"),
                "guardados": p.get("guardados"), "compartidos": p.get("compartidos"),
                "engagement": p.get("engagement"),
                # Los ratios importan MAS que los numeros crudos: miden calidad, no tamaño.
                # Sin esto la IA razona sobre alcance y recomienda repetir la pieza que
                # llego lejos pero no movio a nadie.
                "sends_reach": p.get("sends_reach"), "saves_reach": p.get("saves_reach"),
                "likes_reach": p.get("likes_reach"),
            } for p in r["posts"][:15]],
            "senales_algoritmo": r.get("senales", {}).get("cuenta"),
            "mediana_por_formato": r.get("senales", {}).get("medianas"),
            "senales_automaticas": [i["titulo"] for i in r.get("insights", [])],
        }
    return fuera


ESQUEMA = """{
  "titular": "una frase de 12 palabras maximo que resuma el estado del negocio de contenido",
  "diagnostico": "2 o 3 oraciones. Que esta pasando de verdad, sin suavizar.",
  "analogia": "explica el estado general con una analogia de la vida cotidiana (un local, un gimnasio, una pesca, un asado). Tiene que hacer entender el problema a alguien que no sabe de metricas.",
  "patron": "que tienen en comun las piezas que mas alcanzaron. Concreto, citando ejemplos con sus numeros.",
  "por_red": {
    "instagram": {
      "veredicto": "una frase filosa sobre como esta esa red",
      "analogia": "una analogia distinta y especifica de ESTA red",
      "salud": 0,
      "que_hacer": ["accion concreta 1", "accion concreta 2", "accion concreta 3"]
    },
    "youtube": { "veredicto": "", "analogia": "", "salud": 0, "que_hacer": [] },
    "facebook": { "veredicto": "", "analogia": "", "salud": 0, "que_hacer": [] }
  },
  "recomendaciones": [
    {
      "titulo": "titulo corto de la pieza propuesta",
      "formato": "Reel | Carrusel | Short | Video",
      "red": "instagram | youtube | facebook",
      "gancho": "el primer renglon o la primera frase hablada, escrita textual",
      "porque": "en que dato de la cuenta se apoya esta idea, CON el numero",
      "porque_no": "en que caso esta pieza NO va a funcionar, o que riesgo tiene",
      "objetivo": "Guardado | Compartido | Comentario | Seguidor | Conversion",
      "exito": "que numero concreto tiene que moverse para saber que funciono",
      "duracion": "45s",
      "guion": [
        {"t": "0:00-0:03", "dice": "TEXTUAL lo que se dice a camara, palabra por palabra",
         "pantalla": "que se ve o que texto aparece sobreimpreso",
         "plano": "como se graba: primer plano, pantalla compartida, b-roll de X"},
        {"t": "0:03-0:12", "dice": "", "pantalla": "", "plano": ""},
        {"t": "0:12-0:35", "dice": "", "pantalla": "", "plano": ""},
        {"t": "0:35-0:45", "dice": "", "pantalla": "", "plano": ""}
      ],
      "slides": [
        {"tipo": "portada", "sobre": "etiqueta corta", "titulo": "gancho de portada", "texto": "una linea"},
        {"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "idea 2", "texto": "desarrollo corto"},
        {"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "idea 3", "texto": "desarrollo corto"},
        {"tipo": "cierre", "sobre": "Tu turno", "titulo": "el pedido", "texto": "el CTA"}
      ]
    }
  ],
  "que_dejar_de_hacer": "una cosa concreta que esta gastando esfuerzo sin devolver nada"
}"""


def analizar():
    d = datos_panel()
    datos = json.dumps(resumen(d), ensure_ascii=False)

    prompt = f"""Sos un analista senior de redes sociales con 15 años de oficio.
No sos un generador de frases motivacionales: sos el que mira los numeros y dice
la verdad incomoda que hace ganar plata. Trabajaste con creadores que pasaron de
0 a 500k y con cuentas que se estancaron para siempre, y sabes distinguirlas
por los datos antes de que pase.

Tu marca registrada: explicar con ANALOGIAS de la vida real. Nunca decis
"el engagement rate esta bajo": decis "es como un local con vidriera llena de
gente que mira y nadie entra". Esa es la razon por la que te contratan.

Estos son los datos REALES de las cuentas de {config.marca_para_prompt()}:

{datos}

Analizalos y respondé UNICAMENTE con un JSON valido con esta forma:

{ESQUEMA}

Reglas del analisis:
- Español rioplatense (vos, tenés, publicaste), con acentos correctos.
- "salud" es un numero 0-100 que resume que tan sana esta esa red HOY.
- Cada analogia tiene que ser DISTINTA y hacer entender el problema a alguien
  que no sabe de metricas. Nada de metaforas gastadas tipo "el algoritmo es un
  animal que hay que alimentar".
- 4 recomendaciones. Cada una apoyada en un dato concreto de arriba, con su
  numero. Si no hay dato que la sostenga, no la propongas.

- EL "guion" ES LO MAS IMPORTANTE DE TODA LA RESPUESTA. La prueba que tiene que
  pasar: que alguien agarre el celular, lea el guion y pueda grabar la pieza SIN
  preguntarte nada mas. Si despues de leerlo quedan dudas de que decir o como
  filmarlo, el guion esta mal y no sirve.
  * "dice" va TEXTUAL, palabra por palabra, en rioplatense hablado, como se dice
    en voz alta. NO es un resumen ni una descripcion de lo que hay que decir.
    MAL:  "explicar el problema de los turnos perdidos"
    BIEN: "Son las nueve de la noche. A tu cliente le duele una muela y te
           escribe. Vos estas durmiendo. Manana te escribe al que le contesto."
  * "pantalla" es que se VE en ese tramo: texto sobreimpreso, una captura, un
    chat, un grafico. Si no hay nada, decir "cara a camara".
  * "plano" es la instruccion de camara: "primer plano, celular vertical",
    "pantalla compartida de n8n", "b-roll: manos sobre el teclado".
  * 4 a 6 tramos con tiempos que sumen la duracion declarada.
  * El primer tramo (0:00-0:03) se juega todo: si no frena el scroll, el resto
    no existe. Ahi va el gancho mas filoso, nunca un saludo ni una presentacion.
  * Para Carrusel y Story el guion puede ser mas corto, pero los "slides"
    siguen siendo obligatorios: son las placas.

- "porque_no" es obligatorio y tiene que ser honesto: cuando esta pieza NO
  conviene, que riesgo corre o que supuesto puede fallar. Una recomendacion sin
  contraindicacion es publicidad, no analisis.
- "exito" tiene que nombrar UNA metrica de las que ya medimos y un numero a
  batir, sacado de la mediana de su propio formato.
- Los "slides" tienen que ser el contenido REAL de la pieza, listo para
  renderizar: titulos de 6 palabras maximo, textos de 15 palabras maximo,
  porque van en una imagen que se lee en un celular.
- Los ganchos, especificos del nicho: nada de plantillas genericas.
- Nunca inventes una metrica que no este en los datos.
- Si una red no tiene datos suficientes, decilo en su veredicto en vez de
  inventar un diagnostico.

Como leer las metricas (esto define si el analisis sirve o no):
- Priorizá los RATIOS sobre los numeros crudos. Instagram confirmo que sus tres
  señales son: tiempo de visualizacion, compartidos/alcance y likes/alcance.
  Los compartidos pesan 3-5 veces mas que un like y son LA señal para llegar a
  gente que NO te sigue.
- La pieza de mayor alcance NO es necesariamente la mejor. Una con mucho alcance
  y sends_reach en 0 llego lejos y no movio a nada. Decilo asi.
- NUNCA compares piezas de formatos distintos entre si. Instagram usa cuatro
  sistemas de ranking (Feed, Reels, Stories, Explore) y los reels rinden 80-120%
  mas que el feed por diseño. Compara cada pieza contra "mediana_por_formato"
  de SU PROPIO formato.
- Benchmark de cuentas chicas (menos de 10k): engagement 6-7%. No uses los
  benchmarks de cuentas grandes, que son mucho mas bajos.
- Si "senales_algoritmo.alerta" trae un texto, es el hallazgo mas importante de
  esa red: el analisis tiene que hacerse cargo de eso antes que de nada.
- Nada de texto fuera del JSON."""

    print("Analizando con IA (puede tardar ~30s)...")
    try:
        analisis = ia.preguntar_json(prompt, timeout=300)
    except (RuntimeError, json.JSONDecodeError) as e:
        sys.exit(f"No se pudo analizar: {e}")

    analisis["generado_para"] = d["generado"]
    json.dump(analisis, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return analisis


BANCO = os.path.join(AQUI, "ideas.json")

# Las combinaciones que de verdad se usan. No generamos las 60 posibles
# (3 redes x 4 formatos x 5 objetivos): la mayoria no tiene sentido y el
# banco quedaria lleno de relleno.
COMBOS = [
    ("instagram", "Reel", "DM"), ("instagram", "Reel", "Tráfico a perfil"),
    ("instagram", "Reel", "Venta"), ("instagram", "Carrusel", "Guardado"),
    ("instagram", "Carrusel", "Registro"), ("instagram", "Story", "DM"),
    ("instagram", "Story", "Agenda"), ("instagram", "Ad", "Agenda"),
    ("instagram", "Ad", "Venta"),
    ("youtube", "Short", "Tráfico a perfil"), ("youtube", "Short", "Registro"),
    ("youtube", "Video", "Registro"), ("youtube", "Video", "Venta"),
    ("youtube", "Video", "Agenda"),
    ("facebook", "Reel", "DM"), ("facebook", "Carrusel", "Agenda"),
    ("facebook", "Ad", "Venta"), ("facebook", "Ad", "Registro"),
]


def ideas():
    """Banco de ideas de contenido, una por combinacion red/formato/objetivo.

    Se genera una sola vez y el panel las filtra al instante: asi el
    generador responde como una app sin necesitar backend ni API en vivo.
    """
    d = datos_panel()
    datos = json.dumps(resumen(d), ensure_ascii=False)
    combos = "\n".join(f"- {r} / {f} / objetivo {o}" for r, f, o in COMBOS)

    prompt = f"""Sos un analista senior de redes sociales y guionista de contenido.
Trabajas con {config.marca_para_prompt()}.

Estos son los datos REALES de sus cuentas:

{datos}

Generá UNA idea de contenido para cada una de estas combinaciones:

{combos}

Respondé UNICAMENTE con un JSON valido:

{{
  "ideas": [
    {{
      "red": "instagram|youtube|facebook",
      "formato": "Reel|Carrusel|Story|Ad|Short|Video",
      "objetivo": "DM|Agenda|Registro|Venta|Tráfico a perfil|Guardado",
      "titulo": "titulo corto e interno de la pieza",
      "gancho": "el primer renglon o la primera frase hablada, textual",
      "angulo": "en una frase, desde donde se cuenta",
      "porque": "en que dato concreto de la cuenta se apoya, con el numero",
      "porque_no": "cuando esta pieza NO va a funcionar o que riesgo tiene",
      "exito": "que numero tiene que moverse para saber que funciono",
      "cta": "que se le pide exactamente a la persona",
      "duracion": "45s",
      "guion": [
        {{"t": "0:00-0:03", "dice": "textual, palabra por palabra", "pantalla": "que se ve", "plano": "como se graba"}},
        {{"t": "0:03-0:15", "dice": "", "pantalla": "", "plano": ""}},
        {{"t": "0:15-0:35", "dice": "", "pantalla": "", "plano": ""}},
        {{"t": "0:35-0:45", "dice": "", "pantalla": "", "plano": ""}}
      ],
      "slides": [
        {{"tipo": "portada", "sobre": "etiqueta", "titulo": "max 6 palabras", "texto": "max 15 palabras"}},
        {{"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "max 6 palabras", "texto": "max 15 palabras"}},
        {{"tipo": "cuerpo", "sobre": "etiqueta", "titulo": "max 6 palabras", "texto": "max 15 palabras"}},
        {{"tipo": "cierre", "sobre": "Tu turno", "titulo": "max 6 palabras", "texto": "el CTA"}}
      ]
    }}
  ]
}}

Reglas:
- Español rioplatense con acentos correctos.
- Las {len(COMBOS)} ideas, en el mismo orden de la lista.
- Cada "porque" tiene que citar un numero real de los datos de arriba.
- Los ganchos, especificos del nicho pyme argentino: turnos perdidos, WhatsApp
  sin contestar, facturas a mano, empleados que renuncian, stock descontrolado.
  Nada de "descubri el secreto" ni plantillas de gurú.

- EL "guion" ES LO MAS IMPORTANTE. La prueba que tiene que pasar: que alguien
  agarre el celular, lea el guion y grabe la pieza sin preguntar nada mas.
  * "dice" va TEXTUAL, palabra por palabra, en rioplatense hablado.
    MAL:  "plantear el problema del turno perdido"
    BIEN: "Son las ocho y cuarto de la noche. Le duele una muela y le escribe a
           tres consultorios. Manana a la manana le contesta uno solo."
    Un renglon suelto tipo "son las 20:15 y le duele una muela" NO es un guion:
    es un gancho. El guion sigue: que pasa despues, que mostras, como cierra.
  * "pantalla": que se ve o que texto va sobreimpreso. Si no hay nada,
    "cara a camara".
  * "plano": la instruccion de camara.
  * 4 a 6 tramos, con tiempos que sumen la duracion declarada.
  * El tramo 0:00-0:03 frena el scroll o no existe el resto. Nunca un saludo.
- "porque_no" es obligatorio y honesto: cuando NO conviene esta pieza.
- Las Story y los Ad tambien llevan slides: son placas.
- Nada de texto fuera del JSON."""

    print(f"Generando banco de {len(COMBOS)} ideas (puede tardar ~1 min)...")
    try:
        banco = ia.preguntar_json(prompt, timeout=600)
    except (RuntimeError, json.JSONDecodeError) as e:
        sys.exit(f"No se pudo generar el banco de ideas: {e}")
    banco["generado_para"] = d["generado"]
    json.dump(banco, open(BANCO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(banco.get('ideas', []))} ideas guardadas en ideas.json")
    return banco


def cargar_ideas():
    if not os.path.exists(BANCO):
        return None
    return json.load(open(BANCO, encoding="utf-8"))


def cargar(generado=None):
    """Devuelve el analisis cacheado si corresponde al panel actual."""
    if not os.path.exists(CACHE):
        return None
    a = json.load(open(CACHE, encoding="utf-8"))
    if generado and a.get("generado_para") != generado:
        return None
    return a


def demo():
    """Autocomprobacion sin gastar una corrida de IA."""
    falso = {"dias": 30, "redes": {"instagram": {
        "conectada": True, "cuenta": "@x", "seguidores": 10,
        "kpis": [{"nombre": "Alcance", "valor": 100}],
        "posts": [{"fecha": "2026-08-01", "tipo": "Reel", "texto": "hola",
                   "alcance": 50, "interacciones": 2}],
        "insights": [{"titulo": "algo"}]}}}
    r = resumen(falso)
    assert "instagram" in r["redes"], "no compacto la red conectada"
    assert r["redes"]["instagram"]["kpis"]["Alcance"] == 100, "perdio los KPIs"
    assert len(r["redes"]["instagram"]["piezas"]) == 1, "perdio las piezas"
    # una red desconectada no debe ocupar lugar en el prompt
    falso["redes"]["youtube"] = {"conectada": False}
    assert "youtube" not in resumen(falso)["redes"], "mando una red desconectada al prompt"
    print("OK — el resumen para la IA se arma bien")


if __name__ == "__main__":
    if "--ideas" in sys.argv:
        ideas()
    elif "--ver" in sys.argv:
        a = cargar()
        print(json.dumps(a, ensure_ascii=False, indent=1) if a else "Todavia no hay analisis.")
    elif "--test" in sys.argv:
        demo()
    else:
        a = analizar()
        print(f"\n{a['titular']}\n")
        print(a["diagnostico"])
        print(f"\nPatron: {a['patron']}\n")
        for i, rec in enumerate(a["recomendaciones"], 1):
            print(f"{i}. [{rec['formato']} · {rec['red']}] {rec['titulo']}")
            print(f"   Gancho: {rec['gancho']}")
            print(f"   Porque: {rec['porque']}\n")
        print(f"Dejar de hacer: {a['que_dejar_de_hacer']}")
