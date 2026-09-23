# Lo que falta, paso a paso

Estado verificado el 23 de septiembre de 2026 contra la API de GitHub y el repositorio.
El [ROADMAP](ROADMAP.md) explica **por qué** importa cada cosa; esto es **qué hacer**, en
orden, con los clics.

---

## Ya está hecho (verificado, no supuesto)

| | Cómo se verificó |
|---|---|
| Descripción en los 5 repositorios | `GET /users/DavinsonR/repos` — ninguno devuelve `description: null` |
| Topics en los 4 repos de proyecto | 12, 12, 13 y 10 topics. El repo de perfil va sin topics, a propósito |
| La bio ya no contradice al perfil | Ya no dice *"currently pursuing an MSc"* |
| CI en verde | Última corrida `2b40aea`: success |

Quedan **tres**. Dos son de media hora entre las dos; la tercera es la única que no
puede hacer nadie más que tú, y es la que más vale en una entrevista.

---

# 1 · Las dos claves de LLM

**15 minutos. Sin tarjeta de crédito.** Detalle completo y solución de problemas en
[LLM_PROVIDERS.md](LLM_PROVIDERS.md).

## 1.1 · Groq

1. Entra a **<https://console.groq.com>**.
2. Crea la cuenta (Google o GitHub es más rápido que email + verificación).
3. Menú lateral → **API Keys** → **Create API Key**.
4. Nómbrala `credit-risk-mlops-local`.
5. **Cópiala en ese momento.** Empieza por `gsk_` y **solo se muestra una vez**. Si la
   pierdes no se recupera: se borra y se crea otra.

## 1.2 · Gemini

1. Entra a **<https://aistudio.google.com/app/apikey>** con tu cuenta de Google.
2. Acepta los términos de la API (solo la primera vez).
3. **Create API key** → *Create API key in new project*.
4. Cópiala. Esta sí puedes volver a verla en la misma pantalla.

> **Es AI Studio, no Vertex AI.** Vertex exige facturación; AI Studio no. Si la clave
> empieza distinto o te pide habilitar facturación, estás en el sitio equivocado.

## 1.3 · Pegarlas

El archivo **ya está creado** en la raíz del repositorio:
`C:\Users\davin\Desktop\Claude\MachineLearning\credit-risk-mlops\.env`

Ábrelo con el Bloc de notas y rellena las dos líneas:

```
FRED_API_KEY=
CENSUS_API_KEY=
GROQ_API_KEY=gsk_lo_que_copiaste_de_groq
GEMINI_API_KEY=AIza_lo_que_copiaste_de_google
```

Sin comillas, sin espacios alrededor del `=`, y **guarda**.

`.env` está en `.gitignore`: no se sube. Si alguna vez se te escapa una clave a un
commit, no basta con borrarla del archivo — hay que **revocarla** en la consola del
proveedor, porque el commit queda en el historial.

## 1.4 · Comprobar

```bash
.\run llm-evals
```

Mira la primera línea de la salida. Tiene que decir **cinco brazos**:

```
Brazos: template/deterministic, ollama/llama3.2:3b, ollama/qwen2.5:7b, groq/llama-3.3-70b-versatile, gemini/gemini-2.0-flash
```

Si falta alguno, el mensaje te dice exactamente qué pasó:

| Dice | Significa |
|---|---|
| `No hay .env en la raiz del repo` | El archivo no está donde debe (tiene que estar junto a `config.yaml`) |
| `.env existe. Sin valor: GROQ_API_KEY` | Está el archivo pero la línea quedó vacía |
| `.env existe. Claves cargadas pero el proveedor no respondio.` | La clave llegó y la llamada falló — mira la columna `error` |

**Y avísame.** Yo corro el harness completo y actualizo el ADR 0009 con lo que salga.
Tarda 3–5 minutos.

> **Qué estamos midiendo.** El ADR 0009 concluyó que la consistencia de un LLM local
> **no reproduce entre máquinas**: 0.83 aquí, 0.33 en otro equipo, mismo commit. La
> pregunta abierta es si eso es de la **inferencia local** o del **problema**. Dos
> modelos que corren en el servidor del proveedor separan una cosa de la otra.
> Cualquiera de las dos respuestas es publicable.

> **Una advertencia que corresponde.** El tier gratuito de Gemini puede usar las
> entradas para entrenar sus modelos. Aquí da igual —los tres casos del harness son
> sintéticos y están escritos en el repositorio, no hay ni un dato real de un
> solicitante— pero es justo el argumento que el proyecto usa a favor de Ollama
> (*"corre local, ningún dato sale de la máquina"*). Ese argumento vale para el brazo
> local y **no** vale para los dos hospedados. Por eso está escrito.

---

# 2 · Abrir el informe de Power BI

**Una hora.** El informe **ya está escrito** —4 páginas, 20 visuales, validados contra
los esquemas publicados de Microsoft—. Lo que falta es abrirlo, y eso solo lo puede
hacer alguien con Desktop. Detalle completo en [POWERBI.md](POWERBI.md).

## 2.1 · Instalar Power BI Desktop

Microsoft Store → *Power BI Desktop*, o <https://powerbi.microsoft.com/desktop/>.
Gratis, sin cuenta de Power BI Service, **sin licencia Pro** para lo que vas a hacer.

## 2.2 · Activar las DOS banderas de vista previa

**Archivo → Opciones y configuración → Opciones → Características de vista previa.**

Marca las dos:

- ☐ **Guardar archivos de proyecto de Power BI (.pbip)**
- ☐ **Almacenar informes usando el formato de metadatos mejorado (PBIR)**

**Sin la segunda no abre.** El informe de este repositorio está escrito en PBIR. Si tu
versión de Desktop no ofrece esa casilla, actualízala — llegó a mediados de 2024.

Reinicia Desktop.

## 2.3 · Abrir

Doble clic en **`powerbi\credit-risk-mlops.pbip`**.

Deberías ver cuatro páginas: *Desempeño*, *Pérdida en dólares*, *Equidad*, *Estrés*.

## 2.4 · Si no abre — esto es lo importante

**Apunta el mensaje de error tal cual y mándamelo.** No es un trámite: es el único dato
que yo no puedo obtener, y con él corrijo el generador. Nadie ha abierto estos archivos
en Desktop; cumplen los esquemas de Microsoft, pero cumplir un esquema no es cargar.

Los tres fallos posibles, en orden de probabilidad:

1. **"La característica de vista previa no está habilitada"** → vuelve al 2.2.
2. **Desktop rechaza el informe PBIR** → mándame el mensaje. En [POWERBI.md](POWERBI.md)
   está la salida provisional mientras tanto.
3. **Un error de TMDL** → también mándamelo, con la tabla y la línea que diga.

## 2.5 · Ajustar la ruta

**Inicio → Transformar datos → Administrar parámetros → `RutaRepo`.**

El valor guardado es:

```
C:\Users\davin\Desktop\Claude\MachineLearning\credit-risk-mlops
```

Si el repositorio está ahí, no toques nada. Si lo moviste, pon la ruta nueva **sin barra
final** — es la carpeta que contiene `config.yaml`.

Luego **Inicio → Actualizar**.

## 2.6 · Qué mirar en cada página

| Página | Qué tiene que verse |
|---|---|
| **1 · Desempeño** | Los **tres** modelos, baseline incluido. No solo el ganador |
| **2 · Pérdida en dólares** | Las **dos líneas en el mismo visual**: pérdida evitada y volumen sacrificado |
| **3 · Equidad** | **Todos** los grupos, y el veredicto diciendo NO CUMPLE |
| **4 · Estrés** | Las dos tarjetas de crisis **del mismo tamaño** que el AUC de la página 1 |

Las cuatro llevan al pie la medida `Procedencia`, con el vintage y las dos huellas.

## 2.7 · Lo que vas a tener que ajustar a mano

El generador escribe estructura, no estética:

- **Separador de miles** en los importes.
- **Los ejes de la página 2.** `loss_avoided` va en cientos de millones y
  `good_volume_foregone` en miles de millones. Usa eje secundario o escala logarítmica —
  pero **no los separes en dos visuales**, que es justo el punto de esa página.
- **Ordenar** la tabla de la página 1 por `auc_test` descendente.
- **Formato condicional** en la página 3: el veredicto en rojo cuando dice NO CUMPLE.

## 2.8 · Al guardar

**Archivo → Guardar.** Luego, antes de commitear:

```bash
.\run test
```

Y mira dos cosas en el diff:

- Que **`RutaRepo` no cambie** a la ruta de otra máquina.
- Que no aparezcan credenciales (no debería: las fuentes son archivos locales).

> **No corras `run pbir` después de ajustar en Desktop.** El generador **borra y
> reescribe** `definition/`: perderías todo lo que ajustaste. Si arreglas algo, dímelo
> y lo llevo al script, para que la próxima generación ya salga bien en vez de que el
> arreglo viva solo en tu copia.

## 2.9 · Cuando quede

Cuatro capturas en `powerbi/shots/`. La que más vale es **la página 3**: un tablero que
enseña su propio modelo bloqueado por el gate de equidad. Esa no la tiene nadie.

---

# 3 · Los veintiún `_(escribir: ...)_` de NOTES.md

**Una a dos horas, y es lo único de esta lista que nadie más puede hacer.**

Están vacíos **a propósito**. Cada uno está en el punto exacto donde el proyecto aprendió
algo, y son las preguntas que te van a hacer en una entrevista. Escritos por otro no
sirven para eso: un párrafo mío ahí convertiría el argumento del proyecto en su
contrario.

## Cómo encontrarlos

```bash
grep -n "_(escribir:" NOTES.md
```

## Cómo escribirlos

Dos o tres frases cada uno, en tu voz. No hace falta que sean elegantes: hacen falta que
sean **tuyos**. Si uno no te sale, bórralo — un hueco menos y honesto vale más que un
párrafo de relleno.

Los cuatro que yo respondería primero, porque son los que un entrevistador va a tocar:

| Dónde | La pregunta |
|---|---|
| Semana 10 | Qué se siente publicar tu propio registro de errores como argumento de venta, y por qué funciona mejor que el AUC |
| Semana 11 | Qué cambia en cómo lees un gradiente temporal cuando el período base es un **régimen** y no un año |
| Semana 11 | Por qué un ajuste por tendencia previa es tan fácil de defender en un seminario y tan difícil de justificar aquí |
| Semana 11 | Por qué escribir el instructivo encuentra cosas que correr el código no encuentra |

---

## Resumen

| # | Qué | Tiempo | Quién |
|---|---|---|---|
| 1 | Las dos claves de LLM | 15 min | Tú creas las cuentas; yo corro el harness |
| 2 | Abrir el informe de Power BI | 1 hora | Solo tú (hace falta Desktop) |
| 3 | Los `_(escribir: ...)_` | 1–2 horas | Solo tú, y por eso existen |

**Nada de esto bloquea mostrar el proyecto.** CI en verde, 239 tests, 10 gates, 14 ADRs,
página propia en el portafolio y la demo corriendo en el navegador. Esto es lo que
faltaría para cerrarlo del todo.
