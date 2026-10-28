"""Etiqueta de hablante ("¿quién habla?") con un embedding de voz ONNX.

Modelo: ERes2Net de 3D-Speaker (39 MB, ONNX, CPU) — el mismo que usa sherpa-onnx.
Entrada: fbank kaldi de 80 mels a 16 kHz. Salida: vector unitario por tramo.
Medido con dos voces de piper y textos distintos: misma voz 0,75-0,87 de similitud,
voces distintas 0,19-0,21. Umbral 0,5 sobra de margen.

ponytail: agrupa hablantes por similitud (no identifica personas entre sesiones ni
separa voces casi iguales); para eso haría falta un modelo de reconocimiento de
locutor y audio de enrolamiento.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import numpy as np

_DEFAULT_SR = 16_000
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)


def default_model_path() -> Path:
    env = os.environ.get("KATETO_SPEAKER_MODEL")
    if env:
        return Path(env)
    return Path.home() / ".cache/kateto-speakers/eres2net.onnx"


class SpeakerTracker:
    """Agrupa tramos de audio en hablantes por similitud de embedding (coseno)."""

    def __init__(self, *, model_path: Path | None = None, threshold: float = 0.5, max_speakers: int = 4) -> None:
        self.model_path = model_path or default_model_path()
        self.threshold = threshold
        self.max_speakers = max_speakers
        self._centroids: list[np.ndarray] = []
        self._counts: list[int] = []
        self._session = None
        self.owner: int | None = None

    # -- modelo ------------------------------------------------------------
    def _ensure_model(self):
        if self._session is not None:
            return self._session
        if not self.model_path.is_file():
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL, self.model_path)  # noqa: S310 - URL fija
        import onnxruntime as ort

        self._session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        return self._session

    # -- embedding ---------------------------------------------------------
    def embed(self, samples: bytes, sample_rate: int = _DEFAULT_SR) -> np.ndarray | None:
        """PCM s16le mono -> vector unitario (embedding de locutor)."""
        if not samples or len(samples) < sample_rate // 2:  # <0.5 s: no hay timbre
            return None
        import torch
        import torchaudio

        audio = np.frombuffer(samples[: len(samples) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        if audio.size < sample_rate // 2:
            return None
        wave = torch.from_numpy(audio)
        if sample_rate != _DEFAULT_SR:
            wave = torchaudio.functional.resample(wave, sample_rate, _DEFAULT_SR)
        feats = torchaudio.compliance.kaldi.fbank(
            wave.unsqueeze(0), num_mel_bins=80, sample_frequency=_DEFAULT_SR, dither=0.0
        ).numpy()[None]
        session = self._ensure_model()
        out = session.run(None, {session.get_inputs()[0].name: feats})[0]
        vec = np.asarray(out).reshape(-1, out.shape[-1]).mean(axis=0)
        norm = float(np.linalg.norm(vec))
        return None if norm == 0.0 else vec / norm

    # -- asignación --------------------------------------------------------
    def assign(self, embedding: np.ndarray | None) -> str | None:
        """Devuelve 'owner', 'other' u 'other2'... None si no hay embedding."""
        if embedding is None:
            return None
        vec = embedding
        if not self._centroids:
            self._add(vec)
            self.owner = 0
            return "owner"
        sims = [float(vec @ c) for c in self._centroids]
        best = int(np.argmax(sims))
        if sims[best] >= self.threshold:
            # media móvil: el timbre deriva con el micrófono y el volumen
            n = self._counts[best]
            updated = (self._centroids[best] * n + vec) / (n + 1)
            self._centroids[best] = updated / max(float(np.linalg.norm(updated)), 1e-9)
            self._counts[best] = n + 1
        elif len(self._centroids) < self.max_speakers:
            self._add(vec)
            best = len(self._centroids) - 1
        return "owner" if best == self.owner else ("other" if best == 1 else f"other{best}")

    def _add(self, vec: np.ndarray) -> None:
        self._centroids.append(vec)
        self._counts.append(1)
