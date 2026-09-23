"""Cliente minimo para pedir a la API de Claude una sugerencia de respuesta.

Esta es la unica pieza del modo "Interprete" que no es offline: el resto
(transcripcion con faster-whisper y traduccion con Argos Translate) sigue
funcionando igual que en el modo Audio.
"""

from __future__ import annotations

import re

_MODEL = "claude-sonnet-5"


def suggest_reply(api_key: str, recent_lines: list[str], model: str = _MODEL) -> dict:
    """Dadas las ultimas frases dichas por el interlocutor (en su idioma
    original), devuelve {"reply": <respuesta en ingles>, "pronunciation":
    <guia de pronunciacion fonetica para un hispanohablante>}."""
    if not api_key:
        raise ValueError("falta la API key de Anthropic (configúrala en 'Intérprete')")
    if not recent_lines:
        return {"reply": "", "pronunciation": ""}

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    convo = "\n".join(f"- {line}" for line in recent_lines)
    prompt = (
        "Estás ayudando a alguien a seguir una conversación en tiempo real "
        "(por ejemplo una entrevista, clase o reunión). Esto es lo último que ha dicho "
        "la otra persona, en orden cronológico:\n\n"
        f"{convo}\n\n"
        "Sugiere, en inglés, una respuesta natural, breve (1-3 frases) y apropiada que la "
        "persona podría decir a continuación.\n\n"
        "Responde con EXACTAMENTE estas dos líneas, sin nada más antes ni después:\n"
        "RESPUESTA: <la respuesta sugerida, en inglés, sin comillas>\n"
        "PRONUNCIACION: <esa misma respuesta escrita fonéticamente, usando letras y "
        "sonidos del español para que la pueda leer en voz alta alguien que no domina "
        "el inglés; marca la sílaba tónica de cada palabra en MAYÚSCULAS>"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
    return _parse_reply(text)


def _parse_reply(text: str) -> dict:
    reply_match = re.search(r"RESPUESTA\s*:\s*(.+)", text, re.IGNORECASE)
    pron_match = re.search(r"PRONUNCIACI[OÓ]N\s*:\s*(.+)", text, re.IGNORECASE)
    # Si Claude no siguió el formato pedido, se usa el texto completo como
    # respuesta y se deja la pronunciación vacía en vez de romper el pipeline.
    reply = reply_match.group(1).strip() if reply_match else text
    pronunciation = pron_match.group(1).strip() if pron_match else ""
    return {"reply": reply, "pronunciation": pronunciation}
