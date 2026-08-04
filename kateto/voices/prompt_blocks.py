from __future__ import annotations

from typing import Callable


def _boson_prompt_block() -> str:
    return (
        "AUDIO GENERATION INSTRUCTION (Boson TTS): Output text will be spoken via Boson TTS. "
        "Keep speech expressive, natural, and avoid unpronounceable characters or code blocks."
    )


_PROMPT_BLOCK_REGISTRY: dict[str, Callable[[], str]] = {
    "boson": _boson_prompt_block,
}


def get_agent_prompt_block(provider: str) -> str | None:
    fn = _PROMPT_BLOCK_REGISTRY.get(provider.lower())
    if fn is not None:
        return fn()
    return None
