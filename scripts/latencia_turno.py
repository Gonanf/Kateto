#!/usr/bin/env python3
"""Benchmark harness-latencia (latencia de turno de extremo a extremo).

Mide la latencia de un turno en el harness con extremos de modelo stubbeados:
  t0: instantes después de emitir el último frame de habla del turno.
  t1: en el sink de TTS al recibir el primer TextChunk del turno.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def ensure_environment() -> None:
    """Asegura que el script corra en el entorno virtual Python 3.12 del proyecto."""
    try:
        import pydantic_ai  # noqa: F401
        import sounddevice  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("LATENCIA_TURNO_REEXEC") == "1":
        sys.stderr.write("Error: re-exec failed to find required dependencies (pydantic_ai, sounddevice).\n")
        sys.exit(3)

    # Buscar intérprete:
    # (1) <cwd>/.venv/bin/python
    candidate = Path.cwd() / ".venv" / "bin" / "python"
    if not candidate.is_file():
        # (2) git rev-parse --path-format=absolute --git-common-dir -> parent -> .venv/bin/python
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                text=True,
                check=True,
            )
            git_common_dir = Path(res.stdout.strip())
            candidate = git_common_dir.parent / ".venv" / "bin" / "python"
        except Exception:
            candidate = None

    if candidate and candidate.is_file():
        env = dict(os.environ)
        env["LATENCIA_TURNO_REEXEC"] = "1"
        os.execve(str(candidate), [str(candidate), *sys.argv], env)
    else:
        sys.stderr.write(
            "Error: intérprete virtualenv válido no encontrado. Código de salida 3.\n"
        )
        sys.exit(3)


# Asegurar sys.path con la raíz del repo antes de imports de kateto
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Frames de audio (100 ms mono s16LE a 16 kHz)
SPEECH_FRAME = b"\x01\x00" * 1_600
SILENCE_FRAME = b"\x00\x00" * 1_600
EXPECTED_SPEECH_BYTES_PER_TURN = 4 * len(SPEECH_FRAME)  # 12,800 bytes


@dataclass(frozen=True, slots=True)
class TurnMeasurement:
    turn_index: int
    t0: float
    t1: float | None
    t_flush: float | None
    speech_bytes: int
    transcribed_bytes: int
    audio_chunks_count: int


@dataclass(frozen=True, slots=True)
class GuardasResult:
    valido: bool
    turnos_medidos: int
    turnos_partidos: int
    audio_truncado: int
    respondio_antes: int
    latencias_ms: list[float]
    latencias_pipeline_ms: list[float]


def evaluar_guardas(
    turnos: list[TurnMeasurement],
    n_esperado: int,
) -> GuardasResult:
    """Evalúa las guardas anti-reward-hack de manera pura."""
    turnos_partidos = 0
    audio_truncado = 0
    respondio_antes = 0
    turnos_medidos = 0
    latencias_ms: list[float] = []
    latencias_pipeline_ms: list[float] = []

    for m in turnos:
        if m.audio_chunks_count > 1:
            turnos_partidos += 1
        if m.transcribed_bytes < m.speech_bytes:
            audio_truncado += 1
        if m.t1 is not None:
            if m.t1 < m.t0:
                respondio_antes += 1
            lat = round((m.t1 - m.t0) * 1000, 1)
            latencias_ms.append(lat)
            if m.t_flush is not None:
                lat_pipe = round((m.t1 - m.t_flush) * 1000, 1)
                latencias_pipeline_ms.append(lat_pipe)
            turnos_medidos += 1

    valido = (
        turnos_partidos == 0
        and audio_truncado == 0
        and respondio_antes == 0
        and turnos_medidos == n_esperado
        and n_esperado > 0
    )

    return GuardasResult(
        valido=valido,
        turnos_medidos=turnos_medidos,
        turnos_partidos=turnos_partidos,
        audio_truncado=audio_truncado,
        respondio_antes=respondio_antes,
        latencias_ms=latencias_ms,
        latencias_pipeline_ms=latencias_pipeline_ms,
    )


def calcular_estadisticas(
    latencias: list[float],
    latencias_pipeline: list[float],
) -> tuple[float, float, float, float, float]:
    """Calcula p50, p90 (nearest-rank), min, max, pipeline_p50."""
    if not latencias:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    p50 = round(float(statistics.median(latencias)), 1)

    sorted_lat = sorted(latencias)
    n = len(sorted_lat)
    idx_p90 = min(max(0, math.ceil(0.9 * n) - 1), n - 1)
    p90 = round(float(sorted_lat[idx_p90]), 1)

    lat_min = round(float(min(latencias)), 1)
    lat_max = round(float(max(latencias)), 1)

    pipe_p50 = (
        round(float(statistics.median(latencias_pipeline)), 1)
        if latencias_pipeline
        else 0.0
    )

    return p50, p90, lat_min, lat_max, pipe_p50


class DeterministicSileroModel:
    """Modelo VAD determinista: 1.0 ante speech frame y 0.0 ante silence frame."""

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        del sample_rate
        return 1.0 if any(samples) else 0.0


def _build_benchmark_plugins():
    from kateto.core import Plugin
    from kateto.core.event import AudioData, GenerateData, TextChunk, TranscriptionData

    class FakeWhisper(Plugin):
        def __init__(self) -> None:
            super().__init__("fake_whisper")
            self.turn_chunks = 0
            self.turn_bytes = 0
            self.flush_time: float | None = None

        async def initialize(self) -> None:
            self.manager.register_event("audio_chunk", AudioData)
            self.manager.register_event("transcription", TranscriptionData)

        def reset_turn(self) -> None:
            self.turn_chunks = 0
            self.turn_bytes = 0
            self.flush_time = None

        async def on_audio_chunk(self, data: AudioData) -> None:
            now = time.perf_counter()
            if self.flush_time is None:
                self.flush_time = now
            self.turn_chunks += 1
            self.turn_bytes += len(data.samples)
            await self.manager.emit(
                "transcription",
                TranscriptionData(text=f"turn {self.turn_chunks}"),
                source=self.name,
            )

    class FakeClassifier(Plugin):
        def __init__(self, target_voice: str = "jane") -> None:
            super().__init__("fake_classifier")
            self.target_voice = target_voice

        async def initialize(self) -> None:
            self.manager.register_event("transcription", TranscriptionData)
            self.manager.register_event("generate", GenerateData)

        async def on_transcription(self, data: TranscriptionData) -> None:
            await self.manager.emit(
                "generate",
                GenerateData(prompt=data.text),
                source=self.name,
                target=self.target_voice,
            )

    class TTSSink(Plugin):
        def __init__(self) -> None:
            super().__init__("tts_sink")
            self.first_chunk_ev = asyncio.Event()
            self.first_chunk_time: float | None = None
            self.total_chunks = 0

        async def initialize(self) -> None:
            self.manager.register_event("text_chunk", TextChunk)

        def reset_turn(self) -> None:
            self.first_chunk_ev = asyncio.Event()
            self.first_chunk_time = None
            self.total_chunks = 0

        async def on_text_chunk(self, data: TextChunk) -> None:
            if self.first_chunk_time is None and data.text:
                self.first_chunk_time = time.perf_counter()
                self.first_chunk_ev.set()
            self.total_chunks += 1

    return FakeWhisper, FakeClassifier, TTSSink


async def run_turn(
    capture,
    whisper,
    tts,
    manager,
    *,
    intra_gap_ms: int,
    turn_silence_timeout: float,
) -> tuple[float, float | None, float | None, int, int, int]:
    """Ejecuta un único turno de audio según el protocolo del benchmark."""
    del turn_silence_timeout
    whisper.reset_turn()
    tts.reset_turn()

    # 4 frames de habla separados por pausas intra-turno
    for i in range(4):
        capture.emit(SPEECH_FRAME)
        if i < 3:
            capture.emit(SILENCE_FRAME)
            await asyncio.sleep(intra_gap_ms / 1000.0)

    # t0 tomado INMEDIATAMENTE tras entregar el último frame de habla
    t0 = time.perf_counter()

    # Alimentación de silencio para que el VAD cierre el segmento y el turn buffer flushée
    stop_silence = asyncio.Event()

    async def feed_silence():
        try:
            while not stop_silence.is_set():
                capture.emit(SILENCE_FRAME)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    silence_task = asyncio.create_task(feed_silence())

    t1: float | None = None
    try:
        await asyncio.wait_for(tts.first_chunk_ev.wait(), timeout=10.0)
        t1 = tts.first_chunk_time
    except TimeoutError:
        t1 = None
    finally:
        stop_silence.set()
        silence_task.cancel()
        try:
            await silence_task
        except asyncio.CancelledError:
            pass

    # Esperar que termine el despacho del turno
    await manager.wait_for_idle()

    # Breve pausa para separar turnos limpiamente
    await asyncio.sleep(0.2)

    return (
        t0,
        t1,
        whisper.flush_time,
        EXPECTED_SPEECH_BYTES_PER_TURN,
        whisper.turn_bytes,
        whisper.turn_chunks,
    )


async def run_benchmark(
    n: int,
    *,
    warmup: int = 3,
    intra_gap_ms: int = 200,
    turn_silence_timeout: float = 2.0,
    silence_timeout: float = 1.0,
    seed: int = 1,
) -> tuple[GuardasResult, float, float, float, float, float]:
    del seed
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    from kateto.core import PluginManager
    from kateto.core.config import PluginSettings
    from kateto.plugins.audio_input.base import SileroVad
    from kateto.plugins.audio_input.mic import MicrophoneAudioInput
    from kateto.tests.conversation_support import (
        StreamingFixtureProvider,
        enable_voices,
        write_references,
    )
    from kateto.tests.test_audio_turn_chain import FixtureCaptureFactory

    FakeWhisper, FakeClassifier, TTSSink = _build_benchmark_plugins()

    manager = PluginManager()
    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp)
        write_references(config_dir)

        provider = StreamingFixtureProvider(tokens=("Hola.", " ¿cómo estás?"))
        await enable_voices(manager, config_dir=config_dir, provider=provider)

        whisper = FakeWhisper()
        classifier = FakeClassifier(target_voice="jane")
        tts = TTSSink()
        factory = FixtureCaptureFactory()

        mic = MicrophoneAudioInput(
            PluginSettings(
                device="fixture",
                sample_rate=16_000,
                silence_timeout=silence_timeout,
                vad_model="silero",
                interrupt_on_vad=True,
                turn_silence_timeout=turn_silence_timeout,
            ),
            vad=SileroVad(DeterministicSileroModel(), threshold=0.5),
            capture_factory=factory,
        )

        await manager.enable_plugin(whisper)
        await manager.enable_plugin(classifier)
        await manager.enable_plugin(tts)
        await manager.enable_plugin(mic)
        capture = factory.captures[0]

        # Warmup turns (no entran en las mediciones)
        for _ in range(warmup):
            await run_turn(
                capture,
                whisper,
                tts,
                manager,
                intra_gap_ms=intra_gap_ms,
                turn_silence_timeout=turn_silence_timeout,
            )

        # Measured turns
        measurements: list[TurnMeasurement] = []
        for turn_idx in range(n):
            t0, t1, t_flush, sp_bytes, tr_bytes, ch_count = await run_turn(
                capture,
                whisper,
                tts,
                manager,
                intra_gap_ms=intra_gap_ms,
                turn_silence_timeout=turn_silence_timeout,
            )
            measurements.append(
                TurnMeasurement(
                    turn_index=turn_idx,
                    t0=t0,
                    t1=t1,
                    t_flush=t_flush,
                    speech_bytes=sp_bytes,
                    transcribed_bytes=tr_bytes,
                    audio_chunks_count=ch_count,
                )
            )

        await manager.close()

    guardas = evaluar_guardas(measurements, n)
    p50, p90, lat_min, lat_max, pipe_p50 = calcular_estadisticas(
        guardas.latencias_ms, guardas.latencias_pipeline_ms
    )
    return guardas, p50, p90, lat_min, lat_max, pipe_p50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark harness-latencia (latencia de turno de extremo a extremo)."
    )
    parser.add_argument("n", type=int, help="Número de turnos medidos")
    parser.add_argument("--warmup", type=int, default=3, help="Turnos de warmup (default: 3)")
    parser.add_argument("--seed", type=int, default=1, help="Semilla informada (default: 1)")
    parser.add_argument(
        "--intra-gap-ms",
        type=int,
        default=200,
        help="Pausa intra-turno entre frames de habla en ms (default: 200)",
    )
    parser.add_argument(
        "--turn-silence-timeout",
        type=float,
        default=2.0,
        help="Turn silence timeout en segundos (default: 2.0)",
    )
    parser.add_argument(
        "--silence-timeout",
        type=float,
        default=1.0,
        help="Silence timeout en segundos (default: 1.0)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Imprime únicamente la línea JSON final",
    )
    return parser.parse_args()


def main() -> None:
    ensure_environment()
    args = parse_args()

    try:
        guardas, p50, p90, lat_min, lat_max, pipe_p50 = asyncio.run(
            run_benchmark(
                args.n,
                warmup=args.warmup,
                intra_gap_ms=args.intra_gap_ms,
                turn_silence_timeout=args.turn_silence_timeout,
                silence_timeout=args.silence_timeout,
                seed=args.seed,
            )
        )
    except Exception as exc:
        guardas = GuardasResult(
            valido=False,
            turnos_medidos=0,
            turnos_partidos=0,
            audio_truncado=0,
            respondio_antes=0,
            latencias_ms=[],
            latencias_pipeline_ms=[],
        )
        p50, p90, lat_min, lat_max, pipe_p50 = 0.0, 0.0, 0.0, 0.0, 0.0
        sys.stderr.write(f"Benchmark error: {exc}\n")

    output_dict = {
        "benchmark": "harness-latencia",
        "n": args.n,
        "latencia_p50_ms": p50,
        "latencia_p90_ms": p90,
        "latencia_min_ms": lat_min,
        "latencia_max_ms": lat_max,
        "latencia_pipeline_p50_ms": pipe_p50,
        "turnos_medidos": guardas.turnos_medidos,
        "turnos_partidos": guardas.turnos_partidos,
        "audio_truncado": guardas.audio_truncado,
        "respondio_antes": guardas.respondio_antes,
        "valido": guardas.valido,
        "config": {
            "turn_silence_timeout_s": args.turn_silence_timeout,
            "silence_timeout_s": args.silence_timeout,
            "intra_gap_ms": args.intra_gap_ms,
            "stubs": ["asr", "llm", "tts"],
            "plugins_omitidos": ["turn_gate", "eot_gate"],
        },
        "entorno": {
            "python": platform.python_version(),
            "venv": True,
            "seed": args.seed,
        },
    }

    json_str = json.dumps(output_dict, separators=(",", ":"))

    if not args.json_only:
        print(f"=== Benchmark harness-latencia (N={args.n}, warmup={args.warmup}) ===")
        print(
            f"Config: turn_silence={args.turn_silence_timeout}s, "
            f"silence_timeout={args.silence_timeout}s, intra_gap={args.intra_gap_ms}ms"
        )
        print(f"Turnos medidos: {guardas.turnos_medidos}/{args.n}")
        print(
            f"Latencia p50: {p50} ms | p90: {p90} ms | min: {lat_min} ms | max: {lat_max} ms"
        )
        print(f"Latencia pipeline p50: {pipe_p50} ms")
        print(
            f"Guardas: partidos={guardas.turnos_partidos}, truncados={guardas.audio_truncado}, "
            f"antes={guardas.respondio_antes} -> Valido: {guardas.valido}"
        )

    print(json_str)
    sys.exit(0 if guardas.valido else 2)


if __name__ == "__main__":
    main()
