# Lo que falta

Estado al 23 de septiembre de 2026. El alcance está cerrado: CI verde, 261 tests,
10 gates, 14 ADRs, y el proyecto tiene su propia página en el portafolio con la demo
corriendo en el navegador. **Nada de esta lista bloquea mostrarlo.**

El orden no es cronológico: es por cuánto cambia el resultado. Los dos que quedan son
de su autor: uno necesita un programa que yo no tengo, y el otro no tendría sentido
escrito por otro.

## Cerrado en la semana 11

Tres puntos que estaban en esta lista salieron, y el primero cambió una cifra que el
proyecto venía citando:

- **El estudio de evento sobre el shock de tasas de 2022.** Sobre 93.4M solicitudes
  (FY2018–2025, tres años más que el panel publicado). La brecha post-shock está a
  **0.03 pp** de la pre-pandemia: no se amplió, revirtió. El +2.59 pp que circulaba
  mide el auge de refinanciación acabándose, porque estaba anclado a 2021. No se
  publica efecto causal, y las tres razones están medidas —
  [ADR 0014](adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md).
- **El costo de armonizar `business_age`.** 0.0015 de AUC a cambio de +74.7 pp de
  cobertura. El argumento cualitativo del ADR 0011 era correcto en dirección y
  despreciable en magnitud.
- **La instrumentación del híbrido.** Cero cambios de camino: la hipótesis del ADR
  0009 era mía y era falsa.
- **La demo WASM, publicada y bilingüe**, hoy como sección de la página del proyecto:
  [davirson.com/es/projects/credit-risk](https://davirson.com/es/projects/credit-risk#demo).
  Estaba construida y nunca se había pulsado: el valor por defecto de la garantía no
  era múltiplo de su propio `step`, así que el formulario nacía inválido y el botón
  no hacía nada.
- **Página propia en el portafolio**, con el acantilado de vocabulario, la curva de
  decisión, el gate bloqueando y el estudio de evento. Ningún número se teclea: la
  página lee el mismo bundle que el repositorio verifica.
- **El informe de Power BI, escrito en PBIR** y validado contra los esquemas de
  Microsoft: cuatro páginas, veinte visuales, cada campo comprobado contra el TMDL.
  El primer intento de abrirlo en Desktop falló por el `.pbism` (defecto 22), ya
  corregido; falta volver a abrirlo, que es el punto 1.

Y dejaron seis defectos en la bitácora: la muestra de análisis la definía el sistema de
archivos, el manifiesto de procedencia se sobrescribía en vez de fusionarse, la demo del
navegador nunca se había pulsado, `.env` no lo leía nadie, el `.pbip` apuntaba a un
artefacto inexistente, y `ci-local` copiaba el árbol de trabajo sin borrar nada —así que
no veía las eliminaciones—. Los tres últimos salieron de escribir los instructivos y de
generar el informe, que es exactamente para lo que sirve escribirlos.

Y el 23 de septiembre salieron dos más, verificados contra la API de GitHub y no
supuestos: **los cinco repositorios ya tienen descripción**, los cuatro de proyecto
tienen topics, y **la bio de la cuenta dejó de contradecir al perfil**.

El 23 de septiembre, además, **los brazos de Groq y Gemini quedaron corriendo**. Su
resultado está en la [quinta revisión del ADR 0009](adr/0009-la-plantilla-gana-al-llm.md)
y costó cuatro defectos: una clave real escrita en tres artefactos que se commitean, un
redactor que nació con el defecto 4 adentro, dos identificadores de modelo caducados, y
un presupuesto de tokens a punto de publicarse como fidelidad del modelo. El quinto vino
después: publiqué una consistencia medida una sola vez y la segunda corrida la mató.

**De los once puntos originales quedan dos, y los dos son tuyos.**

> **Paso a paso, con los clics: [docs/CHECKLIST.md](CHECKLIST.md).** Esta página explica
> por qué importa cada cosa; esa dice qué hacer y en qué orden.

---

## Después — lo que queda a medias

### 1. Abrir el informe de Power BI y verificarlo
**Quién:** solo Davirson (hace falta Power BI Desktop) · **Esfuerzo:** una hora

El modelo semántico estaba escrito en TMDL y verificado por test. **Ahora el informe
también está escrito**: cuatro páginas y veinte visuales en PBIR —el formato de
metadatos mejorado, un archivo por página y uno por visual— generados por
`run pbir`, que valida cada archivo contra los esquemas publicados de Microsoft y
comprueba que cada campo existe en el TMDL leyéndolo del TMDL.

**Lo que falta es abrirlo.** Cumplir un esquema no es cargar en Desktop. El primer
intento lo demostró: Desktop pidió un `model.bim` porque el `.pbism` declaraba la
versión 1.0 junto a un modelo TMDL ([defecto 22](DEFECTS.es.md)). Está corregido, pero
ningún intento ha cargado el proyecto todavía. Puede fallar por un tipo de visual, por un rol que ese visual no acepta, o
porque PBIR es vista previa y exige una versión reciente.

**Procedimiento: [docs/POWERBI.md](POWERBI.md)** — las dos banderas de vista previa que
hay que activar, los seis exports que tienen que existir, los tres fallos posibles al
abrir, qué mirar en cada página, qué formato vas a tener que ajustar a mano, y qué
revisar en el diff al guardar.

Si algo no abre, **apunta el mensaje tal cual**: es el dato que yo no puedo obtener y
con él corrijo el generador.

---

## Abierto — trabajo de verdad, no acabados

### 2. Los `_(escribir: ...)_` de NOTES.md
**Quién:** solo Davirson · **Esfuerzo:** dos horas

Veinticuatro huecos deliberados en la bitácora, cada uno en el punto donde el proyecto aprendió
algo. **Están vacíos a propósito**: son lo que hay que poder defender en una entrevista, y
escritos por otro no sirven para eso.

---

## Lo que NO está en esta lista, y por qué

- **Subir el AUC.** 0.7005 sin bureau score ni estados financieros es el rango correcto,
  y el proyecto ya midió que el margen sobre el scorecard interpretable es +0.0311 con un
  IC95 que excluye el cero. Perseguir décimas cambiaría el argumento del proyecto por el
  de cualquier notebook.
- **Desplegar en la nube.** El presupuesto es cero y la demo WASM no necesita servidor.
- **Kubernetes, Terraform, un feature store.** No hay nada real que orquestar, y un
  revisor técnico lo nota.
- **Vigilar la deriva de las normas.** SR 11-7 fue reemplazada cinco meses antes de que
  el proyecto empezara y nadie se enteró hasta la semana 10. Queda anotado en el ADR 0012
  como límite conocido: el monitoreo vigila los datos, no el regulador. Automatizarlo
  sería teatro; lo que corresponde es revisar la cita cuando alguien la mire.
