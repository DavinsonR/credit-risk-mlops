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

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

TIMEOUT = 120


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

    def run(self, prompt: str, **kw) -> Generation:
        import time

        t0 = time.perf_counter()
        try:
            text = self.generate(prompt, **kw)
            return Generation(self.name, self.model, text, time.perf_counter() - t0)
        except Exception as exc:
            return Generation(
                self.name, self.model, "", time.perf_counter() - t0, f"{type(exc).__name__}: {exc}"
            )


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

    def __init__(self, model: str = "llama-3.3-70b-versatile") -> None:
        self.model = model
        self.key = os.environ.get("GROQ_API_KEY", "")

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
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
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
