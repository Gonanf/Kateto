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


# ── formato `rwkv-kateto` (el que VIO el modelo) ─────────────────────────────
# No es ChatML ni RWKV-World. Marcadores en TEXTO (el vocab no tiene tokens
# especiales): `<|im_user|>` (humano), `<|im_start|>{voz}` + `<|im_end|>` (la
# propia voz) y `<|im_dev|>` (rol no-humano `developer`: eventos, workflows,
# pedidos de otras voces).
#
# El esqueleto del turno humano/voz NO se copia acá: lo emite el formateador
# canónico del motor (`KatetoInferenceEngine.format_chat_prompt`), que es el
# anclaje que entrena y sirve byte a byte. El marcador `<|im_dev|>` todavía no
# vive en ese formateador (su definición canónica está en `chat_template.py` del
# repo de training, card FORMATO aparte): se serializa acá en UN solo lugar, con
# la gramática de `<|im_user|>`, y se alinea cuando esa card aterrice.
IM_DEV = "<|im_dev|>"
IM_END = "<|im_end|>"


def _turno_humano_abierto(texto: str, voice: str) -> str:
    """Turno ABIERTO del motor: `<|im_user|>{texto}<|im_end|>\\n<|im_start|>{voz}\\n`."""
    return KatetoInferenceEngine.format_chat_prompt(None, texto, voice, None, 1)


def _encabezado_voz(voice: str) -> str:
    """`<|im_start|>{voz}\\n`, tomado del formateador canónico (no copiado)."""
    return _turno_humano_abierto("", voice).split("\n", 1)[1]


def _destilar_prompt_debate(texto: str) -> str:
    """Destila prompts verbose de bate_debate para modelos compactos."""
    if "TEMA DEL DEBATE:" in texto and "TU POSTURA ASIGNADA:" in texto:
        topic = stance = ""
        for linea in texto.split("\n"):
            if linea.startswith("TEMA DEL DEBATE:"):
                topic = linea.replace("TEMA DEL DEBATE:", "").strip()
            elif linea.startswith("TU POSTURA ASIGNADA:"):
                stance = linea.replace("TU POSTURA ASIGNADA:", "").strip()
        return (
            f"Tema del debate: {topic}\nTu postura asignada: {stance}\n"
            "Defendé tu posición con 2 oraciones contundentes en tono rioplatense:"
        )
    if "OBJECION" in texto and "INSTRUCCIONES:" in texto:
        return texto.split("INSTRUCCIONES:")[0].strip() + "\nFormulá tu objeción de forma directa:"
    if "INSTRUCCIONES:" in texto:
        return texto.split("INSTRUCCIONES:")[0].strip()
    return texto


def _turnos(messages: Sequence[ChatMessage]) -> list[tuple[str, str, str | None]]:
    """Agrupa la conversación en turnos `(rol, texto, respuesta|None)`.

    Un turno lo abre un mensaje que NO es de la voz (`user` o `developer`) y lo
    cierra la respuesta `assistant`. Los `system` (SOUL, schemas, memoria) NO se
    serializan: el formato `rwkv-kateto` no tiene marcador de sistema y la
    personalidad de la voz vive en sus pesos/estado, no en el prompt.
    """
    turnos: list[tuple[str, str, str | None]] = []
    for msg in messages:
        texto = msg.content.strip()
        if not texto:
            continue
        if msg.role == "system":
            continue
        if msg.role == "assistant":
            if turnos and turnos[-1][2] is None and turnos[-1][0] != "assistant":
                rol, cabeza, _ = turnos[-1]
                turnos[-1] = (rol, cabeza, texto)
            else:
                turnos.append(("assistant", texto, None))
            continue
        if msg.role == "user":
            texto = _destilar_prompt_debate(texto)
        turnos.append((msg.role, texto, None))  # user | developer
    return turnos


def format_messages_to_prompt(messages: Sequence[ChatMessage], voice: str) -> str:
    """Serializa la conversación al formato `rwkv-kateto` con el rol correcto.

    `user` -> `<|im_user|>…<|im_end|>`; `developer` -> `<|im_dev|>…<|im_end|>`;
    `assistant` -> `<|im_start|>{voz}\\n…<|im_end|>`. El último turno queda
    ABIERTO (sin cierre), que es el prefijo que el modelo continúa.
    """
    voz = "seco" if voice == "none" else voice
    turnos = _turnos(messages)
    partes: list[str] = []
    for i, (rol, texto, respuesta) in enumerate(turnos):
        ultimo = i == len(turnos) - 1
        if rol == "assistant":
            partes.append(_encabezado_voz(voz) + texto + IM_END)
            continue
        if rol == "developer":
            cabeza = f"{IM_DEV}{texto}{IM_END}\n" + _encabezado_voz(voz)
        else:  # user: el esqueleto canónico lo emite el motor
            cabeza = _turno_humano_abierto(texto, voz)
        if ultimo and respuesta is None:
            partes.append(cabeza)  # prompt abierto: la voz responde acá
        else:
            partes.append(cabeza + (respuesta or "") + IM_END)
    return "".join(partes)


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

    def _format_messages_to_prompt(
        self, messages: Sequence[ChatMessage], *, voice: str | None = None
    ) -> str:
        return format_messages_to_prompt(messages, voice or self.voice_id)

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

        formatted = self._format_messages_to_prompt(messages, voice=mapped_state)
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
        # Paradas del formato `rwkv-kateto` (el que vio el modelo). El cierre de
        # turno es `<|im_end|>`; los marcadores viejos (`User:`/`Assistant:`) eran
        # del template divorciado del entrenamiento y se eliminaron.
        stop_markers = ["<|endoftext|>", "<|im_end|>", "<|im_user|>", IM_DEV, "<|im_start|>"]

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
