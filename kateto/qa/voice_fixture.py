from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from kateto.core import PluginManager
from kateto.core.event import GenerateData, PluginErrorData, TextChunk, VoiceIdleData
from kateto.voices.base import GenerationRequest
from kateto.voices.conquest import Conquest
from kateto.voices.doktor import Doktor
from kateto.voices.jane import Jane


_VOICE_NAMES = {"jane": "Jane", "doktor": "Doktor", "conquest": "Conquest"}


@dataclass(frozen=True, slots=True)
class VoiceFixtureResult:
    response_voices: tuple[str, ...]
    idle_voices: tuple[str, ...]
    error_voices: tuple[str, ...]
    manager_alive: bool


class FixtureProvider:
    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        return self._tokens(request)

    async def _tokens(self, request: GenerationRequest) -> AsyncIterator[str]:
        yield f"{_VOICE_NAMES[request.voice_id]} response"


async def run_fixture(prompt: str, missing_reference_voice: str | None = None) -> VoiceFixtureResult:
    with TemporaryDirectory(prefix="kateto-voice-fixture-") as temporary_directory:
        config_dir = Path(temporary_directory)
        for voice in _VOICE_NAMES:
            if voice != missing_reference_voice:
                reference = config_dir / "voices" / voice / "reference.wav"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_bytes(b"RIFFfixtureWAVE")

        provider = FixtureProvider()
        manager = PluginManager()
        voices = (
            Jane(config_dir=config_dir, provider=provider),
            Doktor(config_dir=config_dir, provider=provider),
            Conquest(config_dir=config_dir, provider=provider),
        )
        for voice in voices:
            await manager.enable_plugin(voice)
        try:
            await manager.emit("generate", GenerateData(prompt=prompt), source="voice_fixture")
            await manager.wait_for_idle()
            events = manager.get_events()
            responses = tuple(
                data.voice_id
                for event in events
                if event.name == "text_chunk"
                and isinstance(data := event.data, TextChunk)
                and data.final
                and data.voice_id is not None
            )
            idles = tuple(
                data.voice
                for event in events
                if event.name == "voice_idle" and isinstance(data := event.data, VoiceIdleData)
            )
            errors = tuple(
                data.plugin
                for event in events
                if event.name == "error" and isinstance(data := event.data, PluginErrorData)
            )
            return VoiceFixtureResult(
                response_voices=responses,
                idle_voices=idles,
                error_voices=errors,
                manager_alive=all(voice.enabled for voice in manager.get_plugins()),
            )
        finally:
            await manager.close()


def _display(voice: str) -> str:
    return _VOICE_NAMES.get(voice, voice)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--missing-reference", choices=tuple(_VOICE_NAMES))
    arguments = parser.parse_args()
    result = asyncio.run(run_fixture(arguments.prompt, arguments.missing_reference))
    for voice in result.response_voices:
        print(f"VOICE_RESPONSE voice={_display(voice)}")
    for voice in result.idle_voices:
        print(f"VOICE_IDLE voice={_display(voice)}")
    for voice in result.error_voices:
        print(f"VOICE_ERROR voice={_display(voice)}")
    print(
        "TRACE "
        f"responses={len(result.response_voices)} "
        f"idles={len(result.idle_voices)} "
        f"errors={len(result.error_voices)} "
        f"manager_alive={str(result.manager_alive).lower()}",
    )
    expected_errors = () if arguments.missing_reference is None else (arguments.missing_reference,)
    return 0 if result.manager_alive and result.error_voices == expected_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
