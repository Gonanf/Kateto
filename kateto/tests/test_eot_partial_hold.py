from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.exceptions import ProviderError
from kateto.plugins.audio_input.base import AudioInputConfig, SileroVad
from kateto.plugins.audio_input.mic import MicrophoneAudioInput
from kateto.plugins.system.eot_gate import EotAction, EotResult
from kateto.providers import ParakeetServerProvider

SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600


class SequencedSileroModel:
    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self._index = 0

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        del samples, sample_rate
        score = self._scores[self._index]
        self._index = min(self._index + 1, len(self._scores) - 1)
        return score


class FixtureCapture:
    def __init__(self, callback: Callable[[bytes, int, None, None], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def emit(self, samples: bytes) -> None:
        self._callback(samples, len(samples) // 2, None, None)


class FixtureCaptureFactory:
    def __init__(self) -> None:
        self.captures: list[FixtureCapture] = []

    def create(
        self,
        config: AudioInputConfig,
        callback: Callable[[bytes, int, None, None], None],
    ) -> FixtureCapture:
        del config
        capture = FixtureCapture(callback)
        self.captures.append(capture)
        return capture


class FakeParakeetProvider:
    async def transcribe_parcial(
        self, pcm: bytes, *, sample_rate: int = 16_000
    ) -> str:
        del pcm, sample_rate
        return "Hola, ¿cómo estás?"


class FakeParakeetProcessor(Plugin):
    def __init__(self, provider: object) -> None:
        super().__init__("audio_processor_parakeet")
        self._provider = provider

    @property
    def provider(self) -> object | None:
        return self._provider


class FakeEotGate(Plugin):
    def __init__(self) -> None:
        super().__init__("eot_gate")
        self.classified_texts: list[str] = []

    @property
    def available(self) -> bool:
        return True

    async def aclassify(self, text: str) -> EotResult:
        self.classified_texts.append(text)
        return EotResult(action=EotAction.WAIT)


@pytest.mark.asyncio
async def test_transcribe_parcial_postea_wav_y_devuelve_texto() -> None:
    captured_urls: list[str] = []
    captured_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        captured_bodies.append(request.read())
        if request.url.path.endswith("/v1/audio/transcriptions"):
            return httpx.Response(
                200, json={"text": "Hola, ¿cómo estás?", "language": "es"}
            )
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = PluginSettings(
        backend="server", host="127.0.0.1", port=8098, language="es"
    )
    provider = ParakeetServerProvider(settings, client=client)

    await provider.__aenter__()
    try:
        pcm = b"\x00\x00" * 16_000
        text = await provider.transcribe_parcial(pcm)

        assert text == "Hola, ¿cómo estás?"
        assert captured_urls[-1].endswith("/v1/audio/transcriptions")
        assert b"RIFF" in captured_bodies[-1]
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_transcribe_parcial_propaga_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server exploded"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = PluginSettings(
        backend="server", host="127.0.0.1", port=8098, language="es"
    )
    provider = ParakeetServerProvider(settings, client=client)

    await provider.__aenter__()
    try:
        pcm = b"\x00\x00" * 1_600
        with pytest.raises(ProviderError):
            await provider.transcribe_parcial(pcm)
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_resolver_arma_desde_el_plugin_de_parakeet() -> None:
    manager = PluginManager()
    provider = FakeParakeetProvider()
    parakeet_plugin = FakeParakeetProcessor(provider)

    settings = PluginSettings(
        device="fixture",
        sample_rate=16_000,
        silence_timeout=0.1,
        vad_model="silero",
        interrupt_on_vad=True,
        turn_silence_timeout=0.5,
        eot_partial_hold=True,
    )
    mic = MicrophoneAudioInput(
        settings,
        vad=SileroVad(SequencedSileroModel([0.9]), threshold=0.5),
        capture_factory=FixtureCaptureFactory(),
    )

    await manager.enable_plugin(parakeet_plugin)
    await manager.enable_plugin(mic)
    try:
        resolved = mic._resolve_partial_transcriber()
        assert resolved is provider
        assert mic._partial_transcriber is provider
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_hold_dispara_sin_inyeccion_manual() -> None:
    manager = PluginManager()
    provider = FakeParakeetProvider()
    parakeet_plugin = FakeParakeetProcessor(provider)
    gate = FakeEotGate()

    factory = FixtureCaptureFactory()
    settings = PluginSettings(
        device="fixture",
        sample_rate=16_000,
        silence_timeout=0.05,
        vad_model="silero",
        interrupt_on_vad=True,
        turn_silence_timeout=0.1,
        eot_partial_hold=True,
    )
    mic = MicrophoneAudioInput(
        settings,
        vad=SileroVad(SequencedSileroModel([0.9, 0.1, 0.1, 0.1]), threshold=0.5),
        capture_factory=factory,
    )

    await manager.enable_plugin(parakeet_plugin)
    await manager.enable_plugin(gate)
    await manager.enable_plugin(mic)
    try:
        assert mic._partial_transcriber is None

        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)

        await asyncio.sleep(0.25)
        await manager.wait_for_idle()

        assert len(mic._turn_buffer) > 0
        assert mic._partial_transcriber is provider
        assert len(gate.classified_texts) > 0
    finally:
        await manager.close()
