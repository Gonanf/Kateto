"""kateto/tests/test_contexto_fondo.py — Tests del script scripts/contexto_fondo.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

_SPEC = importlib.util.spec_from_file_location(
    "contexto_fondo", Path(__file__).resolve().parents[2] / "scripts" / "contexto_fondo.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cf)


def test_ambient_line_cases():
    """1. _ambient_line recorta y colapsa (corto intacto, \\n→espacio, corte en palabra + …)."""
    # Caso 1: corto intacto
    assert cf._ambient_line("Hola mundo", 50) == "Hola mundo"

    # Caso 2: \n -> espacio y colapsa espacios
    assert cf._ambient_line("Hola\nmundo\r\notro\ntexto", 50) == "Hola mundo otro texto"

    # Caso 3: corte en palabra + …
    texto = "primera segunda tercera cuarta"
    # con max_chars=18, corta en el último espacio antes de 18 ("primera segunda") + …
    res = cf._ambient_line(texto, 18)
    assert res == "primera segunda…"


def test_tokens_distintivos_filtra_turno_y_system():
    """2. _tokens_distintivos no devuelve palabras presentes en el turno ni en el system."""
    bloque = "terminal con un error de compilación sobre pagos.py y latencia"
    turno = "¿Me revisás este error por favor?"
    system = "Sos una terminal inteligente"
    tokens = cf._tokens_distintivos(bloque, turno, system)

    assert "error" not in tokens
    assert "terminal" not in tokens
    assert "favor" not in tokens
    assert "compilación" in tokens
    assert "pagos" in tokens
    assert "latencia" in tokens


def test_detector_mencion():
    """3. Detector de mención: reply con sustantivo → True; reply charlatán sin sustantivo → False."""
    tokens = ["compilación", "pagos", "gunicorn"]
    reply_con_sustantivo = "Detecté un error de compilación en pagos."
    reply_charlatan = "Comprendido perfectamente, voy a revisar el estado sin novedades."

    assert cf._menciona_fondo(reply_con_sustantivo, tokens) is True
    assert cf._menciona_fondo(reply_charlatan, tokens) is False


def test_agregados_p50_par_e_impar():
    """4. Agregados: p50 de una lista par e impar (mediana real, no promedio)."""
    # Impar: [10, 20, 100], media es 43.33, mediana real es 20.0
    impar = [10, 20, 100]
    assert cf._p50(impar) == 20.0

    # Par: [10, 20, 30, 100], media es 40.0, mediana real es 25.0
    par = [10, 20, 30, 100]
    assert cf._p50(par) == 25.0


def test_guardas_turno_recortado_invalida():
    """5. Guardas: con un turno recortado entre condiciones, turno_identico es False y valido es False."""
    seeds = [1]
    turns = 1
    turno_completo = "¿Me pasás el resumen del sprint de esta semana por favor? Necesito revisar las tareas completadas."
    turno_recortado = "¿Me pasás el resumen del sprint"

    mediciones_validas = [
        {"seed": 1, "condicion": "base", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 100, "cache_n": 10, "ttft_ms": 10.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_1", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 150, "cache_n": 10, "ttft_ms": 11.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_2", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 200, "cache_n": 10, "ttft_ms": 12.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_sin_guia", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 180, "cache_n": 10, "ttft_ms": 12.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
    ]
    guardas_val, valido = cf.evaluar_guardas(mediciones_validas, seeds, turns)
    assert guardas_val["turno_identico"] is True
    assert valido is True

    mediciones_invalidas = [
        {"seed": 1, "condicion": "base", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 100, "cache_n": 10, "ttft_ms": 10.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_1", "turno_idx": 0, "turno": turno_recortado, "prompt_tokens": 150, "cache_n": 10, "ttft_ms": 11.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_2", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 200, "cache_n": 10, "ttft_ms": 12.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
        {"seed": 1, "condicion": "fondo_sin_guia", "turno_idx": 0, "turno": turno_completo, "prompt_tokens": 180, "cache_n": 10, "ttft_ms": 12.0, "reply": "ok", "menciona_fondo": False, "tokens_distintivos": []},
    ]
    guardas_inv, valido_inv = cf.evaluar_guardas(mediciones_invalidas, seeds, turns)
    assert guardas_inv["turno_identico"] is False
    assert valido_inv is False


def test_self_check_end_to_end():
    """6. --self-check end-to-end: rc == 0 y parsea como JSON valido."""
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "contexto_fondo.py"
    proc = subprocess.run(
        [sys.executable, str(script_path), "--self-check"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"Error en self-check: {proc.stderr}"
    data = json.loads(proc.stdout.strip())
    assert data["valido"] is True
    assert 0.4 <= data["tasa_mencion_no_solicitada"] <= 0.6
    assert data["delta_tokens_vs_base_p50"] > 0
    assert isinstance(data["delta_ttft_pct_p50"], (int, float))
