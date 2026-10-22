"""Reparto por ROL de los eventos que entran al historial de la voz.

Antes `VoiceAgent._remember_event` mandaba casi todo como `user` con texto
crudo: el humano, otra voz, un evento de workflow y un resultado de tool eran
indistinguibles para el modelo. Ahora (spec de dataset §1.3, decisión del dueño):

    user      -> SOLO la transcripción del humano (`TranscriptionData`)
    developer -> eventos, workflows y pedidos de otras voces (`VoiceRequestData`,
                 `GenerateData`, `Workflow*Data`, `VisionDescribeResultData`)
    assistant -> la propia voz (`TextChunk`) + `tool_call` / `tool_result`

Y el serializador RWKV (`kateto/providers/rwkv_rocm.py`) sirve el formato
`rwkv-kateto` con el marcador de cada rol: `<|im_user|>` (humano),
`<|im_dev|>` (developer) y `<|im_start|>{voz}` + `<|im_end|>` (la voz).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from kateto.core.config import VoiceSettings
from kateto.core.event import (
    EventEnvelope,
    GenerateData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VisionDescribeResultData,
    VoiceRequestData,
    WorkflowRunData,
)
from kateto.providers._models import ChatMessage
from kateto.providers.rwkv_rocm import format_messages_to_prompt
from kateto.voices.base import VoiceAgent, VoiceProfile, VoiceRole


def _voice(tmp_path: Path) -> VoiceAgent:
    profile = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.SITUATIONAL_ABSURD,
        system_prompt="system",
        relevance_terms=frozenset(),
    )
    return VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(),
    )


def _remember(voice: VoiceAgent, name: str, data: Any) -> ChatMessage:
    envelope: EventEnvelope[Any] = EventEnvelope(name=name, data=data, source="fixture")
    voice._remember_event(envelope)
    return voice._event_messages[-1]


def _vision_result() -> VisionDescribeResultData:
    return VisionDescribeResultData(
        text="terminal with code on screen",
        frame_count=5,
        kept_count=3,
        dropped=0,
        window_start=10.0,
        window_end=15.0,
        source="screen",
        via="recap",
    )


# ── reparto por rol ──────────────────────────────────────────────────────────


def test_human_transcription_is_the_only_user_turn(tmp_path: Path) -> None:
    message = _remember(_voice(tmp_path), "transcription", TranscriptionData(text="hola kateto"))
    assert message.role == "user"
    assert message.content == "hola kateto"


@pytest.mark.parametrize(
    ("name", "data"),
    (
        ("voice_request", VoiceRequestData(voice="doktor", prompt="pasame el backlog")),
        ("generate", GenerateData(prompt="contame un chiste")),
        ("workflow_run", WorkflowRunData(workflow="brief", voice="jane")),
    ),
)
def test_non_human_events_are_developer(tmp_path: Path, name: str, data: Any) -> None:
    message = _remember(_voice(tmp_path), name, data)
    assert message.role == "developer"


def test_voice_request_from_another_voice_is_not_user(tmp_path: Path) -> None:
    # El pedido de OTRA VOZ no puede salir como `user`: es indistinguible de una
    # persona hablando, que es exactamente el síntoma que se arregla.
    message = _remember(
        _voice(tmp_path),
        "voice_request",
        VoiceRequestData(voice="doktor", prompt="pasame el backlog del sprint"),
    )
    assert message.role == "developer"
    assert message.role != "user"


def test_vision_describe_result_is_developer(tmp_path: Path) -> None:
    message = _remember(_voice(tmp_path), "vision_describe_result", _vision_result())
    assert message.role == "developer"


def test_own_voice_and_tools_are_assistant(tmp_path: Path) -> None:
    voice = _voice(tmp_path)
    assert _remember(voice, "text_chunk", TextChunk(text="hola, todo bien", sequence=0)).role == "assistant"
    call = _remember(
        voice,
        "tool_call",
        ToolCallData(tool_name="read_file", arguments={"path": "x"}, correlation_id="c1", voice="jane"),
    )
    assert call.role == "assistant"
    result = _remember(
        voice,
        "tool_result",
        ToolResultData(correlation_id="c1", tool_name="read_file", result="ok", voice="jane"),
    )
    assert result.role == "assistant"


# ── render del serializador RWKV ─────────────────────────────────────────────


def test_three_roles_render_with_their_own_marker() -> None:
    # Conversación con los TRES roles. El humano bajo `<|im_user|>`, OTRO AGENTE
    # (developer) bajo `<|im_dev|>` y la voz bajo `<|im_start|>{voz}`.
    messages = (
        ChatMessage(role="system", content="SOUL + schemas (no se serializa)"),
        ChatMessage(role="user", content="hola kateto"),
        ChatMessage(role="assistant", content="hola, que onda"),
        ChatMessage(role="developer", content="evento: arrancó el workflow brief"),
        ChatMessage(role="assistant", content="tomo nota"),
        ChatMessage(role="user", content="y vos?"),
    )

    render = format_messages_to_prompt(messages, "seco")

    esperado = (
        "<|im_user|>hola kateto<|im_end|>\n<|im_start|>seco\nhola, que onda<|im_end|>"
        "<|im_dev|>evento: arrancó el workflow brief<|im_end|>\n<|im_start|>seco\ntomo nota<|im_end|>"
        "<|im_user|>y vos?<|im_end|>\n<|im_start|>seco\n"
    )
    assert render == esperado
    # El humano y el otro agente NO comparten marcador.
    assert "<|im_user|>hola kateto" in render
    assert "<|im_dev|>evento: arrancó el workflow brief" in render
    assert "<|im_dev|>hola kateto" not in render


def test_user_turn_skeleton_matches_the_canonical_engine_formatter() -> None:
    # Anclaje: el esqueleto del turno humano/voz sale del formateador canónico
    # del motor, no de una copia local del template.
    from rwkv_pipeline.infer_kateto import KatetoInferenceEngine

    render = format_messages_to_prompt(
        (ChatMessage(role="user", content="hola"),),
        "seco",
    )
    canonico = KatetoInferenceEngine.format_chat_prompt(None, "hola", "seco", None, 1)
    assert render == canonico
