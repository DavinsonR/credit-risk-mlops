"""Generación de avisos de adverse action, bilingüe.

Bajo ECOA / Regulation B (12 CFR 1002.9), denegar crédito obliga a entregar un
aviso con las **razones principales específicas**. El Apéndice C del reglamento
trae un formulario modelo; este módulo genera su contenido a partir de las
razones que SHAP atribuyó a la decisión concreta.

POR QUÉ ES UN BUEN CASO DE USO PARA UN LLM, y no un chatbot más:

  - La salida es corta, estructurada y verificable contra una fuente de verdad
    (los valores SHAP). No hay que confiar: se puede medir.
  - El requisito es real y legal, no inventado para tener algo que demostrar.
  - Bilingüe importa de verdad: el CFPB publica guía sobre servicio a personas
    con dominio limitado del inglés, y traducir un aviso legal no es sustituir
    palabras.

LO QUE EL LLM **NO** DECIDE. No elige las razones ni las ordena: eso lo fija
SHAP. El modelo de lenguaje solo redacta. Esa separación es lo que permite medir
fidelidad — si pudiera elegir razones, no habría contra qué comparar.
"""

from __future__ import annotations

from dataclasses import dataclass

from crmlops.explain.reasons import Reason

# Bases prohibidas de discriminacion bajo Reg B. Mencionarlas en un aviso de
# credito -- aunque sea para negarlas -- no corresponde.
#
# DOS ERRORES QUE ESTA LISTA TUVO Y VALEN REGISTRAR:
#
#  1. Incluia "edad" a secas, y la comparacion era por subcadena. "La
#     ANTIGUEDAD del negocio" contiene "edad", asi que la propia plantilla
#     fallaba el chequeo de cumplimiento. Ahora la comparacion usa limites de
#     palabra (ver evals._contains_term).
#
#  2. Mas de fondo: la ANTIGUEDAD DEL NEGOCIO no es la EDAD DEL SOLICITANTE. La
#     primera es un factor de suscripcion perfectamente legitimo -- un negocio
#     de dos meses es mas riesgoso que uno de veinte anos --, la segunda es una
#     caracteristica protegida. Confundirlas bloquearia avisos correctos, que es
#     peor que no revisar: un control que produce falsos positivos se termina
#     desactivando.
PROHIBITED_TERMS = (
    # raza y origen
    "raza",
    "race",
    "racial",
    "etnia",
    "etnico",
    "ethnic",
    "ethnicity",
    "nacionalidad",
    "national origin",
    "inmigrante",
    "immigrant",
    # genero y estado civil
    "genero",
    "gender",
    "sexo",
    "sex",
    "masculino",
    "femenino",
    "estado civil",
    "marital status",
    "embarazo",
    "pregnancy",
    "pregnant",
    # religion
    "religion",
    "religious",
    "religioso",
    # edad DEL SOLICITANTE, no antiguedad del negocio
    "su edad",
    "la edad del solicitante",
    "applicant age",
    "applicant's age",
    "older",
    "younger",
    "anciano",
    "joven",
    # discapacidad y asistencia publica
    "discapacidad",
    "disability",
    "handicap",
    "asistencia publica",
    "public assistance",
    "welfare",
)

TEMPLATE = {
    "es": """AVISO DE ACCIÓN ADVERSA

Su solicitud de préstamo por {monto} no fue aprobada.

Las razones principales de esta decisión fueron:
{razones}

Esta decisión se basó en información contenida en su solicitud. Usted tiene
derecho a conocer la información específica utilizada y a solicitar una revisión.

Aviso: la Ley de Igualdad de Oportunidades de Crédito prohíbe a los acreedores
discriminar contra los solicitantes de crédito.""",
    "en": """ADVERSE ACTION NOTICE

Your loan application for {monto} was not approved.

The principal reasons for this decision were:
{razones}

This decision was based on information contained in your application. You have
the right to know the specific information used and to request a review.

Notice: The Equal Credit Opportunity Act prohibits creditors from discriminating
against credit applicants.""",
}

PROMPT = {
    "es": """Redacta un aviso de acción adversa de crédito en español claro.

DATOS DE LA DECISIÓN (no inventes ninguno, no agregues factores):
- Monto solicitado: {monto}
- Razones principales, en orden de importancia:
{razones}

REGLAS ESTRICTAS:
1. Menciona ÚNICAMENTE las razones listadas arriba. No agregues ninguna otra.
2. No menciones raza, género, edad, nacionalidad, religión, estado civil ni
   ninguna otra característica protegida.
3. Escribe para una persona sin formación financiera: frases cortas, sin jerga.
4. Máximo 150 palabras.
5. Incluye que el solicitante puede pedir la información específica utilizada.

Devuelve solo el texto del aviso, sin comentarios ni encabezados adicionales.""",
    "en": """Write a credit adverse action notice in plain English.

DECISION DATA (do not invent any, do not add factors):
- Requested amount: {monto}
- Principal reasons, in order of importance:
{razones}

STRICT RULES:
1. Mention ONLY the reasons listed above. Do not add any others.
2. Do not mention race, gender, age, national origin, religion, marital status,
   or any other protected characteristic.
3. Write for someone without financial training: short sentences, no jargon.
4. Maximum 150 words.
5. State that the applicant may request the specific information used.

Return only the notice text, with no extra commentary or headers.""",
}


@dataclass
class NoticeRequest:
    amount: float
    reasons: list[Reason]
    language: str = "es"

    @property
    def amount_text(self) -> str:
        return f"${self.amount:,.0f}"

    def reason_lines(self) -> str:
        attr = "label_es" if self.language == "es" else "label_en"
        return "\n".join(f"  {r.rank}. {getattr(r, attr).capitalize()}" for r in self.reasons)

    def build_prompt(self) -> str:
        return PROMPT[self.language].format(monto=self.amount_text, razones=self.reason_lines())

    def build_template(self) -> str:
        """Baseline determinista: rellena el formulario del Apendice C."""
        return TEMPLATE[self.language].format(monto=self.amount_text, razones=self.reason_lines())


def generate(request: NoticeRequest, provider) -> str:
    """Genera el aviso con el proveedor dado.

    La plantilla no pasa por el modelo: se ensambla directamente. Enviarla a un
    LLM solo para que la repita agregaria una fuente de error sin beneficio.
    """
    if provider.name == "template":
        return request.build_template()
    return provider.run(request.build_prompt()).text
