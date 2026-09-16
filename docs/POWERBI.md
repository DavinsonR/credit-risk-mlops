# Armar el informe de Power BI

Punto 4 del [ROADMAP](ROADMAP.md). Medio día, y es el único punto que no puedo hacer yo:
requiere **Power BI Desktop**, que solo corre en Windows y no se puede automatizar desde
línea de comandos.

`powerbi/README.md` es la **especificación** —qué tabla alimenta qué visual, y qué no
debe mostrarse—. Este documento es el **procedimiento**: qué hacer, en qué orden, y qué
hacer cuando algo falle.

---

## Lo que ya está hecho, y lo que no

| | Estado |
|---|---|
| Modelo semántico en TMDL: 7 tablas, 16 medidas DAX, parámetro de ruta | **Escrito** |
| Cada `sourceColumn` verificada contra el encabezado real del CSV | **Verificada por test** (`tests/test_pbip_bindings.py`) |
| Que ninguna medida DAX tenga un umbral o un nombre de modelo escrito a mano | **Verificado por test** |
| Que la cadena de artefactos del `.pbip` resuelva | **Verificada por test** (nuevo: ver abajo) |
| **El layout: páginas, visuales, formato** | **No está. Es lo que vas a hacer.** |

**Declaración honesta, y sigue en pie:** este modelo **nunca se ha abierto en Power BI
Desktop.** Se escribió a mano porque TMDL es texto y porque el enlace a los datos sí es
verificable sin Power BI. Que el TMDL pase los tests de este repo **no garantiza** que
Desktop lo cargue sin ajustes. Si algo no abre, no es sorpresa: es exactamente el riesgo
que el README de `powerbi/` declara.

> **Un defecto que salió al escribir esta guía.** El `.pbip` declaraba el artefacto
> `credit-risk-mlops.Report` y **esa carpeta no existía** — solo se había escrito el
> modelo semántico. Desktop no abre un proyecto cuyo informe no existe, así que la
> primera instrucción de la guía anterior (*"abrir `credit-risk-mlops.pbip`"*) era
> inejecutable. Ya está creado el andamiaje mínimo, y hay un test que ahora comprueba lo
> que el propio `.pbip` declara en vez de una lista escrita a mano. Ese andamiaje
> **tampoco se ha abierto en Desktop**: si lo rechaza, el paso 2 de abajo dice qué hacer.

---

## 0 · Antes de abrir nada

### Instalar Power BI Desktop

Microsoft Store → *Power BI Desktop*, o <https://powerbi.microsoft.com/desktop/>. Es
gratis y no necesita cuenta de Power BI Service para trabajar en local. **No hace falta
licencia Pro** para lo que vas a hacer aquí.

### Activar el formato PBIP

Está detrás de una bandera de vista previa y **sin ella Desktop no abre un `.pbip`**:

**Archivo → Opciones y configuración → Opciones → Características de vista previa** →
marcar **"Guardar archivos de proyecto de Power BI (.pbip)"**.

Reinicia Desktop.

### Comprobar que los exports están

El modelo lee seis CSV. Si falta alguno, el refresco falla con un error de archivo no
encontrado, que es confuso porque parece un problema de ruta:

```powershell
.\run all            # entrena, gates, model card, economics
.\run web-exports    # el bundle JSON que alimentan Config y Umbrales
```

Los seis archivos que tienen que existir en `exports/`:

| Archivo | Lo produce |
|---|---|
| `model_comparison.csv` | `run train` |
| `decision_curve.csv` | `run economics` |
| `stress_test.csv` | `run stress` |
| `scorecard_points.csv` | `run train` |
| `hmda_fairness_race.csv` | `run hmda-train` |
| `hmda_fairness_delta.csv` | `run hmda-train` |

Y dos JSON, en `exports/web/`: `modelos.json` y `manifest.json` (los produce
`run web-exports`). Están commiteados, así que en un clon nuevo ya están — salvo que
hayas reentrenado.

**Comprobación rápida** de que no falta ninguno:

```powershell
.\run test
```

`test_cada_csv_que_el_modelo_lee_existe` y `test_cada_json_que_el_modelo_lee_existe`
fallan si falta uno, con el nombre del que falta.

---

## 1 · Abrir el proyecto

Doble clic en **`powerbi/credit-risk-mlops.pbip`**.

Desktop carga el modelo semántico desde TMDL y abre un informe con una página vacía
llamada *"1 - Desempeno"*.

## 2 · Si no abre

Tres fallos posibles, en orden de probabilidad:

**a) "La característica de vista previa no está habilitada".** Vuelve al paso 0. Es lo
más común y el mensaje es claro.

**b) Desktop rechaza `report.json`.** El andamiaje del informe lo escribí a mano y no lo
he podido verificar contra Desktop. Si pasa:

1. Borra la carpeta `powerbi/credit-risk-mlops.Report/` entera.
2. Abre Desktop en blanco → **Archivo → Guardar como** → elige *Power BI project
   (.pbip)* → guárdalo **encima** de `powerbi/credit-risk-mlops.pbip`.
3. Desktop genera su propia carpeta `.Report`, que es la buena.
4. Luego conecta ese informe al modelo semántico que ya está: el `definition.pbir` que
   Desktop genere tiene que apuntar a `../credit-risk-mlops.SemanticModel`.

Si haces esto, corre `.\run test` después: hay un test que comprueba que la referencia
sea **relativa** y no una ruta absoluta de tu máquina.

**c) Un error de TMDL.** Es el riesgo que el README declara. El mensaje de Desktop dice
la tabla y la línea. Anótalo tal cual y lo arreglamos: es información que solo se puede
obtener abriéndolo, y es la razón por la que este paso es tuyo.

## 3 · Ajustar la ruta del repositorio

**Es el único valor que depende de tu máquina.**

**Inicio → Transformar datos → Administrar parámetros** → `RutaRepo`.

El valor commiteado es la ruta de la máquina donde se escribió el modelo:

```
C:\Users\davin\Desktop\Claude\MachineLearning\credit-risk-mlops
```

Si el repo está ahí, no toques nada. Si lo moviste o lo clonaste en otro sitio, ponle la
ruta nueva: **sin barra final**, y es la carpeta que contiene `config.yaml`, no la que
contiene `exports/`.

Luego **Inicio → Actualizar**.

Si un error dice `File.Contents ... no se encontró`, la ruta está mal o falta un export.
El mensaje trae el nombre del archivo; compáralo con la tabla del paso 0.

---

## 4 · Las cuatro páginas

La especificación completa —qué visual, con qué campo, y por qué— está en
[`powerbi/README.md`](../powerbi/README.md). Aquí va el resumen ejecutable.

### Página 1 · Desempeño

| Visual | Campos |
|---|---|
| Tabla | `Modelos`: `modelo`, `auc_test`, `drop_oot`, `brier_test`, `ece_test` + la medida `Es produccion` |
| Tarjeta | `AUC produccion` |
| Tarjeta | `Margen sobre baseline` |
| Tarjeta | `Margen cumple` (devuelve "Cumple" / "NO cumple") |

La tabla tiene que mostrar **los tres modelos**, baseline incluido. Enseñar solo el
ganador convierte una comparación en una afirmación.

### Página 2 · Pérdida en dólares

| Visual | Campos |
|---|---|
| Gráfico de líneas | Eje: `Decision[decline_rate]`. Valores: `Perdida evitada al corte` **y** `Volumen bueno sacrificado` |
| Tarjeta | `Costo por dolar evitado` |

**Las dos líneas van en el mismo visual, no en pestañas separadas.** Son el mismo
análisis: rechazar el 10% más riesgoso evita $276M y renuncia a $1.99B de volumen sano,
7.2x. Un tablero que enseña solo la primera está vendiendo, no informando.

### Página 3 · Equidad

| Visual | Campos |
|---|---|
| Tabla | `EquidadRaza` completa: `group`, `n`, `selection_rate`, `positive_rate`, `calibration_ratio` |
| Tarjeta grande | `Veredicto equidad` |
| Tabla | `EquidadDelta`: `dimension`, `dir_observado`, `dir_modelo`, `delta` |

**Los seis grupos, no los que quedan bien.** Y `EquidadDelta` es la comparación que casi
nadie hace: mide cuánta disparidad **agrega** el modelo sobre la que ya había en los
datos históricos.

### Página 4 · Estrés

| Visual | Campos |
|---|---|
| Tabla | `Estres` por cohorte |
| Tarjeta | `AUC en crisis` |
| Tarjeta | `Subestimacion en crisis` |

**Las dos tarjetas del mismo tamaño que el AUC de la página 1.** Un AUC citado sin
régimen es un número de un solo escenario: en un régimen tipo 2007 el modelo cae a
**0.5456** y subestima el riesgo **8x**.

### Pie de página, en las cuatro

Un cuadro de texto con la medida **`Procedencia`**, que imprime el vintage de los datos y
las dos huellas (configuración y código). Un validador cruza eso con
`exports/metrics.json` y con el commit, y sabe que el tablero y el repositorio hablan de
la misma corrida.

---

## 5 · Lo que NO debe mostrar

Esto no es estilo, es el contenido del proyecto:

- **El modelo de acceso como aprobado.** No lo está: disparate impact **0.7639** contra
  un umbral de **0.80**, y `promoted: false` en el artefacto. La medida
  `Veredicto equidad` ya lo dice — no la sustituyas por un semáforo verde.
- **La pérdida evitada sin el volumen sacrificado.** Ver página 2.
- **Números que el proyecto retractó:** el benchmark DuckDB/PySpark de 29.3x (no
  replicó: 14.3x en otra máquina) y la consistencia de 0.83 del LLM (0.33 en otra
  máquina). Si los quieres, publica el rango y en cuántos equipos se midió.
- **Un umbral tecleado en una medida DAX.** Hay un test que lo prohíbe
  (`test_ninguna_medida_hardcodea_un_umbral`): todos salen de la tabla `Umbrales`, que
  sale de `config.yaml`. Si el tablero tuviera su propia copia, podría mostrar "cumple"
  sobre algo que el gate bloquea — y el tablero es lo que alguien mira en una reunión.

---

## 6 · Al guardar

**Archivo → Guardar.** Desktop reescribe el TMDL y el JSON del informe.

Antes de commitear:

```powershell
.\run test
git diff --stat powerbi/
```

Dos cosas que mirar en el diff:

1. **Que `RutaRepo` no cambie a otra máquina.** Si tu repo está en otra ruta, Desktop la
   va a guardar. Devuélvela al valor commiteado antes de empujar, o el siguiente que
   clone tendrá que cambiarla igual — y peor, el diff dirá que cambió el modelo cuando
   solo cambió tu escritorio.
2. **Que no aparezcan credenciales.** Desktop a veces guarda información de conexión.
   Aquí las fuentes son archivos locales, así que no debería, pero es un diff de dos
   segundos.

Si algún test falla después de guardar, léelo: están escritos para atrapar exactamente
las tres regresiones que importan (un umbral hardcodeado, un nombre de modelo escrito a
mano, y una columna enlazada a un CSV que no la tiene).

---

## 7 · Cuando esté listo

Actualiza tres sitios:

1. **`powerbi/README.md`** — quita la declaración de "nunca se ha abierto en Desktop" y
   pon qué versión lo abrió. Esa frase es cierta hoy y deja de serlo ese día.
2. **`docs/ROADMAP.md`** — el punto 4 sale de la lista.
3. **Capturas.** Cuatro PNG en `powerbi/shots/` y enlazadas desde el README. El
   portafolio ya tiene un patrón para esto en `lib/powerbi-shots.ts`; la página de
   credit-risk puede mostrarlas igual que la de Medallion Insights.

La captura que más vale es **la página 3**: un tablero que enseña su propio modelo
bloqueado por el gate de equidad. Esa no la tiene nadie.
