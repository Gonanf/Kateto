#!/usr/bin/env python3
"""Probe del wire ToolSearch del REPO real (kateto/voices/tools.py, KatetoToolset).

Contra un echo server (sin inferencia) valida que, con `defer_loading=True` y la
capability ToolSearch auto-inyectada por pydantic_ai:
  1. turn 1: el wire lleva solo ALWAYS_TOOLS + search_tools; las diferidas NO viajan.
  2. tras un search_tools, request 2: la tool descubierta aparece con su schema
     COMPLETO de parameters (reveal) y las demas diferidas siguen ocultas.

Salida: 0 si pasa, 1 si no.
"""
from __future__ import annotations

import json
import sys
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT: list[dict] = []     # respuestas guionadas
BODIES: list[dict] = []     # requests capturados


class ScriptedEcho(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(n)
        try:
            BODIES.append(json.loads(raw))
        except Exception:
            BODIES.append({})
        msg = SCRIPT.pop(0) if SCRIPT else {"role": "assistant", "content": "ok"}
        body = json.dumps({
            "id": "chatcmpl-probe",
            "object": "chat.completion",
            "created": 0,
            "model": "echo",
            "choices": [{
                "index": 0,
                "message": msg,
                "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop",
            }],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:  # silencio
        return


def fn_name(tool: dict) -> str | None:
    return (tool.get("function") or tool).get("name")


def main() -> int:
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    from kateto.voices.tools import ALWAYS_TOOLS, KatetoToolset, VoiceToolExecutor

    srv = HTTPServer(("127.0.0.1", 0), ScriptedEcho)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(name: str, args: str) -> dict:
        return {"role": "assistant", "tool_calls": [{
            "id": "call-1", "type": "function", "function": {"name": name, "arguments": args},
        }]}

    with tempfile.TemporaryDirectory() as tmp:
        executor = VoiceToolExecutor(config_dir=Path(tmp))
        toolset = KatetoToolset(executor).toolset
        model = OpenAIChatModel(
            model_name="echo",
            provider=OpenAIProvider(base_url=f"http://127.0.0.1:{port}/v1", api_key="sk-probe"),
        )
        agent = Agent(model=model, system_prompt="probe", toolsets=[toolset])
        SCRIPT.extend([
            call("search_tools", '{"queries": ["read file"]}'),          # turn 1
            call("read_file", '{"path": "SOUL.md"}'),                    # turn 2 (reveal)
            {"role": "assistant", "content": "sin mas"},                 # turn 3
        ])
        agent.run_sync("probe", model_settings={"temperature": 0.0, "max_tokens": 16})
    srv.shutdown()

    ok = True
    bodies = [b for b in BODIES if b.get("tools")]
    if not bodies:
        print("FALLO: ningun request con tools capturado")
        return 1

    wire1 = [fn_name(t) for t in bodies[0]["tools"]]
    esperado1 = sorted({*ALWAYS_TOOLS, "search_tools"})
    print("[turn 1] wire:", [n for n in wire1 if n != "search_tools"])
    print("[turn 1] esperado:", esperado1)
    if [n for n in wire1 if n != "search_tools"] and sorted(n for n in wire1 if n != "search_tools") == esperado1 and "search_tools" in wire1:
        print("[turn 1]                 OK")
    else:
        ok = False
        print("[turn 1] FALLO: el wire no es ALWAYS_TOOLS + search_tools")
    search = next(t.get("function") for t in bodies[0]["tools"] if fn_name(t) == "search_tools")
    catalogo = search.get("description", "")
    if "- write_file" in catalogo and "- run_command" in catalogo:
        print("[turn 1] catalogo name — desc en search_tools: OK")
    else:
        ok = False
        print("[turn 1] catalogo: FALLO (sin write_file/run_command)")

    if len(bodies) < 2:
        ok = False
        print("[turn 2] FALLO: no hubo request 2 (reveal)")
    else:
        wire2 = [t.get("function") for t in bodies[1]["tools"]]
        read_file = next((f for f in wire2 if f.get("name") == "read_file"), None)
        path_schema = (read_file or {}).get("parameters", {}).get("properties", {}).get("path", {})
        if path_schema.get("type") == "string":
            print("[turn 2] read_file revelada con schema completo: OK")
        else:
            ok = False
            print("[turn 2] FALLO: read_file sin schema completo tras search_tools")
        ocultas = [f.get("name") for f in wire2 if f.get("name") not in esperado1 | {"read_file"}]
        if ocultas:
            ok = False
            print(f"[turn 2] FALLO: aparecerian diferidas no reveladas: {ocultas}")
        else:
            print("[turn 2] otras diferidas siguen ocultas: OK")

    print("probe_toolsearch:", "OK" if ok else "FALLO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
