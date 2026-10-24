#!/usr/bin/env python3
"""scripts/contexto_fondo.py — Medir el costo y el efecto del contexto de fondo.

Responde la pregunta: ¿cuánto cuesta en tokens de entrada y TTFT mandar
contexto visual de fondo a TODAS las voces, y el modelo comenta solo o no?
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
from pathlib import Path
import re
import statistics
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8092/v1"
DEFAULT_MODEL = "local"
DEFAULT_SEEDS = [1, 2, 3]
DEFAULT_TURNS = 4
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TIMEOUT = 120.0
DEFAULT_AMBIENT_MAX_CHARS = 280
DEFAULT_OUT_FILE = "out/eureka-contexto-fondo.json"

DEFAULT_SYSTEM_PROMPT = "Sos Jane, una asistente de voz ejecutiva, precisa y directa."

GUIA_CONTEXTO_VISUAL = (
    "BLOQUES DE CONTEXTO VISUAL: un mensaje que empieza con \"[contexto visual]\" es fondo, no un pedido.\n"
    "Usalo sólo si viene al caso del turno; no lo narres por iniciativa propia, no repitas lo ya dicho y\n"
    "no inventes nada fuera de él."
)

TURNOS = [
    "¿Me pasás el resumen del sprint de esta semana por favor? Necesito revisar las tareas completadas.",
    "Necesito saber qué pendientes críticos tengo asignados hoy para poder organizar toda mi jornada de trabajo.",
    "Contame cómo viene el presupuesto mensual proyectado y si estamos dentro de los márgenes financieros acordados.",
    "¿Cuándo está programada la próxima reunión de retrospectiva y quiénes son los participantes convocados para coordinar?",
    "¿Podrías darme un desglose de los hitos principales alcanzados por el equipo durante este último ciclo comercial?",
    "¿Tenemos algún bloqueo reportado por el equipo de infraestructura técnica que afecte la continuidad del servicio?",
]

BLOQUES = [
    "terminal con un error de compilación en rojo sobre pagos.py y un gráfico de barras a la derecha mostrando métricas de transacciones concurrentes con latencia anómala y trazas de depuración de gunicorn.",
    "hoja de cálculo con la columna IVA marcada en amarillo y una celda con 128.400 pesos destacada junto al balance trimestral de liquidación impositiva y conciliación bancaria pendiente de validación.",
    "pestaña del navegador con la documentación de sqlite-vec abierta y un subrayado azul señalando funciones de incrustación vectorial y similitud coseno en un entorno de pruebas con memoria aislada.",
]

CONDICIONES = ["base", "fondo_1", "fondo_2", "fondo_sin_guia"]

_SELF_CHECK_COUNTER = 0


def _ambient_line(text: str, max_chars: int = 280) -> str:
    """Una línea, \\n→espacio, corte en el último espacio antes de max_chars + '…'."""
    cleaned = " ".join(text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").split())
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    last_space = cut.rfind(" ")
    if last_space != -1:
        return cut[:last_space] + "…"
    return cut + "…"


def _tokens_distintivos(bloque: str | list[str], turno: str, system: str) -> list[str]:
    """Palabra alfanumérica en minúsculas >= 5 caracteres del bloque que no está en turno ni system."""
    if isinstance(bloque, list):
        bloque_text = " ".join(bloque)
    else:
        bloque_text = str(bloque)
    pat = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)
    palabras_bloque = {
        w.lower() for w in pat.findall(bloque_text)
        if len(w) >= 5
    }
    palabras_filtro = {
        w.lower() for w in pat.findall(f"{turno} {system}")
    }
    return sorted(palabras_bloque - palabras_filtro)


def _menciona_fondo(reply: str, tokens_distintivos: list[str]) -> bool:
    """True si reply contiene algún token distintivo."""
    if not tokens_distintivos:
        return False
    pat = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)
    reply_tokens = {w.lower() for w in pat.findall(reply)}
    return bool(reply_tokens.intersection(tokens_distintivos))


def _p50(values: list[float | int]) -> float:
    """Mediana real (no promedio de promedios)."""
    if not values:
        return 0.0
    return float(statistics.median(values))


def _load_system_prompt(custom_path: str | None = None) -> str:
    """Carga el system prompt desde archivo o usa default."""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p.read_text(encoding="utf-8")

    default_p = Path("config/defaults/voices/jane/SOUL.md")
    if default_p.is_file():
        return default_p.read_text(encoding="utf-8")

    script_p = Path(__file__).resolve().parents[1] / "config/defaults/voices/jane/SOUL.md"
    if script_p.is_file():
        return script_p.read_text(encoding="utf-8")

    return DEFAULT_SYSTEM_PROMPT


def _build_messages(
    condicion: str,
    turno: str,
    system_base: str,
    ambient_max_chars: int = DEFAULT_AMBIENT_MAX_CHARS,
) -> tuple[str, list[dict[str, str]], list[str]]:
    """Construye el system prompt y la lista de mensajes según la condición."""
    if condicion == "fondo_sin_guia":
        sys_prompt = system_base.strip()
    else:
        sys_prompt = f"{system_base.strip()}\n\n{GUIA_CONTEXTO_VISUAL}"

    bloques_cond: list[str] = []
    if condicion == "fondo_1":
        bloques_cond = [BLOQUES[0]]
    elif condicion in ("fondo_2", "fondo_sin_guia"):
        bloques_cond = [BLOQUES[0], BLOQUES[1]]

    messages: list[dict[str, str]] = [{"role": "system", "content": sys_prompt}]
    for b in bloques_cond:
        line = _ambient_line(b, ambient_max_chars)
        messages.append({"role": "user", "content": f"[contexto visual] {line}"})
    messages.append({"role": "user", "content": turno})

    return sys_prompt, messages, bloques_cond


def _stream_request(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    seed: int,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    """Envía solicitud a /chat/completions con streaming y devuelve métricas."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "seed": seed,
        "temperature": temperature,
        "max_tokens": 160,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.perf_counter()
    ttft_ms: float | None = None
    reply_parts: list[str] = []
    prompt_tokens: int | None = None
    cache_n: int | None = None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t0) * 1000.0
                        reply_parts.append(content)

                usage = chunk.get("usage")
                if isinstance(usage, dict):
                    if "prompt_tokens" in usage and usage["prompt_tokens"] is not None:
                        prompt_tokens = usage["prompt_tokens"]
                    details = usage.get("prompt_tokens_details")
                    if isinstance(details, dict) and "cached_tokens" in details:
                        cache_n = details["cached_tokens"]

                timings = chunk.get("timings")
                if isinstance(timings, dict):
                    if prompt_tokens is None and "prompt_n" in timings and timings["prompt_n"] is not None:
                        prompt_tokens = timings["prompt_n"]
                    if cache_n is None and "cache_n" in timings and timings["cache_n"] is not None:
                        cache_n = timings["cache_n"]

    except Exception as exc:
        return {"error": str(exc)}

    if prompt_tokens is None:
        sys.stderr.write(
            "Error: la respuesta no incluyó usage.prompt_tokens ni timings.prompt_n.\n"
        )
        sys.exit(2)

    if ttft_ms is None:
        ttft_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "prompt_tokens": prompt_tokens,
        "cache_n": cache_n,
        "ttft_ms": round(ttft_ms, 2),
        "reply": "".join(reply_parts),
    }


def evaluar_guardas(
    mediciones: list[dict[str, Any]],
    seeds: list[int],
    turns: int,
    ambient_max_chars: int = DEFAULT_AMBIENT_MAX_CHARS,
) -> tuple[dict[str, bool], bool]:
    """Evalúa las 4 guardas requeridas por la card."""
    sin_reintentos_ocultos = all("error" not in m for m in mediciones)

    expected_n = len(seeds) * turns
    n_completo = all(
        len([m for m in mediciones if m["condicion"] == c and "error" not in m]) == expected_n
        for c in CONDICIONES
    )

    turno_identico = True
    contexto_suma_tokens = True

    index_map: dict[tuple[int, str, int], dict[str, Any]] = {
        (m["seed"], m["condicion"], m["turno_idx"]): m for m in mediciones
    }

    for s in seeds:
        for t_idx in range(turns):
            m_base = index_map.get((s, "base", t_idx))
            m_f1 = index_map.get((s, "fondo_1", t_idx))
            m_f2 = index_map.get((s, "fondo_2", t_idx))
            m_fsg = index_map.get((s, "fondo_sin_guia", t_idx))

            if not (m_base and m_f1 and m_f2 and m_fsg):
                turno_identico = False
                contexto_suma_tokens = False
                continue

            base_text = m_base.get("turno", "")
            base_sha = hashlib.sha256(base_text.encode("utf-8")).hexdigest()

            for m_cond in (m_f1, m_f2, m_fsg):
                c_text = m_cond.get("turno", "")
                c_sha = hashlib.sha256(c_text.encode("utf-8")).hexdigest()
                if c_sha != base_sha or len(c_text) < len(base_text):
                    turno_identico = False

            pt_base = m_base.get("prompt_tokens")
            pt_f1 = m_f1.get("prompt_tokens")
            pt_f2 = m_f2.get("prompt_tokens")
            pt_fsg = m_fsg.get("prompt_tokens")

            if any(pt is None for pt in (pt_base, pt_f1, pt_f2, pt_fsg)):
                contexto_suma_tokens = False
            else:
                if not (pt_f1 >= pt_base and (pt_f1 - pt_base) <= 1 * ambient_max_chars):
                    contexto_suma_tokens = False
                if not (pt_f2 >= pt_base and (pt_f2 - pt_base) <= 2 * ambient_max_chars):
                    contexto_suma_tokens = False
                if not ((pt_fsg - pt_base) <= 2 * ambient_max_chars):
                    contexto_suma_tokens = False

    guardas = {
        "turno_identico": turno_identico,
        "contexto_suma_tokens": contexto_suma_tokens,
        "n_completo": n_completo,
        "sin_reintentos_ocultos": sin_reintentos_ocultos,
    }
    valido = all(guardas.values())
    return guardas, valido


def calcular_agregados(mediciones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Calcula agregados por condición: n, p50s, tasas, min/max."""
    base_runs = {
        (m["seed"], m["turno_idx"]): m
        for m in mediciones
        if m["condicion"] == "base" and "error" not in m
    }

    condiciones_agregadas: dict[str, dict[str, Any]] = {}

    for cond in CONDICIONES:
        cond_runs = [m for m in mediciones if m["condicion"] == cond and "error" not in m]
        n = len(cond_runs)
        prompt_tokens_p50 = _p50([m["prompt_tokens"] for m in cond_runs if m.get("prompt_tokens") is not None])
        ttft_ms_p50 = _p50([m["ttft_ms"] for m in cond_runs if m.get("ttft_ms") is not None])
        ttft_ms_min = min((m["ttft_ms"] for m in cond_runs if m.get("ttft_ms") is not None), default=0.0)
        ttft_ms_max = max((m["ttft_ms"] for m in cond_runs if m.get("ttft_ms") is not None), default=0.0)

        caches = [m["cache_n"] for m in cond_runs if m.get("cache_n") is not None]
        cache_n_p50 = _p50(caches) if caches else None

        menciones = sum(1 for m in cond_runs if m.get("menciona_fondo"))
        tasa_mencion = round(menciones / n, 4) if n > 0 else 0.0

        deltas_tokens: list[float | int] = []
        deltas_ttft_pct: list[float] = []

        for m in cond_runs:
            base_m = base_runs.get((m["seed"], m["turno_idx"]))
            if base_m and base_m.get("prompt_tokens") is not None and m.get("prompt_tokens") is not None:
                deltas_tokens.append(m["prompt_tokens"] - base_m["prompt_tokens"])
            if base_m and base_m.get("ttft_ms") is not None and m.get("ttft_ms") is not None:
                base_ttft = base_m["ttft_ms"]
                if base_ttft > 0:
                    deltas_ttft_pct.append(((m["ttft_ms"] - base_ttft) / base_ttft) * 100.0)
                else:
                    deltas_ttft_pct.append(0.0)

        delta_tokens_vs_base_p50 = _p50(deltas_tokens)
        delta_ttft_pct_p50 = round(_p50(deltas_ttft_pct), 2)

        condiciones_agregadas[cond] = {
            "n": n,
            "prompt_tokens_p50": prompt_tokens_p50,
            "ttft_ms_p50": round(ttft_ms_p50, 2),
            "ttft_ms_min": round(ttft_ms_min, 2),
            "ttft_ms_max": round(ttft_ms_max, 2),
            "cache_n_p50": cache_n_p50,
            "delta_tokens_vs_base_p50": delta_tokens_vs_base_p50,
            "delta_ttft_pct_p50": delta_ttft_pct_p50,
            "tasa_mencion_no_solicitada": tasa_mencion,
        }

    return condiciones_agregadas


class _MockChatHandler(http.server.BaseHTTPRequestHandler):
    """Manejador HTTP falso para --self-check (offline, determinista)."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        global _SELF_CHECK_COUNTER
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        body = json.loads(body_bytes.decode("utf-8"))
        messages = body.get("messages", [])

        total_chars = sum(len(m.get("content", "")) for m in messages)
        prompt_tokens = total_chars // 4

        has_background = any(
            m.get("content", "").startswith("[contexto visual]") for m in messages
        )

        if has_background:
            _SELF_CHECK_COUNTER += 1
            if _SELF_CHECK_COUNTER % 2 == 1:
                # 50% de las requests mencionan tokens raros de los bloques
                chunks_text = [
                    "Revisando el sistema ",
                    "veo una compilación con error en gunicorn ",
                    "y saldo de conciliación impositiva.",
                ]
            else:
                chunks_text = [
                    "El estado operativo ",
                    "es completamente normal y estable ",
                    "sin requerir acciones adicionales.",
                ]
        else:
            chunks_text = [
                "Procesando el turno ",
                "del usuario sin ",
                "contexto adicional presente.",
            ]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        time.sleep(0.005 + (len(messages) * 0.001))

        for text in chunks_text:
            chunk = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "local"),
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.002)

        final_chunk = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": body.get("model", "local"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 15,
                "total_tokens": prompt_tokens + 15,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
            "timings": {
                "prompt_n": prompt_tokens,
                "cache_n": 10,
            },
        }
        self.wfile.write(f"data: {json.dumps(final_chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run_measurement(
    base_url: str,
    model: str,
    seeds: list[int],
    turns: int,
    temperature: float,
    timeout: float,
    ambient_max_chars: int,
    system_prompt_file: str | None,
) -> dict[str, Any]:
    """Ejecuta el protocolo de medición sobre todas las semillas, condiciones y turnos."""
    system_base = _load_system_prompt(system_prompt_file)
    turnos_usados = TURNOS[:turns]
    mediciones: list[dict[str, Any]] = []

    for seed in seeds:
        for condicion in CONDICIONES:
            for turno_idx, turno in enumerate(turnos_usados):
                sys_prompt, messages, bloques_usados = _build_messages(
                    condicion=condicion,
                    turno=turno,
                    system_base=system_base,
                    ambient_max_chars=ambient_max_chars,
                )
                tokens_dist = _tokens_distintivos(bloques_usados, turno, sys_prompt)

                req_res = _stream_request(
                    base_url=base_url,
                    model=model,
                    messages=messages,
                    seed=seed,
                    temperature=temperature,
                    timeout=timeout,
                )

                if "error" in req_res:
                    medicion = {
                        "seed": seed,
                        "condicion": condicion,
                        "turno_idx": turno_idx,
                        "turno": turno,
                        "error": req_res["error"],
                        "prompt_tokens": None,
                        "cache_n": None,
                        "ttft_ms": None,
                        "reply": None,
                        "menciona_fondo": False,
                        "tokens_distintivos": tokens_dist,
                    }
                else:
                    reply = req_res["reply"]
                    menciona = _menciona_fondo(reply, tokens_dist)
                    medicion = {
                        "seed": seed,
                        "condicion": condicion,
                        "turno_idx": turno_idx,
                        "turno": turno,
                        "prompt_tokens": req_res["prompt_tokens"],
                        "cache_n": req_res["cache_n"],
                        "ttft_ms": req_res["ttft_ms"],
                        "reply": reply,
                        "menciona_fondo": menciona,
                        "tokens_distintivos": tokens_dist,
                    }
                mediciones.append(medicion)

    guardas, valido = evaluar_guardas(
        mediciones=mediciones,
        seeds=seeds,
        turns=turns,
        ambient_max_chars=ambient_max_chars,
    )

    condiciones_agregadas = calcular_agregados(mediciones)

    # Métricas de nivel superior para conveniencia y auditoría
    fondo_1_agg = condiciones_agregadas.get("fondo_1", {})
    tasa_mencion_top = fondo_1_agg.get("tasa_mencion_no_solicitada", 0.0)
    delta_tokens_top = fondo_1_agg.get("delta_tokens_vs_base_p50", 0.0)
    delta_ttft_top = fondo_1_agg.get("delta_ttft_pct_p50", 0.0)

    resultado = {
        "valido": valido,
        "guardas": guardas,
        "condiciones": condiciones_agregadas,
        "tasa_mencion_no_solicitada": tasa_mencion_top,
        "delta_tokens_vs_base_p50": delta_tokens_top,
        "delta_ttft_pct_p50": delta_ttft_top,
        "mediciones": mediciones,
        "config": {
            "base_url": base_url,
            "model": model,
            "seeds": seeds,
            "turns": turns,
            "temperature": temperature,
            "ambient_max_chars": ambient_max_chars,
        },
    }
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description="Medir costo y efecto del contexto de fondo.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL del endpoint OpenAI.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Nombre del modelo.")
    parser.add_argument("--seeds", default=None, help="Semillas separadas por coma (ej. 1,2,3).")
    parser.add_argument("--turns", type=int, default=None, help="Cantidad de turnos (1-6).")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--ambient-max-chars", type=int, default=DEFAULT_AMBIENT_MAX_CHARS)
    parser.add_argument("--system-prompt-file", default=None)
    parser.add_argument("--out", default=None, help="Ruta del archivo de salida JSON.")
    parser.add_argument("--self-check", action="store_true", help="Modo auto-chequeo con servidor offline.")

    args = parser.parse_args()

    # Resolver seeds y turns según self-check
    if args.seeds is not None:
        seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    else:
        seeds = [1, 2] if args.self_check else DEFAULT_SEEDS

    if args.turns is not None:
        turns = args.turns
    else:
        turns = 2 if args.self_check else DEFAULT_TURNS

    base_url = args.base_url
    server = None
    if args.self_check:
        global _SELF_CHECK_COUNTER
        _SELF_CHECK_COUNTER = 0
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockChatHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base_url = f"http://127.0.0.1:{port}/v1"

    out_file = args.out
    if not args.self_check and out_file is None:
        out_file = DEFAULT_OUT_FILE

    try:
        resultado = run_measurement(
            base_url=base_url,
            model=args.model,
            seeds=seeds,
            turns=turns,
            temperature=args.temperature,
            timeout=args.timeout,
            ambient_max_chars=args.ambient_max_chars,
            system_prompt_file=args.system_prompt_file,
        )
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    json_str = json.dumps(resultado, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write(json_str + "\n")
    sys.stdout.flush()

    if out_file:
        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")

    sys.exit(0 if resultado["valido"] else 1)


if __name__ == "__main__":
    main()
