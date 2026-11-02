from __future__ import annotations

import asyncio
import random
import time

from loguru import logger

from kateto.core.config import PluginSettings
from kateto.core.discovery import discovery_context_for
from kateto.core.event import (
    GenerateData,
    InterjectData,
    SpeakingStateData,
    SpeakRequestData,
    TranscriptionData,
    VisionDescribeResultData,
    VoiceEnableData,
    VoiceEnabledData,
    VoiceIdleData,
    VoiceStatusData,
)
from kateto.core.plugin import Plugin
from kateto.voices.base import VoiceProfile

log = logger

_DEFAULT_PROBABILITIES: dict[str, float] = {}

# Lo que se le pide a la voz cuando el impulso decide que hable sola. El "si vale la
# pena" lo resuelve la compuerta (estímulo fresco + azar), no el modelo: pedirle al LLM
# un turno entero para después descartarlo cuesta lo mismo que el turno.
_IMPULSE_PROMPT = (
    "Nadie te habló. Mirá lo último que viste o escuchaste y decí una frase corta, "
    "como si pensaras en voz alta."
)


class VoiceManager(Plugin):
    def __init__(self, settings: PluginSettings | None = None) -> None:
        super().__init__("voice_manager", streaming=True)
        self._settings = settings
        self._probabilities = dict(_DEFAULT_PROBABILITIES)
        self._speaking: str | None = None
        self._last_stimulus = 0.0
        self._impulse_task: asyncio.Task | None = None
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
        self._impulse_task = asyncio.create_task(self._impulse_loop(), name="voice-manager-impulse")

    async def on_transcription(self, data: TranscriptionData) -> None:
        self._last_stimulus = time.monotonic()

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self._last_stimulus = time.monotonic()

    async def _impulse_loop(self) -> None:
        """Decide sola si habla: momento al azar, sólo si nadie habla y hay estímulo fresco."""
        from kateto.plugins.executor.static_vision_plugin import _parse_interval_secs, _setting

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
            if time.monotonic() - self._last_stimulus > ventana:
                continue  # nada nuevo: no inventa charla de la nada
            eligible = self._eligible_voices()
            if not eligible:
                continue
            chosen = self._pick_voice(eligible)
            manager = self.required_manager
            log.info("voice_manager: impulso, {} habla por su cuenta", chosen)
            await manager.emit(
                "speak",
                SpeakRequestData(voice=chosen, prompt=_IMPULSE_PROMPT),
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
        from kateto.voices.factory import create_voice

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
