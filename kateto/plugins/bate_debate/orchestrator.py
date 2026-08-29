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

import json
import random
import re
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
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _strip_constraint(system_prompt: str) -> str:
    if system_prompt.endswith(_VOICE_CONSTRAINT):
        return system_prompt[: -len(_VOICE_CONSTRAINT)]
    return system_prompt


def _debate_system_prompt(voice_id: str) -> str:
    """Real voice system prompt trimmed + switched to written-discussion style."""
    base = _strip_constraint(_PROFILES[voice_id].system_prompt)
    return (
        base + " Estas en un JUICIO ESCRITO entre las voces del equipo Kateto, no"
        " hablando por voz. Responde en ESPANOL, parrafos libres, manteniendo tu rol."
        " Sin markdown, sin listas, sin encabezados."
    )


async def _speak(
    provider: DebateProvider,
    voice_id: str,
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    phase: str = "argument",
) -> str:
    """Run one provider turn and join the streamed tokens (awaitable).

    ``phase`` is encoded into the (otherwise unused) reference_wav filename so a
    provider can recover the debate phase without heuristics on the prompt text.
    """
    sys_text = system_prompt if system_prompt is not None else _debate_system_prompt(voice_id)
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


def _clean_prefix(name: str, text: str) -> str:
    return re.sub(rf"^\s*{re.escape(name)}\s*[:\-]\s*", "", text, flags=re.I).strip()


class _AsyncDebate:
    """Async core. ``run_debate`` wraps it so callers may ``asyncio.run`` it."""

    def __init__(
        self,
        *,
        judge: str,
        debaters: Sequence[str],
        provider_factory: Callable[[str], DebateProvider],
        on_speak: Callable[[str, str, str, str], None] | None = None,
        rng: random.Random,
    ) -> None:
        self.judge = judge
        self.debaters = tuple(debaters)
        self.provider_factory = provider_factory
        self.on_speak = on_speak
        self.rng = rng

    def _profile(self, voice_id: str):
        return _PROFILES[voice_id]

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

    async def _judge_propose_topic(self, provider: DebateProvider, forced: str | None) -> str:
        if forced:
            return forced
        prompt = (
            "Eres el JUEZ de este debate. PROPON un tema polémico, concreto y"
            " debatible para que las voces del equipo Kateto discutan. Una sola"
            " pregunta o afirmacion provocadora, en ESPANOL."
        )
        text = await _speak(provider, self.judge, prompt, system_prompt=_debate_system_prompt(self.judge), phase=PHASE_OPENING)
        return _clean_prefix(self._profile(self.judge).display_name, text) or forced or (
            "¿Vale la pena construir un sistema multi-agente como Kateto?"
        )

    async def _argument(self, provider: DebateProvider, voice_id: str, transcript: str) -> str:
        prompt = (
            f"La moderadora/jueza planteo el tema. El transcript hasta ahora es:\n{transcript}\n\n"
            f"Da tu ARGUMENTO como {self._profile(voice_id).display_name}"
            f" ({self._profile(voice_id).role.value}). Defiende tu postura, 2 a 4 oraciones."
        )
        text = await _speak(provider, voice_id, prompt, system_prompt=_debate_system_prompt(voice_id), phase=PHASE_ARGUMENT)
        return _clean_prefix(self._profile(voice_id).display_name, text)

    async def _objection(self, provider: DebateProvider, raiser: str, target_name: str) -> str:
        template = (
            f"INTERRUMPISTE A {target_name} PARA REALIZAR UNA OBJECION,"
            f" DEMUESTRA QUE {target_name} REALIZO UN GRAVE ERROR EN SU ARGUMENTO"
        )
        text = await _speak(provider, raiser, template, system_prompt=_debate_system_prompt(raiser), phase=PHASE_OBJECTION)
        return _clean_prefix(self._profile(raiser).display_name, text) or template

    async def _rebuttal(self, provider: DebateProvider, target: str, objection_text: str) -> str:
        prompt = (
            f"Se ha presentado esta OBJECION contra ti:\n\"{objection_text}\"\n\n"
            f"REBATE la objecion como {self._profile(target).display_name}, defiende tu argumento."
        )
        text = await _speak(provider, target, prompt, system_prompt=_debate_system_prompt(target), phase=PHASE_REBUTTAL)
        return _clean_prefix(self._profile(target).display_name, text) or "[sin rebatir]"

    async def _ruling(
        self,
        provider: DebateProvider,
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
        text = await _speak(provider, self.judge, prompt, system_prompt=_debate_system_prompt(self.judge), phase=PHASE_RULING)
        parsed = self._parse_rulings(text)
        return _clean_prefix(self._profile(self.judge).display_name, text), parsed

    @staticmethod
    def _parse_rulings(text: str) -> list[tuple[str, str]]:
        # The mock streams token-by-token and reassembles with spaces, so rulings
        # may arrive on one logical line. Scan the whole text for every
        # "ACEPTADA/DENEGADA" occurrence and capture the reasoning that follows.
        results: list[tuple[str, str]] = []
        for m in re.finditer(r"(ACEPTADA|DENEGADA)\s*[:-]?\s*([^.]*(?:\.(?!\s*(?:OBJECION|ACEPTADA|DENEGADA))[^.]*)*\.?)", text, flags=re.I):
            ruling = m.group(1).lower()
            reasoning = m.group(2).strip(" -:")
            results.append((ruling, reasoning))
        return results

    async def _verdict(self, provider: DebateProvider, transcript: str, rulings_block: str) -> str:
        prompt = (
            "Como JUEZ, dicta el VEREDICTO FINAL del debate.\n\n"
            f"DEBATE:\n{transcript}\n\nFALLOS SOBRE OBJECIONES:\n{rulings_block}\n\n"
            "Sintetiza lo mas fuerte de cada postura, senala el argumento mas solido y"
            " cierra con una CONCLUSION. 3 a 5 oraciones. Usa 'VEREDICTO FINAL:' al inicio."
        )
        text = await _speak(provider, self.judge, prompt, system_prompt=_debate_system_prompt(self.judge), phase=PHASE_VERDICT)
        return _clean_prefix(self._profile(self.judge).display_name, text)

    def _transcript(self, turns: Iterable[Turn]) -> str:
        return "\n".join(f"- {t.display_name} ({t.phase}): {t.text}" for t in turns)

    async def run_one(self, topic: str, *, rounds: int = 1) -> DebateRecord:
        judge_provider = self.provider_factory(self.judge)
        rec = DebateRecord(topic=topic, judge=self.judge, debaters=self.debaters)

        # a) Opening: judge frames the topic (or uses provided topic).
        #    When topic is externally provided we still record an opening turn.
        opening = await self._judge_propose_topic(judge_provider, forced=topic)
        rec.topic = opening
        rec.turns.append(self._emit(self.judge, PHASE_OPENING, opening))

        # b) Arguments: each debater in turn, seeing the accumulated transcript.
        for _ in range(max(1, rounds)):
            for vid in self.debaters:
                provider = self.provider_factory(vid)
                text = await self._argument(provider, vid, self._transcript(rec.turns))
                rec.turns.append(self._emit(vid, PHASE_ARGUMENT, text))

        # c) Objection round: each debater objects a random other debater; target rebuts.
        for vid in self.debaters:
            others = [v for v in self.debaters if v != vid]
            if not others:
                continue
            target = self.rng.choice(others)
            provider = self.provider_factory(vid)
            obj_text = await self._objection(provider, vid, self._profile(target).display_name)
            rec.turns.append(self._emit(vid, PHASE_OBJECTION, obj_text))
            tprovider = self.provider_factory(target)
            rebut = await self._rebuttal(tprovider, target, obj_text)
            rec.turns.append(self._emit(target, PHASE_REBUTTAL, rebut))
            rec.objections.append(
                Objection(
                    raised_by=vid,
                    raised_by_name=self._profile(vid).display_name,
                    target=target,
                    target_name=self._profile(target).display_name,
                    objection_text=obj_text,
                    rebuttal_text=rebut,
                    ruling="",
                    reasoning="",
                )
            )

        # d) Judge ruling on each objection.
        objections_block = "\n".join(
            f"OBJECION {i+1}: {o.raised_by_name} contra {o.target_name}\n"
            f"  objecion: {o.objection_text}\n  rebate: {o.rebuttal_text}"
            for i, o in enumerate(rec.objections)
        ) or "(sin objeciones)"
        ruling_text, rulings = await self._ruling(judge_provider, self._transcript(rec.turns), objections_block)
        rec.turns.append(self._emit(self.judge, PHASE_RULING, ruling_text))
        for obj, (ruling, reasoning) in zip(rec.objections, rulings or [("", "")] * len(rec.objections)):
            obj.ruling = ruling or "denied"
            obj.reasoning = reasoning

        # e) Final verdict.
        rulings_block = "\n".join(
            f"- {o.raised_by_name} vs {o.target_name}: {o.ruling}" for o in rec.objections
        ) or "(sin objeciones)"
        verdict = await self._verdict(judge_provider, self._transcript(rec.turns), rulings_block)
        rec.verdict = verdict
        rec.turns.append(self._emit(self.judge, PHASE_VERDICT, verdict))
        return rec


async def run_debate(
    *,
    judge: str,
    debaters: Sequence[str],
    topic: str | None = None,
    provider_factory: Callable[[str], DebateProvider],
    rounds: int = 1,
    infinite: bool = False,
    max_debates: int = 1,
    registry_dir: Path | None = None,
    on_speak: Callable[[str, str, str, str], None] | None = None,
    rng_seed: int | None = None,
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
            on_speak=on_speak,
            rng=rng,
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
    lines.append(f"_Generado {ts:%Y-%m-%d %H:%M} UTC · modo BATE DEBATE DE BATE DE CHOCOLATE_\n")
    lines.append("**Participantes:**\n")
    lines.append(f"- JUEZ: {_PROFILES[rec.judge].display_name} (`{rec.judge}`, {_PROFILES[rec.judge].role.value})")
    for v in rec.debaters:
        lines.append(f"- Debater: {_PROFILES[v].display_name} (`{v}`, {_PROFILES[v].role.value})")
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
            lines.append(f"{i}. **{o.raised_by_name}** objeta a **{o.target_name}** — "
                         f"fallo: **{o.ruling or 'n/a'}**")
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
