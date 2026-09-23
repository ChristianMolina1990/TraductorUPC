"""Cliente minimo para pedir a la API de Claude una sugerencia de respuesta.

Esta es la unica pieza del modo "Interprete" que no es offline: el resto
(transcripcion con faster-whisper y traduccion con Argos Translate) sigue
funcionando igual que en el modo Audio.
"""

from __future__ import annotations

import re

_MODEL = "claude-sonnet-5"


# Que se le pide a Claude segun el boton pulsado.
_TASKS = {
    "start": (
        "La persona quiere INICIAR la conversación ahora. Sugiere, en inglés, una apertura "
        "natural y breve (2-3 frases): un saludo corto, una frase que introduzca uno de los "
        "temas a tratar (el más natural para empezar) y una pregunta final al interlocutor "
        "sobre ese tema para que responda."
    ),
    "reply": (
        "Sugiere, en inglés, una respuesta natural, breve (1-3 frases) y apropiada que la "
        "persona podría decir a continuación."
    ),
    "complement": (
        "La persona ya dio la última respuesta que aparece arriba como 'lo que ya dijo'. "
        "Sugiere, en inglés, 1-2 frases que complementen esa respuesta y que pueda decir "
        "justo después: añade un detalle, un ejemplo concreto o una razón, sin repetir lo "
        "que ya dijo."
    ),
    "question": (
        "Ahora la persona quiere pasarle el turno a su interlocutor. Sugiere, en inglés, "
        "UNA sola pregunta breve (una frase) dirigida al interlocutor sobre el tema que "
        "están tratando (o sobre alguno de los temas a tratar, si se indicaron y encaja), "
        "para que sea el interlocutor quien hable y la conversación siga fluida. "
        "Importante: el texto debe ser ÚNICAMENTE la pregunta y terminar en '?'; no añadas "
        "ninguna afirmación, opinión, detalle ni continuación de lo que la persona ya dijo, "
        "y no preguntes algo que el interlocutor ya haya respondido."
    ),
}


def suggest_reply(
    api_key: str,
    recent_lines: list[str],
    kind: str = "reply",
    own_lines: list[str] | None = None,
    topics: str = "",
    model: str = _MODEL,
) -> dict:
    """Dadas las ultimas frases dichas por el interlocutor (en su idioma
    original) y, opcionalmente, lo ultimo que ya se le sugirio decir a la
    persona, devuelve {"reply": <texto en ingles>, "pronunciation": <guia de
    pronunciacion fonetica para un hispanohablante>}.

    kind: "start" (abrir la conversacion a partir de los temas), "reply"
    (responder), "complement" (ampliar la ultima respuesta) o "question"
    (preguntarle algo al interlocutor sobre el tema).

    topics: temas que la persona quiere tratar; si no hay nada transcrito
    todavia, sirven para abrir la conversacion."""
    if not api_key:
        raise ValueError("falta la API key de Anthropic (configúrala en '⚙ Configuración')")
    topics = (topics or "").strip()
    if not recent_lines and not topics:
        return {"reply": "", "pronunciation": ""}
    task = _TASKS.get(kind, _TASKS["reply"])

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    if recent_lines:
        convo = (
            "Esto es lo último que ha dicho la otra persona, en orden cronológico:\n\n"
            + "\n".join(f"- {line}" for line in recent_lines)
        )
    else:
        convo = (
            "La conversación todavía no ha empezado: nadie ha dicho nada aún. Lo que "
            "sugieras debe abrirla entrando directamente en uno de los temas a tratar "
            "(nada genérico como saludos o 'how are you')."
        )
    own = ""
    if own_lines:
        own = (
            "\n\nLo que ya dijo (o se le sugirió decir) la persona, en orden cronológico:\n\n"
            + "\n".join(f"- {line}" for line in own_lines)
        )
    topic_block = ""
    if topics:
        topic_block = (
            "\n\nTemas que la persona quiere tratar en esta conversación (úsalos para "
            "orientar lo que sugieras y llevar la conversación hacia ellos cuando encaje "
            "de forma natural):\n\n" + topics
        )
    prompt = (
        "Estás ayudando a alguien a mantener una conversación fluida en inglés en tiempo real "
        "(por ejemplo una entrevista, clase, reunión o prueba oral)."
        f"{topic_block}\n\n"
        f"{convo}{own}\n\n"
        f"{task}\n\n"
        "Responde con EXACTAMENTE estas dos líneas, sin nada más antes ni después:\n"
        "RESPUESTA: <el texto sugerido, en inglés, sin comillas>\n"
        "PRONUNCIACION: <ese mismo texto escrito fonéticamente, usando letras y "
        "sonidos del español para que lo pueda leer en voz alta alguien que no domina "
        "el inglés; marca la sílaba tónica de cada palabra en MAYÚSCULAS>"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
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
