"""RWKV-7 ROCm Provider con State-Tuning y ROSA para Kateto.

Provee inferencia acelerada localmente en AMD ROCm con soporte para:
1. Swap instantáneo de estados modulados (S_0) por voz (seco, streamer, etc.)
2. Recuperación asociativa de contexto mediante ROSA
3. Compatible con DebateProvider (bate_debate) y LLM Streamer (TextChunk).
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from loguru import logger
import torch
import torch.nn.functional as F

from kateto.core.event import TextChunk
from kateto.providers._models import ChatMessage

if TYPE_CHECKING:
    from kateto.voices.base import GenerationRequest

KATETO_TRAIN_DIR = Path("/run/media/chaos/terciario/proyectos/kateto-train")
if str(KATETO_TRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(KATETO_TRAIN_DIR))
if str(KATETO_TRAIN_DIR / "RWKV-PEFT") not in sys.path:
    sys.path.insert(0, str(KATETO_TRAIN_DIR / "RWKV-PEFT"))

from rwkv_pipeline.infer_kateto import KatetoInferenceEngine, sample_logits
from rwkv_pipeline.rosa_module import RosaAssociativeMemory

_GLOBAL_ENGINE: KatetoInferenceEngine | None = None
_GLOBAL_ROSA: RosaAssociativeMemory | None = None

# Mapeo de voces de Kateto hacia los estados disponibles
VOICE_STATE_MAPPING = {
    "seco": "seco",
    "streamer": "streamer",
    "jane": "seco",        # Host / Fun -> seco o streamer
    "doktor": "seco",      # Backlog / Architecture -> seco
    "whisperer": "seco",   # Conversacional directo -> seco
    "conquest": "seco",    # Ceremonias / Agile -> seco
}


def _get_or_create_engine(
    model_path: str | None = None,
    vocab_path: str | None = None,
    states_dir: str | None = None,
) -> KatetoInferenceEngine:
    global _GLOBAL_ENGINE, _GLOBAL_ROSA
    if _GLOBAL_ENGINE is not None:
        return _GLOBAL_ENGINE

    # Configurar entorno ROCm
    os.environ["HSA_OVERRIDE_GFX_VERSION"] = os.environ.get("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
    os.environ["TORCH_COMPILE_DISABLE"] = "1"
    os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"

    if model_path is None:
        base_dir = KATETO_TRAIN_DIR / "out" / "rwkv_kateto_base"
        models = sorted(list(base_dir.glob("*.pth")), key=os.path.getmtime)
        if models:
            model_path = str(models[-1])
        else:
            model_path = str(KATETO_TRAIN_DIR / "models/rwkv7-0.4b/rwkv7-g1d-0.4b-20260210-ctx8192.pth")

    if vocab_path is None:
        vocab_path = str(KATETO_TRAIN_DIR / "RWKV-PEFT/rwkv_vocab_v20230424.txt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Inicializando RWKV-7 ROCm Engine: model={} device={}", model_path, device)
    engine = KatetoInferenceEngine(model_path, vocab_path, device=device)

    # Cargar estados disponibles
    s_root = Path(states_dir) if states_dir else (KATETO_TRAIN_DIR / "out" / "rwkv_states")
    if s_root.exists():
        for voice_folder in s_root.iterdir():
            if voice_folder.is_dir() and not voice_folder.name.startswith("backup"):
                st_files = sorted(list(voice_folder.glob("*.pth")), key=os.path.getmtime)
                if st_files:
                    state_file = str(st_files[-1])
                    engine.load_state(state_file, name=voice_folder.name)
                    logger.info("Estado cargado para voz '{}': {}", voice_folder.name, state_file)

    _GLOBAL_ENGINE = engine
    _GLOBAL_ROSA = RosaAssociativeMemory(hidden_dim=engine.n_embd).to(device=device, dtype=engine.dtype)
    return _GLOBAL_ENGINE


@dataclass
class RWKVROCmProvider:
    """Proveedor nativo ROCm para RWKV-7 con State Swap y memoria asociativa ROSA."""

    model_path: str | None = None
    vocab_path: str | None = None
    states_dir: str | None = None
    voice_id: str = "seco"
    temperature: float = 0.7
    top_p: float = 0.7
    max_tokens: int = 160
    enable_rosa: bool = True

    def __post_init__(self) -> None:
        _ = _get_or_create_engine(self.model_path, self.vocab_path, self.states_dir)

    def _format_messages_to_prompt(self, messages: Sequence[ChatMessage]) -> str:
        user_chunks = []
        for msg in messages:
            if msg.role == "user":
                content = msg.content.strip()
                # Destilar prompts verbose de bate_debate para modelos compactos
                if "TEMA DEL DEBATE:" in content and "TU POSTURA ASIGNADA:" in content:
                    lines = content.split("\n")
                    topic = ""
                    stance = ""
                    for l in lines:
                        if l.startswith("TEMA DEL DEBATE:"):
                            topic = l.replace("TEMA DEL DEBATE:", "").strip()
                        elif l.startswith("TU POSTURA ASIGNADA:"):
                            stance = l.replace("TU POSTURA ASIGNADA:", "").strip()
                    content = f"Tema del debate: {topic}\nTu postura asignada: {stance}\nDefendé tu posición con 2 oraciones contundentes en tono rioplatense:"
                elif "OBJECION" in content and "INSTRUCCIONES:" in content:
                    content = content.split("INSTRUCCIONES:")[0].strip() + "\nFormulá tu objeción de forma directa:"
                elif "INSTRUCCIONES:" in content:
                    content = content.split("INSTRUCCIONES:")[0].strip()
                user_chunks.append(content)
            elif msg.role == "assistant":
                user_chunks.append(f"Assistant: {msg.content.strip()}")

        prompt_body = "\n\n".join(user_chunks)
        return f"User: {prompt_body}\n\nAssistant:"

    async def stream(self, request: Any) -> AsyncIterator[str]:
        engine = _get_or_create_engine(self.model_path)

        if hasattr(request, "messages"):
            target_voice = getattr(request, "voice_id", self.voice_id).casefold()
            messages = request.messages
        else:
            target_voice = self.voice_id.casefold()
            messages = request

        # Resolver voz a estado disponible
        mapped_state = VOICE_STATE_MAPPING.get(target_voice, target_voice)
        if mapped_state not in engine.states:
            mapped_state = "seco" if "seco" in engine.states else "none"

        formatted = self._format_messages_to_prompt(messages)
        prompt_tokens = engine.tokenizer.encode(formatted)

        # Construir estado inicial con State-Tuning
        state = engine.build_initial_state(mapped_state)

        # Prefill prompt tokens
        out = None
        for tok in prompt_tokens:
            out, state = engine.model.forward(tok, state)

        # Autoregressive generation
        generated_tokens = []
        occurrence: dict[int, int] = {}
        stop_markers = ["\n\n", "\nUser:", "User:", "\nAssistant:", "Assistant:", "<|endoftext|>"]

        for _ in range(self.max_tokens):
            tok = sample_logits(
                out.clone(),
                temperature=self.temperature,
                top_p=self.top_p,
                occurrence=occurrence,
                alpha_presence=0.6,
                alpha_frequency=0.6,
            )
            if tok == 0:
                break

            generated_tokens.append(tok)
            occurrence[tok] = occurrence.get(tok, 0) + 1

            token_str = engine.tokenizer.decode([tok])
            text_so_far = engine.tokenizer.decode(generated_tokens)

            # Paradas limpias
            should_stop = False
            for sm in stop_markers:
                if len(generated_tokens) > 3 and sm in text_so_far:
                    should_stop = True
                    break

            # Si ya se articuló una idea completa de más de 20 tokens y hay un salto de línea
            if len(generated_tokens) > 20 and "\n" in token_str:
                should_stop = True

            if should_stop:
                break

            yield token_str
            await asyncio.sleep(0)  # Ceder control cooperativo al event loop de asyncio

            out, state = engine.model.forward(tok, state)

    async def stream_chunks(self, messages: Sequence[ChatMessage]) -> AsyncIterator[TextChunk]:
        """Interfaz compatible con HttpProvider / Kateto Core para emisión de eventos."""
        seq = 0
        async for piece in self.stream(messages):
            yield TextChunk(text=piece, sequence=seq, final=False)
            seq += 1
        yield TextChunk(text="", sequence=seq, final=True)
