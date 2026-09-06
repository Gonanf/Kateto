from __future__ import annotations

import math
import struct


def calculate_raw_rms(pcm_data: bytes, sample_width: int = 2) -> float:
    """Calculate raw RMS amplitude (0.0 to 1.0) from 16-bit signed PCM samples."""
    if not pcm_data:
        return 0.0
    count = len(pcm_data) // sample_width
    if count == 0:
        return 0.0
    try:
        samples = struct.unpack(f"<{count}h", pcm_data[: count * sample_width])
        sum_squares = sum(s * s for s in samples)
        rms = math.sqrt(sum_squares / count) / 32768.0
        return max(0.0, min(1.0, rms))
    except Exception:
        return 0.0


def normalize_rms(
    raw_rms: float,
    noise_threshold: float = 0.01,
    peak_threshold: float = 0.8,
) -> float:
    """Normalize raw RMS removing noise floor and scaling to peak threshold."""
    if raw_rms <= noise_threshold:
        return 0.0
    if peak_threshold <= noise_threshold:
        return 1.0 if raw_rms > noise_threshold else 0.0
    factor = (raw_rms - noise_threshold) / (peak_threshold - noise_threshold)
    return max(0.0, min(1.0, factor))


def apply_ema(
    current_value: float,
    previous_ema: float,
    alpha: float = 0.3,
) -> float:
    """Apply Exponential Moving Average smoothing with physical inertia."""
    smoothed = alpha * current_value + (1.0 - alpha) * previous_ema
    if smoothed < 1e-4:
        return 0.0
    return max(0.0, min(1.0, smoothed))


def map_rms_to_jaw_transform(
    rms: float,
    max_offset_y: float = 16.0,
    max_rotation_deg: float = 4.5,
    noise_floor: float = 0.05,
) -> tuple[float, float]:
    """Map normalized RMS to jaw kinematics (translateY in px, rotate in deg).

    Spec:
    - rms < 0.05 -> (0.0, 0.0)
    - factor = clamp((rms - 0.05) / 0.95, 0.0, 1.0)
    - jawOffsetY = factor * 16.0
    - jawRotation = factor * 4.5
    """
    if rms < noise_floor:
        return (0.0, 0.0)
    denominator = 1.0 - noise_floor
    factor = (rms - noise_floor) / denominator if denominator > 0 else 0.0
    factor = max(0.0, min(1.0, factor))
    offset_y = factor * max_offset_y
    rotation = factor * max_rotation_deg
    return (round(offset_y, 4), round(rotation, 4))


def map_rms_to_puppet_transform(
    rms: float,
    *,
    max_offset_y: float = 16.0,
    max_rotation_deg: float = 4.5,
    max_head_offset_y: float = 1.8,
    noise_floor: float = 0.05,
) -> dict[str, float]:
    """Backend-authoritative puppet kinematics for 2-image puppet.

    Returns dict with jawOffsetY, jawRotation, jawOffsetX, headOffsetY.
    jawOffsetX is deterministic (no per-frame jitter); headOffsetY is subtle
    opposite bob (~10% of jaw) so head moves sutilmente.
    """
    if rms < noise_floor:
        return {"jawOffsetX": 0.0, "jawOffsetY": 0.0, "jawRotation": 0.0, "headOffsetY": 0.0}
    denominator = 1.0 - noise_floor
    factor = (rms - noise_floor) / denominator if denominator > 0 else 0.0
    factor = max(0.0, min(1.0, factor))
    jaw_offset_y = round(factor * max_offset_y, 4)
    jaw_rotation = round(factor * max_rotation_deg, 4)
    head_offset_y = round(-factor * max_head_offset_y, 4)
    return {
        "jawOffsetX": 0.0,
        "jawOffsetY": jaw_offset_y,
        "jawRotation": jaw_rotation,
        "headOffsetY": head_offset_y,
    }


class RMSProcessor:
    """Processes PCM audio in real-time with windowing, noise thresholding and EMA smoothing."""

    def __init__(
        self,
        *,
        alpha: float = 0.3,
        noise_threshold: float = 0.01,
        peak_threshold: float = 0.8,
        window_ms: float = 20.0,
        sample_rate: int = 24_000,
    ) -> None:
        self.alpha = alpha
        self.noise_threshold = noise_threshold
        self.peak_threshold = peak_threshold
        self.window_ms = window_ms
        self.sample_rate = sample_rate
        self._current_ema: float = 0.0

    @property
    def current_ema(self) -> float:
        return self._current_ema

    def process(self, pcm_data: bytes) -> float:
        """Process PCM data and return the smoothed normalized RMS value."""
        if not pcm_data:
            return self._current_ema

        # ponytail: process in ~20ms sub-windows to smooth EMA over multi-frame chunks
        bytes_per_sample = 2
        samples_per_window = max(1, int(self.sample_rate * (self.window_ms / 1000.0)))
        window_bytes = samples_per_window * bytes_per_sample

        if len(pcm_data) <= window_bytes:
            raw = calculate_raw_rms(pcm_data)
            norm = normalize_rms(raw, self.noise_threshold, self.peak_threshold)
            self._current_ema = apply_ema(norm, self._current_ema, self.alpha)
        else:
            for offset in range(0, len(pcm_data), window_bytes):
                window = pcm_data[offset : offset + window_bytes]
                if len(window) < bytes_per_sample:
                    continue
                raw = calculate_raw_rms(window)
                norm = normalize_rms(raw, self.noise_threshold, self.peak_threshold)
                self._current_ema = apply_ema(norm, self._current_ema, self.alpha)

        return self._current_ema

    def reset(self) -> None:
        self._current_ema = 0.0
