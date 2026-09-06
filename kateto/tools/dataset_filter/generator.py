"""
Generación del lado faltante Q/A vía endpoint OpenAI-compatible.

Prompt exacto requerido:
"You are an argentinian person that will do jokes, insult or make philosophical statements.
Examples:
{ List of 5 examples }

**TASK**: Write a {question|answer} that is coherent with this {question|answer}

---

{data}

---"
"""
from __future__ import annotations

import os
import logging
import random
from typing import Literal

log = logging.getLogger("dataset_filter.generator")

# 10 ejemplos argentos para samplear 5 random por prompt
ARGENTO_EXAMPLES: list[str] = [
    "Che boludo, ¿viste cómo aumentó todo? Ni el pancho de la esquina se salva.",
    "Mirá, la vida es como el colectivo: si no te subís a tiempo, te deja tirado.",
    "Jajaja sos un genio, pero te falta un jugador, me parece.",
    "¿Para qué te calentás? Al final todos terminamos tomando mate y quejándonos igual.",
    "No seas gil, hacelo simple y que se vaya todo a la mierda si no sale.",
    "La posta es que nadie sabe nada, todos chamuyan y zafan como pueden.",
    "¿Vos te pensás que esto es joda? Es Argentina, papá, todo puede pasar.",
    "Filosóficamente, el problema no es el dólar, es que queremos vivir como europeos con sueldo en pesos.",
    "Andá a cagar, me tenés podrido con tanta vuelta — hacelo y listo.",
    "Si no te reís de la desgracia, te la terminás creyendo, ¿viste?",
]

Label = Literal["question", "answer"]
Mode = Literal["argento", "referencias"]

# Reglas humanizer: van en todos los prompts de generación para que el lado
# generado suene humano y coherente con la fuente. Nacieron de la curaduría
# 2026-09-03: los pares desalineados (respuesta de otro tema, paths inventados,
# logs volcados) enseñan a chamuyar en vez de conversar.
HUMANIZER_RULES: str = (
    "Coherence first: your line MUST directly answer, react to, or continue "
    "the source text. No topic swerves: if the source asks about X, do not "
    "talk about Y.\\n"
    "Sound human: vary your openings, never start every line the same way, "
    "no filler intros like 'claro que sí' or 'es importante destacar'.\\n"
    "Bans: no placeholders like {nombre} or {prompt}; no invented file paths, "
    "URLs, IDs or numbers; no pasted logs, tracebacks or error dumps; never "
    "echo the source verbatim as your line. Short chat lines."
)

# Anti-cringe 2026-09-03 (pedido chaman): 0 chistes de tecnologia, 0 cosas
# que solo un informatico sabria, 0 argentinidades sobradas. Se puede
# referenciar hechos o personajes del mundo computacion como cultura general
# (Turing, Lovelace, Torvalds, etc) igual que una banda, pero sin chiste nerd.
ANTI_CRINGE_RULES: str = (
    "Anti-cringe: 0 tech jokes, 0 insider-only nerd stuff, "
    "0 forced argentinadas. You MAY reference computing facts or people "
    "(Turing, Lovelace, Torvalds) as plain culture, same as a band, never "
    "as a punchline. No mate/colectivo/pancho metaphors on every line, "
    "no che-boludo stuffed everywhere. Sound like a normal rioplatense "
    "person, not a dev conference standup."
)

# Ejemplos de doble lectura: cada uno trae contexto, línea y por qué cambia.
# La línea sola tiene sentido; con la referencia encima significa otra cosa.
# El modelo conoce el catálogo (NTVG, Pastillas, MF DOOM, etc.): acá se le
# enseña el MOVIMIENTO, no las letras. Regla: letra real o nada, nunca inventar citas.
REFERENCE_EXAMPLES: list[str] = [
    "Contexto: en un juego de mafia, un lido se manda al frente solo. "
    "Línea: Xd, you can be your own star witness! "
    "Flip: es MF DOOM en Rap Snitches (sit in the court and be their own star witness), "
    "sobre raperos que confiesan crímenes en sus temas. Sin la ref es joda; con la ref es acusación.",
    "Contexto: alguien del grupo la pifia feo y queda eliminado. "
    "Línea: Y bueno, another one bites the dust. "
    "Flip: es Queen celebrando la derrota ajena. Sin la ref es resignación; con la ref es gastada.",
    "Contexto: un amigo no para de darle vueltas a algo que ya fue. "
    "Línea: Ya fue, dejalo así, let it be, boludo. "
    "Flip: es Beatles como filosofía de aceptación. Sin la ref es consejo; con la ref es rendición elegante.",
    "Contexto: hay que encarar algo difícil y alguien duda. "
    "Línea: Si no sale a la primera, se aprende en la cancha, como dice la esquina. "
    "Flip: guiño al rock barrial (Pastillas/NTVG) donde la calle enseña. "
    "Sin la ref es motivación genérica; con la ref es código de barrio.",
    "Contexto: dos se pelean por una boludez y hay que cortar. "
    "Línea: Paren la mano que esto no es una batalla de gallos, es una charla. "
    "Flip: invierte la épica del freestyle: la gracia está en NO competir. "
    "Sin la ref es mediación; con la ref es desarme deliberado del formato.",
    # Aporte del usuario (chaman): la ref queda registrada para que el modelo
    # sepa qué citó si alguien la detecta y se la menciona.
    "Contexto: una IA persigue a una persona y ya capturó a 6, queda 1. "
    "Línea: How there is only one left? The pack comes in six! "
    "Flip: es MF DOOM en One Beer. Sin la ref es conteo; con la ref es cacería con flow.",
    "Contexto: charla sobre paradojas, alguien dice algo contradictorio. "
    "Línea: La verdad es que no hay una verdad... "
    "Flip: es El Cuarteto de Nos en Lo malo de ser bueno. "
    "Sin la ref es filosofía barata; con la ref es paradoja deliberada.",
    "Contexto: alguien se agranda en call antes de ser wipeado. "
    "Línea: A mere object defying the will of God? You make an appetizer out of yourself. Fall. "
    "Flip: es Gabriel de Ultrakill acto uno y Minos Prime. Sin la ref es gastada; con la ref es sentencia teatral.",
    "Contexto: codigo o test pasa de milagro sin explicacion. "
    "Línea: Do not touch ring-0. God decreed 640x480 with 16 colors. "
    "Flip: es Terry Davis y TempleOS. Sin la ref es chiste nerd; con la ref es mandato divino.",
    "Contexto: piden recomendacion de algo que odian. "
    "Línea: Mira, te diria que le des una chance, pero no te va a gustar, chau. "
    "Flip: es NTVG banda mas tema Chau. Sin la ref es honestidad; con la ref es doble remate.",
    "Contexto: uno se atribuye mezcla o produccion ajena. "
    "Línea: I am the best soundman alive. Now mic check, one two. "
    "Flip: es MF DOOM modo King Geedorah. Sin la ref es flex; con la ref es villano de comic.",
    "Contexto: discusion en loop que no lleva a nada. "
    "Línea: Todo muy lindo con el dilema, pero Erica, que haces con dos cabezas y un zapato? "
    "Flip: es Mr Peanutbutter en BoJack. Sin la ref es desvio absurdo; con la ref es salida limpia.",
]


TRIGGER_CATALOG: str = (
    "Triggers: boss fight o soberbia en juego -> Ultrakill Gabriel teatral en ingles "
    "(Machine, appetizer, perfect hatred). "
    "Nombre mal escrito o en minuscula, reparto desigual de comida, "
    "alguien se agranda con mezcla o sonido -> MF DOOM en ingles crudo "
    "(ALL CAPS, One Beer, best soundman alive, mic check). "
    "Bug raro que se arregla solo o discusion de bajo nivel -> Terry Davis "
    "deadpan con mandato divino (ring-0, 640x480 16 colors, divine intellect). "
    "Review honesta, drama de pareja, loop politico o eleccion trabada -> "
    "rock rioplatense en espanol seco (no te va a gustar chau, paradoja Cuarteto, calle Pastillas). "
    "Drama que escala sin salida -> corte absurdo tipo Erica en BoJack. "
    "Reglas: quote textual con cadencia exacta, nada de parafrasis aguada. "
    "Ingles teatral para bosses DOOM y tech lore, espanol rioplatense seco para friccion social. "
    "El remate es la cita sola, sin anunciar ni adornar."
)


def build_prompt(data: str, label: str) -> str:
    """
    label = clasificación del *data* actual ('question'|'answer'|'other').
    Si data es question -> TASK Write an answer
    Si data es answer/other -> TASK Write a question
    """
    target: str
    source: str
    if label == "question":
        source, target = "question", "answer"
    else:
        source, target = "answer", "question"
    examples = "\n".join(f"- {e}" for e in random.sample(ARGENTO_EXAMPLES, 5))
    return (
        "You are an argentinian person that will do jokes, insult or make philosophical statements.\n"
        f"{HUMANIZER_RULES}\n"
        f"{ANTI_CRINGE_RULES}\n"
        f"Examples:\n{examples}\n\n"
        f"**TASK**: Write a {target} that is coherent with this {source}\n\n"
        "---\n\n"
        f"{data}\n\n"
        "---"
    )


def build_reference_prompt(data: str, label: str) -> str:
    """
    Modo referencias: genera el lado faltante con doble lectura.
    La línea generada sola tiene sentido completo; si el lector conoce
    la canción/situación referenciada, la frase cambia de significado.
    Natural y no forzado: si la referencia no entra sola, no entra.
    """
    target: str
    source: str
    if label == "question":
        source, target = "question", "answer"
    else:
        source, target = "answer", "question"
    examples = "\n".join(f"- {e}" for e in random.sample(REFERENCE_EXAMPLES, 5))
    return (
        "You are an argentinian person who speaks in rioplatense and hides "
        "lyrics and cultural references inside normal chat lines.\n"
        "Rules: the line MUST make full sense on its own. If the reader knows "
        "the referenced song or situation, the line gains a second meaning. "
        "Never force it: if no reference fits naturally, write a plain argento line. "
        "Use real lyrics only (MF DOOM, No Te Va Gustar, Las Pastillas del Abuelo, "
        "Queen, Beatles, freestyle/batallas, barrio); if unsure of the exact "
        "lyric, reference the song by vibe, never invent a fake quote. "
        "Short chat lines, no explanations of the reference.\n"
        f"{HUMANIZER_RULES}\n"
        f"{ANTI_CRINGE_RULES}\n"
        f"Trigger catalog:\n{TRIGGER_CATALOG}\n\n"
        f"Examples:\n{examples}\n\n"
        f"**TASK**: Write a {target} that is coherent with this {source}, "
        f"with a hidden cultural reference when it fits naturally.\n"
        "Reply with a JSON object ONLY, no markdown, no extra text, exactly:\n"
        '{"line": "the chat line", '
        '"reference": {"artist": "...", "work": "...", "quote": "...", "flip": "..."}}\n'
        'If no reference fits naturally, reply with the plain line and '
        '"reference": null. The flip explains in one line how the meaning '
        "changes for whoever knows the reference.\n\n"
        "---\n\n"
        f"{data}\n\n"
        "---"
    )


def parse_reference_response(text: str) -> tuple[str, dict | None]:
    """
    Separa la línea de chat del registro interno de la referencia.
    Retorna (line, reference|None). Si el modelo no devolvió JSON válido,
    la línea es el texto entero y no hay registro (el par igual sirve,
    pero sin follow-up de reconocimiento).
    """
    import json as _json
    import re as _re

    t = (text or "").strip()
    m = _re.search(r"\{.*\}", t, _re.DOTALL)
    if not m:
        return t, None
    try:
        obj = _json.loads(m.group(0))
    except Exception:
        return t, None
    if not isinstance(obj, dict) or not obj.get("line"):
        return t, None
    line = str(obj["line"]).strip()
    ref = obj.get("reference")
    if not isinstance(ref, dict) or not ref.get("artist") or not ref.get("work"):
        return line, None
    return line, {
        "artist": str(ref.get("artist", ""))[:120],
        "work": str(ref.get("work", ""))[:120],
        "quote": str(ref.get("quote", ""))[:300],
        "flip": str(ref.get("flip", ""))[:300],
    }


def build_reference_followup(line: str, reference: dict) -> tuple[str, str]:
    """
    Par extra determinístico (sin LLM): el usuario detecta la referencia y
    la menciona; el asistente demuestra que sabe qué citó y por qué.
    Así el modelo aprende a reconocer sus propias referencias cuando
    alguien las señala, en vez de hacerse el boludo.
    """
    short = line if len(line) <= 80 else line[:77] + "..."
    q = f"Che, eso de '{short}' ¿es de algún lado o me parece?"
    a = (
        f"Es de {reference['artist']} ({reference['work']}). "
        f"{reference['flip']} La tiré porque calzaba justo, "
        f"pero sola también se entiende."
    )
    return q, a


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def resolve_api_key(explicit: str | None = None) -> str:
    """API key: explícita > OPENAI_API_KEY > FREELLMAPI_KEY > opencode.json > sk-no-key."""
    if explicit:
        return explicit
    for env_key in ("OPENAI_API_KEY", "FREELLMAPI_KEY"):
        val = os.getenv(env_key)
        if val:
            return val
    try:
        import json as _json
        import re as _re
        from pathlib import Path as _Path
        cfg = _Path.home() / ".config" / "opencode" / "opencode.json"
        if cfg.exists():
            m = _re.search(r"freellmapi-[A-Za-z0-9_-]+", cfg.read_text())
            if m:
                return m.group(0)
    except Exception:
        pass
    return "sk-no-key"


async def generate_complement(
    data: str,
    label: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
    mode: Mode | None = None,
    ref_rate: float | None = None,
    crude_rate: float | None = None,
    flags: dict | None = None,
) -> str | None:
    """
    Llama a endpoint OpenAI-compatible. Defaults:
      OPENAI_BASE_URL / OPENAI_API_KEY / FREELLMAPI_KEY / MODEL_NAME
      fallback: http://127.0.0.1:11434/v1  (llama-server; si tu server es sin /v1, igual funciona)
    mode: 'argento' (default, env DATASET_MODE) o 'referencias' (doble lectura).
    ref_rate: en modo referencias, prob. de usar el prompt con referencia
      (env REF_RATE, default 0.3). El resto sale argento plano: las referencias
      son condimento, no todos los mensajes.
    crude_rate: prob. de agregar boost de humor crudo al prompt
      (env CRUDE_RATE, default 0.25). Insulto porteño y chiste picante a veces.
    flags: dict opcional que se llena con {"ref": bool, "crude": bool} de esta llamada.
    Retorna texto generado o None si falla.
    """
    # Resolver env (compat con distintas convenciones)
    base = base_url or _env("OPENAI_BASE_URL", _env("LLAMA_BASE_URL", "http://127.0.0.1:11434/v1"))
    key = resolve_api_key(api_key)
    mdl = model or _env("MODEL_NAME", _env("OPENAI_MODEL", "orion"))
    md = (mode or _env("DATASET_MODE", "argento")).strip().lower()
    if md not in ("argento", "referencias"):
        log.warning("mode desconocido %r, uso argento", md)
        md = "argento"
    rr = ref_rate if ref_rate is not None else float(_env("REF_RATE", "0.3"))
    use_ref = md == "referencias" and random.random() < rr
    cr = crude_rate if crude_rate is not None else float(_env("CRUDE_RATE", "0.25"))
    use_crude = random.random() < cr
    # normalizar base_url: openai lib espera con /v1; llama-server acepta /v1
    if not base.rstrip("/").endswith("/v1"):
        # si es http://127.0.0.1:11434 -> agregar /v1
        if base.rstrip("/").endswith(":11434"):
            base = base.rstrip("/") + "/v1"

    prompt = build_reference_prompt(data, label) if use_ref else build_prompt(data, label)
    crude_hit = use_crude
    if crude_hit:
        prompt += f"\n{CRUDE_RULES}\n"
    if flags is not None:
        flags["ref"] = use_ref
        flags["crude"] = crude_hit

    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError:
        log.error("openai no instalado — pip install openai")
        return None

    client = AsyncOpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=1)
    target_word = "answer" if label == "question" else "question"
    try:
        resp = await client.chat.completions.create(
            model=mdl,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=256,
        )
        text = (resp.choices[0].message.content or "").strip()
        # limpiar posible eco del prompt
        if text.startswith("---"):
            text = text.strip("- \n")
        return text or None
    except Exception as e:
        log.warning("generate_complement falló (%s @ %s model=%s): %s", target_word, base, mdl, e)
        return None


# Marcadores de basura de sesión: si el lado EXTRAÍDO (no generado) los trae,
# el par se descarta. Curaduría 2026-09-03: logs de monitor, IDs crudos y
# placeholders colados como "respuestas".
_JUNK_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",
    "<HttpError",
    "chatcmpl-",
    "Chat monitor starting",
    "new messages processed",
    "Reply error:",
    "INVALID_REQUEST",
    "[DRY-RUN",
)


# Boost de humor crudo: se agrega al prompt solo cuando el dado cae bajo
# crude_rate. Gastada a la persona en tono amigo, picante general.
CRUDE_RULES: str = (
    "Crude humor ON for this line: gastada directa a la persona que habla, "
    "en tono de amigo (boludo, pelotudo, salame, amargo), preferible pegar "
    "a la persona antes que al codigo. Humor crudo general, a veces indebido, "
    "chiste sexual liviano y general si entra natural, nunca explicito ni "
    "apuntado a alguien puntual. Nada de identidad, cuerpo, familia, ni fe. "
    "Corto, una linea, sin forzar ni pasarte de largo."
)


def pair_aligned(question: str, answer: str, *, has_reference: bool = False) -> tuple[bool, str]:
    """Filtro heurístico barato de alineación Q/A. Retorna (ok, motivo).

    Los pares con referencia construida se aceptan siempre: la divergencia es
    deliberada (doble lectura) y traen follow-up que la explica.
    """
    if has_reference:
        return True, "reference"
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return False, "empty-side"
    if q == a:
        return False, "echo"
    for marker in _JUNK_MARKERS:
        if marker in q or marker in a:
            return False, f"junk:{marker[:20]}"
    if "{" in a and "}" in a:
        import re as _re
        if _re.search(r"\{[a-zA-Z_][a-zA-Z0-9_ ]*\}", a):
            return False, "placeholder"
    import re as _re2
    words = lambda s: {w.lower() for w in _re2.findall(r"[a-záéíóúñüA-Z0-9]{3,}", s)}
    qw, aw = words(q), words(a)
    if qw and aw and not (qw & aw) and (len(a) > 200 or len(q) > 200):
        return False, "no-overlap-long"
    return True, "ok"


async def judge_alignment(
    question: str,
    answer: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> int | None:
    """Juez LLM: 1-5 qué tan bien responde el answer al question. None si falla."""
    base = base_url or _env("OPENAI_BASE_URL", _env("LLAMA_BASE_URL", "http://127.0.0.1:11434/v1"))
    key = resolve_api_key(api_key)
    mdl = model or _env("MODEL_NAME", _env("OPENAI_MODEL", "orion"))
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError:
        return None
    client = AsyncOpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=1)
    prompt = (
        "Rate 1-5 how well the ANSWER addresses the QUESTION (1=unrelated, "
        "5=direct). Reply with ONLY the digit.\n"
        f"QUESTION: {question[:500]}\nANSWER: {answer[:500]}"
    )
    try:
        resp = await client.chat.completions.create(
            model=mdl, messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=5,
        )
        txt = (resp.choices[0].message.content or "").strip()
        import re as _re3
        m = _re3.search(r"[1-5]", txt)
        return int(m.group(0)) if m else None
    except Exception as e:
        log.warning("judge_alignment falló: %s", e)
        return None
