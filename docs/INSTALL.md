# Instalación

Paso a paso, con lo que debe imprimir cada comando. Todo es gratuito y nada pide
tarjeta de crédito.

**El único prerrequisito real es [`uv`](https://docs.astral.sh/uv/).** Python 3.12
lo instala el propio proyecto: no hace falta tener Python en la máquina, y el que
ya tengas no se toca.

## Resumen: tres niveles

| Nivel | Qué obtienes | Disco | Comandos |
|---|---|---|---|
| **1 — Mínimo** | Suite de tests, lint y los 8 gates de promoción corriendo sobre las métricas commiteadas | **~1.2 GB** | 3 |
| **2 — Con datos** | Entrenamiento real, economía en dólares, stress testing, equidad | +1.7 GB → ~2.9 GB | +2 |
| **3 — Completo** | PyTorch, PySpark, ONNX, API, LLM local | +8 GB → ~11 GB | +5 |

Cifras medidas en esta máquina, no estimadas: entorno base 1.12 GB, intérprete
3.12 aislado 71 MB, SBA crudo 861 MB, HMDA en Parquet 829 MB.

**El nivel 1 verifica el proyecto entero sin descargar un solo dato.** Eso es
deliberado: `exports/metrics.json` está commiteado y el gate de `integridad`
recomputa las métricas desde las predicciones guardadas, así que se puede auditar
el modelo sin acceso a las fuentes. Es la misma razón por la que CI no descarga
nada.

---

## Nivel 1 — Mínimo (3 comandos)

### 1. Instalar `uv`

**Windows** — cualquiera de las dos:

```powershell
winget install astral-sh.uv
```

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verificar (abre una terminal nueva; el instalador modifica el `PATH`):

```powershell
uv --version
```

> Debe imprimir `uv 0.12.x` o superior.

> **Si ya tienes `uv`, salta este paso.** No hay que actualizarlo: el proyecto
> resuelve contra `uv.lock`, así que la versión de `uv` no cambia lo que se
> instala. Y `winget install` sobre un `uv` ya presente intenta *actualizarlo*,
> que es donde aparece el error de la tabla de abajo.

### 2. Clonar el repo

```powershell
git clone https://github.com/DavinsonR/credit-risk-mlops.git
cd credit-risk-mlops
```

### 3. Crear el entorno

**Windows:**

```powershell
.\run setup
```

**Linux / macOS:**

```bash
make setup
```

> **`.\run`, no `.\run.ps1`.** En un Windows por defecto la ExecutionPolicy es
> `Restricted` y llamar al `.ps1` directamente falla con `SecurityException` antes
> de hacer nada:
>
> ```
> .\run.ps1 : File ...\run.ps1 cannot be loaded because running scripts is
> disabled on this system.
> ```
>
> `run.cmd` no está sujeto a esa política y le pasa a `run.ps1` un bypass acotado
> a esa invocación: no cambia ninguna configuración del sistema ni de la cuenta, y
> no persiste nada. PowerShell resuelve `.\run` a `run.cmd` por `PATHEXT`, así que
> se escribe igual de corto.
>
> Si prefieres **no** rodear la política, habilítala una vez para tu usuario y usa
> el `.ps1` directamente. Es un cambio permanente en tu cuenta, así que decídelo
> tú:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
>
> `RemoteSigned` basta: exige firma solo a los scripts descargados de internet, y
> `git clone` no marca los archivos con Mark of the Web.

Hace tres cosas, en este orden:

1. `uv python install 3.12` — descarga un CPython 3.12 aislado. El proyecto está
   pinneado a `>=3.12,<3.13`: `optbinning` y `mlflow` no soportan 3.13 todavía.
2. `uv sync --extra dev` — resuelve `uv.lock` e instala el runtime + `ruff` y
   `pytest`. Versiones exactas, iguales a las de CI.
3. `git config core.hooksPath scripts/hooks` — activa el hook de autoría.

> **Por qué el paso 3 es parte de `setup` y no una instrucción del README:**
> `.git/hooks` no se clona. Sin apuntar `core.hooksPath`, un clon nuevo queda sin
> la protección y un trailer de atribución a IA solo se detectaría en CI, después
> del push. Tarde.

Verificar:

```powershell
uv run python -c "import crmlops, sys; print(crmlops.__name__, sys.version.split()[0])"
git config core.hooksPath
```

> Debe imprimir `crmlops 3.12.x` y `scripts/hooks`.

### 4. Verificar la instalación — sin descargar nada

```powershell
.\run test      # pytest -m "not data"
.\run lint      # ruff check + format check
.\run gates     # los 8 gates de promoción
```

`gates` es la prueba de fuego: lee `exports/metrics.json`, **recomputa** las
métricas desde las predicciones guardadas y compara contra `config.yaml`. Si el
entorno está bien, la salida es exactamente esta:

```
  PASA   config_coherente                n/a >= 0
  PASA   integridad                      n/a >= 0  metricas recomputadas desde predicciones
  PASA   auc_test                     0.7005 >= 0.6894
  PASA   drop_oot                     0.0299 <= 0.08
  PASA   brier_test                   0.0828 <= 0.0868
  PASA   ece_test                     0.0107 <= 0.02
  PASA   margen_sobre_baseline        0.0311 >= 0.02
  PASA   hmda:disparate_impact        0.7639 >= 0.8  peor grupo: Native Hawaiian or Other Pacific Islander  -> NO promovido, gate cumpliendo su funcion
APROBADO: 8 gates pasaron.
```

Si tus números difieren, el entorno no reproduce el publicado y eso es un
problema, no una variación aceptable.

> **El octavo gate se lee raro a propósito.** `hmda:disparate_impact` marca
> `PASA` con 0.7639 contra un umbral de 0.80. No es una contradicción: el gate
> mide correctamente, encuentra que el modelo de acceso **no** cumple el criterio
> de los cuatro quintos y por eso lo deja **sin promover**. El gate pasa porque
> hizo su trabajo; el modelo es el que no pasa. Ver
> [ADR 0006](adr/0006-exclusiones-en-hmda.md).

Los tests marcados `data` se saltan solos porque requieren las fuentes. Es
esperado, y el reporte dice cuáles y por qué.

---

## Nivel 2 — Con datos reales

### 5. SBA 7(a) — modelo de default (861 MB)

```powershell
.\run acquire
```

Descubre las URLs vigentes en `data.sba.gov`, baja 4 CSV (una por era fiscal),
escribe `data/manifests/` con el SHA256 de cada archivo y lo commitea.

| Archivo | Tamaño |
|---|---|
| `FOIA_7a_FY1991_FY1999_asof_260630.csv` | 140 MB |
| `FOIA_7a_FY2000_FY2009_asof_260630.csv` | 304 MB |
| `FOIA_7a_FY2010_FY2019_asof_260630.csv` | 244 MB |
| `FOIA_7a_FY2020_Present_asof_260630.csv` | 173 MB |
| **Total** | **861 MB** → 1,961,455 préstamos |

> **Las URLs se descubren, no están hardcodeadas.** El sufijo de vintage
> (`asof_260630`) rota cada trimestre y el portal ya cambió su estructura una vez
> — ver [ADR 0001](adr/0001-descubrimiento-de-urls-sba.md). Si tu descarga trae
> `asof_` distinto al del manifiesto, es porque hay un vintage nuevo: normal, y
> `verify` te lo dirá.

Verificar y entrenar:

```powershell
.\run verify     # revalida los hashes locales contra el manifiesto
.\run all        # train -> gates -> model card -> economía
```

### 6. HMDA — modelo de acceso y laboratorio de equidad (829 MB)

```powershell
.\run hmda
```

Baja por estado-año desde la API del CFPB y escribe Parquet directo, sin pasar por
CSV crudo. **62,375,170 solicitudes en 829 MB:** poda de 99 columnas a 32 más
compresión zstd. Los CSV equivalentes serían ~18 GB.

Al terminar verifica los conteos contra las agregaciones oficiales del CFPB: no
basta con que la descarga termine, tiene que estar **completa**.

```powershell
.\run disparity     # disparidad observada, antes de cualquier modelo
.\run hmda-train    # modelo de denegación + auditoría de equidad
```

---

## Nivel 3 — Extras opcionales

Cada uno es un `extra` de `pyproject.toml`. Instala solo los que vayas a usar; el
`.venv` con todos puestos pesa 2.2 GB.

| Extra | Comando | Para qué | En disco |
|---|---|---|---|
| `neural` | `uv sync --extra dev --extra neural` | Retador en PyTorch (CPU) | 507 MB |
| `spark` | `uv sync --extra dev --extra spark` | Benchmark DuckDB vs PySpark | 478 MB + 303 MB de JDK |
| `onnx` | `uv sync --extra dev --extra onnx` | Export y tests de paridad de serving | 89 MB |
| `explain` | `uv sync --extra dev --extra explain` | SHAP, razones del adverse action | 3 MB |
| `serve` | `uv sync --extra dev --extra serve` | FastAPI + uvicorn | 3 MB |

Los extras se acumulan; para todos a la vez:

```powershell
uv sync --extra dev --extra neural --extra onnx --extra serve --extra explain --extra spark
```

> **PyTorch sale del índice CPU a propósito.** `pyproject.toml` declara
> `pytorch-cpu` con `explicit = true`: sin eso, `uv` resolvería *todas* las
> dependencias contra el índice de PyTorch y rompería paquetes como `requests`,
> que allí existe en versiones viejas.

### PySpark necesita una JVM

```powershell
uv run python scripts/bootstrap_jdk.py
.\run benchmark
```

Baja el Microsoft Build of OpenJDK 17 (gratuito, sin registro) a `.jdk/` **dentro
del repo**, 303 MB. No instalador, no permisos de administrador, no `JAVA_HOME`
global: nada fuera del proyecto se toca. Spark 4 exige Java 17+.

### LLM local para los avisos de adverse action

El harness corre igual sin ningún LLM: el brazo de la plantilla determinista no
depende de nada. Si quieres los brazos de LLM:

1. Instalar [Ollama](https://ollama.com/download) — gratis, sin cuenta.
2. Bajar los modelos evaluados:

```powershell
ollama pull llama3.2:3b     # 2.0 GB
ollama pull qwen2.5:7b      # 4.7 GB
```

3. Correr el harness:

```powershell
.\run llm-evals
```

`available_providers()` enumera los modelos instalados y evalúa los que
encuentre — no hay que configurar nada. El reporte dice qué brazos corrieron.

> **Los dos tamaños importan.** Comparar 3B contra 7B dentro del mismo proveedor
> responde algo que comparar proveedores no responde: si un fallo viene del modelo
> o de la tarea. Con un solo modelo, este proyecto publicó dos conclusiones falsas
> — ver la revisión al final de
> [ADR 0009](adr/0009-la-plantilla-gana-al-llm.md).

### Claves de API — opcionales, todas de tier gratuito sin tarjeta

```powershell
Copy-Item .env.example .env
```

| Variable | Dónde se obtiene | Para qué |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com | Brazo Llama 3.3 70B del harness |
| `GEMINI_API_KEY` | aistudio.google.com | Brazo Gemini Flash del harness |
| `FRED_API_KEY` | fred.stlouisfed.org | Contexto macro para stress testing |
| `CENSUS_API_KEY` | api.census.gov | Demografía por census tract |

`.env` está en `.gitignore`. Ninguna es necesaria para el modelo, los gates ni el
gobierno: sin claves, esos brazos simplemente no aparecen en el reporte.

### API de scoring

```powershell
.\run onnx      # exporta el modelo y verifica paridad numérica
.\run serve     # API en http://localhost:8000
```

Probarla desde PowerShell — se usa un here-string y `Invoke-RestMethod` en vez de
`curl`: en PowerShell las comillas dobles del JSON se escapan de una forma
distinta y el comando de la documentación de Linux falla sin decir por qué.

```powershell
$body = @'
{"gross_approval":250000,"sba_guaranteed":187500,"initial_rate":8.5,
 "jobs_supported":6,"naics_sector":"72","business_type":"CORPORATION",
 "business_age":"Existing or more than 2 years old","revolver_status":"N",
 "collateral_ind":"Y","rate_type":"V",
 "processing_method":"Preferred Lenders Program",
 "borrower_state":"TX","has_franchise":0}
'@
Invoke-RestMethod -Uri http://localhost:8000/score -Method Post -ContentType application/json -Body $body
```

El mismo caso en Linux / macOS, que es el que corre el smoke test de CI:

```bash
curl -fsS -X POST http://localhost:8000/score -H 'Content-Type: application/json' \
  -d '{"gross_approval":250000,"sba_guaranteed":187500,"initial_rate":8.5,
       "jobs_supported":6,"naics_sector":"72","business_type":"CORPORATION",
       "business_age":"Existing or more than 2 years old","revolver_status":"N",
       "collateral_ind":"Y","rate_type":"V",
       "processing_method":"Preferred Lenders Program",
       "borrower_state":"TX","has_franchise":0}'
```

Demo en el navegador, con el modelo corriendo en WASM y sin backend:

```powershell
.\run web       # http://localhost:8899
```

### Docker (solo si quieres la imagen que construye CI)

```powershell
docker build -f serving/api/Dockerfile -t crmlops-serving .
docker run -p 8000:8000 crmlops-serving
```

CI verifica algo más que "construye": comprueba que la imagen **no** traiga
`lightgbm`, `pandas`, `sklearn`, `torch` ni `pyspark`. La razón de exportar a ONNX
es que el serving no reproduzca el entorno de entrenamiento; si esos paquetes se
colaran, esa separación se habría perdido en silencio.

---

## Problemas conocidos

| Síntoma | Causa | Solución |
|---|---|---|
| `make: command not found` en Windows | No hay `make` en Windows | Usar `.\run <tarea>`. El Makefile sigue siendo la referencia porque CI corre en Linux. |
| `running scripts is disabled on this system` / `UnauthorizedAccess` | ExecutionPolicy `Restricted`, que es el valor por defecto de Windows cliente | Usar `.\run` (el `.cmd`), no `.\run.ps1`. O `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` una vez. Ver el paso 3. |
| `uv: command not found` justo tras instalar | El `PATH` cambió | Abrir una terminal nueva. |
| `winget` falla al actualizar `uv` con `remove: Access is denied` y `0x8a150003` | Hay un proceso `uv run` vivo. `winget` pone el `uv.exe` en su propia carpeta de paquetes y Windows no borra un `.exe` en ejecución — el error no lo dice. Casi siempre es un `run.ps1 web` o `run.ps1 serve` olvidado | No hace falta actualizar: el `uv` que ya tienes sirve. Si igual lo quieres, cerrar el servidor (`Ctrl+C`, o `Get-Process uv \| Stop-Process`) y repetir. |
| `python --version` dice 3.13 o 3.14 | Es tu Python del sistema y no se usa | Irrelevante. `pyproject.toml` pide `>=3.12,<3.13` y `uv` instala su propio 3.12 aislado, sin tocar el tuyo. |
| Acentos rotos en la consola | Codepage de Windows | `run.ps1` fija `PYTHONIOENCODING=utf-8`. Si invocas los módulos a mano, fíjala tú. |
| `RuntimeError: No hay JDK` | PySpark sin JVM | `uv run python scripts/bootstrap_jdk.py` |
| `ModuleNotFoundError: onnxruntime` / `fastapi` | Falta un extra | `uv sync --extra dev --extra onnx --extra serve` |
| `verify` reporta hash distinto | Vintage nuevo de SBA | Esperado cada trimestre. Ver [ADR 0001](adr/0001-descubrimiento-de-urls-sba.md). |
| Un test se salta con `data` | Requiere fuentes descargadas | Esperado en nivel 1. Correr `acquire` primero. |
| El hook de autoría no bloquea nada | `core.hooksPath` sin apuntar, o el hook sin bit de ejecución (git lo ignora **en silencio**) | `setup` apunta el path; `tests/test_authorship_hook.py` verifica que el modo en el índice sea `100755`. Los dos casos existieron en este repo. |

## Qué NO hace falta

Ninguna cuenta en la nube. Ninguna tarjeta de crédito. Ningún Python previo.
Ningún JDK del sistema. Ningún Docker para el modelo, los gates ni el gobierno.
Ninguna clave de API para reproducir los números publicados.

El presupuesto de este proyecto es **$0** y eso es una restricción de diseño, no
una circunstancia: cada dependencia de pago se rechazó o se reemplazó — ver
[docs/AUDIT.md](AUDIT.md).
