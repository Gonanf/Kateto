#!/usr/bin/env python3
"""MASK-1: mide el tiempo hasta el primer byte de audio de un turno vía /events/stream.

Sólo stdlib + `websockets`. Corre contra cualquier runtime con el parche de
/http_server (bug 100) aplicado; contra un master sin parche devuelve 0 frames
de audio y sale 1.

    ./.venv/bin/python script/qa/mask1_egress_client.py --port 8099
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request

import websockets


def post_event(port: int, event_name: str, data: dict, timeout: float) -> dict:
    body = json.dumps({"event_name": event_name, "data": data}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/events/send",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read().decode(errors='replace')}"}


async def run(port: int, voice: str, text: str, timeout: float) -> int:
    url = f"ws://127.0.0.1:{port}/events/stream"
    received: list[tuple[float, dict]] = []
    stop: list[str] = [""]

    async with websockets.connect(url) as ws:
        loop = asyncio.get_running_loop()
        collector = asyncio.create_task(_collect(ws, received, timeout, stop))
        ack = await loop.run_in_executor(None, post_event, port, "text_chunk",
                                        {"text": text, "sequence": 0, "voice_id": voice}, timeout)
        if "error" in ack:
            print(json.dumps({"error": ack["error"]}))
            collector.cancel()
            return 1
        try:
            await collector
        except websockets.WebSocketException as exc:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
            return 1

    first_audio_recv = next(
        ((t, f) for t, f in received if f.get("name") == "audio_output" and f["data"].get("samples_b64")), None
    )
    turn_first_audio: dict | None = None
    turn_index_voice = 0
    for t_recv, frame in received:
        data = frame.get("data") or {}
        line = {"t_recv": round(t_recv, 6), "name": frame.get("name"), "bytes": _pcm_len(data)}
        if frame.get("name") == "turn_start":
            t_in, t_first = data.get("t_in_audio"), data.get("t_first_audio_byte")
            turn_index_voice += 1
            if turn_first_audio is None:
                turn_first_audio = data
            line.update(
                turn_id=data.get("turn_id"),
                t_in_audio=t_in,
                t_first_audio_byte=t_first,
                pipeline_ms=_delta_ms(t_in, t_first),
                red_ms=_delta_ms(t_first, first_audio_recv[0] if first_audio_recv else None),
            )
        print(json.dumps(line), flush=True)

    audio = [f["data"] for _, f in received if f.get("name") == "audio_output" and f["data"].get("samples_b64")]
    first_audio_recv_ts = first_audio_recv[0] if first_audio_recv else None
    turn_end = next((f["data"] for _, f in reversed(received) if f.get("name") == "turn_end"), {})
    measured = turn_first_audio or {}
    t_in, t_first = measured.get("t_in_audio"), measured.get("t_first_audio_byte")
    pcm = b"".join(base64.b64decode(d["samples_b64"]) for d in audio)
    print(json.dumps({
        "turn_id": measured.get("turn_id"),
        "t_in_audio": t_in,
        "t_first_audio_byte": t_first,
        "t_client_recv_first_audio": first_audio_recv_ts,
        "pipeline_ms": _delta_ms(t_in, t_first),
        "red_ms": _delta_ms(t_first, first_audio_recv_ts),
        "frames": turn_end.get("frames"),
        "audio_frames": len(audio),
        "bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest() if pcm else None,
        "turn_index_voice": turn_index_voice or None,
    }), flush=True)
    if not audio or not pcm:
        print(json.dumps({
            "error": "no audio frames decoded with non-empty PCM on /events/stream",
            "stop_reason": stop[0],
            "frames_received": [f.get("name") for _, f in received],
        }), flush=True)
        return 1
    return 0


async def _collect(ws, received: list, timeout: float, stop: list[str]) -> None:
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frame = json.loads(raw)
            received.append((time.time(), frame))
            if frame.get("name") == "turn_end":
                stop[0] = "turn_end"
                return
    except asyncio.TimeoutError:
        stop[0] = f"timeout after {timeout}s"
    except websockets.ConnectionClosed:
        stop[0] = "closed"


def _pcm_len(data: dict) -> int:
    samples = data.get("samples_b64")
    return len(base64.b64decode(samples)) if samples else 0


def _delta_ms(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round((b - a) * 1000, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description="MASK-1 egress probe for /events/stream")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--voice", default="jane")
    parser.add_argument("--text", default="Hola, esto es una prueba de salida de audio.")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.port, args.voice, args.text, args.timeout))
    except (OSError, websockets.WebSocketException) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
