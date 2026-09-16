# Lo que falta

Estado al 16 de septiembre de 2026. El alcance está cerrado: CI verde, 222 tests,
10 gates, 14 ADRs, y el proyecto tiene su propia página en el portafolio con la demo
corriendo en el navegador. **Nada de esta lista bloquea mostrarlo.**

El orden no es cronológico: es por cuánto cambia el resultado. Cada entrada dice quién
puede hacerla, porque cuatro de las seis que quedan no dependen del código.

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
- **La demo WASM, publicada y bilingüe**, en
  [davirsonnovoa.com/credit-risk-demo](https://davirsonnovoa.com/credit-risk-demo/index.html).
  Estaba construida y nunca se había pulsado: el valor por defecto de la garantía no
  era múltiplo de su propio `step`, así que el formulario nacía inválido y el botón
  no hacía nada.
- **Página propia en el portafolio**, con el acantilado de vocabulario, la curva de
  decisión, el gate bloqueando y el estudio de evento. Ningún número se teclea: la
  página lee el mismo bundle que el repositorio verifica.

Y dejaron tres defectos en la bitácora: la muestra de análisis la definía el sistema de
archivos, el manifiesto de procedencia se sobrescribía en vez de fusionarse, y la demo
del navegador nunca se había pulsado.

**De los once puntos originales quedan seis, y cuatro de ellos solo los puedes hacer
tú.** Los dos míos que faltan dependen de una clave gratuita y de Power BI Desktop.

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

## Después — lo que queda a medias

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

---

## Abierto — trabajo de verdad, no acabados

### 5. Los brazos de Groq y Gemini
**Quién:** Davirson pone las claves, yo corro el harness · **Esfuerzo:** 10 minutos suyos

Tiers gratuitos sin tarjeta en `console.groq.com` y `aistudio.google.com`, formato en
`.env.example`. El harness los detecta solo.

Vale por una razón concreta: la segunda revisión del ADR 0009 concluyó que **la
consistencia de un LLM local no es reproducible entre máquinas**. Dos modelos hospedados
pondrían a prueba si eso es de la inferencia local o del problema.

### 6. Los `_(escribir: ...)_` de NOTES.md
**Quién:** solo Davirson · **Esfuerzo:** dos horas

Diecinueve huecos deliberados en la bitácora, cada uno en el punto donde el proyecto aprendió
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
