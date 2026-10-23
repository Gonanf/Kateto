from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _import_latencia_turno_module():
    if "latencia_turno" in sys.modules:
        return sys.modules["latencia_turno"]
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "latencia_turno.py"
    spec = importlib.util.spec_from_file_location("latencia_turno", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_latencia_turno_subprocess() -> None:
    # Given: raíz del repo derivada de __file__ y el script latencia_turno.py
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "latencia_turno.py"
    cmd = [sys.executable, str(script_path), "3", "--warmup", "0"]

    # When: se ejecuta el script con 3 turnos y warmup 0 por subprocess
    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=90,
    )

    # Then: exit code 0 y JSON válido con las guardas en cero
    assert result.returncode == 0, (
        f"Script falló con código {result.returncode}.\n"
        f"Stdout:\n{result.stdout}\nStderr:\n{result.stderr}"
    )
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines, "Stdout vacío tras correr latencia_turno.py"
    last_line = lines[-1]
    assert last_line.startswith("{"), f"La última línea no es JSON: {last_line}"

    data = json.loads(last_line)
    assert data["benchmark"] == "harness-latencia"
    assert data["valido"] is True
    assert data["turnos_medidos"] == 3
    assert data["turnos_partidos"] == 0
    assert data["audio_truncado"] == 0
    assert data["respondio_antes"] == 0
    assert data["latencia_p50_ms"] >= 0


def test_guardas_respondio_antes_invalida() -> None:
    # Given: función pura de guardas y muestra sintética donde la respuesta precede a t0
    mod = _import_latencia_turno_module()
    sample = mod.TurnMeasurement(
        turn_index=0,
        t0=10.0,
        t1=9.0,  # t1 < t0
        t_flush=9.5,
        speech_bytes=12_800,
        transcribed_bytes=54_400,
        audio_chunks_count=1,
    )

    # When: se evalúan las guardas
    resultado = mod.evaluar_guardas([sample], n_esperado=1)

    # Then: respondio_antes se incrementa y valido es False
    assert resultado.valido is False
    assert resultado.respondio_antes == 1
    assert resultado.turnos_partidos == 0
    assert resultado.audio_truncado == 0


def test_guardas_turnos_partidos_invalida() -> None:
    # Given: muestra sintética donde ASR recibió más de un audio_chunk
    mod = _import_latencia_turno_module()
    sample = mod.TurnMeasurement(
        turn_index=0,
        t0=10.0,
        t1=12.5,
        t_flush=12.0,
        speech_bytes=12_800,
        transcribed_bytes=54_400,
        audio_chunks_count=2,  # > 1
    )

    # When: se evalúan las guardas
    resultado = mod.evaluar_guardas([sample], n_esperado=1)

    # Then: turnos_partidos se incrementa y valido es False
    assert resultado.valido is False
    assert resultado.turnos_partidos == 1


def test_guardas_audio_truncado_invalida() -> None:
    # Given: muestra sintética donde los bytes transcritos son menores a los de habla
    mod = _import_latencia_turno_module()
    sample = mod.TurnMeasurement(
        turn_index=0,
        t0=10.0,
        t1=12.5,
        t_flush=12.0,
        speech_bytes=12_800,
        transcribed_bytes=6_400,  # < speech_bytes
        audio_chunks_count=1,
    )

    # When: se evalúan las guardas
    resultado = mod.evaluar_guardas([sample], n_esperado=1)

    # Then: audio_truncado se incrementa y valido es False
    assert resultado.valido is False
    assert resultado.audio_truncado == 1


def test_guardas_turnos_medidos_incompletos_invalida() -> None:
    # Given: lista de turnos menor al N esperado
    mod = _import_latencia_turno_module()
    sample = mod.TurnMeasurement(
        turn_index=0,
        t0=10.0,
        t1=12.5,
        t_flush=12.0,
        speech_bytes=12_800,
        transcribed_bytes=54_400,
        audio_chunks_count=1,
    )

    # When: se evalúan 1 turno con n_esperado = 2
    resultado = mod.evaluar_guardas([sample], n_esperado=2)

    # Then: valido es False porque turnos_medidos != n_esperado
    assert resultado.valido is False
    assert resultado.turnos_medidos == 1


def test_guardas_valido_completo() -> None:
    # Given: mediciones sintéticas válidas que cumplen todas las guardas
    mod = _import_latencia_turno_module()
    samples = [
        mod.TurnMeasurement(
            turn_index=i,
            t0=10.0 + i * 5.0,
            t1=13.0 + i * 5.0,
            t_flush=12.9 + i * 5.0,
            speech_bytes=12_800,
            transcribed_bytes=54_400,
            audio_chunks_count=1,
        )
        for i in range(3)
    ]

    # When: se evalúan con n_esperado = 3
    resultado = mod.evaluar_guardas(samples, n_esperado=3)

    # Then: todas las guardas pasan
    assert resultado.valido is True
    assert resultado.turnos_medidos == 3
    assert resultado.turnos_partidos == 0
    assert resultado.audio_truncado == 0
    assert resultado.respondio_antes == 0
