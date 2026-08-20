<h1 align="center">Panel de Métricas</h1>

<p align="center">
  <b>Todas tus redes en una pantalla. En tu computadora. Gratis.</b><br>
  Instagram · Facebook · YouTube · Meta Ads
</p>

<p align="center">
  <a href="#instalación"><b>Instalar</b></a> ·
  <a href="#qué-vas-a-ver">Qué hace</a> ·
  <a href="#qué-no-hace">Qué NO hace</a> ·
  <a href="#privacidad">Privacidad</a>
</p>

<!--
  ↓ PONER UNA CAPTURA DEL PANEL ACÁ ↓
  Es lo que más convierte en un repo: la gente decide en 3 segundos mirando la imagen.
  Sacá una del panel con tus datos, subila a la carpeta como `captura.png` y descomentá:

  <p align="center"><img src="captura.png" width="900" alt="El panel"></p>
-->

---

## El problema

Abrís Instagram y ves los últimos 30 días. Los de antes, no están. Entrás a
YouTube Studio y ves otra cosa, con otros nombres para lo mismo. Facebook es una
tercera pestaña. Y para saber si lo de este mes fue mejor que lo del anterior,
terminás anotando números en una planilla.

Las plataformas no te muestran tu historia. Te muestran una ventana móvil de las
últimas semanas, cada una en su idioma. Es como manejar un negocio mirando
solamente la caja de hoy: sabés cuánto entró, no sabés si estás creciendo.

Las herramientas que arreglan eso cuestan entre 30 y 100 dólares por mes, y para
funcionar necesitan una copia de tus datos en el servidor de otro.

## Esto

Un panel que corre en tu computadora. Baja tus métricas de las tres redes, las
junta en una sola pantalla, y **va guardando cada día** para que dentro de seis
meses puedas mirar para atrás.

Sin cuenta que crear. Sin suscripción. Sin servidor de nadie en el medio.

```
Instalar.command  →  seis preguntas  →  tu panel abierto en el navegador
```

---

## Qué vas a ver

**Los números, comparados con vos mismo.** Seguidores, alcance, engagement,
guardados, compartidos — cada uno contra el período anterior. No contra el
promedio de la industria: contra vos hace un mes.

**Qué pieza funcionó y por qué.** Cada publicación con sus ratios reales. Y lo
importante: comparada con la mediana **de su propio formato**. Un reel y una foto
del feed juegan campeonatos distintos; medirlos con la misma vara es lo que hace
que la gente crea que "le fue mal" cuando en realidad le fue normal.

**Un análisis escrito, en castellano.** Qué está pasando con tu cuenta, explicado
con analogías, no con jerga. En vez de *"tu engagement rate cayó 12%"*, algo como
*"tenés la vidriera llena de gente que mira y nadie entra"*. Y abajo, qué hacer.

**Ideas de contenido con el guion listo.** A partir de lo que **ya te funcionó**,
no de una lista genérica de "20 ideas para tu nicho". Con el texto que se dice a
cámara, palabra por palabra, y qué se ve en pantalla en cada tramo.

**Quién te comentó y quedó esperando.** Si usás CTAs del tipo *"comentá PANEL y te
lo mando"*, el panel te separa quién comentó la palabra y todavía no recibió nada.
Esa gente levantó la mano y se está enfriando.

**La competencia, al lado tuyo.** Cuentas que elegís vos, con sus números y su
mediana, para saber si el mal mes fue tuyo o del rubro.

**Las campañas pagas** (opcional). Gasto, CPM, CTR, costo por resultado.

**Un histórico que es tuyo.** Cada corrida guarda el día en un archivo local. Es
lo único que ninguna API te devuelve después: los datos de un día que pasó, se
fueron. Este los junta desde el día que instalás.

<details>
<summary><b>Las pantallas, una por una</b> (clic para abrir)</summary>

<br>

| Pantalla | Qué contesta |
|---|---|
| **Lectura general** | Cómo venís, en una mirada |
| **Canal por canal** | Cada red con sus números y su comparación |
| **El mapa de tus piezas** | Todas tus publicaciones ubicadas por alcance y engagement |
| **Cuánto rinde cada formato** | Si te conviene reel, carrusel o foto — con tus datos, no con los de un blog |
| **De dónde vino tu alcance** | Seguidores, explorar, hashtags: qué te trajo gente |
| **Hasta dónde te miran** | La curva de retención de tus videos |
| **Conversación** | Comentarios, quién te escribió y quién quedó esperando |
| **Competencia** | Las cuentas que elegís, al lado de la tuya |
| **Análisis con IA** | El diagnóstico escrito y qué hacer |
| **Piezas recomendadas** | Ideas con guion, sacadas de lo que ya te funcionó |
| **Generar Creativos** | Una pieza nueva, escrita en el momento |
| **Calendario editorial** | Lo que tenés programado (si usás Postiz) |
| **Campañas de Meta Ads** | Lo que gastaste y qué devolvió |
| **Señales automáticas** | Alertas calculadas sobre los números, no opinadas por un modelo |
| **Estado de conexión** | Si tus tokens siguen vivos, ahora |
| **Cómo leer este panel** | Qué significa cada métrica, en castellano |

</details>

---

## Qué NO hace

Prefiero decírtelo antes de que instales:

- **No publica ni programa.** Es un tablero, no un gestor. Se conecta con Postiz
  si lo usás, pero no postea por su cuenta.
- **No lee cuentas personales de Instagram.** La API de Meta solo abre cuentas
  profesionales (Business o Creator) vinculadas a una Página. Es límite de Meta,
  no del panel.
- **No trae retención ni demografía de TikTok.** Esos campos no existen en la API
  pública de TikTok. Están en la app.
- **No adivina el pasado.** Arranca a guardar desde el día que lo instalás. Los
  meses anteriores no los tiene nadie más que la plataforma, y no los presta.
- **No es un producto con soporte.** Es código abierto que funciona. Si algo se
  rompe, tenés todo el código para arreglarlo.

---

## Instalación

### Lo único imprescindible: Python 3

- **macOS** — ya lo tenés. Si no, abrí la Terminal, escribí `python3`, Enter, y el
  sistema te ofrece instalarlo.
- **Windows** — [python.org/downloads](https://python.org/downloads). En el
  instalador, **tildá "Add Python to PATH"** antes de continuar.

> El panel no usa **ninguna** librería externa, solo lo que viene con Python. No
> hay `pip install` de nada, ni entornos virtuales, ni dependencias que se rompan
> en seis meses.

### Tres pasos

1. **Code → Download ZIP** (botón verde arriba), y descomprimilo.
2. Doble clic en **`Instalar.command`** (macOS) o **`Instalar.bat`** (Windows).
3. Contestá las seis preguntas. Al final el panel se abre solo.

> **La primera vez el sistema va a desconfiar.** Es porque el archivo se bajó de
> internet, no porque tenga algo raro.
> - **macOS**: *"no se puede abrir porque es de un desarrollador no identificado"*
>   → clic derecho sobre el archivo → **Abrir** → **Abrir**.
> - **Windows**: *"Windows protegió tu PC"* → **Más información** → **Ejecutar de
>   todas formas**.

### Lo que sí te va a costar

De los seis pasos, cinco son preguntas de treinta segundos. El que lleva tiempo es
**crear la app de Meta**: entrar a `developers.facebook.com`, crear una app,
darle cinco permisos y generar un token.

El instalador te lleva pantalla por pantalla y —esto es lo importante— **verifica
el token contra la API antes de guardarlo**. Si algo salió mal te enterás en ese
momento, no tres días después con el panel vacío y sin saber por qué.

Si te trabás ahí, no sos vos: es el paso donde se traba todo el mundo. Está todo
explicado dentro del instalador.

**Antes de empezar, tenés que tener:**

- Instagram **profesional** (Business o Creator) vinculado a una Página de Facebook
- Ser administrador de esa Página

---

## Usarlo después

Doble clic en **`Abrir panel.command`** / **`Abrir panel.bat`**.

| Para... | Hacé |
|---|---|
| Actualizar los datos | el botón ↻ arriba a la derecha |
| Entender qué significa cada número | la pantalla **Cómo leer este panel** |
| Ver si la conexión con Meta sigue viva | `python3 instalar.py --estado` |
| Actualizar a la última versión | Doble clic en **`Actualizar.command`** / **`Actualizar.bat`** — reemplaza solo el código; tu `.env`, tu configuración y tu histórico quedan intactos |

---

## El análisis con IA (opcional)

**El panel funciona sin esto.** Los números, los gráficos, el histórico y la
competencia no necesitan inteligencia artificial. Lo que se enciende acá es el
análisis escrito y el generador de ideas.

Dos caminos, hace falta uno solo:

| | Cómo | Qué cuesta |
|---|---|---|
| **Claude Code** | `npm i -g @anthropic-ai/claude-code` y logueate | **Nada extra.** Usa la suscripción de Claude que ya pagás |
| **API key** | `ANTHROPIC_API_KEY` en el `.env` | Por uso: unos 4 USD/mes con un análisis por día |

Si ya tenés Claude Code instalado, el panel lo detecta y lo usa. No configurás nada.

---

## YouTube (opcional)

Instagram y Facebook quedan andando con el instalador. **YouTube pide un paso
aparte**, porque Google no acepta un token pegado: hay que autorizar desde el
navegador y volver con el código.

Es una vez y es gratis:

1. `console.cloud.google.com` → crear un proyecto
2. Habilitar **YouTube Data API v3** y **YouTube Analytics API**
3. Credenciales → ID de cliente de OAuth → **Aplicación de escritorio** → descargar el JSON
4. Dejar ese archivo en la carpeta del panel como `client_secret.json`
5. Y después:

```bash
python3 yt_token.py auth          # te da la URL para autorizar
python3 yt_token.py code "<url>"  # pegás la URL entera a la que te devuelve
```

El navegador va a mostrar un error de conexión al volver: es lo esperado, el
código que hace falta está en la barra de direcciones.

Sin esto el panel funciona igual, solo que la pantalla de YouTube queda vacía.

---

## Privacidad

Esto no es una promesa de marketing, es cómo está hecho:

- **No hay backend.** No existe un servidor mío. Nadie recibe copia de nada.
- **El panel se sirve en `127.0.0.1`**, que es tu propia computadora. No queda
  expuesto a internet.
- **Tus credenciales viven en un archivo `.env`** con permisos `600` (solo tu
  usuario puede leerlo) y está en el `.gitignore` para que no se suba por accidente.
- **El código está entero acá.** Son ~20 archivos de Python sin dependencias:
  se puede leer en una tarde y verificar que hace lo que dice.

Si vas a respaldar algo, respaldá **`historico.jsonl`**. Es lo único que no se
puede recuperar: los datos de días pasados no se le pueden volver a pedir a la API.

---

## Si algo no anda

| Síntoma | Qué está pasando |
|---|---|
| *"CERTIFICATE_VERIFY_FAILED"* o *"conexión segura"* | El Python de python.org viene sin certificados raíz. En macOS: doble clic en `Install Certificates.command`, dentro de la carpeta de tu Python en `/Applications`. El instalador te dice la ruta exacta |
| El panel abre vacío | El token venció o le faltan permisos → `python3 instalar.py --estado` |
| *"el token no ve ninguna Página, aunque la administres"* | Meta emitió el token sin activos adentro. El instalador te ofrece entrar por el **ID de la Página** y sigue de largo. Si preferís arreglar el origen: entrá a `facebook.com/settings?tab=business_tools`, suprimí la app y generá el token de nuevo — mientras la autorización siga viva, Meta no vuelve a preguntarte qué Página darle |
| *"no tiene una cuenta de Instagram profesional vinculada"* | Se vincula desde la Página de Facebook, en *Cuentas conectadas* |
| El puerto está ocupado | Se resuelve solo: busca el siguiente libre y te dice cuál usó. Para forzar uno: `PUERTO=8761 python3 servidor.py` |
| La pantalla de YouTube está vacía | Falta autorizar con Google → `python3 yt_token.py auth` (ver arriba) |
| El análisis con IA falla | Falta Claude Code o la API key (ver arriba) |

---

## Para quién lo hice

Lo armé para mí, porque tenía tres pestañas abiertas y una planilla, y me cansé.
Lo publico porque a esta altura funciona y no tiene sentido que lo use uno solo.

Si lo instalás y te sirve, contame. Si te trabás en la app de Meta, también:
ese paso lo puedo hacer yo.

---

<sub>**IamAutom Command Center** — hecho por [@tincho.olivero](https://www.youtube.com/@Tincho.Olivero) · [iamautom.com](https://iamautom.com)</sub>

<sub>MIT. Hacé lo que quieras con esto, incluso venderlo. Sin garantía. Lo único que pide la licencia es que el aviso de copyright siga estando.</sub>
