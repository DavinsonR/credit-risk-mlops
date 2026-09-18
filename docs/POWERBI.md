# Armar el informe de Power BI

Punto 3 del [ROADMAP](ROADMAP.md). El informe **ya está escrito**; lo que falta es
abrirlo, porque eso requiere **Power BI Desktop** y Desktop no se puede automatizar desde
línea de comandos. Calcula una hora, no medio día.

`powerbi/README.md` es la **especificación** —qué tabla alimenta qué visual, y qué no
debe mostrarse—. Este documento es el **procedimiento**: qué hacer, en qué orden, y qué
hacer cuando algo falle.

---

## Lo que ya está hecho, y lo que no

| | Estado |
|---|---|
| Modelo semántico en TMDL: 7 tablas, 16 medidas DAX, parámetro de ruta | **Escrito** |
| Cada `sourceColumn` verificada contra el encabezado real del CSV | **Verificada por test** |
| **El informe: 4 páginas, 20 visuales** | **Escrito en PBIR y validado contra los esquemas de Microsoft** |
| Que cada campo del informe exista en el modelo | **Verificado por test** |
| Que ningún umbral ni nombre de modelo esté escrito a mano | **Verificado por test** |
| **Que Power BI Desktop lo abra** | **No verificado. Es lo que vas a hacer.** |

El informe ya no hay que construirlo clic a clic: está escrito como **PBIR** —el formato
de metadatos mejorado, un archivo por página y uno por visual, con esquemas públicos— y
se genera con `run pbir`, que valida cada archivo contra el esquema que declara y
comprueba que **cada campo existe en el TMDL**, leyéndolo del TMDL y no de una lista
escrita a mano.

Lo que te queda es abrirlo, mirar que se vea bien y ajustar formato.

> **Cumplir el esquema no es abrir en Desktop, y eso hay que decirlo.** Un archivo puede
> validar y aun así no cargar: por un tipo de visual mal elegido, por un rol que ese
> visual no acepta, o porque PBIR es vista previa y exige una versión de Desktop
> reciente. La sección 2 dice qué hacer en cada caso. **Nada de esto se ha abierto en
> Power BI Desktop**, y esa frase sigue siendo cierta hasta que la borres tú.

> **Un defecto que salió al escribir esta guía.** El `.pbip` declaraba el artefacto
> `credit-risk-mlops.Report` y **esa carpeta no existía** — solo se había escrito el
> modelo semántico. Desktop no abre un proyecto cuyo informe no existe, así que la
> primera instrucción de la versión anterior era inejecutable. El test ahora comprueba
> lo que el propio `.pbip` declara en vez de una lista escrita a mano.

## 0 · Antes de abrir nada

### Instalar Power BI Desktop

Microsoft Store → *Power BI Desktop*, o <https://powerbi.microsoft.com/desktop/>. Es
gratis y no necesita cuenta de Power BI Service para trabajar en local. **No hace falta
licencia Pro** para lo que vas a hacer aquí.

### Activar el formato PBIP

Está detrás de una bandera de vista previa y **sin ella Desktop no abre un `.pbip`**:

**Archivo → Opciones y configuración → Opciones → Características de vista previa** →
marcar las **dos**:

- **"Guardar archivos de proyecto de Power BI (.pbip)"**
- **"Almacenar informes usando el formato de metadatos mejorado (PBIR)"**

La segunda es imprescindible: el informe de este repositorio está escrito en PBIR, y sin
esa bandera Desktop no lo reconoce. Si tu versión no la ofrece, actualízala — PBIR llegó
a mediados de 2024.

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

Desktop carga el modelo semántico desde TMDL y el informe desde PBIR: cuatro páginas
—Desempeño, Pérdida en dólares, Equidad, Estrés— con veinte visuales ya colocados.

## 2 · Si no abre

Tres fallos posibles, en orden de probabilidad:

**a) "La característica de vista previa no está habilitada".** Vuelve al paso 0. Es lo
más común y el mensaje es claro.

**b) Desktop rechaza el informe PBIR.** Es el riesgo declarado: los archivos cumplen los
esquemas publicados de Microsoft, pero **nadie los ha abierto en Desktop**. Si pasa:

1. **Apunta el mensaje de error tal cual.** Es la información que yo no puedo obtener, y
   con ella corrijo el generador — no es un trámite, es el dato.
2. Salida provisional: borra `powerbi/credit-risk-mlops.Report/` entera, abre Desktop en
   blanco → **Archivo → Guardar como** → *Power BI project (.pbip)* → guárdalo **encima**
   de `powerbi/credit-risk-mlops.pbip`. Desktop genera su propia carpeta `.Report`, y
   desde ahí se arma a mano con la sección 4 como especificación.
3. Si haces eso, el `definition.pbir` que Desktop genere tiene que apuntar a
   `../credit-risk-mlops.SemanticModel`. Corre las pruebas después: hay un test que
   exige que esa referencia sea **relativa** y no una ruta absoluta de tu máquina.

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

## 4 · Verificar las cuatro páginas

Ya están escritas. Lo que toca es mirarlas. La especificación de por qué cada visual es
el que es está en [`powerbi/README.md`](../powerbi/README.md).

| Página | Qué tiene | Qué mirar |
|---|---|---|
| **1 · Desempeño** | Tabla de los 3 modelos + tarjetas de `AUC produccion`, `Margen sobre baseline`, `Margen cumple` | Que aparezcan **los tres**, baseline incluido |
| **2 · Pérdida en dólares** | Curva con `Perdida evitada al corte` **y** `Volumen bueno sacrificado` en el mismo eje, tarjeta de `Costo por dolar evitado`, tabla de apoyo | Que las **dos líneas** estén en el mismo visual |
| **3 · Equidad** | `EquidadRaza` completa, `EquidadDelta`, tarjetas de `Veredicto equidad` y `Disparate impact modelo`, tabla de `Umbrales` | Que salgan **todos** los grupos y que el veredicto diga NO CUMPLE |
| **4 · Estrés** | Tabla de cohortes + tarjetas de `AUC en crisis` y `Subestimacion en crisis` | Que las dos tarjetas tengan **el mismo tamaño** que el AUC de la página 1 |

Las cuatro llevan al pie la medida **`Procedencia`**, que imprime el vintage y las dos
huellas. Hay un test que falla si alguna se queda sin ella.

### Lo que sí vas a tener que ajustar a mano

El generador escribe **estructura**, no estética. Desktop hace el resto mejor que un
JSON escrito a ciegas:

- **Formato de número.** Los dólares salen sin separador de miles y los ratios con
  demasiados decimales. Selecciona la columna → *Formato*.
- **Ejes de la página 2.** `loss_avoided` va en cientos de millones y
  `good_volume_foregone` en miles de millones: probablemente quieras el eje secundario o
  una escala logarítmica. **No los separes en dos visuales** — ese es el punto.
- **Ordenar la tabla de la página 1** por `auc_test` descendente.
- **Formato condicional en la página 3**: `Veredicto equidad` en rojo cuando dice NO
  CUMPLE.

Cada uno de esos ajustes es un clic, y Desktop los guarda de vuelta en el mismo JSON,
que sigue siendo revisable en un diff.

### Si un visual sale vacío o con error

Es lo más probable que falle, y el diagnóstico es corto:

1. **¿Existe el campo?** `run test` corre
   `test_el_informe_solo_dibuja_campos_que_existen`. Si pasa, el campo está en el
   modelo y el problema es del visual.
2. **¿Es el tipo correcto?** El informe usa `tableEx`, `card` y `lineChart`. Si Desktop
   se queja del tipo, cámbialo desde el panel de visualizaciones: los campos ya están
   puestos y se conservan.
3. **¿Es el rol correcto?** Un `card` espera el rol `Values`; un `lineChart`, `Category`
   y `Y`. Si un campo quedó en el rol equivocado, Desktop lo deja vacío **sin error**.

Los tres se arreglan en Desktop en segundos. Si arreglas algo, **anótalo**: lo corrijo en
`scripts/build_pbir_report.py` para que la próxima generación ya salga bien, en vez de
que el arreglo viva solo en tu copia.

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

**Archivo → Guardar.** Desktop reescribe el TMDL y los JSON del informe.

**Ojo con `run pbir` después de guardar:** el generador **borra y reescribe**
`definition/`, así que perderías todo lo que ajustaste en Desktop. Solo vuelve a correrlo
si quieres partir de cero, y después de trasladar tus ajustes al script.

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
2. **`docs/ROADMAP.md`** — el punto 3 sale de la lista.
3. **Capturas.** Cuatro PNG en `powerbi/shots/` y enlazadas desde el README. El
   portafolio ya tiene un patrón para esto en `lib/powerbi-shots.ts`; la página de
   credit-risk puede mostrarlas igual que la de Medallion Insights.

La captura que más vale es **la página 3**: un tablero que enseña su propio modelo
bloqueado por el gate de equidad. Esa no la tiene nadie.
