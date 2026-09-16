# Lo que falta

Estado al 16 de septiembre de 2026. El alcance está cerrado: CI verde, 233 tests,
10 gates, 14 ADRs, y el proyecto tiene su propia página en el portafolio con la demo
corriendo en el navegador. **Nada de esta lista bloquea mostrarlo.**

El orden no es cronológico: es por cuánto cambia el resultado. Cada entrada dice quién
puede hacerla, y los cinco que quedan son ajustes de cuenta o trabajo que solo puede hacer su autor.

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
  [proyecto-davirson-git.vercel.app/credit-risk-demo](https://proyecto-davirson-git.vercel.app/credit-risk-demo/index.html).
  Estaba construida y nunca se había pulsado: el valor por defecto de la garantía no
  era múltiplo de su propio `step`, así que el formulario nacía inválido y el botón
  no hacía nada.
- **Página propia en el portafolio**, con el acantilado de vocabulario, la curva de
  decisión, el gate bloqueando y el estudio de evento. Ningún número se teclea: la
  página lee el mismo bundle que el repositorio verifica.

Y dejaron cinco defectos en la bitácora: la muestra de análisis la definía el sistema de
archivos, el manifiesto de procedencia se sobrescribía en vez de fusionarse, la demo del
navegador nunca se había pulsado, `.env` no lo leía nadie, y el `.pbip` apuntaba a un
artefacto inexistente. Los dos últimos salieron de escribir los instructivos, que es
exactamente para lo que sirve escribir un instructivo.

**De los once puntos originales quedan cinco, y todos son tuyos.** Dos de ellos ya
tienen instructivo paso a paso: [Power BI](POWERBI.md) y
[Groq + Gemini](LLM_PROVIDERS.md).

---

## Ahora — cuestan minutos y el proyecto ya está público

### 1. Ninguno de los cinco repositorios tiene descripción ni topics
**Quién:** solo Davirson (son ajustes de cuenta) · **Esfuerzo:** 10 minutos

Verificado contra la API de GitHub el 16 de septiembre de 2026: los cinco repos
públicos tienen `description: null` y `topics: []`. Esa línea es lo que aparece en las
búsquedas de GitHub y en la lista de repos, y ahora el perfil apunta a `credit-risk-mlops`
como trabajo principal: un repo sin descripción se lee como abandonado.

Se pone en **Settings → General → Description**, y los topics con el engranaje que hay
al lado de "About" en la portada del repo.

**`credit-risk-mlops`**
```
Credit decisioning with model risk governance on 1.96M SBA loans and 93.4M HMDA applications. Ten promotion gates — one blocks my own model.
```
`credit-risk` · `mlops` · `model-governance` · `fairness` · `causal-inference` · `event-study` · `duckdb` · `lightgbm` · `python`

**`financial-inclusion-colombia`**
```
MSc thesis, built in public: 19 open sources into a dimensional warehouse, a financial inclusion index, and an econometric battery whose null results are published too.
```
`economics` · `reproducible-research` · `econometrics` · `dbt` · `duckdb` · `colombia` · `financial-inclusion` · `open-data`

**`market-data-medallion`**
```
Daily market data pipeline into a PostgreSQL medallion warehouse with dbt, plus an honest backtester: of 1,392 strategy variants, one in eight survived out-of-sample.
```
`data-engineering` · `medallion-architecture` · `dbt` · `postgresql` · `backtesting` · `github-actions` · `power-bi` · `python`

**`proyecto-davirson`**
```
Bilingual portfolio and interactive CV. Next.js, static, no backend — every published figure links to the repository that produces it.
```
`portfolio` · `nextjs` · `typescript` · `tailwindcss` · `i18n` · `vercel`

**`DavinsonR`** (el repo del perfil)
```
Profile README.
```
Sin topics: un repo de perfil no compite en búsquedas y los topics sobran.

**Y la bio de la cuenta**, que es el campo de 160 caracteres del perfil, no del repo
(Settings → Public profile → Bio). La actual dice *"currently pursuing an MSc in
Economics"* y contradice al resto — es el punto 2:
```
Economist building ML that survives an audit. Credit risk, model governance, causal inference. MSc Economics (Nov 2026). Bogotá, US hours.
```

### 2. La bio de GitHub se contradice con el perfil
**Quién:** solo Davirson · **Esfuerzo:** 1 minuto

La bio dice *"currently pursuing an MSc in Economics"*. El README del perfil, el CV del
sitio y la página de investigación dicen los tres lo mismo y es lo correcto: **tesis
radicada en agosto de 2026, grado previsto para noviembre de 2026**. Alguien que compare
las dos cosas encuentra la única inconsistencia del conjunto justo en la credencial.

---

## Después — lo que queda a medias

### 3. El informe de Power BI
**Quién:** solo Davirson (hace falta Power BI Desktop) · **Esfuerzo:** medio día

El modelo semántico está escrito en TMDL y sus enlaces están verificados por test —
cada `sourceColumn` se compara contra el encabezado real del CSV. **Lo que falta es el
layout**, y no puede escribirse a ciegas: `powerbi/README.md` trae la especificación de
las cuatro páginas, qué archivo alimenta cada visual y la lista de lo que no debe
mostrarse.

Es la capacidad que el portafolio ya reclama con TMDL y DAX, y aquí está a medio camino.

**Procedimiento completo: [docs/POWERBI.md](POWERBI.md)** — instalar Desktop, activar la
bandera de PBIP, los seis exports que tienen que existir, qué hacer si no abre, los
campos de cada una de las cuatro páginas, y qué mirar en el diff al guardar.

Escribir esa guía destapó un defecto: el `.pbip` declaraba un artefacto de informe que
**no existía**, así que la primera instrucción —"abrir el .pbip"— era inejecutable. Ya
está el andamiaje, y un test comprueba lo que el propio `.pbip` declara.

---

## Abierto — trabajo de verdad, no acabados

### 4. Los brazos de Groq y Gemini
**Quién:** Davirson pone las claves, yo corro el harness · **Esfuerzo:** 10 minutos suyos

**Procedimiento completo: [docs/LLM_PROVIDERS.md](LLM_PROVIDERS.md)** — dónde sacar cada
clave, dónde pegarla, cómo verificar que llegó, y qué mirar en la corrida.

Tiers gratuitos sin tarjeta en `console.groq.com` y `aistudio.google.com`.

Y otro defecto destapado al escribirlo: **nada leía `.env`**. El repo decía "copiar a
.env" y el harness decía "claves en .env", pero los proveedores solo miraban variables de
entorno reales. Seguir la instrucción oficial dejaba los dos brazos en "no disponibles",
sin error. Ahora lo carga `crmlops.env`, con ocho tests.

Vale por una razón concreta: la segunda revisión del ADR 0009 concluyó que **la
consistencia de un LLM local no es reproducible entre máquinas**. Dos modelos hospedados
pondrían a prueba si eso es de la inferencia local o del problema.

### 5. Los `_(escribir: ...)_` de NOTES.md
**Quién:** solo Davirson · **Esfuerzo:** dos horas

Veinte huecos deliberados en la bitácora, cada uno en el punto donde el proyecto aprendió
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
