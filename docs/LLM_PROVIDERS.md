# Activar Groq y Gemini

Punto 5 del [ROADMAP](ROADMAP.md). Diez minutos, sin tarjeta de crédito, y el harness
los detecta solo.

> **Antes de empezar, una advertencia sobre lo que se pide.** Estas dos cuentas hay que
> crearlas a mano: yo no creo cuentas ni manejo tus credenciales. La clave se pega en
> un archivo `.env` de la raíz del repo, que **está en `.gitignore`** y no se commitea.
> Si alguna vez se te escapa una clave a un commit, no basta con borrarla: hay que
> **revocarla** en la consola del proveedor, porque el commit queda en el historial.

---

## Por qué vale la pena

No es "añadir dos modelos más". La segunda revisión del
[ADR 0009](adr/0009-la-plantilla-gana-al-llm.md) concluyó algo incómodo: **la
consistencia de un LLM local no es reproducible entre máquinas.** El mismo commit, los
mismos modelos recién descargados, en otro equipo, dieron 0.33 donde aquí daban 0.83.

La pregunta que queda abierta es si eso es de **la inferencia local** —dos GPUs
distintas, dos versiones de runtime— o **del problema**, es decir de pedirle a un modelo
que redacte un documento legal. Dos modelos hospedados, que corren en el servidor del
proveedor y no en tu máquina, separan una cosa de la otra.

Es la diferencia entre "mi portátil dio esto" y "esto es una propiedad del sistema", que
es justamente la distinción que el proyecto ya tuvo que retractar dos veces.

---

## 1 · Groq — Llama 3.3 70B

**Qué es.** Groq corre modelos abiertos sobre hardware propio. El tier gratuito da
~30 peticiones por minuto y ~1.000 por día, que es holgado: el harness gasta **24
llamadas por corrida** (3 casos × 2 idiomas × 2 modos × 2 repeticiones).

**No pide tarjeta de crédito.**

### Pasos

1. Entra a **<https://console.groq.com>**.
2. Crea la cuenta (Google o GitHub sirven; es más rápido que email + verificación).
3. Menú lateral → **API Keys** → **Create API Key**.
4. Ponle un nombre que te diga de dónde salió: `credit-risk-mlops-local`.
5. **Copia la clave ahora.** Empieza por `gsk_` y solo se muestra una vez. Si la
   pierdes, se borra y se crea otra — no se puede recuperar.

### Qué modelo usa el proyecto

`llama-3.3-70b-versatile`, fijado en
[`src/crmlops/llm/providers.py`](../src/crmlops/llm/providers.py). Si Groq retira ese
identificador, la llamada devuelve 404 y el harness lo reporta como error del brazo, no
como silencio. Para cambiarlo:

```python
GroqProvider(model="el-que-sea")
```

---

## 2 · Gemini — Google AI Studio

**Qué es.** El tier gratuito de la API de Gemini, a través de AI Studio. Es distinto de
Vertex AI, que sí exige facturación: **AI Studio no pide tarjeta.**

### Pasos

1. Entra a **<https://aistudio.google.com/app/apikey>** con tu cuenta de Google.
2. Acepta los términos de la API (es la primera vez, y solo una vez).
3. **Create API key** → *Create API key in new project*, salvo que ya tengas un
   proyecto de Google Cloud donde la quieras.
4. Copia la clave. Aquí sí puedes volver a verla en esa misma pantalla.

### Una diferencia que importa

**El tier gratuito de Gemini puede usar tus entradas para mejorar sus modelos.** Para
este harness da igual —los casos son sintéticos y están en el repo, no hay ni un dato
real de un solicitante— pero conviene tenerlo escrito, porque es exactamente el
argumento que el proyecto usa a favor de Ollama: *"corre local, ningún dato crediticio
sale de la máquina"*. Ese argumento sigue valiendo para el brazo local y **no** vale para
los dos hospedados.

### Qué modelo usa el proyecto

`gemini-2.0-flash`.

---

## 3 · Pegar las claves

En la **raíz del repositorio** (junto a `config.yaml`), crea un archivo llamado `.env`:

```bash
cp .env.example .env
```

Y edítalo:

```
FRED_API_KEY=
CENSUS_API_KEY=
GROQ_API_KEY=gsk_tu_clave_de_groq
GEMINI_API_KEY=AIza_tu_clave_de_gemini
```

Reglas del formato, que son cuatro:

- `CLAVE=valor`, una por línea.
- `#` al principio de línea es comentario.
- Se admite el prefijo `export`.
- Las comillas envolventes se quitan (`"así"` y `'así'` valen).

**Sin comillas hace falta nada más**, y **no dejes espacios alrededor del `=`** si el
valor los va a heredar — en realidad el parser los recorta, pero no te acostumbres.

> **Esto no funcionaba hasta hoy.** `.env.example` decía "copiar a .env" y el harness
> decía "claves en .env", pero **ningún módulo leía el archivo**: los proveedores hacen
> `os.environ.get(...)`, que solo ve variables de entorno reales. Seguir esta misma
> instrucción dejaba los dos brazos en "no disponibles", sin error y sin pista.
> Ahora lo carga [`src/crmlops/env.py`](../src/crmlops/env.py) al importar los
> proveedores, y hay ocho tests que lo sostienen.

### Alternativa: variables de entorno del sistema

Si prefieres no tener un archivo con claves en el disco del proyecto:

```powershell
# PowerShell, solo para esta sesión
$env:GROQ_API_KEY = "gsk_..."
$env:GEMINI_API_KEY = "AIza..."
```

```powershell
# PowerShell, permanente para tu usuario
setx GROQ_API_KEY "gsk_..."
setx GEMINI_API_KEY "AIza..."
```

**El entorno le gana al archivo.** Si la variable ya existe, `.env` no la pisa: quien la
exportó a mano decidió, y un archivo del disco no debe cambiar esa decisión sin avisar.

---

## 4 · Verificar

Primero, que las claves llegaron:

```powershell
.\run llm-evals
```

La cabecera te dice qué brazos entraron:

```
Brazos: template/deterministic, ollama/llama3.2:3b, ollama/qwen2.5:7b, groq/llama-3.3-70b-versatile, gemini/gemini-2.0-flash
```

Si falta alguno, el mensaje ahora distingue tres situaciones distintas:

| Lo que imprime | Qué pasó |
|---|---|
| `No hay .env en la raiz del repo` | El archivo no existe, o está en otra carpeta |
| `.env existe. Sin valor: GROQ_API_KEY` | El archivo está pero la clave quedó vacía |
| `.env existe. Claves cargadas pero el proveedor no respondio.` | La clave llegó y la llamada falló — mira el error del brazo en la tabla |

Antes las tres imprimían lo mismo, que es cómo se pierde una tarde.

### Cuánto tarda

Con los dos brazos hospedados, unos **3–5 minutos**. Los brazos locales son los lentos
(Ollama en CPU); Groq es el más rápido de los cinco por bastante.

---

## 5 · Qué mirar cuando termine

La corrida escribe tres artefactos en `exports/`:

| Archivo | Qué trae |
|---|---|
| `llm_evals_summary.csv` | La tabla comparativa: fidelidad, cumplimiento, legibilidad, **consistencia** y tasa de aprobación por brazo |
| `llm_evals_detail.csv` | Caso por caso, con las razones citadas y la decisión de la compuerta del híbrido |
| `llm_fallback_analysis.csv` | Si la inconsistencia del híbrido viene de la compuerta o del modelo |

**La columna que responde la pregunta es `consistente`.** Los brazos locales, medidos en
dos máquinas, dieron 0.83 y 0.33. Si Groq y Gemini salen consistentes, la irreproducibilidad
es de la inferencia local. Si también bailan, el problema es pedirle a un LLM que redacte
un documento que tiene que ser idéntico cada vez.

**Cualquiera de las dos respuestas es publicable.** La segunda refuerza la decisión que
el ADR 0009 ya tomó —la plantilla determinista se queda en producción— y la primera la
matiza sin cambiarla.

### Después de correr

Actualiza el ADR 0009 con lo que salga, y no promedies entre máquinas: el propio ADR
dice que un promedio de dos equipos da una cifra más presentable y menos cierta. Se
publica el rango y el número de equipos donde se midió.

---

## Problemas conocidos

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `401 Unauthorized` en Groq | Clave mal copiada, o revocada | Genera otra en la consola. Fíjate en que empiece por `gsk_` |
| `400 API key not valid` en Gemini | Clave de Vertex AI, no de AI Studio | Son APIs distintas. La de AI Studio sale de `aistudio.google.com/app/apikey` |
| `429 Too Many Requests` | Pasaste el límite del tier gratuito | Espera un minuto. El harness son 24 llamadas; si lo corriste varias veces seguidas, es normal |
| Los brazos entran pero fallan todos | Red, proxy o firewall corporativo | El error concreto sale en la columna `error` de `llm_evals_detail.csv` |
| Todo sigue en "no disponibles" con `.env` creado | El archivo está en otra carpeta | Tiene que estar en la **raíz del repo**, al lado de `config.yaml` — no dentro de `src/` ni de `docs/` |

---

## Lo que NO hay que hacer

- **No commitees `.env`.** Está en `.gitignore`, pero `git add -f` lo salta. Si pasa:
  revoca la clave en la consola del proveedor y crea otra. Borrarla del archivo no
  sirve, porque el commit sigue en el historial.
- **No pongas las claves en `config.yaml`.** Ese archivo sí se commitea y además entra
  en el fingerprint de los gates.
- **No metas datos reales de solicitantes en el harness.** Los tres casos son sintéticos
  y están escritos en `src/crmlops/llm/harness.py` a propósito. Los brazos hospedados
  mandan el prompt al servidor del proveedor; el local, no.
