# Lo que falta

Estado al 15 de septiembre de 2026. El alcance de las diez semanas está cerrado: CI
verde, 188 tests, 10 gates, 13 ADRs, y el proyecto ya está enlazado desde el perfil y
el portafolio. **Nada de esta lista bloquea mostrarlo.**

El orden no es cronológico: es por cuánto cambia el resultado. Cada entrada dice quién
puede hacerla, porque cuatro de ellas no dependen del código.

---

## Ahora — cuestan minutos y el proyecto ya está público

### 1. El repositorio no tiene descripción ni topics
**Quién:** solo Davirson (son ajustes de cuenta) · **Esfuerzo:** 2 minutos

`description` y `topics` están vacíos. Esa línea es lo que aparece en las búsquedas de
GitHub y en la lista de repos, y ahora el perfil apunta aquí como trabajo principal: un
repo sin descripción se lee como abandonado.

```
Credit decisioning with model risk governance on 1.96M SBA loans and 62.4M HMDA
applications. Ten promotion gates — one blocks my own model.
```

Topics sugeridos: `credit-risk` `mlops` `model-governance` `fairness` `causal-inference`
`duckdb` `lightgbm` `python`.

### 2. La bio de GitHub se contradice con el perfil
**Quién:** solo Davirson · **Esfuerzo:** 1 minuto

La bio dice *"currently pursuing an MSc in Economics"*. El README del perfil, el CV del
sitio y la página de investigación dicen los tres lo mismo y es lo correcto: **tesis
radicada en agosto de 2026, grado previsto para noviembre de 2026**. Alguien que compare
las dos cosas encuentra la única inconsistencia del conjunto justo en la credencial.

### 3. JARVIS no tiene fecha pública para ordenarlo
**Quién:** solo Davirson · **Esfuerzo:** 1 minuto

El orden del perfil y del portafolio es por fecha de creación del repositorio. JARVIS es
privado, así que no hay fecha contra la cual ordenarlo y quedó al final por convención,
no por evidencia. Si es posterior a agosto de 2026 hay que subirlo — está anotado en el
código con un comentario para que se vea que es una decisión pendiente y no un olvido.

---

## Después — completan lo que ya está a medias

### 4. El informe de Power BI
**Quién:** solo Davirson (hace falta Power BI Desktop) · **Esfuerzo:** medio día

El modelo semántico está escrito en TMDL y sus enlaces están verificados por test —
cada `sourceColumn` se compara contra el encabezado real del CSV. **Lo que falta es el
layout**, y no puede escribirse a ciegas: `powerbi/README.md` trae la especificación de
las cuatro páginas, qué archivo alimenta cada visual y la lista de lo que no debe
mostrarse.

Es la capacidad que el portafolio ya reclama con TMDL y DAX, y aquí está a medio camino.
Abrir `credit-risk-mlops.pbip`, ajustar el parámetro `RutaRepo`, refrescar y armar las
páginas.

### 5. Página propia en el portafolio
**Quién:** yo, leyendo primero `DESIGN.md` · **Esfuerzo:** medio día

Hoy el proyecto es el bloque destacado de la portada y enlaza al repositorio. Le falta
una página como la que tienen trading-sim y powerbi, donde quepan los gráficos que
ninguna tabla de Markdown puede dar:

- **El acantilado de vocabulario** — 0% en FY2015, 48.5% en FY2019, 84% hoy. Es el más
  persuasivo de todos y sus datos ya están en `exports/drift.json`. El pie que lo remata:
  el serving devuelve HTTP 200 mientras tanto.
- **La curva de decisión en dólares**, con la pérdida evitada y el volumen sacrificado en
  el mismo eje, más la bandera `at_boundary` que evita vender un óptimo que está en el
  borde de la grilla.
- **El gate de equidad bloqueando** su propio modelo.
- **La tabla de madurez pareja**, 2.8x ingenuo contra 2.3x honesto.

No lo hice a ciegas a propósito: el sitio tiene un sistema visual con opiniones fuertes y
una página fuera de estilo resta en vez de sumar.

### 6. La demo WASM está construida y apagada
**Quién:** yo · **Esfuerzo:** medio día

`serving/web/` ya tiene el modelo en ONNX de 1,9 MB y la página que lo corre en el
navegador con `onnxruntime-web`. **Nunca se publicó.** Es un modelo de crédito real
puntuando en el navegador del reclutador, sin backend y sin cold start.

Y trae una trampa que vale más que la demo: `Change of Ownership` no está en
`contract.json`, así que se codifica como desconocido y el modelo responde igual de
seguro. El ADR 0011 en vivo, en veinte segundos.

Falta decidir dónde vive —subdirectorio del sitio actual o un despliegue aparte— y
verificar que el `wasmPaths` funcione desde esa ruta, que ya dio problemas una vez.

---

## Abierto — trabajo de verdad, no acabados

### 7. El estudio de evento sobre HMDA en el shock de tasas de 2022
**Quién:** yo · **Esfuerzo:** una a dos semanas

Es el mejor diseño causal que tiene el proyecto y está nombrado en el ADR 0013
precisamente para que se vea que no estimar el efecto de la garantía fue una decisión de
identificación y no falta de alternativas.

Tiene 62,4M de solicitudes, un shock exógeno a mitad del panel, dos períodos previos para
falsificar tendencias paralelas, y clases protegidas que SBA no trae. El gradiente
descriptivo ya está medido: la razón de cuatro quintos cayó de 0.827 en 2020 a 0.729 en
2023. Y el ajuste por covariables de alta dimensión aporta algo real aquí, porque el
proyecto ya midió que la composición del pool cambió de forma estructural (PSI de forma
0.2099).

**Puede salir nulo, y eso está bien**: con este diseño un nulo está identificado, que es
exactamente lo que el ADR 0013 dice que el de la garantía no estaba. Hay que declarar el
MDE antes de estimar.

### 8. Armonizar el vocabulario de `business_age`
**Quién:** yo · **Esfuerzo:** dos a tres días

El ADR 0011 lo deja abierto a propósito. Reentrenar no lo arregla: la ventana vieja tiene
el vocabulario viejo, y la nueva choca con la madurez de la etiqueta. Armonizar tampoco
es mecánico — `Existing or more than 2 years old` agrupa cuatro buckets viejos, así que el
mapeo **pierde** resolución, y `Change of Ownership` no existía como antigüedad: no es un
renombre, es un concepto nuevo.

Lo honesto es medir cuánto cuesta el mapeo grueso en AUC y publicar las dos versiones, no
elegir una y callar la otra.

### 9. Instrumentar la decisión de fallback del híbrido
**Quién:** yo · **Esfuerzo:** un día

La pregunta abierta del ADR 0009: los híbridos salen **menos** consistentes que el modelo
solo. La hipótesis es que validar-y-caer introduce varianza en el borde, y está escrita
como hipótesis porque no se midió. Cerrarla es registrar por caso si se usó el LLM o el
fallback y comparar esa decisión entre corridas.

### 10. Los brazos de Groq y Gemini
**Quién:** Davirson pone las claves, yo corro el harness · **Esfuerzo:** 10 minutos suyos

Tiers gratuitos sin tarjeta en `console.groq.com` y `aistudio.google.com`, formato en
`.env.example`. El harness los detecta solo.

Vale por una razón concreta: la segunda revisión del ADR 0009 concluyó que **la
consistencia de un LLM local no es reproducible entre máquinas**. Dos modelos hospedados
pondrían a prueba si eso es de la inferencia local o del problema.

### 11. Los `_(escribir: ...)_` de NOTES.md
**Quién:** solo Davirson · **Esfuerzo:** una hora

Cinco huecos deliberados en la bitácora, cada uno en el punto donde el proyecto aprendió
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
