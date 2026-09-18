"""`isError` del sidecar ya no se pierde: el cliente lo propaga y la visión lo usa.

Cubre el bug 117: `ExternalMcpClient.call_tool` descartaba el flag `isError`
del sidecar video-rag, así que errores sin forma conocida (p. ej.
`image 0 exceeds ~1.5MB data-URL cap (...)`) llegaban como texto plano y el
plugin los narraba como descripción.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from loguru import logger

from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin, _is_sidecar_error
from kateto.plugins.system.external_mcp import (
    ExternalMcpClient,
    ExternalMcpManager,
    ToolCallResult,
)


def _text_part(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _session_result(text: str, *, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(content=[_text_part(text)], is_error=is_error)


class _FakeSession:
    def __init__(self, result: SimpleNamespace | BaseException) -> None:
        self._result = result

    async def call_tool(self, name: str, arguments: dict):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _client_with(session: _FakeSession | None) -> ExternalMcpClient:
    client = ExternalMcpClient("video_rag", "video-rag", ["mcp", "serve"])
    client._session = session  # type: ignore[assignment]
    return client


@pytest.mark.asyncio
async def test_call_tool_result_propagates_is_error_and_call_tool_returns_text() -> None:
    # Given: el sidecar responde isError=true con el texto del cap de data-URL
    err = "image 0 exceeds ~1.5MB data-URL cap (9999999 bytes)"
    client = _client_with(_FakeSession(_session_result(err, is_error=True)))

    # When: se llama por el camino nuevo y por el viejo
    result = await client.call_tool_result("describe_images", {"prompt": "p", "images": []})
    text = await client.call_tool("describe_images", {"prompt": "p", "images": []})

    # Then: el flag viaja en el resultado y el texto plano sigue igual
    assert isinstance(result, ToolCallResult)
    assert result.is_error is True
    assert result.text == err
    assert result.server == "video_rag"
    assert result.tool == "describe_images"
    assert text == err


@pytest.mark.asyncio
async def test_call_tool_result_ok_is_not_error() -> None:
    # Given: una descripción válida sin flag
    client = _client_with(_FakeSession(_session_result("a cat on a desk")))

    # When:
    result = await client.call_tool_result("describe_images", {})

    # Then:
    assert result.is_error is False
    assert result.text == "a cat on a desk"


@pytest.mark.asyncio
async def test_timeout_marks_is_error_with_timeout_text() -> None:
    # Given: la sesión cuelga (el wait_for de 30 s la corta)
    client = _client_with(_FakeSession(asyncio.TimeoutError()))

    # When:
    result = await client.call_tool_result("describe_images", {})
    text = await client.call_tool("describe_images", {})

    # Then: el timeout es error y el texto JSON histórico se mantiene
    assert result.is_error is True
    assert result.text == '{"error": "MCP tool timed out: describe_images"}'
    assert text == result.text


@pytest.mark.asyncio
async def test_client_not_started_marks_is_error() -> None:
    # Given: cliente sin sesión
    client = _client_with(None)

    # When:
    result = await client.call_tool_result("describe_images", {})
    text = await client.call_tool("describe_images", {})

    # Then: compat total en el texto, pero ahora marcado como error
    assert result.is_error is True
    assert result.text == '{"error": "MCP client not started"}'
    assert text == result.text


@pytest.mark.asyncio
async def test_manager_try_call_tool_result_keeps_flag_and_text_compat() -> None:
    # Given: un manager con cliente corriendo que marca isError
    err = "describe_images needs at least one image data-URL"
    manager = ExternalMcpManager()

    async def has_tool(name: str) -> bool:
        return name == "describe_images"

    async def call_tool_result(name: str, arguments: dict) -> ToolCallResult:
        return ToolCallResult(text=err, is_error=True, server="video_rag", tool=name)

    manager._clients["video_rag"] = SimpleNamespace(  # type: ignore[assignment]
        is_running=True, has_tool=has_tool, call_tool_result=call_tool_result
    )

    # When:
    result = await manager.try_call_tool_result(["video_rag"], "describe_images", {})
    text = await manager.try_call_tool(["video_rag"], "describe_images", {})
    missing = await manager.try_call_tool_result(["video_rag"], "nope", {})

    # Then:
    assert result is not None and result.is_error is True and result.text == err
    assert text == err
    assert missing is None


def _sections() -> tuple[list, list]:
    parts = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xx"}}]
    sections = [("screen", [(1.0, b"x")], 1, "p", parts)]
    content: list = [{"type": "text", "text": "p"}, *parts]
    return sections, content


class _FlaggedMCP:
    def __init__(self, result: ToolCallResult) -> None:
        self._result = result

    async def try_call_tool_result(self, servers, tool, args):
        return self._result


class _LegacyStrMCP:
    """Sin try_call_tool_result: sólo el camino viejo de texto plano."""

    def __init__(self, result: str | None) -> None:
        self.result = result

    async def try_call_tool(self, servers, tool, args):
        return self.result


@pytest.mark.asyncio
async def test_plugin_flagged_data_url_cap_error_goes_to_recap_and_logs_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: el sidecar marca isError con un error sin forma conocida
    err = "image 0 exceeds ~1.5MB data-URL cap (9999999 bytes)"
    flagged = ToolCallResult(text=err, is_error=True, server="video_rag", tool="describe_images")
    monkeypatch.setattr(
        svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=_FlaggedMCP(flagged))
    )
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    sections, content = _sections()
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        # When: cae al fallback
        text, via = await plugin._describe_fallback("p", content, {}, sections)
    finally:
        logger.remove(handler_id)

    # Then: no se usa como descripción — va al recap que la nombra
    assert via == "recap"
    assert err not in text.split("recap", 1)[0]
    assert err in text
    joined = "\n".join(messages)
    assert "[vision] sidecar describe_images error" in joined
    assert err in joined


@pytest.mark.asyncio
async def test_plugin_valid_caption_returns_sidecar_and_logs_raw_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: una descripción válida sin flag
    caption = "a cat on a desk by the river"
    ok = ToolCallResult(text=caption, is_error=False, server="video_rag", tool="describe_images")
    monkeypatch.setattr(
        svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=_FlaggedMCP(ok))
    )
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    sections, content = _sections()
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        # When:
        text, via = await plugin._describe_fallback("p", content, {}, sections)
    finally:
        logger.remove(handler_id)

    # Then: via=sidecar y el log crudo incluye el texto
    assert via == "sidecar"
    assert text == caption
    joined = "\n".join(messages)
    assert caption in joined


@pytest.mark.asyncio
async def test_plugin_secondary_net_still_catches_unflagged_vlm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: el camino viejo con un error de forma conocida y sin flag
    err = "video-rag describe_images: VLM unreachable at http://x (model y)"
    assert _is_sidecar_error(err) is True
    monkeypatch.setattr(
        svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=_LegacyStrMCP(err))
    )
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    sections, content = _sections()

    # When:
    text, via = await plugin._describe_fallback("p", content, {}, sections)

    # Then: la red secundaria lo manda al recap igual
    assert via == "recap"
    assert err in text
