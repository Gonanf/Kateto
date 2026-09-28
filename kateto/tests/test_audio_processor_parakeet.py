from __future__ import annotations

import asyncio
import json
from collections import deque
from pathlib import Path

import httpx
import pytest

from kateto.core import PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.exceptions import ProviderError
from kateto.core.plugin import Plugin
from kateto.plugins.audio_processor import ParakeetAudioProcessor
from kateto.providers import (
    ParakeetProvider,
    ParakeetServerProvider,
    ParakeetStreamProvider,
    create_parakeet_provider,
)
from kateto.providers.errors import UnsupportedAudioPayload


class FixtureParakeet:
    def __init__(self, *, fail: bool = False) -> None:
        self.received: list[AudioData] = []
        self.fail = fail

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        self.received.append(audio)
        if self.fail:
            msg = "boom: binary exploded"
            raise RuntimeError(msg)
        return TranscriptionData(text="hola kateo", language="es")


class _TestableParakeetProcessor(ParakeetAudioProcessor):
    """Test helper that injects a fixture provider instead of the real one."""

    def __init__(self, fixture: FixtureParakeet) -> None:
        super().__init__(settings=PluginSettings())
        self._fixture = fixture

    async def enable(self) -> None:
        self._provider = self._fixture  # type: ignore[assignment]

    async def disable(self) -> None:
        self._provider = None


class TranscriptionSink(Plugin):
    def __init__(self) -> None:
        super().__init__("transcription_sink")
        self.received: list[TranscriptionData] = []

    async def on_transcription(self, data: TranscriptionData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_audio_chunk_flows_through_parakeet_processor_to_transcription() -> None:
    # Given: the documented processor boundary is connected to a parakeet adapter and a sink.
    manager = PluginManager()
    parakeet = FixtureParakeet()
    processor = _TestableParakeetProcessor(parakeet)
    sink = TranscriptionSink()
    await manager.enable_plugin(processor)
    await manager.enable_plugin(sink)

    try:
        # When: one audio chunk enters the event bus.
        audio = AudioData(samples=b"\x01\x00", format="pcm_s16le", source="fixture")
        await manager.emit("audio_chunk", audio, source="audio_input_mic/microphone")
        await manager.wait_for_idle()

        # Then: the adapter sees the exact chunk and the processor emits one typed transcription.
        assert parakeet.received == [audio]
        assert sink.received == [TranscriptionData(text="hola kateo", language="es")]
        assert [(event.name, event.source) for event in manager.get_events()] == [
            ("audio_chunk", "audio_input_mic/microphone"),
            ("transcription", "audio_processor_parakeet"),
        ]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_parakeet_processor_fail_open_keeps_runtime_alive() -> None:
    # Given: a provider that crashes on transcription (missing/hung binary).
    manager = PluginManager()
    processor = _TestableParakeetProcessor(FixtureParakeet(fail=True))
    sink = TranscriptionSink()
    await manager.enable_plugin(processor)
    await manager.enable_plugin(sink)

    try:
        # When: one audio chunk hits the failing provider.
        audio = AudioData(samples=b"\x01\x00", format="pcm_s16le", source="fixture")
        await manager.emit("audio_chunk", audio, source="audio_input_mic/microphone")
        await manager.wait_for_idle()

        # Then: no transcription is emitted, no exception escapes, and the plugin
        # is neither disabled nor wedged — the bus keeps serving.
        assert sink.received == []
        assert processor.enabled is True
        # a follow-up event is still dispatched (runtime not dead).
        await manager.emit("audio_chunk", audio, source="audio_input_mic/microphone")
        await manager.wait_for_idle()
        assert processor.enabled is True
    finally:
        await manager.close()


def _fake_bin(tmp_path: Path) -> Path:
    script = tmp_path / "fake_crispasr.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""; base=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "-of" ]; then base="$a"; fi\n'
        '  prev="$a"\n'
        "done\n"
        'printf "hola kateo" > "$base.txt"\n'
    )
    script.chmod(0o755)
    return script


@pytest.mark.asyncio
async def test_parakeet_provider_writes_wav_and_maps_transcription(tmp_path: Path) -> None:
    # Given: a fake crispasr binary that writes the transcript txt next to -of.
    settings = PluginSettings(
        bin=str(_fake_bin(tmp_path)),
        motor="ultra",
        backend="vulkan",
        device="1",
        language="es",
        timeout=30,
    )
    provider = ParakeetProvider(settings)
    await provider.__aenter__()
    try:
        # When: transcribing a 16 kHz mono s16le chunk.
        pcm = b"\x00\x00" * 16000  # 1 s of silence at 16 kHz
        audio = AudioData(
            samples=pcm,
            format="pcm_s16le",
            sample_rate=16000,
            channels=1,
            duration_ms=1000,
        )
        result = await provider.transcribe(audio)

        # Then: the provider maps the CLI output onto a typed TranscriptionData.
        assert result.text == "hola kateo"
        assert result.language == "es"
        assert result.duration_ms == 1000
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_parakeet_provider_rejects_non_s16le_payload() -> None:
    # Given: an arbitrary unsupported payload format.
    provider = ParakeetProvider(PluginSettings(bin="/bin/true", motor="ultra"))
    await provider.__aenter__()
    try:
        # When/Then: an unsupported audio format raises before touching the binary.
        with pytest.raises(UnsupportedAudioPayload):
            await provider.transcribe(AudioData(samples=b"\x01\x00", format="ogg"))
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_parakeet_provider_missing_binary_raises_provider_error(tmp_path: Path) -> None:
    # Given: a configured binary path that does not exist (fail-open to the plugin).
    provider = ParakeetProvider(
        PluginSettings(bin=str(tmp_path / "does-not-exist"), motor="ultra")
    )
    await provider.__aenter__()
    try:
        # When: transcribing triggers the subprocess launch.
        # Then: it surfaces as ProviderError, which the plugin swallows into empty output.
        with pytest.raises(ProviderError):
            await provider.transcribe(
                AudioData(samples=b"\x00\x00", format="pcm_s16le", sample_rate=16000, channels=1)
            )
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# Server transport (CrispASR `--server` + POST /v1/audio/transcriptions).
# These tests run against a mocked HTTP transport — no real server is required.
# ---------------------------------------------------------------------------


def _server_transport(
    *,
    text: str = "hola kateo",
    status: int = 200,
    health_status: int = 200,
    captured: list | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(str(request.url))
        if request.url.path.endswith("/health"):
            return httpx.Response(health_status, json={"status": "ok"})
        if request.url.path.endswith("/v1/audio/transcriptions"):
            if status != 200:
                return httpx.Response(status, json={"error": "boom"})
            return httpx.Response(200, json={"text": text})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _wav_audio() -> AudioData:
    return AudioData(
        samples=b"\x00\x00" * 16000,
        format="pcm_s16le",
        sample_rate=16000,
        channels=1,
        duration_ms=1000,
    )


@pytest.mark.asyncio
async def test_parakeet_server_provider_transcribes_via_openai_endpoint() -> None:
    # Given: a mocked CrispASR server answering POST /v1/audio/transcriptions.
    captured: list[str] = []
    transport = _server_transport(text="hola kateo server", captured=captured)
    settings = PluginSettings(backend="server", host="127.0.0.1", port=8098, language="es")
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    provider = ParakeetServerProvider(settings, client=client)

    await provider.__aenter__()
    try:
        # When: transcribing one audio chunk.
        result = await provider.transcribe(_wav_audio())

        # Then: the provider posts to the OpenAI-compatible path and maps the
        # response onto a typed TranscriptionData.
        assert captured[-1].endswith("/v1/audio/transcriptions")
        assert result.text == "hola kateo server"
        assert result.duration_ms == 1000
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_parakeet_server_provider_health_probe() -> None:
    # Given: a mocked server that is up (200 on /health).
    client = httpx.AsyncClient(transport=_server_transport(), timeout=5.0)
    provider = ParakeetServerProvider(PluginSettings(backend="server"), client=client)

    await provider.__aenter__()
    try:
        # When: probing health while the server is up.
        # Then: it reports reachable.
        assert await provider.health() is True
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_parakeet_server_provider_health_false_when_down() -> None:
    # Given: a transport that refuses every request (server not running).
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(refused))
    provider = ParakeetServerProvider(
        PluginSettings(backend="server", host="127.0.0.1", port=1), client=client
    )

    await provider.__aenter__()
    try:
        # When/Then: health is False, never raising.
        assert await provider.health() is False
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_parakeet_server_provider_fail_open_on_upstream_error() -> None:
    # Given: a server that answers the transcribe endpoint with HTTP 500.
    client = httpx.AsyncClient(transport=_server_transport(status=500), timeout=5.0)
    provider = ParakeetServerProvider(PluginSettings(backend="server"), client=client)

    await provider.__aenter__()
    try:
        # When/Then: an upstream error surfaces as ProviderError, which the plugin
        # swallows into empty output (the bus stays alive).
        with pytest.raises(ProviderError):
            await provider.transcribe(_wav_audio())
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_parakeet_server_provider_rejects_empty_text() -> None:
    # Given: a server returning an empty transcription payload.
    client = httpx.AsyncClient(transport=_server_transport(text="  "), timeout=5.0)
    provider = ParakeetServerProvider(PluginSettings(backend="server"), client=client)

    await provider.__aenter__()
    try:
        # When/Then: empty output is treated as a provider error (fail-open up the chain).
        with pytest.raises(ProviderError):
            await provider.transcribe(_wav_audio())
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_create_parakeet_provider_selects_backend_by_setting() -> None:
    # Given: only the transport `backend` differs.
    # When/Then: "server" (and the default) pick the server provider, "cli" the CLI one.
    assert isinstance(create_parakeet_provider(PluginSettings(backend="server")), ParakeetServerProvider)
    assert isinstance(create_parakeet_provider(PluginSettings()), ParakeetServerProvider)
    assert isinstance(create_parakeet_provider(PluginSettings(backend="cli")), ParakeetProvider)
    assert isinstance(create_parakeet_provider(PluginSettings(backend="stream")), ParakeetStreamProvider)
    # A legacy GPU name is NOT a valid transport, so it also resolves to the server.
    assert isinstance(create_parakeet_provider(PluginSettings(backend="vulkan")), ParakeetServerProvider)


# ---------------------------------------------------------------------------
# Streaming transport (CrispASR `--stream --stream-json`, PCM over stdin).
# The child process is faked: scripted stdout lines, controllable death.
# No real binary is required.
# ---------------------------------------------------------------------------


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise BrokenPipeError("fake stdin closed")
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    """Scripted stdout: yields queued lines, then blocks until cancelled."""

    def __init__(self, lines: list[bytes] | None = None, *, eof: bool = False) -> None:
        self._lines: deque[bytes] = deque(lines or [])
        self._eof = eof

    async def readline(self) -> bytes:
        while not self._lines:
            if self._eof:
                return b""
            await asyncio.sleep(0.005)
        return self._lines.popleft()


class _FakeProc:
    def __init__(self, stdout_lines: list[bytes] | None = None, *, eof: bool = False) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.stdin: _FakeStdin | None = _FakeStdin()
        self.stdout: _FakeStdout | None = _FakeStdout(stdout_lines, eof=eof)
        self.stderr: _FakeStdout | None = _FakeStdout([], eof=True)
        self.killed = False
        self._waiters: list[asyncio.Future[None]] = []

    async def wait(self) -> int | None:
        while self.returncode is None:
            await asyncio.sleep(0.005)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _stream_lines(*events: dict) -> list[bytes]:
    return [(json.dumps(event) + "\n").encode() for event in events]


def _fake_spawn(
    monkeypatch: pytest.MonkeyPatch,
    procs: list[_FakeProc],
    captured_argv: list[list[str]],
    *,
    stdout_lines: list[bytes] | None = None,
    eof: bool = False,
) -> None:
    async def fake_create_subprocess_exec(*argv: str, **kwargs) -> _FakeProc:  # noqa: ANN002, ANN003
        captured_argv.append(list(argv))
        proc = _FakeProc(stdout_lines if len(procs) == 0 else None, eof=eof)
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


@pytest.mark.asyncio
async def test_parakeet_stream_provider_emits_partial_then_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fake child emitting partial, garbage, then final on stdout.
    procs: list[_FakeProc] = []
    captured_argv: list[list[str]] = []
    lines = [
        *_stream_lines({"type": "partial", "utterance_id": 1, "text": "hola", "t0": 0.0, "t1": 0.5}),
        b"esta linea no es json\n",
        *_stream_lines({"type": "final", "utterance_id": 1, "text": "hola kateo", "t0": 0.0, "t1": 1.0}),
    ]
    _fake_spawn(monkeypatch, procs, captured_argv, stdout_lines=lines)
    settings = PluginSettings(backend="stream", stream_step_ms=500, stream_final_on_silence_ms=600)
    provider = ParakeetStreamProvider(settings)
    received: list[TranscriptionData] = []
    provider.on_event = lambda data: received.append(data) or asyncio.sleep(0)  # type: ignore[assignment]

    await provider.__aenter__()
    try:
        # When: PCM is fed and the reader parses the scripted lines.
        await provider.feed(b"\x00\x00" * 1600)
        for _ in range(400):
            if len(received) >= 2:
                break
            await asyncio.sleep(0.005)

        # Then: argv carries the streaming flags and only real events surface,
        # with the partial flag telling them apart (garbage line ignored).
        assert "--stream" in captured_argv[0] and "--stream-json" in captured_argv[0]
        assert "--stream-step" in captured_argv[0] and "500" in captured_argv[0]
        assert [data.text for data in received] == ["hola", "hola kateo"]
        assert [data.partial for data in received] == [True, False]
        assert procs[0].stdin is not None and procs[0].stdin.written == [b"\x00\x00" * 1600]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_parakeet_stream_provider_restarts_dead_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a child that is already dead (EOF on stdout, nonzero exit).
    procs: list[_FakeProc] = []
    captured_argv: list[list[str]] = []
    _fake_spawn(monkeypatch, procs, captured_argv, eof=True)
    settings = PluginSettings(backend="stream", stream_max_restarts=2)
    provider = ParakeetStreamProvider(settings)
    await provider.__aenter__()
    try:
        procs[0].returncode = 1
        await asyncio.sleep(0.05)

        # When: feeding while the child is dead.
        # Then: the provider restarts it instead of raising (fail-open).
        await provider.feed(b"\x01\x02" * 800)
        assert len(procs) == 2
        assert provider._degraded is False
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_parakeet_stream_provider_degrades_after_restart_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a child that dies on every spawn, with a restart budget of 1.
    procs: list[_FakeProc] = []
    captured_argv: list[list[str]] = []
    _fake_spawn(monkeypatch, procs, captured_argv, eof=True)
    settings = PluginSettings(backend="stream", stream_max_restarts=1)
    provider = ParakeetStreamProvider(settings)
    await provider.__aenter__()
    try:
        for proc in list(procs):
            proc.returncode = 1
        await provider.feed(b"\x00" * 320)  # restart #1
        procs[-1].returncode = 1
        await asyncio.sleep(0.05)

        # When: feeding once the budget is exhausted.
        # Then: no raise, no new spawn — PCM is dropped (degraded, bus alive).
        spawns_before = len(procs)
        await provider.feed(b"\x00" * 320)
        assert provider._degraded is True
        assert len(procs) == spawns_before
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_parakeet_stream_aclclose_waits_for_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an open stream whose child exits 0 right after stdin closes.
    procs: list[_FakeProc] = []
    captured_argv: list[list[str]] = []
    lines = _stream_lines({"type": "final", "utterance_id": 7, "text": "chau", "t0": 0.0, "t1": 0.4})
    _fake_spawn(monkeypatch, procs, captured_argv, stdout_lines=lines)
    settings = PluginSettings(backend="stream", stream_final_wait_s=5.0)
    provider = ParakeetStreamProvider(settings)
    received: list[TranscriptionData] = []
    provider.on_event = lambda data: received.append(data) or asyncio.sleep(0)  # type: ignore[assignment]
    await provider.__aenter__()
    proc = procs[0]

    async def _exit_soon() -> None:
        for _ in range(200):
            if proc.stdin is not None and proc.stdin.closed:
                break
            await asyncio.sleep(0.005)
        proc.returncode = 0

    closer = asyncio.create_task(_exit_soon())
    try:
        # When: closing (stdin EOF lets the child emit its last final).
        await provider.aclose()

        # Then: the final arrived before teardown and the child is gone.
        assert [data.text for data in received] == ["chau"]
        assert received[0].partial is False
        assert provider._proc is None
    finally:
        closer.cancel()


@pytest.mark.asyncio
async def test_parakeet_stream_plugin_feeds_pcm_and_emits_transcriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the real stream processor on the bus with a faked child.
    procs: list[_FakeProc] = []
    captured_argv: list[list[str]] = []
    lines = [
        *_stream_lines({"type": "partial", "utterance_id": 1, "text": "hola", "t0": 0.0, "t1": 0.5}),
        *_stream_lines({"type": "final", "utterance_id": 1, "text": "hola kateo", "t0": 0.0, "t1": 1.0}),
    ]
    _fake_spawn(monkeypatch, procs, captured_argv, stdout_lines=lines)
    manager = PluginManager()
    processor = ParakeetAudioProcessor(PluginSettings(backend="stream"))
    sink = TranscriptionSink()
    await manager.enable_plugin(processor)
    await manager.enable_plugin(sink)
    try:
        # When: one audio chunk enters the bus.
        pcm = b"\x00\x00" * 1600
        await manager.emit(
            "audio_chunk",
            AudioData(samples=pcm, format="pcm_s16le", sample_rate=16000, channels=1),
            source="audio_input_mic/microphone",
        )
        for _ in range(400):
            if len(sink.received) >= 2:
                break
            await asyncio.sleep(0.005)
        await manager.wait_for_idle()

        # Then: PCM reached the child and both events surface as `transcription`
        # (partial=True vs final partial=False); old listeners that ignore the
        # flag keep working — finals still carry partial=False.
        assert procs[0].stdin is not None and b"".join(procs[0].stdin.written) == pcm
        assert [data.text for data in sink.received] == ["hola", "hola kateo"]
        assert [data.partial for data in sink.received] == [True, False]
        assert [(event.name, event.source) for event in manager.get_events()] == [
            ("audio_chunk", "audio_input_mic/microphone"),
            ("transcription", "audio_processor_parakeet"),
            ("transcription", "audio_processor_parakeet"),
        ]
    finally:
        await manager.close()