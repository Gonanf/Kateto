"""Check de SpeakerTracker: dos voces y textos distintos -> owner / other / owner / other."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kateto.plugins.audio_processor.speakers import SpeakerTracker

VOICES = Path.home() / ".local/share/piper/voices"
A = VOICES / "es_AR-daniela-high.onnx"
B = VOICES / "es_ES-davefx-medium.onnx"

# Textos distintos a propósito: con el mismo texto dos síntesis son idénticas y la
# prueba no mediría variación intra-hablante.
TURNOS = [
    ("a1", A, "owner", "Che, mirá, esto es una prueba de hablante para la aplicación del teléfono."),
    ("b1", B, "other", "El otro día fui al supermercado y me olvidé la billetera en casa."),
    ("a2", A, "owner", "Me parece que mañana va a llover y no quiero salir a la calle."),
    ("b2", B, "other", "Vamos a tomar algo por la zona de Palermo cuando termine el trabajo."),
]


def sintetizar(modelo: Path, texto: str, salida: Path) -> tuple[bytes, int]:
    subprocess.run(
        [sys.executable, "-m", "piper", "-m", str(modelo), "-f", str(salida)],
        input=texto.encode(),
        check=True,
        capture_output=True,
    )
    with wave.open(str(salida)) as w:
        return w.readframes(w.getnframes()), w.getframerate()


def main() -> int:
    if not A.is_file() or not B.is_file():
        print(f"faltan voces de piper: {A} / {B}")
        return 2
    tracker = SpeakerTracker()
    obtenido: list[str | None] = []
    with tempfile.TemporaryDirectory() as tmp:
        for nombre, voz, _, texto in TURNOS:
            pcm, sr = sintetizar(voz, texto, Path(tmp) / f"{nombre}.wav")
            etiqueta = tracker.assign(tracker.embed(pcm, sr))
            obtenido.append(etiqueta)
            print(f"{nombre}: {etiqueta}")
    esperado = [e for _, _, e, _ in TURNOS]
    ok = obtenido == esperado
    print("OK" if ok else f"FAIL (esperado {esperado})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
