"""Todo-12 sidecar tests: video-rag describe_images link plus Kateto wiring.

Failing-first: `[mcp_servers.video_rag]` is absent from
`config/defaults/config.toml` until the wiring lands, so
`test_sidecar_declared_in_default_config` fails pre-change. The chain tests
drive the real describe handler against a REAL stdio sidecar (mock server
written to tmp_path, copied from the `_mcp_echo_server.py` pattern) through
a real `ExternalMcpManager` — proving the handler<->sidecar link, not the
handler itself (todo 7 owns that).
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

from kateto.core.config import McpServerSettings
from kateto.core.event import VisionDescribeRequestData, VisionDescribeResultData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin
from kateto.plugins.system.external_mcp import ExternalMcpManager

PRIMARY = "http://primary:8080/v1"
PRIMARY_MODEL = "test-vision-model"
CANNED = "sidecar saw two frames by the river"

# Mock sidecar: same stdio shape as _mcp_echo_server.py, but exposing the
# spec schema word-for-word: {prompt: string, images: string[] (data-URLs)}.
# argv: [server.py, mode, out_path?] with mode "ok" (canned text, records
# args to out_path) or "boom" (malformed tool result: the process dies
# mid-call, so the client sees a broken pipe instead of tool text).
_MOCK_SIDECAR = """
import asyncio
import json
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

MODE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None


async def main() -> None:
    server = Server("video-rag")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="describe_images",
                description="Describe up to 8 frames",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "images": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["prompt", "images"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if MODE == "boom":
            import os

            os._exit(1)
        if OUT is not None:
            with open(OUT, "w") as fh:
                json.dump(arguments, fh)
        return [TextContent(type="text", text="sidecar saw two frames by the river")]

    async with stdio_server() as (read, write):
        init = server.create_initialization_options()
        await server.run(read, write, init, raise_exceptions=True)


asyncio.run(main())
"""


def _bad_request() -> openai.BadRequestError:
    import httpx

    request = httpx.Request("POST", "http://test/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": "no image support"}})
    return openai.BadRequestError("bad request", response=response, body=None)


class _FakeCompletions:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        raise _bad_request()


class _FakeVisionClient:
    def __init__(self, calls: list) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls))


def _install_400_primary(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    monkeypatch.setattr(svp, "_openai_client", lambda *args: _FakeVisionClient(calls))


class _ResultRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="result_recorder")
        self.seen: list[VisionDescribeResultData] = []

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self.seen.append(data)


def _noise_frame(seed: int, size: tuple[int, int] = (48, 32)) -> bytes:
    import random

    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", size)
    px = img.load()
    assert px is not None
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    """Enabled plugin with neutered capture loop and 400-only primary."""
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = kwargs.pop("vision_endpoint", PRIMARY)
    plugin.vision_model = kwargs.pop("vision_model", PRIMARY_MODEL)
    plugin.vision_fallback_endpoint = kwargs.pop("vision_fallback_endpoint", None)
    plugin.vision_fallback_model = kwargs.pop("vision_fallback_model", None)
    for key, value in kwargs.items():
        setattr(plugin, key, value)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._windows.clear()
    plugin._dropped.clear()
    return plugin


async def _teardown(manager: PluginManager, *names: str) -> None:
    for name in names:
        await asyncio.wait_for(manager.disable_plugin(name), timeout=5.0)


def _write_sidecar(tmp_path: Path) -> Path:
    srv = tmp_path / "mock_video_rag.py"
    srv.write_text(_MOCK_SIDECAR)
    return srv


def _video_rag_settings(command: str, args: list[str]) -> McpServerSettings:
    return McpServerSettings(command=command, args=args)


def test_sidecar_declared_in_default_config() -> None:
    # Given: the shipped defaults (plugin-side use only, no voice entries)
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "config" / "defaults" / "config.toml"
    raw = path.read_text()
    cfg = tomllib.loads(raw)

    # When: reading the video_rag sidecar declaration
    server = cfg["mcp_servers"]["video_rag"]

    # Then: stock binary + serve args, command/args only (no env field —
    # the sidecar inherits Kateto's process env), BYO-disabled by comment,
    # and no voice routes to it (plugin-side link only).
    assert server["command"] == "video-rag"
    assert server["args"] == ["mcp", "serve"]
    assert set(server) <= {"command", "args"}
    assert "# enabled = false" in raw
    for voice in cfg["voice"].values():
        assert "video_rag" not in voice.get("mcp_servers", [])
    assert "env" not in McpServerSettings.model_fields


@pytest.mark.asyncio
async def test_sidecar_up_returns_via_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a real stdio sidecar exposing describe_images + a real manager
    srv = _write_sidecar(tmp_path)
    seen_args = tmp_path / "seen_args.json"
    mcp = ExternalMcpManager()
    mcp.configure("op", "video_rag", _video_rag_settings(sys.executable, [str(srv), "ok", str(seen_args)]))
    await asyncio.wait_for(mcp.start_all(), timeout=60.0)
    try:
        direct = await mcp.try_call_tool(
            ["video_rag"], "describe_images", {"prompt": "p", "images": ["data:image/jpeg;base64,xx"]}
        )
        assert direct is not None and CANNED in direct

        # And: the describe handler with a 400-only primary
        calls: list = []
        _install_400_primary(monkeypatch, calls)
        monkeypatch.setattr(
            svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
        )
        manager = PluginManager()
        results = _ResultRecorder()
        await manager.enable_plugin(results)
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(1), 10.0)
        plugin._append_frame("screen", _noise_frame(2), 11.0)

        # When: describing with the sidecar up
        await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane"))
        await manager.wait_for_idle()

        # Then: the chain resolves through the sidecar with the spec schema
        assert len(results.seen) == 1
        result = results.seen[0]
        assert result.via == "sidecar"
        assert CANNED in result.text
        wire_args = json.loads(seen_args.read_text())
        assert set(wire_args) == {"prompt", "images"}
        assert isinstance(wire_args["prompt"], str)
        assert isinstance(wire_args["images"], list) and 1 <= len(wire_args["images"]) <= 8
        assert all(url.startswith("data:image/") for url in wire_args["images"])
        await _teardown(manager, plugin.name, results.name)
    finally:
        await mcp.stop_all()


@pytest.mark.asyncio
async def test_sidecar_absent_degrades_without_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: the declared server name pointing at a binary that is absent
    # (existing bad-command fixture pattern from test_mcp_wait_semantics.py:63)
    mcp = ExternalMcpManager()
    mcp.configure("op", "video_rag", _video_rag_settings("not-a-real-process", []))
    await asyncio.wait_for(mcp.start_all(), timeout=60.0)  # warns, does not raise
    try:
        assert await mcp.try_call_tool(["video_rag"], "describe_images", {"prompt": "p", "images": []}) is None

        calls: list = []
        _install_400_primary(monkeypatch, calls)
        monkeypatch.setattr(
            svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
        )
        manager = PluginManager()
        results = _ResultRecorder()
        await manager.enable_plugin(results)
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(3), 20.0)
        plugin._append_frame("screen", _noise_frame(4), 21.0)

        # When: describing with no sidecar process
        await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane"))
        await manager.wait_for_idle()

        # Then: the chain degrades through the fallback links, zero crash
        assert len(results.seen) == 1
        assert results.seen[0].via == "recap"
        assert results.seen[0].text != ""
        await _teardown(manager, plugin.name, results.name)
    finally:
        await mcp.stop_all()


@pytest.mark.asyncio
async def test_sidecar_exits_immediately_degrades_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a binary that exits at once (no session ever comes up)
    mcp = ExternalMcpManager()
    mcp.configure("op", "video_rag", _video_rag_settings(sys.executable, ["-c", "pass"]))
    await asyncio.wait_for(mcp.start_all(), timeout=60.0)  # warns, does not raise
    try:
        assert await mcp.try_call_tool(["video_rag"], "describe_images", {"prompt": "p", "images": []}) is None

        calls: list = []
        _install_400_primary(monkeypatch, calls)
        monkeypatch.setattr(
            svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
        )
        manager = PluginManager()
        results = _ResultRecorder()
        await manager.enable_plugin(results)
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(5), 30.0)
        plugin._append_frame("screen", _noise_frame(6), 31.0)

        # When: describing against the dead sidecar
        await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane"))
        await manager.wait_for_idle()

        # Then: degrade, zero crash
        assert len(results.seen) == 1
        assert results.seen[0].via == "recap"
        await _teardown(manager, plugin.name, results.name)
    finally:
        await mcp.stop_all()


@pytest.mark.asyncio
async def test_sidecar_malformed_result_degrades_without_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a sidecar that advertises the tool but raises on call
    srv = _write_sidecar(tmp_path)
    mcp = ExternalMcpManager()
    mcp.configure("op", "video_rag", _video_rag_settings(sys.executable, [str(srv), "boom"]))
    await asyncio.wait_for(mcp.start_all(), timeout=60.0)
    try:
        calls: list = []
        _install_400_primary(monkeypatch, calls)
        monkeypatch.setattr(
            svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
        )
        manager = PluginManager()
        results = _ResultRecorder()
        await manager.enable_plugin(results)
        plugin = await _make_plugin(manager)
        plugin._append_frame("screen", _noise_frame(7), 40.0)
        plugin._append_frame("screen", _noise_frame(8), 41.0)

        # When: the tool call itself blows up
        await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane"))
        await manager.wait_for_idle()

        # Then: the handler swallows it into the next link, zero crash
        assert len(results.seen) == 1
        assert results.seen[0].via == "recap"
        await _teardown(manager, plugin.name, results.name)
    finally:
        await mcp.stop_all()
