from __future__ import annotations

import asyncio
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import Final


_VOICE_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_FILE_LOCKS: dict[Path, asyncio.Lock] = {}


@dataclass(frozen=True, slots=True)
class PathIsolationError(Exception):
    attempted_path: str
    voice: str

    def __str__(self) -> str:
        return f"voice {self.voice} cannot access path {self.attempted_path!r}"


def _lock_for(path: Path) -> asyncio.Lock:
    resolved_path = path.resolve()
    existing_lock = _FILE_LOCKS.get(resolved_path)
    if existing_lock is not None:
        return existing_lock
    created_lock = asyncio.Lock()
    _FILE_LOCKS[resolved_path] = created_lock
    return created_lock


async def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    await atomic_write_bytes(path, content.encode(encoding))


async def atomic_write_bytes(path: Path, content: bytes) -> None:
    target_path = path.resolve()
    async with _lock_for(target_path):
        _write_atomically(target_path, content)


def _write_atomically(target_path: Path, content: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=f".{target_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, target_path)
        _sync_directory(target_path.parent)
    finally:
        with suppress(FileNotFoundError):
            temporary_path.unlink()


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class VoiceFileStore:
    config_dir: Path
    voice: str
    root: Path

    @classmethod
    def for_voice(cls, *, config_dir: Path, voice: str) -> VoiceFileStore:
        if _VOICE_NAME.fullmatch(voice) is None:
            raise PathIsolationError(attempted_path=voice, voice=voice)
        resolved_config_dir = config_dir.resolve()
        voice_root = resolved_config_dir / "voices" / voice
        resolved_voice_root = voice_root.resolve()
        if voice_root.is_symlink() or not resolved_voice_root.is_relative_to(resolved_config_dir):
            raise PathIsolationError(attempted_path=str(voice_root), voice=voice)
        return cls(
            config_dir=resolved_config_dir,
            voice=voice,
            root=resolved_voice_root,
        )

    def path_for(self, relative_path: str | Path) -> Path:
        candidate_path = Path(relative_path)
        windows_path = PureWindowsPath(relative_path)
        if (
            candidate_path.is_absolute()
            or windows_path.is_absolute()
            or ".." in PurePath(relative_path).parts
            or ".." in windows_path.parts
        ):
            raise PathIsolationError(attempted_path=str(relative_path), voice=self.voice)
        resolved_path = (self.root / candidate_path).resolve()
        if not resolved_path.is_relative_to(self.root):
            raise PathIsolationError(attempted_path=str(relative_path), voice=self.voice)
        return resolved_path

    async def write_text(self, relative_path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
        await atomic_write_text(self.path_for(relative_path), content, encoding=encoding)
