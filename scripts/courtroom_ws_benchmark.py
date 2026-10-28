#!/usr/bin/env python3
"""Benchmark courtroom-ws — conectividad WebSocket como gate de stream.

Mide la conectividad WS al endpoint /ws/overlay:
  - handshake HTTP 101
  - N pings con timeout configurable
  - latencia p50/p90, % pings exitosos
  - falla (exit 1) si handshake != 101, n_pings != N, o latencia_p50 > 100ms
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets


@dataclass(frozen=True, slots=True)
class PingMeasurement:
    seq: int
    latency_ms: float | None
    success: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark courtroom-ws — conectividad WebSocket como gate de stream."
    )
    parser.add_argument(
        "--url",
        type=str,
        default="ws://127.0.0.1:8099/ws/overlay",
        help="URL WebSocket (default: ws://127.0.0.1:8099/ws/overlay)",
    )
    parser.add_argument(
        "-n",
        "--n-pings",
        type=int,
        default=20,
        help="Número de pings a enviar (default: 20)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=1000,
        help="Timeout por ping en ms (default: 1000)",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=100,
        help="Intervalo entre pings en ms (default: 100)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Imprime únicamente la línea JSON final",
    )
    return parser.parse_args(argv)


async def run_benchmark(
    url: str,
    n_pings: int,
    timeout_ms: int,
    interval_ms: int,
) -> tuple[list[PingMeasurement], bool, float, float]:
    """Ejecuta el benchmark WS y devuelve mediciones, handshake_ok, p50, p90."""
    measurements: list[PingMeasurement] = []
    handshake_ok = False

    try:
        async with websockets.connect(url, open_timeout=timeout_ms / 1000.0) as ws:
            handshake_ok = True

            for seq in range(1, n_pings + 1):
                payload = json.dumps({"type": "ping", "seq": seq, "ts": time.time()}).encode()

                t0 = time.perf_counter()
                try:
                    await ws.send(payload)
                    # Esperar pong con timeout
                    pong = await asyncio.wait_for(ws.recv(), timeout=timeout_ms / 1000.0)
                    t1 = time.perf_counter()

                    # Validar que es pong para nuestro seq
                    try:
                        pong_data = json.loads(pong)
                        success = pong_data.get("type") == "pong" and pong_data.get("seq") == seq
                    except Exception:
                        success = False

                    latency_ms = round((t1 - t0) * 1000, 1)
                    measurements.append(
                        PingMeasurement(seq=seq, latency_ms=latency_ms, success=success)
                    )

                except asyncio.TimeoutError:
                    measurements.append(
                        PingMeasurement(seq=seq, latency_ms=None, success=False)
                    )
                except Exception:
                    measurements.append(
                        PingMeasurement(seq=seq, latency_ms=None, success=False)
                    )

                # Intervalo entre pings
                if seq < n_pings:
                    await asyncio.sleep(interval_ms / 1000.0)

    except Exception:
        # Error de conexión/handshake
        handshake_ok = False

    # Calcular p50 y p90 solo de pings exitosos
    successful_latencies = [m.latency_ms for m in measurements if m.success and m.latency_ms is not None]

    if successful_latencies:
        p50 = round(float(statistics.median(successful_latencies)), 1)
        sorted_lat = sorted(successful_latencies)
        n = len(sorted_lat)
        idx_p90 = min(max(0, math.ceil(0.9 * n) - 1), n - 1)
        p90 = round(float(sorted_lat[idx_p90]), 1)
    else:
        p50 = 0.0
        p90 = 0.0

    return measurements, handshake_ok, p50, p90


def main() -> None:
    args = parse_args()

    try:
        measurements, handshake_ok, p50, p90 = asyncio.run(
            run_benchmark(
                args.url,
                args.n_pings,
                args.timeout_ms,
                args.interval_ms,
            )
        )
    except Exception as exc:
        # Error inesperado en el benchmark
        output_dict = {
            "benchmark": "courtroom-ws",
            "url": args.url,
            "ws_conectado_pct": 0.0,
            "latencia_p50_ms": 0.0,
            "latencia_p90_ms": 0.0,
            "handshake_ok": False,
            "n_pings": args.n_pings,
            "n_exitosos": 0,
            "error": f"Benchmark error: {exc}",
        }
        print(json.dumps(output_dict, separators=(",", ":")))
        sys.exit(1)

    n_exitosos = sum(1 for m in measurements if m.success)
    ws_conectado_pct = round((n_exitosos / args.n_pings) * 100, 2) if args.n_pings > 0 else 0.0

    # Criterios de fallo (exit 1 = REJECT para el driver)
    reject = False
    reject_reasons: list[str] = []

    if not handshake_ok:
        reject = True
        reject_reasons.append("handshake_failed")
    if n_exitosos != args.n_pings:
        reject = True
        reject_reasons.append(f"n_pings_mismatch: got {n_exitosos}/{args.n_pings}")
    if p50 > 100.0:
        reject = True
        reject_reasons.append(f"latencia_p50_ms_exceeded: {p50} > 100")

    output_dict = {
        "benchmark": "courtroom-ws",
        "url": args.url,
        "ws_conectado_pct": ws_conectado_pct,
        "latencia_p50_ms": p50,
        "latencia_p90_ms": p90,
        "handshake_ok": handshake_ok,
        "n_pings": args.n_pings,
        "n_exitosos": n_exitosos,
    }

    if not args.json_only:
        print(f"=== Benchmark courtroom-ws ===")
        print(f"URL: {args.url}")
        print(f"N pings: {args.n_pings} | Timeout: {args.timeout_ms}ms | Interval: {args.interval_ms}ms")
        print(f"Handshake: {'OK (101)' if handshake_ok else 'FAIL'}")
        print(f"Pings exitosos: {n_exitosos}/{args.n_pings} ({ws_conectado_pct}%)")
        print(f"Latencia p50: {p50} ms | p90: {p90} ms")
        if reject:
            print(f"REJECT: {', '.join(reject_reasons)}")
        else:
            print("PASS")

    print(json.dumps(output_dict, separators=(",", ":")))
    sys.exit(1 if reject else 0)


if __name__ == "__main__":
    main()