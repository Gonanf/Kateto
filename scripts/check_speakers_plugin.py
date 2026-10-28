"""Check de integración: el plugin de parakeet etiqueta el hablante de cada turno.

Ejercita el camino real (_buffer + _label_speaker) con audio de dos voces distintas,
sin pasar por el ASR ni por el transporte HTTP.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.plugins.audio_processor.parakeet import ParakeetAudioProcessor

V = Path.home() / ".local/share/piper/voices"
A = V / "es_AR-daniela-high.onnx"
B = V / "es_ES-davefx-medium.onnx"
TURNOS = [
    (A, "owner", "Che, mirá, esto es una prueba de hablante para la aplicación del teléfono."),
    (B, "other", "El otro día fui al supermercado y me olvidé la billetera en casa."),
    (A, "owner", "Me parece que mañana va a llover y no quiero salir a la calle."),
]


def pcm_de(modelo: Path, texto: str) -> AudioData:
    out = Path(tempfile.mktemp(suffix=".wav"))
    subprocess.run(
        [sys.executable, "-m", "piper", "-m", str(modelo), "-f", str(out)],
        input=texto.encode(),
        check=True,
        capture_output=True,
    )
    with wave.open(str(out)) as w:
        frames, sr = w.readframes(w.getnframes()), w.getframerate()
    out.unlink(missing_ok=True)
    return AudioData(samples=frames, sample_rate=sr, channels=1, format="pcm_s16le")


def main() -> int:
    plugin = ParakeetAudioProcessor(PluginSettings(speaker_id=True))
    etiquetas = []
    for modelo, esperado, texto in TURNOS:
        plugin._buffer(pcm_de(modelo, texto))
        etiqueta = plugin._label_speaker(TranscriptionData(text=texto)).speaker
        etiquetas.append(etiqueta)
        print(f"{etiqueta} (esperado {esperado})")
    ok = etiquetas == [e for _, e, _ in TURNOS]
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
