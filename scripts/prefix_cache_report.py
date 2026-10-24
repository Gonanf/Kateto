#!/usr/bin/env python3
"""Prefix Cache Report — Instrumento de medición de prefijo de prompt en Kateto.

Mide el reuso de prefijo KV-cache entre voces reales en dos layouts:
- legacy: secciones en orden previo (persona primero)
- current: secciones con prefijo común independiente primero (spec 2026-10-24)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tomllib
from typing import Any
import urllib.error
import urllib.request

# Asegurar sys.path con la raíz del repo antes de imports de kateto
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kateto.core.config import VoiceSettings
from kateto.core.workflow import WorkflowCatalog
from kateto.voices.base import VoiceAgent
from kateto.voices.factory import _PROFILES
from kateto.voices.ledger import VoiceMemoryLedger
from kateto.voices.prompt_blocks import (
    get_agent_prompt_block,
    get_mcp_prompt_block,
    get_workflow_prompt_block,
)
from kateto.voices.skills import LoadedSkill, load_skills


class StubProvider:
    """Provider stub que no se usa para generar."""
    pass


class StubToolExecutor:
    """Tool executor stub con servers MCP reales."""
    def __init__(self, mcp_server_names: tuple[str, ...] = ("system",)) -> None:
        self._mcp_server_names = mcp_server_names


def assemble_legacy_prompt(
    *,
    soul: str,
    profile_system_prompt: str,
    response_language: str | None,
    workflow_block: str | None,
    mcp_block: str | None,
    delegation_block: str | None,
    boson_block: str | None,
    skills: tuple[LoadedSkill, ...],
    memories: str | None,
) -> str:
    """Ensambla el prompt en el orden legacy previo."""
    sections: list[str] = []

    if profile_system_prompt.strip():
        sections.append(profile_system_prompt)
    if soul.strip() and soul.strip() != profile_system_prompt.strip():
        sections.append(soul)
    if response_language:
        sections.append(
            "Always respond in the project's configured language: "
            f"{response_language}. This instruction overrides the language of the user input."
        )

    for block in (workflow_block, mcp_block, delegation_block, boson_block):
        if block:
            sections.append(block)
    for skill in skills:
        instructions = getattr(skill, "instructions", None)
        if instructions:
            sections.append(instructions)

    if memories and memories.strip():
        sections.append(memories)

    sections.append(
        "Voice turn constraint: Always speak to the user in 1-2 short natural sentences (under 40 words). Never use lists, bullet points, headers, or markdown formatting."
    )

    return "\n\n".join(sections)


async def build_voice_prompts(
    config_dir: Path,
    falta_insumo: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Construye los prompts en ambos layouts (legacy y current) para las 4 voces reales."""
    voices = ("jane", "doktor", "conquest", "whisperer")

    config_file = config_dir / "config.toml"
    language = "es_ar"
    if config_file.is_file():
        try:
            cfg = tomllib.loads(config_file.read_text(encoding="utf-8"))
            language = cfg.get("kateto", {}).get("language", "es_ar")
        except Exception as exc:
            falta_insumo.append(f"Error reading {config_file}: {exc}")
    else:
        falta_insumo.append(str(config_file))

    legacy_prompts: dict[str, str] = {}
    current_prompts: dict[str, str] = {}

    for vname in voices:
        profile = _PROFILES.get(vname)
        if profile is None:
            falta_insumo.append(f"profile:{vname}")
            continue

        cfg_file = config_dir / "voices" / vname / "config.toml"
        if cfg_file.is_file():
            try:
                vdata = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                settings = VoiceSettings(**vdata)
            except Exception as exc:
                falta_insumo.append(f"Error reading {cfg_file}: {exc}")
                settings = VoiceSettings()
        else:
            falta_insumo.append(str(cfg_file))
            settings = VoiceSettings()

        soul_file = config_dir / "voices" / vname / "SOUL.md"
        if not soul_file.is_file():
            falta_insumo.append(str(soul_file))

        wf_dir = config_dir / "voices" / vname / "workflows"
        if not wf_dir.is_dir():
            falta_insumo.append(str(wf_dir))

        for s in settings.skills:
            skill_file = config_dir / "skills" / s / "SKILL.md"
            if not skill_file.is_file():
                falta_insumo.append(str(skill_file))

        loaded_skills = load_skills(config_dir=config_dir, names=tuple(settings.skills))

        agent = VoiceAgent(
            profile=profile,
            config_dir=config_dir,
            provider=StubProvider(),
            settings=settings,
            response_language=language,
        )
        agent._tool_executor = StubToolExecutor()
        agent._pydantic_agent = None
        agent._skills = loaded_skills

        # 1. Current prompt vía camino real del runtime
        current_prompts[vname] = await agent.build_stable_prompt()

        # 2. Legacy prompt usando las mismas secciones en orden legacy
        soul = await agent._memory.read_soul()
        if not soul.strip():
            restored = await agent._memory.rollback_soul()
            if restored:
                soul = restored
        memories = await agent._memory.read_memories()
        dept = agent.profile.depts[0] if agent.profile.depts else ""
        block = (
            VoiceMemoryLedger.for_dept(config_dir=agent._config_dir, dept=dept).render_block()
            if dept
            else ""
        )
        if block:
            memories = f"{memories}\n\n{block}" if memories else block

        workflows = WorkflowCatalog(config_dir=agent._config_dir).discover(voice=agent.name)
        mcp_block = (
            get_mcp_prompt_block(agent._tool_executor._mcp_server_names)
            if agent._tool_executor is not None
            else None
        )
        delegation_block = None
        tts_block = None
        current_tts = getattr(agent._settings, "tts_provider", None) or (
            agent._settings.get("tts_provider") if hasattr(agent._settings, "get") else None
        )
        if current_tts:
            tts_block = get_agent_prompt_block(str(current_tts))

        legacy_prompts[vname] = assemble_legacy_prompt(
            soul=soul,
            profile_system_prompt=profile.system_prompt,
            response_language=language,
            workflow_block=get_workflow_prompt_block(workflows if workflows else None),
            mcp_block=mcp_block,
            delegation_block=delegation_block,
            boson_block=tts_block,
            skills=agent._skills,
            memories=memories,
        )

    return legacy_prompts, current_prompts


def http_post_json(url: str, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        sys.stderr.write(f"HTTP POST {url} failed: {exc}\n")
        sys.exit(2)


def http_get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        sys.stderr.write(f"HTTP GET {url} failed: {exc}\n")
        sys.exit(2)


def check_server(endpoint: str) -> tuple[str, str]:
    models_resp = http_get_json(f"{endpoint}/v1/models")
    data = models_resp.get("data") or models_resp.get("models") or []
    if not data:
        sys.stderr.write("Server returned empty model list\n")
        sys.exit(2)
    first = data[0]
    model_name = first.get("id") or first.get("name") or "local"
    return endpoint, model_name


def tokenize(endpoint: str, text: str) -> list[int]:
    resp = http_post_json(f"{endpoint}/tokenize", {"content": text})
    tokens = resp.get("tokens")
    if tokens is None or not isinstance(tokens, list):
        sys.stderr.write(f"Invalid tokenize response: {resp}\n")
        sys.exit(2)
    return tokens


def run_chat_turn(
    endpoint: str,
    model: str,
    prompt: str,
    user_msg: str,
    seed: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ],
        "cache_prompt": True,
        "stream": False,
        "max_tokens": 8,
        "temperature": 0,
        "seed": seed,
    }
    resp = http_post_json(f"{endpoint}/v1/chat/completions", payload)
    timings = resp.get("timings")
    if (
        not timings
        or "cache_n" not in timings
        or "prompt_n" not in timings
        or "prompt_ms" not in timings
    ):
        sys.stderr.write(f"Chat completion response without timings: {resp}\n")
        sys.exit(2)
    return {
        "prompt_n": timings["prompt_n"],
        "cache_n": timings["cache_n"],
        "prompt_ms": timings["prompt_ms"],
    }


def parse_seeds(raw_seeds: list[Any]) -> list[int]:
    result: list[int] = []
    for item in raw_seeds:
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, str):
            for part in item.split(","):
                part = part.strip()
                if part:
                    result.append(int(part))
    return result or [1, 2, 3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefix cache measurement report")
    parser.add_argument("--config-dir", type=Path, default=Path("/home/chaos/.config/kateto"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8092")
    parser.add_argument("--seed", nargs="+", default=[1, 2, 3])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-cache-shared-tokens", type=int, default=0)
    args = parser.parse_args()

    seeds = parse_seeds(args.seed)

    # 1. Verificar server
    url, modelo_servido = check_server(args.endpoint)
    server_info = {"url": url, "modelo_servido": modelo_servido}

    # 2. Construir prompts (primera pasada)
    falta_insumo: list[str] = []
    legacy_prompts_1, current_prompts_1 = asyncio.run(
        build_voice_prompts(args.config_dir, falta_insumo)
    )

    # 3. Determinismo (segunda pasada): exit 3 si difieren los sha256
    falta_insumo_2: list[str] = []
    legacy_prompts_2, current_prompts_2 = asyncio.run(
        build_voice_prompts(args.config_dir, falta_insumo_2)
    )

    for v in legacy_prompts_1:
        h1 = hashlib.sha256(legacy_prompts_1[v].encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(legacy_prompts_2[v].encode("utf-8")).hexdigest()
        if h1 != h2:
            sys.stderr.write(f"Non-deterministic prompt for legacy voice {v}\n")
            sys.exit(3)

    for v in current_prompts_1:
        h1 = hashlib.sha256(current_prompts_1[v].encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(current_prompts_2[v].encode("utf-8")).hexdigest()
        if h1 != h2:
            sys.stderr.write(f"Non-deterministic prompt for current voice {v}\n")
            sys.exit(3)

    # Deduplicar falta_insumo
    falta_insumo = sorted(list(set(falta_insumo)))

    # 4. Medir cada layout
    layouts = {
        "legacy": legacy_prompts_1,
        "current": current_prompts_1,
    }

    report: dict[str, Any] = {
        "server": server_info,
        "falta_insumo": falta_insumo,
    }

    for layout_name, prompts in layouts.items():
        # (a) tokens por voz
        tokens_por_voz: dict[str, int] = {}
        tokens_ids: dict[str, list[int]] = {}
        for vname, ptext in prompts.items():
            toks = tokenize(args.endpoint, ptext)
            tokens_por_voz[vname] = len(toks)
            tokens_ids[vname] = toks

        # (b) prefijo común por par de voces
        prefijo_comun_pares: dict[str, int] = {}
        voice_names = sorted(prompts.keys())
        for i in range(len(voice_names)):
            for j in range(i + 1, len(voice_names)):
                v1, v2 = voice_names[i], voice_names[j]
                t1, t2 = tokens_ids[v1], tokens_ids[v2]
                common = 0
                for a, b in zip(t1, t2):
                    if a == b:
                        common += 1
                    else:
                        break
                prefijo_comun_pares[f"{v1}_{v2}"] = common
                prefijo_comun_pares[f"{v1}-{v2}"] = common

        # (c) secuencia en vivo: a: voice A -> b: voice A -> c: voice B -> d: voice A
        # (A=jane, B=doktor)
        p_jane = prompts["jane"]
        p_doktor = prompts["doktor"]
        seeds_data: list[dict[str, Any]] = []

        for s in seeds:
            # a: voice A
            _ = run_chat_turn(args.endpoint, modelo_servido, p_jane, f"Turn A seed {s}", s)
            # b: voice A (mismo_voz)
            mismo = run_chat_turn(args.endpoint, modelo_servido, p_jane, f"Turn B seed {s}", s)
            # c: voice B (cambio_voz)
            cambio = run_chat_turn(args.endpoint, modelo_servido, p_doktor, f"Turn C seed {s}", s)
            # d: voice A (vuelta)
            vuelta = run_chat_turn(args.endpoint, modelo_servido, p_jane, f"Turn D seed {s}", s)

            seeds_data.append({
                "seed": s,
                "mismo_voz": mismo,
                "cambio_voz": cambio,
                "vuelta": vuelta,
            })

        cache_n_cambio_voz_mediana = statistics.median([s["cambio_voz"]["cache_n"] for s in seeds_data])
        prompt_n_cambio_voz_mediana = statistics.median([s["cambio_voz"]["prompt_n"] for s in seeds_data])

        report[layout_name] = {
            "tokens_por_voz": tokens_por_voz,
            "prefijo_comun_pares": prefijo_comun_pares,
            "seeds": seeds_data,
            "cache_n_cambio_voz_mediana": cache_n_cambio_voz_mediana,
            "prompt_n_cambio_voz_mediana": prompt_n_cambio_voz_mediana,
            "falta_insumo": falta_insumo,
            "server": server_info,
        }

    # 5. Verificar min-cache-shared-tokens en current
    if args.min_cache_shared_tokens > 0:
        current_data = report["current"]
        achieved = max(
            current_data["cache_n_cambio_voz_mediana"],
            current_data["prefijo_comun_pares"].get("doktor_jane", 0),
            current_data["prefijo_comun_pares"].get("jane_doktor", 0),
        )
        if achieved < args.min_cache_shared_tokens:
            sys.stderr.write(
                f"Error: min-cache-shared-tokens {args.min_cache_shared_tokens} not reached in current layout (achieved: {achieved})\n"
            )
            sys.exit(4)

    # 6. Guardar archivo si se especificó --out
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report written to {args.out}")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
