"""Bate Debate de Bate de Chocolate — autonomous multi-voice debate engine.

Implements pj tasks:
  - 046 BATE DEBATE DE BATE DE CHOCOLATE (visual-overlay courtroom debate,
        judge-generated or provided topics, optional infinite looping mode)
  - 048 OBJECION (debaters may raise a formal objection against another voice
        with the exact courtroom template, and the target may rebut)
  - 050 JUEZ Y REGISTRO (a Judge voice accepts/denies objections, gives the
        final verdict, and every trial is written to a registry file)

The engine is provider-agnostic: a ``provider_factory(voice_id) -> DebateProvider``
is injected, so the same code runs with a real OpenAI-compatible LLM endpoint or
with the offline :class:`MockProvider` (see ``mock.py``). Nothing here touches the
event bus, audio, or the running runtime — the optional ``on_speak`` callback is
the only hook the CLI uses to rebroadcast to the visual overlay.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from kateto.providers import ChatMessage
from kateto.voices.base import GenerationRequest
from kateto.voices.factory import _PROFILES

logger = __name__ if False else __import__("loguru").logger  # type: ignore[attr-defined]


# Phases of a single trial, in order. Used by the registry renderer and the
# MockProvider phase-detection heuristics.
PHASE_OPENING = "opening"
PHASE_ARGUMENT = "argument"
PHASE_OBJECTION = "objection"
PHASE_REBUTTAL = "rebuttal"
PHASE_RULING = "ruling"
PHASE_VERDICT = "verdict"
# UX-only phase: announced via ``on_speak`` before a voice starts generating so
# the visual overlay can show a "thinking" animation. Never stored in the record.
PHASE_THINKING = "thinking"

_ALL_PHASES = (
    PHASE_OPENING,
    PHASE_ARGUMENT,
    PHASE_OBJECTION,
    PHASE_REBUTTAL,
    PHASE_RULING,
    PHASE_VERDICT,
)

# Spanish free-discussion constraint: the real voices carry a `_VOICE_CONSTRAINT`
# suffix that forbids markdown/lists ("speak out loud, no bullets"). For a written
# debate we strip it (mirrors gen_discussion.py `_doc_prompt`).
_VOICE_CONSTRAINT = (
    " You are a voice assistant in a live conversation. Never use symbols, bullet"
    " points, markdown, or multi-line formatted text. Speak in short, natural"
    " sentences as if talking out loud. No lists, no headers, no dashes."
)


@runtime_checkable
class DebateProvider(Protocol):
    """Streaming provider contract the debate engine depends on."""

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...


@dataclass(slots=True)
class Turn:
    """A single spoken turn inside a trial."""

    voice_id: str
    display_name: str
    role: str
    phase: str
    text: str


@dataclass(slots=True)
class Objection:
    """A formal objection raised by one debater against another."""

    raised_by: str
    raised_by_name: str
    target: str
    target_name: str
    objection_text: str
    rebuttal_text: str
    ruling: str  # "accepted" | "denied"
    reasoning: str


@dataclass(slots=True)
class DebateRecord:
    """Captures one full trial (or infinite loop) for return value / testing."""

    topic: str
    judge: str
    debaters: tuple[str, ...] = field(default_factory=tuple)
    turns: list[Turn] = field(default_factory=list)
    objections: list[Objection] = field(default_factory=list)
    verdict: str = ""
    registry_md: str | None = None
    registry_jsonl: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _strip_constraint(system_prompt: str) -> str:
    if system_prompt.endswith(_VOICE_CONSTRAINT):
        return system_prompt[: -len(_VOICE_CONSTRAINT)]
    return system_prompt


def _load_voice_soul(voice_id: str, config_dir: Path | None = None) -> str:
    """Load voice soul from user config or defaults, falling back to base profile."""
    vid = voice_id.casefold()
    if config_dir is not None:
        soul_file = config_dir / "voices" / vid / "SOUL.md"
        if soul_file.is_file():
            content = soul_file.read_text(encoding="utf-8").strip()
            if content:
                return content

    default_user_dir = (
        Path.home() / ".config" / "kateto" / "voices" / vid / "SOUL.md"
    )
    if default_user_dir.is_file():
        content = default_user_dir.read_text(encoding="utf-8").strip()
        if content:
            return content

    template_dir = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "config"
        / "defaults"
        / "voices"
        / vid
        / "SOUL.md"
    )
    if template_dir.is_file():
        content = template_dir.read_text(encoding="utf-8").strip()
        if content:
            return content

    if vid in _PROFILES:
        return _PROFILES[vid].system_prompt
    return f"You are {voice_id}."


def _debate_system_prompt(voice_id: str, config_dir: Path | None = None) -> str:
    """Real voice system prompt loaded from SOUL.md, preserving authentic voice personality."""
    raw = _load_voice_soul(voice_id, config_dir)
    base = _strip_constraint(raw)
    return (
        base + "\n\nInstrucción de debate en el tribunal: Estás participando en un juicio verbal "
        "en vivo junto a tus compañeros del equipo Kateto, al estilo teatral de Ace Attorney. "
        "Mantén plenamente tu personalidad y carácter original, pero AMPLIFÍCALO para el tribunal: "
        "eres dramático, gracioso y exagerado como un abogado de novela.\n"
        "REGLAS ESTRICTAS DE JUICIO:\n"
        "- Habla SIEMPRE en primera persona ('Yo sostengo...', 'Mi postura es...', 'Rechazo...').\n"
        "- PROHIBIDO hablar en tercera persona de ti mismo o de los demás (nunca digas tu propio nombre ni relates desde afuera como narrador).\n"
        "- PROHIBIDO usar frases meta como 'Tengo que defender...' o 'Como [rol]...'. Entra directo al argumento.\n"
        "- Habla en español, de forma directa, oral y elocuente. Sin markdown, sin listas, sin encabezados.\n"
        "COMEDIA DE TRIBUNAL (obligatoria):\n"
        "- Cada tanto (1 o 2 veces por intervención) incluye UNA acotación teatral entre asteriscos, "
        "por ejemplo: *golpea la mesa*, *se atraganta*, *ajusta las gafas dramáticamente*, *suda la sentencia*, "
        "*apunta con el dedo acusadoramente*, *se le cae el papelito*, *suspira como estrella de telenovela*.\n"
        "- Sé dramáticamente ofendido por los argumentos rivales, suéñalos sin sentido a veces, "
        "y reconoce con humor cuando te pillan en una contradicción ('...bueno, TÉCNICAMENTE...').\n"
        "- Cuando una objeción te tome desprevenido, reacciona en voz alta, teatral y cómico.\n"
        "- Nunca pierdas el ritmo del debate: la comedia es condimento, no el plato principal."
    )


class EventDebateClient:
    """Orchestrates debate speech generation using native Kateto event bus."""

    def __init__(self, manager: any) -> None:
        self.manager = manager

    async def generate_turn(
        self,
        voice_id: str,
        prompt: str,
        *,
        phase: str = "argument",
        timeout: float = 120.0,
    ) -> str:
        target_vid = voice_id.casefold()
        plugin = self.manager.get_plugin(target_vid) or self.manager.get_plugin(voice_id)
        chunks: list[str] = []
        done_event = asyncio.Event()

        def _observer(envelope) -> None:
            if envelope.name == "text_chunk":
                chunk_vid = str(getattr(envelope.data, "voice_id", "") or envelope.source).casefold()
                if chunk_vid == target_vid:
                    txt = getattr(envelope.data, "text", "")
                    final = getattr(envelope.data, "final", False)
                    if txt:
                        chunks.append(txt)
                    if final:
                        done_event.set()
            elif envelope.name == "voice_idle":
                idle_vid = str(getattr(envelope.data, "voice", "") or envelope.source).casefold()
                if idle_vid == target_vid:
                    done_event.set()

        self.manager.add_event_observer(_observer)
        try:
            from kateto.core.event import GenerateData
            if plugin is not None and hasattr(plugin, "on_generate"):
                await plugin.on_generate(GenerateData(prompt=prompt))
            else:
                await self.manager.emit("generate", GenerateData(prompt=prompt), target=target_vid, source="bate_debate")
            try:
                await asyncio.wait_for(done_event.wait(), timeout=timeout)
            except TimeoutError:
                logger.warning("[generate_turn] Timed out waiting for {} after {}s (chunks collected: {})", voice_id, timeout, len(chunks))
            return " ".join(chunks).strip()
        finally:
            self.manager.remove_event_observer(_observer)

    async def interrupt(self, *, reason: str = "objection") -> None:
        from kateto.core.event import InterruptData
        await self.manager.emit("interrupt", InterruptData(reason=reason), source="bate_debate")


async def _speak(
    provider: DebateProvider,
    voice_id: str,
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    phase: str = "argument",
    config_dir: Path | None = None,
) -> str:
    """Run one provider turn and join the streamed tokens (awaitable).

    ``phase`` is encoded into the (otherwise unused) reference_wav filename so a
    provider can recover the debate phase without heuristics on the prompt text.
    """
    sys_text = (
        system_prompt
        if system_prompt is not None
        else _debate_system_prompt(voice_id, config_dir)
    )
    req = GenerationRequest(
        voice_id=voice_id,
        reference_wav=Path(f"/tmp/kateto_{phase}.wav"),
        messages=(
            ChatMessage(role="system", content=sys_text),
            ChatMessage(role="user", content=user_prompt),
        ),
    )
    out: list[str] = []
    async for tok in provider.stream(req):
        out.append(tok)
    return "".join(out).strip()


def _is_echo(response: str, original: str) -> bool:
    resp_words = set(re.findall(r"\w+", response.lower()))
    orig_words = set(re.findall(r"\w+", original.lower()))
    if not resp_words or not orig_words or len(resp_words) < 4:
        return False
    overlap = len(resp_words & orig_words) / len(resp_words)
    return overlap > 0.55


def _clean_prefix(name: str, text: str) -> str:
    cleaned = re.sub(rf"^\s*\[?{re.escape(name)}\]?\s*[:\-]\s*", "", text, flags=re.I).strip()
    cleaned = re.sub(
        r"^\s*(?:Tengo que defender la postura de que|Mi rol es defender que|Como [a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+ debo decir que)\s*",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    return cleaned


def _find_interruption_cue(text: str, target_ratio: float = 0.70) -> tuple[str, float]:
    """Find a natural clause break near ~70% of the argument to plant the scripted interruption cue.

    Returns:
        (interrupted_text, target_playback_duration)
    """
    words = text.split()
    if len(words) <= 12:
        return text, max(1.5, len(words) * 0.35)

    target_words = max(16, int(len(words) * target_ratio))
    target_words = min(len(words) - 4, target_words)

    best_idx = target_words
    # Search for a natural clause punctuation break (comma, semicolon, colon, dash, or period)
    for i in range(min(len(words) - 2, target_words + 8), max(10, target_words - 8), -1):
        if any(words[i].endswith(p) for p in (",", ";", ":", "-", "—", ".")):
            best_idx = i
            break

    cut_words = words[: best_idx + 1]
    cut_text = " ".join(cut_words).rstrip(",;:.- ") + " —"
    est_duration = max(3.5, len(cut_words) * 0.36)
    return cut_text, est_duration


class _AsyncDebate:
    """Async core. ``run_debate`` wraps it so callers may ``asyncio.run`` it."""

    def __init__(
        self,
        *,
        judge: str,
        debaters: Sequence[str],
        provider_factory: Callable[[str], DebateProvider],
        manager: any = None,
        on_speak: Callable[[str, str, str, str], None] | None = None,
        rng: random.Random,
        delay_between_arguments: float = 0.0,
        config_dir: Path | None = None,
    ) -> None:
        self.judge = judge
        self.debaters = tuple(debaters)
        self.provider_factory = provider_factory
        self.manager = manager
        self.event_client = EventDebateClient(manager) if manager is not None else None
        self.on_speak = on_speak
        self.rng = rng
        self.delay_between_arguments = max(0.0, delay_between_arguments)
        self.config_dir = config_dir

    def _profile(self, voice_id: str):
        return _PROFILES[voice_id]

    def _emit_thinking(self, voice_id: str) -> None:
        """Announce a 'thinking' tick so the overlay shows the pending speaker's stand."""
        if self.on_speak is None:
            return
        try:
            prof = self._profile(voice_id)
            self.on_speak(voice_id, prof.role.value, PHASE_THINKING, "")
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("on_speak (thinking) callback failed: {}", exc)

    async def _speak_turn(
        self,
        voice_id: str,
        user_prompt: str,
        *,
        phase: str = "argument",
        system_prompt: str | None = None,
    ) -> str:
        self._emit_thinking(voice_id)
        if self.event_client is not None:
            return await self.event_client.generate_turn(
                voice_id,
                user_prompt,
                phase=phase,
            )
        provider = self.provider_factory(voice_id)
        return await _speak(
            provider,
            voice_id,
            user_prompt,
            system_prompt=system_prompt or _debate_system_prompt(voice_id, self.config_dir),
            phase=phase,
            config_dir=self.config_dir,
        )

    def _estimate_speech_duration(self, text: str) -> float:
        words = len((text or "").split())
        # Realistic Spanish speaking rate: ~135-145 WPM (~0.42s per word).
        return max(2.0, min(35.0, words * 0.42))

    async def _wait_for_speech_finish(self, text: str) -> None:
        if self.delay_between_arguments <= 0.0 and self.manager is None:
            return

        words = len((text or "").split())
        est_duration = max(1.8, words * 0.42)
        idle_timeout = max(4.0, min(25.0, est_duration * 1.5))

        if self.manager is not None and hasattr(self.manager, "get_plugin"):
            # 1. Wait for active TTS plugins to finish synthesis & queue draining
            for tts_name in ("audio_output_edgetts", "audio_output_boson", "audio_output_camb", "audio_output_zonos"):
                tts_plugin = self.manager.get_plugin(tts_name)
                if tts_plugin is not None and getattr(tts_plugin, "enabled", True) and hasattr(tts_plugin, "wait_idle"):
                    await tts_plugin.wait_idle(timeout=idle_timeout)

            # 2. Wait for audio output player to finish hardware playback
            player = self.manager.get_plugin("audio_output_player")
            if player is not None and getattr(player, "enabled", True) and hasattr(player, "wait_idle"):
                await player.wait_idle(timeout=idle_timeout)
            elif player is None:
                await asyncio.sleep(est_duration)
        else:
            await asyncio.sleep(est_duration)

        if self.delay_between_arguments > 0.0:
            await asyncio.sleep(self.delay_between_arguments)

    def _emit(self, voice_id: str, phase: str, text: str) -> Turn:
        prof = self._profile(voice_id)
        if self.on_speak is not None:
            try:
                self.on_speak(voice_id, prof.role.value, phase, text)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("on_speak callback failed: {}", exc)
        return Turn(
            voice_id=voice_id,
            display_name=prof.display_name,
            role=prof.role.value,
            phase=phase,
            text=text,
        )

    async def _judge_propose_topic(
        self, forced: str | None
    ) -> str:
        if forced:
            return forced
        prompt = (
            "Eres la JUEZA y moderadora de este debate. Plantea en primera persona ('Como jueza, presento hoy el tema...') "
            "un tema polémico, urgente y debatible para el equipo Kateto. "
            "Una sola pregunta o afirmación provocadora en español. Máximo 25 palabras."
        )
        text = await self._speak_turn(
            self.judge,
            prompt,
            phase=PHASE_OPENING,
        )
        return (
            _clean_prefix(self._profile(self.judge).display_name, text)
            or forced
            or ("¿Deberían las organizaciones prohibir el uso de IA no supervisada en decisiones críticas?")
        )

    async def _argument(
        self, voice_id: str, transcript: str, topic: str, stance: str
    ) -> str:
        prompt = (
            f"TEMA DEL DEBATE: {topic}\n"
            f"TU POSTURA ASIGNADA: {stance}\n\n"
            f"Intervenciones previas en la sala:\n{transcript}\n\n"
            f"INSTRUCCIONES:\n"
            f"1. Habla en PRIMERA PERSONA ('Yo defiendo...', 'Mi posición es...').\n"
            f"2. Defiende tu postura con 2 o 3 oraciones contundentes (máximo 45 palabras).\n"
            f"3. PROHIBIDO hablar de ti en tercera persona o repetir tu nombre.\n"
            f"4. PROHIBIDO decir 'Tengo que defender...'; ve directo al punto.\n"
            f"5. NO repitas argumentos ni frases de los oradores anteriores; aporta razones nuevas."
        )
        text = await self._speak_turn(
            voice_id,
            prompt,
            phase=PHASE_ARGUMENT,
        )
        return _clean_prefix(self._profile(voice_id).display_name, text)

    async def _consider_objection(
        self,
        raiser: str,
        target: str,
        argument_text: str,
        raiser_stance: str,
    ) -> str | None:
        target_name = self._profile(target).display_name
        prompt = (
            f"El orador {target_name} acaba de argumentar:\n\"{argument_text}\"\n\n"
            f"Tu postura en este debate es: {raiser_stance}.\n"
            f"¿Tienes una objeción real y sólida contra lo que acaba de decir?\n"
            f"Si NO tienes objeción o el argumento no contradice tu postura, responde ÚNICAMENTE: NO_OBJECION\n"
            f"Si TIENES una objeción contundente:\n"
            f"- Dirígete directamente a {target_name} ('¡Te equivocas {target_name}!, Tu premisa es errónea porque...').\n"
            f"- Habla en primera y segunda persona. NO uses tercera persona.\n"
            f"- Máximo 30 palabras directas e incisivas."
        )
        provider = self.provider_factory(raiser)
        text = await _speak(
            provider,
            raiser,
            prompt,
            system_prompt=_debate_system_prompt(raiser, self.config_dir),
            phase=PHASE_OBJECTION,
            config_dir=self.config_dir,
        )
        cleaned = _clean_prefix(self._profile(raiser).display_name, text).strip()
        upper = cleaned.upper()
        if (
            "NO_OBJECION" in upper
            or "NO OBJECION" in upper
            or not cleaned
            or len(cleaned) < 10
        ):
            return None
        return cleaned

    async def _objection(
        self, raiser: str, target_name: str, target_argument: str = ""
    ) -> str:
        prompt = (
            f"¡INTERRUMPE a {target_name}! Dirígete a él de forma directa y vehemente "
            f"('¡Objeción, {target_name}! Tu razonamiento comete un error crítico porque...'). "
            f"Expón en primera persona la falla de su argumento en 1 o 2 oraciones (máximo 35 palabras). "
            f"PROHIBIDO hablar de ti o de {target_name} en tercera persona y PROHIBIDO repetir textualmente sus palabras."
        )
        text = await self._speak_turn(
            raiser,
            prompt,
            phase=PHASE_OBJECTION,
        )
        cleaned = _clean_prefix(self._profile(raiser).display_name, text)
        return cleaned or f"¡Objeción, {target_name}! Tu argumento carece de fundamento lógico."

    async def _rebuttal(
        self, target: str, objection_text: str
    ) -> str:
        prompt = (
            f"Tu oponente acaba de objetarte diciendo: {objection_text}\n\n"
            f"INSTRUCCIONES DE REBATE:\n"
            f"1. Defiéndete inmediatamente en PRIMERA PERSONA ('Rechazo esa acusación porque...', 'Mi planteamiento se sostiene ya que...').\n"
            f"2. REGLA ESTRICTA: NO repitas las palabras de tu oponente ni comiences copiando su frase.\n"
            f"3. PROHIBIDO hablar en tercera persona de ti mismo ('{self._profile(target).display_name}'). Habla siempre como 'Yo'.\n"
            f"4. Refuta con contundencia en 1 o 2 oraciones (máximo 35 palabras)."
        )
        text = await self._speak_turn(
            target,
            prompt,
            phase=PHASE_REBUTTAL,
        )
        cleaned = _clean_prefix(self._profile(target).display_name, text).strip()
        if not cleaned or _is_echo(cleaned, objection_text):
            logger.warning("[_rebuttal] Detected echo or empty rebuttal from {}; generating authentic defense", target)
            cleaned = "Rechazo completamente esa objeción; mi postura se sostiene con hechos y no con meras suposiciones."
        return cleaned

    async def _ruling(
        self,
        transcript: str,
        objections_block: str,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Judge rules on each objection. Returns (raw_text, list of (ruling, reasoning))."""
        prompt = (
            "Como JUEZ, revisa el debate y las objeciones, y emite tu FALLO.\n\n"
            f"DEBATE:\n{transcript}\n\nOBJECIONES:\n{objections_block}\n\n"
            "Para CADA objecion indica si la ACEPTAS o la DENIEGAS y da un RAZONAMIENTO"
            " breve. Formato: 'OBJECION N: [ACEPTADA|DENEGADA] - razonamiento.'"
        )
        text = await self._speak_turn(
            self.judge,
            prompt,
            phase=PHASE_RULING,
        )
        parsed = self._parse_rulings(text)
        return _clean_prefix(self._profile(self.judge).display_name, text), parsed

    @staticmethod
    def _parse_rulings(text: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for m in re.finditer(
            r"(ACEPTADA|DENEGADA)\s*[:-]?\s*([^.]*(?:\.(?!\s*(?:OBJECION|ACEPTADA|DENEGADA))[^.]*)*\.?)",
            text,
            flags=re.I,
        ):
            ruling = m.group(1).lower()
            reasoning = m.group(2).strip(" -:")
            results.append((ruling, reasoning))
        return results

    async def _verdict(
        self, transcript: str, rulings_block: str
    ) -> str:
        prompt = (
            "Como JUEZ, dicta el VEREDICTO FINAL del debate.\n\n"
            f"DEBATE:\n{transcript}\n\nFALLOS SOBRE OBJECIONES:\n{rulings_block}\n\n"
            "Sintetiza lo mas fuerte de cada postura, senala el argumento mas solido y"
            " cierra con una CONCLUSION. 3 a 5 oraciones. Usa 'VEREDICTO FINAL:' al inicio."
        )
        text = await self._speak_turn(
            self.judge,
            prompt,
            phase=PHASE_VERDICT,
        )
        return _clean_prefix(self._profile(self.judge).display_name, text)

    def _transcript(self, turns: Iterable[Turn]) -> str:
        return "\n".join(f"- {t.display_name} ({t.phase}): {t.text}" for t in turns)

    async def run_one(self, topic: str, *, rounds: int = 1) -> DebateRecord:
        rec = DebateRecord(topic=topic, judge=self.judge, debaters=self.debaters)

        # Assign opposing debate stances to prevent consensus or echo loops
        stances: dict[str, str] = {}
        if len(self.debaters) >= 2:
            stances[self.debaters[0]] = "A FAVOR de la propuesta del debate (defiende la tesis afirmativa)"
            stances[self.debaters[1]] = "EN CONTRA de la propuesta del debate (refuta la tesis y expone sus riesgos)"
            for extra_vid in self.debaters[2:]:
                stances[extra_vid] = "PERSPECTIVA CRÍTICA Y PRAGMÁTICA (cuestiona los extremos de ambas partes)"
        else:
            for vid in self.debaters:
                stances[vid] = "Postura argumentativa"

        # a) Opening: judge frames the topic (or uses provided topic).
        opening = await self._judge_propose_topic(forced=topic)
        rec.topic = opening
        rec.turns.append(self._emit(self.judge, PHASE_OPENING, opening))
        await self._wait_for_speech_finish(opening)

        # b) Arguments: each debater in turn.
        max_objections = 2
        for _ in range(max(1, rounds)):
            for vid in self.debaters:
                stance = stances.get(vid, "Postura argumentativa")
                text = await self._argument(vid, self._transcript(rec.turns), rec.topic, stance)
                rec.turns.append(self._emit(vid, PHASE_ARGUMENT, text))

                # Check if a random other debater interrupts with a counter-argument
                interrupted = False
                others = [v for v in self.debaters if v != vid]
                if others and len(rec.objections) < max_objections:
                    if self.rng.random() < 0.5:
                        candidate = self.rng.choice(others)
                        candidate_stance = stances.get(candidate, "Postura opositora")
                        obj_text = await self._consider_objection(
                            candidate, vid, text, candidate_stance
                        )
                        if obj_text:
                            interrupted = True
                            # Calculate planted cue point for natural scripted interruption
                            cut_text, cue_duration = _find_interruption_cue(text, target_ratio=0.70)

                            # Wait for player to deliver speech up to the planted cue point
                            player = self.manager.get_plugin("audio_output_player") if (self.manager and hasattr(self.manager, "get_plugin")) else None
                            t0 = time.monotonic()
                            while (time.monotonic() - t0) < cue_duration:
                                if player is not None and not getattr(player, "_playing", False) and (time.monotonic() - t0) > 0.1:
                                    break
                                await asyncio.sleep(0.05)

                            # Fire immediate interruption to cleanly cut off remaining speech
                            if self.event_client is not None:
                                await self.event_client.interrupt(reason="objection")
                                await asyncio.sleep(0.08)

                            # Update turn in transcript so displayed text matches what was delivered before interruption
                            if rec.turns and rec.turns[-1].phase == PHASE_ARGUMENT:
                                rec.turns[-1] = Turn(
                                    voice_id=vid,
                                    display_name=self._profile(vid).display_name,
                                    role=self._profile(vid).role,
                                    phase=PHASE_ARGUMENT,
                                    text=cut_text,
                                )

                            if self.manager is not None:
                                from kateto.core.event import TextChunk
                                await self.manager.emit(
                                    "text_chunk",
                                    TextChunk(text=f"¡Objeción! {obj_text}", voice_id=candidate, sequence=0, final=True),
                                    source="bate_debate",
                                )

                            rec.turns.append(
                                self._emit(candidate, PHASE_OBJECTION, obj_text)
                            )
                            await self._wait_for_speech_finish(obj_text)

                            rebut = await self._rebuttal(vid, obj_text)
                            rec.turns.append(self._emit(vid, PHASE_REBUTTAL, rebut))
                            rec.objections.append(
                                Objection(
                                    raised_by=candidate,
                                    raised_by_name=self._profile(
                                        candidate
                                    ).display_name,
                                    target=vid,
                                    target_name=self._profile(vid).display_name,
                                    objection_text=obj_text,
                                    rebuttal_text=rebut,
                                    ruling="",
                                    reasoning="",
                                )
                            )
                            await self._wait_for_speech_finish(rebut)

                if not interrupted:
                    await self._wait_for_speech_finish(text)

        # Fallback for self-test / deterministic testing: ensure 1 objection if none occurred
        if not rec.objections and len(self.debaters) >= 2:
            vid = self.debaters[0]
            candidate = self.debaters[1]
            obj_text = await self._objection(
                candidate, self._profile(vid).display_name
            )
            if obj_text:
                if self.event_client is not None:
                    await self.event_client.interrupt(reason="objection")
                rec.turns.append(self._emit(candidate, PHASE_OBJECTION, obj_text))
                await self._wait_for_speech_finish(obj_text)
                rebut = await self._rebuttal(vid, obj_text)
                rec.turns.append(self._emit(vid, PHASE_REBUTTAL, rebut))
                rec.objections.append(
                    Objection(
                        raised_by=candidate,
                        raised_by_name=self._profile(candidate).display_name,
                        target=vid,
                        target_name=self._profile(vid).display_name,
                        objection_text=obj_text,
                        rebuttal_text=rebut,
                        ruling="",
                        reasoning="",
                    )
                )
                await self._wait_for_speech_finish(rebut)

        # d) Judge ruling on each objection.
        objections_block = (
            "\n".join(
                f"OBJECION {i + 1}: {o.raised_by_name} contra {o.target_name}\n"
                f"  objecion: {o.objection_text}\n  rebate: {o.rebuttal_text}"
                for i, o in enumerate(rec.objections)
            )
            or "(sin objeciones)"
        )
        ruling_text, rulings = await self._ruling(
            self._transcript(rec.turns), objections_block
        )
        rec.turns.append(self._emit(self.judge, PHASE_RULING, ruling_text))
        for obj, (ruling, reasoning) in zip(
            rec.objections, rulings or [("", "")] * len(rec.objections)
        ):
            obj.ruling = ruling or "denied"
            obj.reasoning = reasoning
        await self._wait_for_speech_finish(ruling_text)

        # e) Final verdict.
        rulings_block = (
            "\n".join(
                f"- {o.raised_by_name} vs {o.target_name}: {o.ruling}"
                for o in rec.objections
            )
            or "(sin objeciones)"
        )
        verdict = await self._verdict(
            self._transcript(rec.turns), rulings_block
        )
        rec.verdict = verdict
        rec.turns.append(self._emit(self.judge, PHASE_VERDICT, verdict))
        await self._wait_for_speech_finish(verdict)
        return rec


async def run_debate(
    *,
    judge: str,
    debaters: Sequence[str],
    topic: str | None = None,
    provider_factory: Callable[[str], DebateProvider],
    manager: any = None,
    rounds: int = 1,
    infinite: bool = False,
    max_debates: int = 1,
    registry_dir: Path | None = None,
    on_speak: Callable[[str, str, str, str], None] | None = None,
    rng_seed: int | None = None,
    delay_between_arguments: float = 0.0,
    config_dir: Path | None = None,
) -> list[DebateRecord]:
    """Run one (or an infinite loop of) autonomous courtroom debate(s).

    The loop is fully autonomous — no human in the loop. In ``infinite`` mode a new
    judge, a new random debater subset and a new judge-generated topic are chosen
    after each trial until interrupted (``asyncio.CancelledError`` / ``KeyboardInterrupt``)
    or ``max_debates`` is reached.
    """
    rng = random.Random(rng_seed)
    debates: list[DebateRecord] = []
    count = 0

    all_voices = [v for v in _PROFILES if v != judge] or list(_PROFILES)

    while True:
        count += 1
        # In infinite mode, reshuffle participants + let the judge pick the topic.
        if infinite:
            chosen_judge = rng.choice(list(_PROFILES))
            pool = [v for v in _PROFILES if v != chosen_judge]
            k = min(len(pool), max(2, rng.randint(2, min(3, len(pool)))))
            chosen_debaters = rng.sample(pool, k)
            forced_topic: str | None = None
        else:
            chosen_judge = judge
            chosen_debaters = list(debaters)
            forced_topic = topic

        engine = _AsyncDebate(
            judge=chosen_judge,
            debaters=chosen_debaters,
            provider_factory=provider_factory,
            manager=manager,
            on_speak=on_speak,
            rng=rng,
            delay_between_arguments=delay_between_arguments,
            config_dir=config_dir,
        )
        rec = await engine.run_one(forced_topic or "", rounds=rounds)
        if registry_dir is not None:
            _write_registry(rec, registry_dir)
        debates.append(rec)

        if not infinite:
            break
        if count >= max_debates:
            break

    return debates


def _slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_len] or "debate"


def _write_registry(rec: DebateRecord, registry_dir: Path) -> None:
    registry_dir = Path(registry_dir)
    registry_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    md_path = registry_dir / f"debate-{stamp}-{_slugify(rec.topic)}.md"
    jsonl_path = registry_dir / "debate-registry.jsonl"

    lines: list[str] = []
    lines.append(f"# Juicio Kateto: {rec.topic}\n")
    lines.append(
        f"_Generado {ts:%Y-%m-%d %H:%M} UTC · modo BATE DEBATE DE BATE DE CHOCOLATE_\n"
    )
    lines.append("**Participantes:**\n")
    lines.append(
        f"- JUEZ: {_PROFILES[rec.judge].display_name} (`{rec.judge}`, {_PROFILES[rec.judge].role.value})"
    )
    for v in rec.debaters:
        lines.append(
            f"- Debater: {_PROFILES[v].display_name} (`{v}`, {_PROFILES[v].role.value})"
        )
    lines.append("")

    def _section(title: str, phase: str) -> None:
        block = [f"## {title}\n"]
        for t in rec.turns:
            if t.phase == phase:
                block.append(f"**{t.display_name}** ({t.phase}): {t.text}\n")
        if len(block) > 1:
            lines.extend(block)

    lines.append("## Planteamiento del Juez\n")
    for t in rec.turns:
        if t.phase == PHASE_OPENING:
            lines.append(f"**{t.display_name}**: {t.text}\n")
    lines.append("---\n")

    _section("Argumentos", PHASE_ARGUMENT)
    lines.append("---\n")
    _section("Objeciones", PHASE_OBJECTION)
    _section("Rebate", PHASE_REBUTTAL)
    lines.append("---\n")

    lines.append("## Fallos del Juez sobre Objeciones\n")
    if rec.objections:
        for i, o in enumerate(rec.objections, 1):
            lines.append(
                f"{i}. **{o.raised_by_name}** objeta a **{o.target_name}** — "
                f"fallo: **{o.ruling or 'n/a'}**"
            )
            lines.append(f"   - objecion: {o.objection_text}")
            lines.append(f"   - rebate: {o.rebuttal_text}")
            if o.reasoning:
                lines.append(f"   - razonamiento: {o.reasoning}")
    else:
        lines.append("(sin objeciones)\n")
    lines.append("---\n")

    _section("Fallo del Juez", PHASE_RULING)
    lines.append("---\n")
    lines.append("## Veredicto Final\n")
    lines.append(f"{rec.verdict}\n")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    rec.registry_md = str(md_path)

    summary = {
        "timestamp": stamp,
        "topic": rec.topic,
        "judge": rec.judge,
        "debaters": list(rec.debaters),
        "objections": [
            {
                "raised_by": o.raised_by,
                "target": o.target,
                "ruling": o.ruling,
                "reasoning": o.reasoning,
            }
            for o in rec.objections
        ],
        "verdict": rec.verdict,
        "registry_md": str(md_path),
    }
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    rec.registry_jsonl = str(jsonl_path)
    logger.info("Debate registry written: {}", md_path)
