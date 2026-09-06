"""Dataset de tool calling para Kateto y RWKV.

Genera pares sinteticos con un teacher via endpoint OpenAI-compatible y los
exporta en dos formatos: OpenAI chat con tools y RWKV G1 con tags
think mas tool_call mas tool_response. Sin LLM igual sirve: trae seeds
deterministicos para arrancar ya.
"""
from __future__ import annotations

import json
import os
import random

TOOLS = [
    {"name": "send_event", "args": {"event": "string", "data": "object", "target": "plugin|voice|null"}},
    {"name": "list_events", "args": {}},
    {"name": "list_plugins", "args": {}},
    {"name": "enable_plugin", "args": {"name": "string"}},
    {"name": "disable_plugin", "args": {"name": "string"}},
    {"name": "create_workflow", "args": {"name": "string", "voice": "string", "phases": "array"}},
    {"name": "update_workflow", "args": {"name": "string", "phase": "string", "status": "string"}},
    {"name": "create_skill", "args": {"name": "string", "content": "string"}},
    {"name": "update_skill", "args": {"name": "string", "content": "string"}},
    {"name": "read_file", "args": {"path": "string"}},
    {"name": "write_file", "args": {"path": "string", "content": "string"}},
    {"name": "run_command", "args": {"command": "string"}},
    {"name": "get_weather", "args": {"city": "string", "units": "celsius|fahrenheit"}},
    {"name": "mcp_call", "args": {"server": "string", "tool": "string", "arguments": "object"}},
]

KATETO_SEEDS = [
    ("Jane, pedile feedback a Doktor sobre el plan del sprint", "send_event", {"event": "VoiceFeedback", "data": {"from": "jane", "ask": "revisa el plan"}, "target": "doktor"}),
    ("Arranca el workflow de review con Conquest", "create_workflow", {"name": "review", "voice": "conquest", "phases": ["plan", "review", "close"]}),
    ("Marca la fase plan como completa en el workflow review", "update_workflow", {"name": "review", "phase": "plan", "status": "complete"}),
    ("Lee la skill de planning-poker para la ceremonia", "read_file", {"path": "skills/planning-poker/SKILL.md"}),
    ("Lista los plugins activos del runtime", "list_plugins", {}),
    ("Llama al MCP de calendario para buscar huecos", "mcp_call", {"server": "calendar", "tool": "find_free_slots", "arguments": {"date": "2026-05-08"}}),
]

SEEDS = [
    ("Que clima hace en Buenos Aires hoy?", "get_weather", {"city": "Buenos Aires", "units": "celsius"}),
    ("Agendame un sync de 30 con Bob manana a la tarde", "find_free_slots", {"date": "2026-05-08", "duration_minutes": 30, "time_window": "afternoon"}),
    ("Busca donde se define VoiceAgent en el repo", "search_files", {"pattern": "VoiceAgent", "path": "kateto/voices"}),
    ("Corre los tests del event bus", "run_tests", {"target": "kateto/tests/test_event_bus.py"}),
]


def build_toolcall_prompt(user_msg: str) -> str:
    tools = "\n".join(f"- {t['name']}({t['args']})" for t in TOOLS)
    return (
        "You generate tool-calling training pairs in rioplatense context.\n"
        f"Available tools:\n{tools}\n\n"
        f"User message: {user_msg}\n\n"
        "Reply with JSON ONLY, exactly:\n"
        '{"tool": "...", "arguments": {...}, "answer": "respuesta corta en espanol rioplatense"}'
    )


def to_rwkv_pair(user_msg: str, tool: str, args: dict, answer: str) -> dict:
    call = json.dumps({"name": tool, "arguments": args}, ensure_ascii=False)
    return {
        "system": "Tools: " + ", ".join(t["name"] for t in TOOLS) + ". Return only a JSON function call.",
        "user": user_msg,
        "assistant_rwkv": f"<think>\nHay que llamar a {tool}.\n</think>\n<tool_call>\n{call}\n</tool_call>",
        "tool_response": '{"ok": true}',
        "assistant_final": answer,
    }


def to_openai_pair(user_msg: str, tool: str, args: dict, answer: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": "Respond ONLY with a valid JSON tool call."},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": json.dumps({"tool": tool, "arguments": args, "answer": answer}, ensure_ascii=False)},
        ]
    }


def seed_dataset(n: int = 200) -> list[dict]:
    out = []
    for _ in range(n):
        pool = KATETO_SEEDS + SEEDS
        u, tool, args = random.choice(pool)
        ans = "Dale, lo chequeo y te aviso."
        if tool == "get_weather":
            ans = "Hoy en Buenos Aires clima agradable, 22 grados y algo nublado."
        out.append({"openai": to_openai_pair(u, tool, args, ans), "rwkv": to_rwkv_pair(u, tool, args, ans)})
    return out


async def synthesize_one(user_msg: str, model: str | None = None, base_url: str | None = None) -> dict | None:
    base = base_url or os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    key = os.getenv("OPENAI_API_KEY", "sk-no-key")
    mdl = model or os.getenv("MODEL_NAME", "Kateto")
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    client = AsyncOpenAI(api_key=key, base_url=base, timeout=120, max_retries=1)
    try:
        resp = await client.chat.completions.create(
            model=mdl, messages=[{"role": "user", "content": build_toolcall_prompt(user_msg)}],
            temperature=0.4, max_tokens=300,
        )
        txt = (resp.choices[0].message.content or "").strip()
        start = txt.find("{")
        obj = json.loads(txt[start:])
        return {"openai": to_openai_pair(user_msg, obj["tool"], obj["arguments"], obj.get("answer", "")),
                "rwkv": to_rwkv_pair(user_msg, obj["tool"], obj["arguments"], obj.get("answer", ""))}
    except Exception:
        return None
