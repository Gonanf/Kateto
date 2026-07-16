# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "pydantic==2.13.4"]
# ///
# ─── How to run ───
# uv run python kateto/qa/fixture_models.py --scenario stream
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import TracebackType
from typing import Final

import anyio
import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, Classification, TextChunk


class FixtureScenario(StrEnum):
    STREAM = "stream"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class FixtureRequest:
    path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes


class _FixtureState:
    def __init__(self, scenario: FixtureScenario, category: Classification) -> None:
        self.scenario = scenario
        self.category = category
        self.requests: list[FixtureRequest] = []
        self.block_started = Event()
        self.release = Event()


class FixtureModelServer:
    def __init__(
        self,
        *,
        scenario: FixtureScenario = FixtureScenario.STREAM,
        category: Classification = Classification.EXECUTE,
    ) -> None:
        self._state = _FixtureState(scenario, category)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_type(self._state))
        self._thread = Thread(target=self._server.serve_forever, name="kateto-fixture-models")
        self._started = False

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> tuple[FixtureRequest, ...]:
        return tuple(self._state.requests)

    @property
    def block_started(self) -> Event:
        return self._state.block_started

    @property
    def is_closed(self) -> bool:
        return self._started and not self._thread.is_alive()

    def __enter__(self) -> FixtureModelServer:
        self._thread.start()
        self._started = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._started:
            return
        self._state.release.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def _handler_type(state: _FixtureState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state.requests.append(
                FixtureRequest(path=self.path.partition("?")[0], headers=tuple(self.headers.items()), body=body),
            )
            if state.scenario is FixtureScenario.TIMEOUT:
                state.block_started.set()
                state.release.wait(timeout=10)
                return
            match self.path.partition("?")[0]:
                case "/inference":
                    self._whisper()
                case "/v1/chat/completions":
                    self._chat(body)
                case "/v1/responses":
                    self._responses(body)
                case "/v1/audio/speech":
                    self._zonos()
                case _:
                    self._json(404, {"error": "unknown fixture route"})

        def log_message(self, format: str, *args: str) -> None:
            return

        def _whisper(self) -> None:
            if state.scenario is FixtureScenario.MALFORMED:
                self._json(200, {"language": "en"})
                return
            self._json(200, {"text": "fixture transcription", "language": "en", "confidence": 0.99})

        def _chat(self, body: bytes) -> None:
            if b'"response_format"' in body:
                content = "UNKNOWN" if state.scenario is FixtureScenario.MALFORMED else state.category.value
                self._json(200, {"choices": [{"message": {"content": content}}]})
                return
            if state.scenario is FixtureScenario.MALFORMED:
                self._sse(("data: {not-json}\n\n",))
                return
            self._chat_stream(body)

        def _chat_stream(self, body: bytes) -> None:
            self._sse_start()
            self._sse_data('{"choices":[{"delta":{"content":"fixture"}}]}')
            if b"BLOCK" in body:
                state.block_started.set()
                state.release.wait(timeout=10)
            self._sse_data('{"choices":[{"delta":{"content":" token"}}]}')
            self._sse_data("[DONE]")
            self._sse_end()

        def _responses(self, body: bytes) -> None:
            if state.scenario is FixtureScenario.MALFORMED:
                self._sse(("event: response.output_text.delta\n", "data: {not-json}\n\n"))
                return
            self._sse_start()
            self._sse_data('{"type":"response.output_text.delta","delta":"response"}', event="response.output_text.delta")
            if b"BLOCK" in body:
                state.block_started.set()
                state.release.wait(timeout=10)
            self._sse_data('{"type":"response.output_text.delta","delta":" token"}', event="response.output_text.delta")
            self._sse_data('{"type":"response.completed"}', event="response.completed")
            self._sse_end()

        def _zonos(self) -> None:
            if state.scenario is FixtureScenario.MALFORMED:
                self._json(200, {"error": "expected PCM"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/L16")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            self._chunk(b"\x01\x00\x02\x00")
            self._chunk(b"\x03\x00\x04\x00")
            self._chunk(b"")

        def _json(self, status: int, payload: dict[str, object]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _sse(self, lines: tuple[str, ...]) -> None:
            self._sse_start()
            for line in lines:
                self._chunk(line.encode("utf-8"))
            self._sse_end()

        def _sse_start(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()

        def _sse_data(self, data: str, *, event: str | None = None) -> None:
            prefix = "" if event is None else f"event: {event}\n"
            self._chunk(f"{prefix}data: {data}\n\n".encode("utf-8"))

        def _sse_end(self) -> None:
            self._chunk(b"")

        def _chunk(self, body: bytes) -> None:
            try:
                self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def _settings(endpoint: str) -> PluginSettings:
    return PluginSettings(endpoint=endpoint, model_endpoint=endpoint, model="fixture-model", sample_rate=24_000)


async def _stream_scenario() -> int:
    from kateto.providers import (
        ChatMessage,
        LlamaCppChatProvider,
        OpenAIResponsesProvider,
        WhisperProvider,
        ZonosProvider,
    )

    with FixtureModelServer() as server:
        settings = _settings(server.endpoint)
        async with WhisperProvider(settings) as whisper:
            transcription = await whisper.transcribe(
                AudioData(samples=b"\x01\x00\x02\x00", format="pcm_s16le"),
            )
        print(f"transcription={transcription.text}")
        from kateto.providers import ClassifierProvider

        async with ClassifierProvider(settings) as classifier:
            classification = await classifier.classify(transcription.text)
        print(f"classification={classification.category.value}")
        messages = (ChatMessage(role="user", content="fixture prompt"),)
        async with LlamaCppChatProvider(settings) as llama:
            async for chunk in llama.stream(messages):
                if chunk.text:
                    print(f"token={chunk.text}")
        async with OpenAIResponsesProvider(settings) as responses:
            async for chunk in responses.stream(messages):
                if chunk.text:
                    print(f"token={chunk.text}")
        async with ZonosProvider(settings) as zonos:
            async for audio in zonos.stream_sentence(TextChunk(text="fixture sentence", sequence=0), voice_id="jane"):
                if audio.samples:
                    print(f"audio={len(audio.samples)}")
    return 0


async def _timeout_scenario() -> int:
    from kateto.providers import WhisperProvider

    provider_closed = False
    server_closed = False
    try:
        with FixtureModelServer(scenario=FixtureScenario.TIMEOUT) as server:
            provider = WhisperProvider(_settings(server.endpoint), timeout_s=0.05)
            try:
                async with provider:
                    await provider.transcribe(AudioData(samples=b"\x01\x00", format="pcm_s16le"))
            except httpx.ReadTimeout:
                print("timeout_event=ReadTimeout")
            else:
                print("timeout_event=missing", file=sys.stderr)
                return 1
            provider_closed = provider.is_closed
        server_closed = server.is_closed
    finally:
        if not provider_closed or not server_closed:
            print("no_leaked_client_task=false", file=sys.stderr)
            return 1
    print("no_leaked_client_task=true")
    return 0


def main() -> int:
    match sys.argv[1:]:
        case ["--scenario", "stream"]:
            return anyio.run(_stream_scenario)
        case ["--scenario", "timeout"]:
            return anyio.run(_timeout_scenario)
        case _:
            print("usage: fixture_models.py --scenario {stream,timeout}", file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
