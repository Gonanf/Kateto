from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import torch

from .base import AudioInputConfigurationError, SAMPLE_RATE


SILERO_WINDOW_SAMPLES: Final = 512
PCM_S16_MAX: Final = 32_768


@dataclass(frozen=True, slots=True)
class SileroBackendUnavailableError(Exception):
    reason: str
    action: str

    def __str__(self) -> str:
        return f"Silero VAD backend unavailable: {self.reason}. {self.action}"


class SileroModelAdapter:
    def __init__(
        self,
        model: Callable,
        to_tensor: Callable,
    ) -> None:
        self._model = model
        self._to_tensor = to_tensor

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        if sample_rate != SAMPLE_RATE or not samples or len(samples) % 2:
            return 0.0
        pcm_values = tuple(
            int.from_bytes(
                samples[index : index + 2],
                byteorder="little",
                signed=True,
            )
            / PCM_S16_MAX
            for index in range(0, len(samples), 2)
        )
        scores: list[float] = []
        # ponytail: torch.no_grad prevents the Silero VAD model's internal
        # LSTM hidden state from chaining autograd graphs across calls.
        # Without this, ~31 inferences/sec builds an ever-growing computation
        # graph chain through the model's state, leaking memory until OOM.
        with torch.no_grad():
            for start in range(0, len(pcm_values), SILERO_WINDOW_SAMPLES):
                window = pcm_values[start : start + SILERO_WINDOW_SAMPLES]
                if len(window) < SILERO_WINDOW_SAMPLES:
                    window += (0.0,) * (SILERO_WINDOW_SAMPLES - len(window))
                scores.append(self._model(self._to_tensor(window), sample_rate).item())
        return max(scores)


class PythonSileroModelLoader:
    def load_model(self) -> SileroModelAdapter:
        silero_vad = importlib.import_module("silero_vad")
        torch = importlib.import_module("torch")
        load_silero_vad = getattr(silero_vad, "load_silero_vad")
        to_tensor = getattr(torch, "tensor")
        return SileroModelAdapter(model=load_silero_vad(), to_tensor=to_tensor)


def load_silero_model() -> SileroModelAdapter:
    """Load the installed Silero VAD model or explain how to repair setup."""
    try:
        return PythonSileroModelLoader().load_model()
    except ImportError as error:
        raise AudioInputConfigurationError(
            field="vad_model",
            reason=(
                "Silero VAD requires the `silero-vad` and `torch` packages; "
                "install them with `uv add silero-vad torch` and restart Kateto"
            ),
        ) from error
    except AttributeError as error:
        raise AudioInputConfigurationError(
            field="vad_model",
            reason=(
                "the installed `silero-vad` package does not expose its model "
                "loader; reinstall it with `uv add --reinstall silero-vad`"
            ),
        ) from error
    except (OSError, RuntimeError) as error:
        raise AudioInputConfigurationError(
            field="vad_model",
            reason=(
                "Silero model assets could not be loaded; reinstall `silero-vad` "
                "so its packaged model assets are available"
            ),
        ) from error


class InstalledSileroBackend:
    def __init__(self, model_loader: PythonSileroModelLoader | None = None) -> None:
        self._model_loader = (
            PythonSileroModelLoader() if model_loader is None else model_loader
        )

    def load_model(self) -> SileroModelAdapter:
        try:
            return self._model_loader.load_model()
        except (AttributeError, ImportError) as error:
            raise SileroBackendUnavailableError(
                reason="the required `silero-vad` runtime is not installed",
                action="install it with `uv add silero-vad` and restart Kateto",
            ) from error
        except (OSError, RuntimeError) as error:
            raise SileroBackendUnavailableError(
                reason="the configured Silero model assets could not be loaded",
                action="reinstall `silero-vad` so its packaged model assets are available",
            ) from error
