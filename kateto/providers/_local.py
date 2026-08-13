from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from kateto.core.config import PluginSettings
from kateto.core.exceptions import ProviderError

__all__ = ["LocalCommandProvider", "_capture", "_first_json"]


class LocalCommandProvider:
    """Subprocess-backed model: no HTTP server, binary invoked per call.

    Selected when PluginSettings.command is set; otherwise the HTTP provider
    is used. `model` is interpreted as a model-file PATH in local mode.
    """

    def __init__(self, settings: PluginSettings) -> None:
        if not settings.command:
            msg = f"{type(self).__name__} requires settings.command (local backend)"
            raise ProviderError(msg)
        self._command = settings.command
        self._args: Sequence[str] = tuple(settings.args or ())
        self._model = settings.model

    async def __aenter__(self) -> "LocalCommandProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        return None

    def _argv(self, *extra: str) -> list[str]:
        return [self._command, *extra, *self._args]


async def _capture(argv: Sequence[str], *, timeout_s: float = 120.0) -> str:
    """Run a binary, return stdout, raise on non-zero exit."""
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except FileNotFoundError as error:
        raise ProviderError(f"local command not found: {argv[0]}") from error
    except asyncio.TimeoutError as error:
        if proc is not None:
            proc.kill()
        raise ProviderError(f"local command timed out after {timeout_s}s") from error
    if proc.returncode != 0:
        raise ProviderError(
            f"local command failed ({proc.returncode}): {err.decode(errors='replace')[:200]}"
        )
    return out.decode(errors="replace")


def _first_json(text: str) -> dict | None:
    """Extract the first balanced {...} object from messy stdout."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _read_whisper_json(candidates: Sequence[Path]) -> dict | None:
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                return None
    return None
