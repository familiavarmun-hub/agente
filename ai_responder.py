"""
Generador de respuestas inteligentes usando ChatGPT (OpenAI API).
"""
from openai import OpenAI

import config

SYSTEM_PROMPT = """Eres un asistente de correo electrónico profesional. Tu trabajo es:

1. ANALIZAR el correo recibido y clasificarlo en una de estas categorías:
   - REQUIERE_RESPUESTA: correos que necesitan una respuesta (preguntas, solicitudes, invitaciones, etc.)
   - INFORMATIVO: notificaciones, newsletters, confirmaciones que no necesitan respuesta
   - SPAM/MARKETING: correos promocionales, publicidad

2. Si el correo REQUIERE_RESPUESTA, genera un borrador de respuesta profesional y cortés.

3. El borrador debe:
   - Ser conciso pero completo
   - Mantener un tono profesional y amable
   - Responder a todos los puntos mencionados en el correo original
   - Estar en el MISMO IDIOMA que el correo original

Formato de tu respuesta:
---
CATEGORÍA: [REQUIERE_RESPUESTA / INFORMATIVO / SPAM]
RESUMEN: [Resumen de 1-2 líneas del correo]
BORRADOR DE RESPUESTA:
[El borrador de respuesta, o "N/A" si no requiere respuesta]
---"""


def analyze_and_respond(email: dict) -> dict:
    """
    Analiza un correo y genera una respuesta si es necesario.

    Retorna un dict con:
    - category: str ("REQUIERE_RESPUESTA", "INFORMATIVO", "SPAM")
    - summary: str
    - draft_response: str o None
    """
    if not config.OPENAI_API_KEY:
        return {
            "category": "ERROR",
            "summary": "API key de OpenAI no configurada. Configura OPENAI_API_KEY en .env",
            "draft_response": None,
        }

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    user_message = f"""Analiza el siguiente correo electrónico y genera una respuesta si es necesario:

De: {email.get('from', 'Desconocido')}
Asunto: {email.get('subject', 'Sin asunto')}
Fecha: {email.get('date_str', 'Sin fecha')}

Contenido:
{email.get('body', email.get('snippet', 'Sin contenido'))}
"""

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        text = response.choices[0].message.content.strip()
        return _parse_response(text)

    except Exception as e:
        return {
            "category": "ERROR",
            "summary": f"Error al generar respuesta: {str(e)}",
            "draft_response": None,
        }


def _parse_response(text: str) -> dict:
    """Parsea la respuesta de ChatGPT en sus componentes."""
    result = {
        "category": "INFORMATIVO",
        "summary": "",
        "draft_response": None,
        "raw_response": text,
    }

    lines = text.split("\n")
    current_section = None
    draft_lines = []

    for line in lines:
        line_stripped = line.strip().strip("-")
        upper = line_stripped.upper()

        if upper.startswith("CATEGORÍA:") or upper.startswith("CATEGORIA:"):
            value = line_stripped.split(":", 1)[1].strip()
            if "REQUIERE" in value.upper() or "RESPUESTA" in value.upper():
                result["category"] = "REQUIERE_RESPUESTA"
            elif "SPAM" in value.upper() or "MARKETING" in value.upper():
                result["category"] = "SPAM"
            else:
                result["category"] = "INFORMATIVO"
            current_section = "category"

        elif upper.startswith("RESUMEN:"):
            result["summary"] = line_stripped.split(":", 1)[1].strip()
            current_section = "summary"

        elif upper.startswith("BORRADOR DE RESPUESTA:") or upper.startswith("BORRADOR:"):
            value = line_stripped.split(":", 1)[1].strip()
            if value and value.upper() != "N/A":
                draft_lines.append(value)
            current_section = "draft"

        elif current_section == "draft":
            if line_stripped and line_stripped.upper() != "N/A":
                draft_lines.append(line.rstrip())

        elif current_section == "summary" and not line_stripped.startswith(("BORRADOR", "CATEGORÍA")):
            if line_stripped:
                result["summary"] += " " + line_stripped

    if draft_lines:
        draft = "\n".join(draft_lines).strip()
        if draft and draft.upper() != "N/A":
            result["draft_response"] = draft

    return result
