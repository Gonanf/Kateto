#!/usr/bin/env python3
"""Vigilante del LLM de voz (:8092): detecta degradacion silenciosa y repara la unit."""

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PROMPT = "Conta en una frase que es un vigilante de servicio."

logger = logging.getLogger("vigilante-voice-llm")


def _setup_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _default_estado_path() -> str:
    try:
        uid = os.getuid()
        run_user = Path(f"/run/user/{uid}")
        if run_user.is_dir():
            return str(run_user / "kateto-voice-llm-watchdog.json")
    except (AttributeError, OSError):
        pass
    return str(Path(tempfile.gettempdir()) / "kateto-voice-llm-watchdog.json")


def medir_tok_s(url: str, max_tokens: int, timeout: float = 30.0) -> float | None:
    """POST {url}/v1/chat/completions y devuelve timings.predicted_per_second o None."""
    if max_tokens < 2:
        max_tokens = 2

    endpoint = f"{url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "cache_prompt": True,
    }

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read()
            data = json.loads(body.decode("utf-8"))
            timings = data.get("timings")
            if isinstance(timings, dict):
                pps = timings.get("predicted_per_second")
                if pps is not None:
                    return float(pps)
            return None
    except Exception:
        return None


def decidir(mediciones: list[float | None], umbral: float, intentos: int) -> str:
    """Decide el estado segun las mediciones: 'sano' | 'degradado' | 'indeterminado'.

    - None cuenta como degradada (endpoint caido tambien es degradacion).
    - 'degradado' solo si hay `intentos` mediciones seguidas por debajo de `umbral`.
    """
    if not mediciones:
        return "indeterminado"

    consecutive_degraded = 0
    max_consecutive_degraded = 0
    for m in mediciones:
        if m is None or m < umbral:
            consecutive_degraded += 1
            if consecutive_degraded > max_consecutive_degraded:
                max_consecutive_degraded = consecutive_degraded
        else:
            consecutive_degraded = 0

    if max_consecutive_degraded >= intentos:
        return "degradado"

    if all(m is not None and m >= umbral for m in mediciones):
        return "sano"

    return "indeterminado"


def reiniciar(unit: str, simular: bool = False, timeout: float = 180.0) -> bool:
    """systemctl --user restart <unit> (subprocess.run, captura salida).

    simular=True => no lo ejecuta.
    Devuelve True si rc==0 (o si simular).
    """
    if simular:
        return True
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "restart", unit],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode == 0
    except Exception:
        return False


def leer_estado(path: str | Path) -> dict:
    """Lee el estado JSON desde el archivo indicado. Si no existe o falla, devuelve {}."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def escribir_estado(path: str | Path, data: dict) -> None:
    """Escritura atomica de JSON en path usando un archivo temporal y os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def main(
    argv: list[str] | None = None,
    medir=medir_tok_s,
    reparar=reiniciar,
    reloj=time.time,
    dormir=time.sleep,
) -> int:
    """Punto de entrada del vigilante."""
    _setup_logging()
    try:
        parser = argparse.ArgumentParser(description="Vigilante del LLM de voz")
        parser.add_argument("--url", default="http://127.0.0.1:8092")
        parser.add_argument("--unit", default="kateto-voice-llm.service")
        parser.add_argument("--umbral-tok-s", type=float, default=15.0)
        parser.add_argument("--intentos", type=int, default=2)
        parser.add_argument("--max-tokens", type=int, default=8)
        parser.add_argument("--cooldown-s", type=float, default=600.0)
        parser.add_argument("--estado", default=_default_estado_path())
        parser.add_argument("--simular", action="store_true")

        args = parser.parse_args(argv)

        mediciones: list[float | None] = []
        for i in range(args.intentos):
            if i > 0:
                dormir(1.0)
            val = medir(args.url, args.max_tokens)
            mediciones.append(val)

        decision = decidir(mediciones, args.umbral_tok_s, args.intentos)

        if decision == "sano":
            validos = [m for m in mediciones if m is not None]
            avg = sum(validos) / len(validos) if validos else 0.0
            logger.info("sano: %.1f tok/s", avg)
            return 0

        if decision == "indeterminado":
            medidos_str = ", ".join(f"{m:.1f}" if m is not None else "None" for m in mediciones)
            logger.info("indeterminado: mediciones [%s]", medidos_str)
            return 0

        if decision == "degradado":
            estado = leer_estado(args.estado)
            ahora = reloj()
            ultimo_reinicio = estado.get("ultimo_reinicio")

            if ultimo_reinicio is not None and (ahora - ultimo_reinicio) < args.cooldown_s:
                logger.error("degradado y en cooldown, no reinicio")
                return 6

            medidos_str = ", ".join(f"{m:.1f}" if m is not None else "None" for m in mediciones)
            logger.error("degradado detectado en %s: %s tok/s (umbral %.1f)", args.unit, medidos_str, args.umbral_tok_s)

            try:
                ok = reparar(args.unit, simular=args.simular)
            except TypeError:
                ok = reparar(args.unit)

            if ok:
                estado["ultimo_reinicio"] = ahora
                escribir_estado(args.estado, estado)
                logger.info("reinicio exitoso de %s", args.unit)
                return 3
            else:
                logger.info("reinicio fallido de %s", args.unit)
                return 4

        return 0
    except Exception as exc:
        logger.error("error inesperado: %s", exc)
        return 5


if __name__ == "__main__":
    sys.exit(main())
