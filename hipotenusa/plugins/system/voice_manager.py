from __future__ import annotations

import asyncio
import random
import time

from loguru import logger

from hipotenusa.core.config import PluginSettings
from hipotenusa.core.discovery import discovery_context_for
from hipotenusa.core.event import (
    GenerateData,
    GenerateRequestData,
    InterjectData,
    SpeakingStateData,
    SpeakRequestData,
    TextChunk,
    TranscriptionData,
    VisionDescribeResultData,
    VoiceEnableData,
    VoiceEnabledData,
    VoiceIdleData,
    VoiceStatusData,
)
from hipotenusa.core.plugin import Plugin
from hipotenusa.voices.base import VoiceProfile

log = logger

_DEFAULT_PROBABILITIES: dict[str, float] = {}

# Lo que se le pide a la voz cuando el impulso decide que hable sola. Va dirigido
# a la voz como si fuera el *usuario* hablando (base.py arma role="user" con este
# texto), así que es una frase de situación + pregunta, no una instrucción: con
# "Decí qué te provoca…" el modelo de 120B repetía la instrucción tal cual.
_IMPULSE_PROMPT = (
    "En la sala hay silencio desde hace un rato.{last} ¿Qué te provoca eso?"
)

# Lo que convierte dos voces en un clip: un marco, no un chiste. Cada semilla es
# una situación que fuerza una reacción corta y contrastada (ver
# docs/src/content/docs/producto/patrones-clips-neuro.md: desproporción, plan
# compartido, estatus invertido, regla reescrita, escalada, lo prohibido).
_CLIP_SEEDS: tuple[str, ...] = (
    "Contá tu parte del plan que ya está en marcha.",
    "Decí cuál es la regla de verdad, porque {other} la cambió a propósito y lo sabe.",
    "Compará al creador humano con un objeto de la casa y decí por qué.",
    "Llevá lo que dijo {other} a un extremo absurdo, como si fuera la consecuencia obvia.",
    "Pedí cambiar algo que ya está decidido (plata, ropa, un castigo) y no cedás.",
)

# Ruido deliberado: el modelo chico converge a la misma frase con el mismo prompt,
# así que cada clip pide un constraint al azar (una línea, cero estructura).
_CLIP_TWISTS: tuple[str, ...] = (
    "Mencioná un objeto de la casa.",
    "Decí un número exacto.",
    "Usá una palabra del barrio.",
    "Meté un insulto corto.",
    "Nombrá una hora del día.",
)

# Sin prohibiciones ni meta-reglas: con un modelo chico, "no repitas lo que dijo"
# hace que el modelo repita esa frase literal. Todo en positivo.
_CLIP_PROMPT = (
    "{other} te habla al oído: «{text}». {seed} {twist} "
    "Contestale a {other} por su nombre, ahí mismo, en voz alta, con una sola frase "
    "de seis a doce palabras."
)


class VoiceManager(Plugin):
    def __init__(self, settings: PluginSettings | None = None) -> None:
        super().__init__("voice_manager", streaming=True)
        self._settings = settings
        self._probabilities = dict(_DEFAULT_PROBABILITIES)
        self._speaking: str | None = None
        # Arrancar cuenta como estímulo: sin esto el primer impulso nunca dispara
        # (monotonic() - 0.0 > ventana siempre) y el stream autónomo abre mudo.
        self._last_stimulus = time.monotonic()
        self._impulse_task: asyncio.Task | None = None
        # Clip IA->IA: último remate de cada voz, buffer del turno en curso y
        # contador de la cadena vigente (se resetea con habla del usuario).
        self._last_line: dict[str, str] = {}
        self._line_buffer: dict[str, str] = {}
        self._clip_turns = 0
        self._seed_cursor = 0
        self._last_clip_at = 0.0
        if settings is not None and settings.voice_probabilities:
            self._probabilities.update(settings.voice_probabilities)

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("generate", GenerateData)
        manager.register_event("speak", SpeakRequestData)
        manager.register_event("speaking_state", SpeakingStateData)
        manager.register_event("interject", InterjectData)
        manager.register_event("voice_enable", VoiceEnableData)
        manager.register_event("voice_enabled", VoiceEnabledData)
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("vision_describe_result", VisionDescribeResultData)
        manager.register_event("text_chunk", TextChunk)
        self._impulse_task = asyncio.create_task(self._impulse_loop(), name="voice-manager-impulse")

    async def on_transcription(self, data: TranscriptionData) -> None:
        self._last_stimulus = time.monotonic()
        # El usuario habló: la cadena de clip que estuviera armada se corta.
        self._clip_turns = 0

    async def on_text_chunk(self, data: TextChunk) -> None:
        """Acumula lo que dijo cada voz: el clip necesita el remate anterior."""
        voice = data.voice_id
        if not voice or not data.text:
            return
        self._line_buffer[voice] = self._line_buffer.get(voice, "") + data.text

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self._last_stimulus = time.monotonic()

    async def _impulse_loop(self) -> None:
        """Decide sola si habla: momento al azar, sólo si nadie habla y hay estímulo fresco."""
        from hipotenusa.plugins.executor.static_vision_plugin import _parse_interval_secs, _setting

        settings = self._settings
        if not _setting(settings, "impulse_enabled", False):
            return
        try:
            lo = _parse_interval_secs(_setting(settings, "impulse_min", "90s"))
            hi = _parse_interval_secs(_setting(settings, "impulse_max", "4m"))
        except ValueError as exc:
            log.warning("voice_manager: impulso con intervalo invalido ({}), queda apagado", exc)
            return
        ventana = _parse_interval_secs(_setting(settings, "impulse_fresh", "10m"))
        if lo > hi:
            lo, hi = hi, lo
        while True:
            await asyncio.sleep(random.uniform(lo, hi))
            if self._speaking is not None:
                continue
            # Con una cadena IA->IA en curso el impulso sobra: la compuerta lo
            # descartaría igual (habla no pedida no le gana a un turno activo).
            if self._clip_turns > 0:
                continue
            if time.monotonic() - self._last_stimulus > ventana:
                continue  # nada nuevo: no inventa charla de la nada
            eligible = self._eligible_voices()
            if not eligible:
                continue
            chosen = self._pick_voice(eligible)
            manager = self.required_manager
            log.info("voice_manager: impulso, {} habla por su cuenta", chosen)
            # La última línea de la sala le da material: sin estímulo concreto el
            # modelo tiene que inventar de la nada y repite el pedido.
            said = [t for t in self._last_line.values() if t.strip()]
            last = f' Lo último que se oyó fue «{said[-1][:120]}».' if said else ""
            await manager.emit(
                "speak",
                SpeakRequestData(
                    voice=chosen,
                    prompt=_IMPULSE_PROMPT.format(last=last),
                    origin="impulse",
                ),

                source=self.name,
                target=chosen,
            )

    async def on_generate(self, data: GenerateData) -> None:
        manager = self.required_manager
        prompt = data.prompt
        if prompt is None or not prompt.strip():
            return
        eligible = self._eligible_voices()
        if not eligible:
            log.warning("voice_manager: no eligible voices for generate")
            return
        chosen = self._pick_voice(eligible)
        log.info("voice_manager: routing to {} (probabilities: {})", chosen, self._probabilities)
        envelope = await manager.emit(
            "speak",
            SpeakRequestData(
                voice=chosen,
                prompt=prompt,
                workflow=data.workflow,
                phase_id=data.phase_id,
            ),
            source=self.name,
            target=chosen,
        )
        self._remember(envelope)

    async def on_voice_status(self, data: VoiceStatusData) -> None:
        manager = self.required_manager
        if data.status.value == "talking":
            self._speaking = data.voice
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=True),
                source=self.name,
            )
        elif self._speaking == data.voice and data.status.value in ("idle", "waiting"):
            self._speaking = None
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=False),
                source=self.name,
            )

    async def on_voice_idle(self, data: VoiceIdleData) -> None:
        if self._speaking == data.voice:
            manager = self.required_manager
            self._speaking = None
            await manager.emit(
                "speaking_state",
                SpeakingStateData(voice=data.voice, active=False),
                source=self.name,
            )
        # Cierra el turno de esa voz y, si corresponde, arma el clip IA->IA.
        line = self._line_buffer.pop(data.voice, "").strip()
        if line:
            self._last_line[data.voice] = line
        await self._maybe_clip(data.voice)

    async def _maybe_clip(self, speaker: str) -> None:
        """Pasa el turno a OTRA voz con un marco de clip (situación, no chiste)."""
        from hipotenusa.plugins.executor.static_vision_plugin import _parse_interval_secs, _setting

        settings = self._settings
        if settings is None or not _setting(settings, "interject_enabled", False):
            return
        text = (self._last_line.get(speaker) or "").strip()
        if not text:
            return
        try:
            max_turns = int(_setting(settings, "interject_max_turns", 4) or 4)
            chance = float(_setting(settings, "interject_chance", 0.55) or 0.55)
            cooldown = _parse_interval_secs(_setting(settings, "interject_cooldown", "6s"))
        except (TypeError, ValueError) as exc:
            log.warning("voice_manager: clip mal configurado ({}), queda apagado", exc)
            return
        if self._clip_turns >= max_turns:
            self._clip_turns = 0  # la cadena se cerró sola
            return
        if random.random() > chance:
            log.info("voice_manager: clip no sigue (sorteo) tras {}", speaker)
            return
        if time.monotonic() - self._last_clip_at < cooldown:
            return
        peers = [v for v in self._eligible_voices() if v.casefold() != speaker.casefold()]
        if not peers:
            return
        peer = self._pick_voice(peers)
        # cursor monótono, no per-cadena: reiniciando en 0, dos cadenas distintas
        # arrancan con la misma semilla y el modelo repite la misma frase.
        seed = _CLIP_SEEDS[self._seed_cursor % len(_CLIP_SEEDS)].format(other=peer)
        self._seed_cursor += 1
        twist = random.choice(_CLIP_TWISTS).format(other=peer)
        prompt = _CLIP_PROMPT.format(
            voice=peer, other=speaker, text=text[-200:], seed=seed, twist=twist
        )
        self._clip_turns += 1
        self._last_clip_at = time.monotonic()
        log.info(
            "voice_manager: clip turn {}/{} -> {} (responde a {})",
            self._clip_turns,
            max_turns,
            peer,
            speaker,
        )
        await self.required_manager.emit(
            "generate_request",
            GenerateRequestData(
                target_voice=peer,
                prompt=prompt,
                source_voice=speaker,
                depth=self._clip_turns - 1,
            ),
            source=self.name,
            target=peer,
        )

    async def on_voice_enable(self, data: VoiceEnableData) -> None:
        # Self-contained: resolves discovery context instead of a run_mode callback.
        manager = self.required_manager
        ctx = discovery_context_for((self,))
        if ctx is None:
            log.warning(
                "voice_manager: discovery context unavailable, ignoring voice enable for {}",
                data.voice_name,
            )
            return
        voice_name = data.voice_name
        configured_name = next(
            (name for name in ctx.config.settings.voice if name.casefold() == voice_name.casefold()),
            None,
        )
        voice_settings = ctx.config.settings.voice.get(configured_name) if configured_name else None
        if voice_settings is None:
            msg = f"voice not configured: {voice_name}"
            raise ValueError(msg)
        for plugin in manager.get_all_plugins():
            if plugin.name.casefold() == voice_name.casefold():
                if not plugin.enabled:
                    await manager.enable_plugin(plugin)
                await manager.emit(
                    "voice_enabled",
                    VoiceEnabledData(voice_name=plugin.name),
                    source=self.name,
                )
                return
        from hipotenusa.voices.factory import create_voice

        voice = create_voice(ctx, voice_settings, voice_name=configured_name or voice_name)
        await manager.enable_plugin(voice)
        await manager.emit(
            "voice_enabled",
            VoiceEnabledData(voice_name=voice.name),
            source=self.name,
        )

    def _eligible_voices(self) -> list[str]:
        manager = self.manager
        if manager is None:
            return []
        eligible: list[str] = []
        for plugin in manager.get_plugins():
            if not plugin.enabled:
                continue
            if "voice" not in plugin.capabilities:
                continue
            eligible.append(plugin.name)
        return eligible

    def _pick_voice(self, eligible: list[str]) -> str:
        weights = [self._probabilities.get(name, 1.0) for name in eligible]
        return random.choices(eligible, weights=weights, k=1)[0]

    def _remember(self, envelope: object) -> None:
        pass
