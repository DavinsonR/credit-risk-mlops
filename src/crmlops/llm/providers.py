"""Proveedores de generación para los avisos de adverse action.

CUATRO BRAZOS, y el primero no es un LLM.

El proyecto ya tiene una regla: el retador debe superar a un baseline
interpretable. El scorecard WoE cumple ese papel frente al GBM. Aquí el papel lo
cumple una **plantilla determinista**.

Si el LLM no supera a la plantilla en fidelidad, cumplimiento y legibilidad, la
plantilla es la elección correcta: no alucina, no depende de red, cuesta cero y
un validador la lee entera en un minuto. Incluirla no es una concesión — es la
única forma de saber si el LLM aporta algo.

Los tres brazos con LLM funcionan a costo cero:
  - Ollama local  -- ningún dato sale de la máquina, que en crédito es un
                     argumento de cumplimiento, no una comodidad
  - Groq          -- tier gratuito, sin tarjeta
  - Google AI Studio (Gemini Flash) -- tier gratuito, sin tarjeta

Ninguno es obligatorio: `available_providers()` devuelve solo los que responden,
y el harness reporta cuáles se evaluaron.
"""

from __future__ import annotations

import contextlib
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from crmlops.env import load as load_env

# WORD_BOUNDARY y no "": en una cadena no-raw eso es el caracter BACKSPACE, y el
# regex deja de hacer lo que dice. Es el defecto 4 del ledger, y acaba de repetirse
# aqui mismo -- en el arreglo que redacta secretos, que es el peor sitio posible.
from crmlops.llm.evals import WORD_BOUNDARY

TIMEOUT = 120

# --- Redaccion de secretos en los mensajes de error --------------------------
# La API de Gemini toma la clave en la QUERY STRING, asi que un 404 de `requests`
# trae la URL completa --clave incluida-- dentro del texto de la excepcion. Ese
# texto se guardaba tal cual en `Generation.error`, viajaba a
# `exports/llm_evals_detail.csv` y a `llm_evals.json`, y esos archivos SE
# COMMITEAN.
#
# Paso: una clave real quedo impresa en la consola y escrita en tres artefactos.
# No llego a git de milagro --se detecto antes del commit-- y eso no es un
# control, es suerte.
#
# La regla es la de siempre en este proyecto: el control no puede depender de que
# nadie haga algo razonable. Aqui lo razonable era mirar el error.
_SECRETO = re.compile(r"(?i)(key=|api[_-]?key=|access_token=|Bearer\s+)[A-Za-z0-9._\-]{8,}")
# Formatos conocidos de clave, por si aparecen sueltas y no tras un `key=`.
_CLAVE_SUELTA = re.compile(
    WORD_BOUNDARY + r"(gsk_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{20,}|AQ\.[A-Za-z0-9_\-]{20,})"
)


def redactar(texto: str) -> str:
    """Quita claves de un texto antes de que se guarde o se imprima.

    Se aplica en el BORDE --donde el error se convierte en dato-- y no en cada
    sitio que imprime: un solo punto que olvidar es un solo punto que arreglar.
    """
    texto = _SECRETO.sub(lambda m: m.group(1) + "[REDACTADO]", texto)
    return _CLAVE_SUELTA.sub("[REDACTADO]", texto)


# `.env` se vuelca al entorno AL IMPORTAR este modulo, que es el unico punto por el
# que pasan los tres proveedores hospedados. Antes no lo leia nadie: el repo decia
# "copiar a .env", el harness decia "claves en .env", y las claves nunca llegaban a
# os.environ. Ver crmlops.env.
load_env()


@dataclass
class Generation:
    provider: str
    model: str
    text: str
    seconds: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


class Provider(ABC):
    name: str
    model: str

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def generate(self, prompt: str, *, temperature: float = 0.0, seed: int = 42) -> str: ...

    def warm_up(self) -> None:
        """Descarta una generacion antes de medir.

        LA PRIMERA LLAMADA TRAS CARGAR EL MODELO NO ES DETERMINISTA. Verificado
        sobre llama3.2:3b y qwen2.5:7b con temperatura 0 y semilla fija: la
        primera salida difiere y las siguientes coinciden entre si. Con una
        llamada de calentamiento descartada, tres corridas dan un unico hash.

        Sin esto, el harness mide un artefacto de arranque en frio y lo atribuye
        al modelo -- que es exactamente lo que hizo en su primera version.
        """
        # Si el calentamiento falla, se sigue: la generacion medida vendra despues
        # y reportara su propio error con contexto. Abortar aqui convertiria un
        # detalle de instrumentacion en un fallo del harness.
        with contextlib.suppress(Exception):
            self.generate("Responde solo: ok", temperature=0.0, seed=42)

    # Reintentos SOLO ante saturacion, y acotados. El tier gratuito de Gemini
    # devuelve 503 "high demand" de forma intermitente: sin reintento, el brazo se
    # reporta como fallido cuando lo que paso es que habia cola. No se reintenta un
    # 4xx --esos son errores de la peticion, no del momento-- porque insistir sobre
    # una clave mala solo tarda mas en dar la misma respuesta.
    # Cinco y no tres: el tier gratuito de Gemini devuelve 503 "high demand" de forma
    # sostenida --medido, cinco intentos para un exito-- y con tres el brazo se
    # reportaba como fallido cuando lo que habia era cola.
    REINTENTOS_SATURACION = 5

    def run(self, prompt: str, **kw) -> Generation:
        import time

        t0 = time.perf_counter()
        for intento in range(self.REINTENTOS_SATURACION):
            try:
                text = self.generate(prompt, **kw)
                return Generation(self.name, self.model, text, time.perf_counter() - t0)
            except Exception as exc:
                codigo = getattr(getattr(exc, "response", None), "status_code", None)
                if codigo in (429, 503) and intento < self.REINTENTOS_SATURACION - 1:
                    time.sleep(2**intento)
                    continue
                return Generation(
                    self.name,
                    self.model,
                    "",
                    time.perf_counter() - t0,
                    redactar(f"{type(exc).__name__}: {exc}"),
                )
        raise AssertionError("inalcanzable")


class TemplateProvider(Provider):
    """Baseline determinista. NO usa modelo de lenguaje.

    Rellena el formato del Apéndice C de Reg B con las razones que SHAP entregó.
    Por construcción no puede inventar un factor que el modelo no usó, así que su
    fidelidad es 1.0 y el techo del harness queda fijado por algo verificable.
    """

    name = "template"
    model = "deterministic"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, *, temperature: float = 0.0, seed: int = 42) -> str:
        # La plantilla no consume el prompt: recibe las razones ya estructuradas
        # desde `crmlops.llm.adverse_action`. Este metodo existe para cumplir la
        # interfaz; el ensamblado real vive alli.
        return prompt


class OllamaProvider(Provider):
    """Modelo local. Ningun dato sale de la maquina."""

    name = "ollama"

    def __init__(self, model: str = "llama3.2:3b", host: str | None = None) -> None:
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def available(self) -> bool:
        return self.model in installed_ollama_models(self.host)

    def generate(self, prompt: str, *, temperature: float = 0.0, seed: int = 42) -> str:
        r = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                # temperature 0 + seed fijo: un aviso legal no puede variar entre
                # ejecuciones para la misma solicitud.
                "options": {"temperature": temperature, "seed": seed, "num_predict": 400},
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["response"].strip()


class GroqProvider(Provider):
    name = "groq"

    # MODELOS QUE CADUCAN. `llama-3.3-70b-versatile` estaba fijado aqui y Groq lo
    # retiro: la API devolvia 404 y el brazo entero se leia como "el modelo fallo"
    # cuando lo que fallaba era el identificador. Verificado el 23-09-2026 contra
    # `GET /openai/v1/models` con la clave real; el catalogo actual de chat es
    # openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b y allam-2-7b.
    #
    # Se elige el mas grande de propuesto general: el harness compara un retador
    # contra una plantilla, y darle al retador su mejor version es lo que hace
    # honesta la comparacion.
    # Familias que devuelven tokens de razonamiento. No es una lista de modelos
    # sino un prefijo: `openai/gpt-oss-*` son todos de razonamiento.
    FAMILIAS_QUE_RAZONAN = ("openai/gpt-oss",)

    def __init__(self, model: str = "openai/gpt-oss-120b") -> None:
        self.model = model
        self.key = os.environ.get("GROQ_API_KEY", "")
        self.razona = model.startswith(self.FAMILIAS_QUE_RAZONAN)

    def available(self) -> bool:
        return bool(self.key)

    def generate(self, prompt: str, *, temperature: float = 0.0, seed: int = 42) -> str:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "seed": seed,
                "max_tokens": 500,
                # MODELOS DE RAZONAMIENTO: los tokens de pensamiento salen del MISMO
                # presupuesto que la respuesta. Con `max_tokens: 500` y esfuerzo por
                # defecto, gpt-oss-120b gastaba 1.887 tokens razonando, terminaba con
                # finish_reason="length" y devolvia `content` VACIO.
                #
                # El harness lo registraba como "salida vacia" y el brazo salia con
                # fidelidad 0.33. Habria sido la tercera vez que este proyecto publica
                # una medicion propia como propiedad del sistema -- el benchmark de
                # 29.3x y la consistencia de 0.83 fueron las dos primeras.
                #
                # `reasoning_effort: low` deja el presupuesto para la RESPUESTA, que es
                # lo que se esta comparando. Los 500 tokens siguen siendo iguales para
                # todos los brazos: se iguala la salida, no el pensamiento.
                **({"reasoning_effort": "low"} if self.razona else {}),
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class GeminiProvider(Provider):
    name = "gemini"

    # ALIAS, NO VERSION FIJA. `gemini-2.0-flash` estaba fijado aqui y devolvia 404;
    # `gemini-2.5-flash` responde "This model is no longer available". Verificado el
    # 23-09-2026 contra la API con la clave real.
    #
    # Y hay un detalle que vale la pena: `GET /v1beta/models` LISTA modelos que
    # luego no se pueden llamar. El catalogo no es la verdad; la llamada si. Por eso
    # se usa el alias `-latest`, que Google reapunta, en vez de una version que
    # caduca sin avisar y convierte "el modelo fallo" en el diagnostico equivocado.
    # `-lite` y no `-flash`: la cuota gratuita es POR MODELO, y la de
    # `gemini-flash-latest` son 20 peticiones AL DIA. El harness gasta 24 solo en este
    # brazo (3 casos x 2 idiomas x 2 modos x 2 corridas), asi que no cabe ni con la
    # cuota intacta. El lite tiene su propia cuota y mejor disponibilidad.
    def __init__(self, model: str = "gemini-flash-lite-latest") -> None:
        self.model = model
        self.key = os.environ.get("GEMINI_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def generate(self, prompt: str, *, temperature: float = 0.0, seed: int = 42) -> str:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 500},
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


ALL_PROVIDERS: tuple[type[Provider], ...] = (
    TemplateProvider,
    OllamaProvider,
    GroqProvider,
    GeminiProvider,
)


def installed_ollama_models(host: str | None = None) -> list[str]:
    """Modelos presentes en el Ollama local."""
    host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        r = requests.get(f"{host}/api/tags", timeout=3)
        return sorted(m["name"] for m in r.json().get("models", []))
    except requests.RequestException:
        return []


def available_providers() -> list[Provider]:
    """Los que responden ahora mismo. El harness reporta cuales se evaluaron.

    Se enumeran TODOS los modelos locales instalados, no solo uno. Comparar
    tamanos dentro del mismo proveedor responde una pregunta que comparar
    proveedores no responde: si un fallo viene del modelo o de la tarea.
    """
    out: list[Provider] = [TemplateProvider()]
    out += [OllamaProvider(model=m) for m in installed_ollama_models()]
    for cls in (GroqProvider, GeminiProvider):
        p = cls()
        if p.available():
            out.append(p)
    return out
