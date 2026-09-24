from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loguru import logger

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk

log = logger

# Matches the piper CLI ecosystem convention (rhasspy/piper, OHF-Voice piper1-gpl).
DEFAULT_VOICE_DIR = Path.home() / ".local" / "share" / "piper" / "voices"


class PiperVoiceNotAvailableError(RuntimeError):
    """piper-tts is missing, or a requested voice model cannot be loaded."""


class PiperProvider:
    """Local CPU TTS via the piper-tts package (onnxruntime; no torch).

    Voice models load lazily on first synthesis and stay cached for the
    lifetime of the process. Synthesis runs in a worker thread and yields PCM
    as piper produces it (one chunk per sentence; never the full turn).
    """

    def __init__(self, settings: PluginSettings) -> None:
        configured_dir = settings.get("download_dir")
        self._download_dir = (
            Path(str(configured_dir)).expanduser() if configured_dir else DEFAULT_VOICE_DIR
        )
        self._voices: dict[str, tuple[Any, int]] = {}
        self._piper_voice_cls: Any | None = None

    def _piper(self) -> Any:
        if self._piper_voice_cls is None:
            try:
                from piper import PiperVoice  # noqa: PLC0415
            except ImportError as err:
                raise PiperVoiceNotAvailableError(
                    "piper-tts is not installed; run `pip install 'kateto[piper]'` "
                    "(or `uv add --optional piper 'piper-tts>=1.6.0'`) to enable local TTS"
                ) from err
            self._piper_voice_cls = PiperVoice
        return self._piper_voice_cls

    def _model_path(self, voice: str) -> Path:
        onnx = self._download_dir / f"{voice}.onnx"
        if not onnx.is_file():
            raise PiperVoiceNotAvailableError(
                f"piper voice model not found at {onnx}. Download it with: "
                f"`python -c \"from piper.download_voices import download_voice; "
                f"from pathlib import Path; download_voice('{voice}', Path('{self._download_dir}'))\"`"
            )
        return onnx

    def _prepare_voice(self, voice: str) -> tuple[Any, int]:
        cached = self._voices.get(voice)
        if cached is not None:
            return cached
        model = self._model_path(voice)  # fail fast on missing model, before importing piper
        piper_voice_cls = self._piper()
        try:
            # CPU-only: use_cuda=False (default). No torch anywhere in the path.
            voice_obj = piper_voice_cls.load(model, config_path=None, use_cuda=False)
        except Exception as err:
            raise PiperVoiceNotAvailableError(
                f"piper voice {voice!r} could not be loaded from {model}: {err}"
            ) from err
        sample_rate = int(getattr(getattr(voice_obj, "config", None), "sample_rate", 22_050))
        self._voices[voice] = (voice_obj, sample_rate)
        return voice_obj, sample_rate

    async def stream_sentence(
        self,
        sentence: TextChunk,
        *,
        voice: str,
        length_scale: float = 1.0,
        speaker_id: int | None = None,
    ) -> AsyncIterator[AudioOutput]:
        voice_obj, sample_rate = await asyncio.to_thread(self._prepare_voice, voice)
        bridge: queue.Queue[bytes | None] = queue.Queue()
        first_chunk_at: list[float] = [0.0]

        def _synthesize() -> None:
            import time

            from piper.config import SynthesisConfig  # noqa: PLC0415

            syn_config = SynthesisConfig(
                speaker_id=speaker_id,
                length_scale=length_scale,
            )
            try:
                for chunk in voice_obj.synthesize(sentence.text, syn_config=syn_config):
                    pcm = getattr(chunk, "audio_int16_bytes", None)
                    if pcm is None:
                        array = getattr(chunk, "audio_int16_array", None)
                        if array is not None:
                            pcm = array.tobytes()
                    if not pcm:
                        continue
                    if first_chunk_at[0] == 0.0:
                        first_chunk_at[0] = time.monotonic()
                    bridge.put(bytes(pcm))
            except Exception as exc:
                log.warning("[piper] synthesize failed voice={} chars={}: {}", voice, len(sentence.text), exc)
            finally:
                bridge.put(None)

        worker = asyncio.create_task(asyncio.to_thread(_synthesize))
        seq = 0
        total_bytes = 0
        final_yielded = False
        try:
            while True:
                pcm = await asyncio.to_thread(bridge.get)
                if pcm is None:
                    break
                total_bytes += len(pcm)
                yield AudioOutput(
                    samples=pcm,
                    sample_rate=sample_rate,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=voice,
                    sequence=seq,
                    text=sentence.text,
                )
                seq += 1
        except asyncio.CancelledError:
            # Can't stop onnxruntime mid-synthesis; the worker thread finishes
            # and its bridge is discarded.
            # ponytail: background synth tail on interrupt, add a stop token if latency matters.
            final_yielded = True
            raise
        finally:
            await worker
        if first_chunk_at[0]:
            log.debug(
                "[piper] voice={} chars={} first_chunk={:.3f}s total={}B chunks={}",
                voice, len(sentence.text), first_chunk_at[0], total_bytes, seq,
            )
        if final_yielded:
            return
        yield AudioOutput(
            samples=b"",
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=seq,
            final=True,
            text=sentence.text,
        )
