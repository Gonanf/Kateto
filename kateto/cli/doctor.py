from __future__ import annotations

import importlib.util
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from kateto.core.config import KatetoConfig, resolve_secret


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ServerStatus:
    reachable: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    reachable: bool
    models: tuple[str, ...] = ()
    loaded: tuple[str, ...] = ()
    tool_calling: bool | None = None
    tool_probe_model: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorEnv:
    config_text: str | None
    servers: Mapping[str, ServerStatus] = field(default_factory=dict)
    ollama: OllamaStatus | None = None


def mask_key(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def parse_config(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return None, [f"malformed TOML: {error}"]
    try:
        _ = KatetoConfig.model_validate(raw)
    except ValidationError as error:
        issues = []
        for issue in error.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in issue["loc"])
            issues.append(f"{location}: {issue['msg']}")
        return raw, issues
    return raw, []


def check_config(config_text: str) -> CheckResult:
    _raw, issues = parse_config(config_text)
    if issues:
        return CheckResult("config", False, "; ".join(issues))
    return CheckResult("config", True, "config.toml validates")


def check_vad() -> CheckResult:
    if importlib.util.find_spec("silero_vad") is None or importlib.util.find_spec("torch") is None:
        action = "install with `uv add silero-vad torch` and restart"
        return CheckResult("vad", False, f"silero-vad/torch not importable — {action}")
    return CheckResult("vad", True, "silero-vad + torch available")


def _resolved_plugin_settings(raw: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sections = raw.get("plugin")
    if not isinstance(sections, dict):
        return {}
    resolved: dict[str, dict[str, Any]] = {}
    for name, section in sections.items():
        if not isinstance(section, dict):
            continue
        api_key = section.get("api_key")
        if isinstance(api_key, str):
            section = {**section, "api_key": resolve_secret(api_key)}
        resolved[str(name)] = section
    return resolved


def check_keys(raw: Mapping[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name, section in sorted(_resolved_plugin_settings(raw).items()):
        api_key = section.get("api_key")
        if isinstance(api_key, str) and api_key:
            results.append(CheckResult(f"keys.{name}", True, f"api_key present ({mask_key(api_key)})"))
            continue
        if not section.get("enabled", True):
            continue
        enabled_requires_key = "camb" in name
        if api_key is None and not enabled_requires_key:
            continue
        if enabled_requires_key:
            results.append(
                CheckResult(
                    f"keys.{name}",
                    False,
                    "api_key missing — run `kateto setup` or add it to secrets/.env",
                )
            )
    return results


def check_servers(env: DoctorEnv) -> list[CheckResult]:
    results: list[CheckResult] = []
    for label, status in sorted(env.servers.items()):
        if status.reachable:
            results.append(CheckResult(f"server.{label}", True, "reachable"))
        else:
            reason = f" — {status.error}" if status.error else ""
            done = f"{reason} (start it, then re-run `kateto doctor`)"
            results.append(CheckResult(f"server.{label}", False, f"unreachable{done}"))
    return results


def check_ollama_models(env: DoctorEnv) -> list[CheckResult]:
    status = env.ollama
    if status is None:
        return [CheckResult("ollama", True, "skipped — no LLM endpoint on Ollama :11434")]
    if not status.reachable:
        reason = f" — {status.error}" if status.error else ""
        return [CheckResult("ollama", False, f"unreachable{reason}. Start `ollama serve`")]
    results = [CheckResult("ollama", True, "reachable")]
    if not status.models:
        results.append(CheckResult("ollama.models", False, "no models loaded in Ollama — run `ollama pull <model>`"))
    for model in status.models:
        loaded = model in status.loaded or not status.loaded
        if loaded:
            results.append(CheckResult(f"ollama.model.{model}", True, "present and loaded"))
        else:
            results.append(CheckResult(f"ollama.model.{model}", False, "present but not loaded — warm it up or disable cold-start"))
    if status.tool_probe_model:
        match status.tool_calling:
            case True:
                results.append(CheckResult(f"ollama.tools.{status.tool_probe_model}", True, "supports tool-calling"))
            case False:
                results.append(
                    CheckResult(
                        f"ollama.tools.{status.tool_probe_model}",
                        False,
                        "tool-calling probe returned no tool_calls — voice tools will not work",
                    )
                )
            case None:
                results.append(
                    CheckResult(
                        f"ollama.tools.{status.tool_probe_model}",
                        False,
                        "tool-calling could not be verified — pick a tool-capable model or investigate",
                    )
                )
    return results


def run_doctor(env: DoctorEnv) -> tuple[int, list[CheckResult]]:
    results: list[CheckResult] = []
    config_text = env.config_text
    if config_text is None:
        results.append(CheckResult("config", False, "no config.toml found — run `kateto setup`"))
        return 1 if any(not r.ok for r in results) else 0, results
    results.append(check_config(config_text))
    results.append(check_vad())
    raw, issues = parse_config(config_text)
    if raw is None or issues:
        return 1 if any(not r.ok for r in results) else 0, results
    results.extend(check_keys(raw))
    results.extend(check_servers(env))
    results.extend(check_ollama_models(env))
    return (1 if any(not r.ok for r in results) else 0), results


def _ollama_base_for(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port not in {11434, None}:
        return None
    if parsed.port is None and parsed.hostname != "127.0.0.1" and parsed.hostname != "localhost":
        return None
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    return f"{parsed.scheme or 'http'}://{host}:{port}"


def probe_server(endpoint: str, *, timeout_s: float = 2.0) -> ServerStatus:
    # ponytail: any HTTP response (even 404) proves the server is up; only
    # connection-level failures matter for a reachability probe.
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            _ = client.get(endpoint)
        return ServerStatus(reachable=True)
    except httpx.HTTPError as error:
        return ServerStatus(reachable=False, error=str(error).splitlines()[0])


def probe_ollama(
    base_url: str,
    *,
    tool_model: str | None = None,
    timeout_s: float = 5.0,
) -> OllamaStatus:
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            tags_response = client.get(f"{base_url.rstrip('/')}/api/tags")
            if tags_response.status_code != 200:
                return OllamaStatus(
                    reachable=False,
                    error=f"responded {tags_response.status_code} to /api/tags (not Ollama?)",
                )
            tags = tags_response.json()
            ps = client.get(f"{base_url.rstrip('/')}/api/ps").json()
    except (httpx.HTTPError, ValueError) as error:
        return OllamaStatus(reachable=False, error=str(error).splitlines()[0])
    models = tuple(str(item.get("name", "")).removesuffix(":latest") for item in tags.get("models", []))
    loaded = tuple(str(item.get("name", "")).removesuffix(":latest") for item in ps.get("models", []))
    tool_calling: bool | None = None
    if tool_model:
        # ponytail: one tiny chat with a tool definition; skipped when the
        # voice LLM is not served by Ollama.
        payload = {
            "model": tool_model,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "answer pong",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "stream": False,
            "options": {"num_predict": 1},
        }
        try:
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(f"{base_url.rstrip('/')}/api/chat", json=payload)
            if response.status_code == 200:
                body = response.json()
                tool_calling = bool(body.get("message", {}).get("tool_calls"))
        except (httpx.HTTPError, ValueError):
            tool_calling = None
    return OllamaStatus(
        reachable=True,
        models=models,
        loaded=loaded,
        tool_calling=tool_calling,
        tool_probe_model=tool_model,
    )


def _plugin_section(raw: Mapping[str, Any], name: str) -> dict[str, Any]:
    plugins = raw.get("plugin")
    if isinstance(plugins, dict):
        section = plugins.get(name)
        if isinstance(section, dict):
            return section
    return {}


def doctor_report(config_text: str | None) -> tuple[int, list[CheckResult]]:
    if config_text is None:
        return run_doctor(DoctorEnv(config_text=None))
    raw, issues = parse_config(config_text)
    if raw is None or issues:
        return run_doctor(DoctorEnv(config_text=config_text))
    voice = _plugin_section(raw, "voice_llm")
    whisper = _plugin_section(raw, "audio_processor_whisper")
    zonos = _plugin_section(raw, "audio_output_zonos")
    camb = _plugin_section(raw, "audio_output_camb")
    servers = {
        label: probe_server(endpoint)
        for label, endpoint in (
            ("whisper", whisper.get("endpoint")),
            ("tts.zonos", zonos.get("endpoint")),
            ("tts.camb", camb.get("endpoint")),
        )
        if isinstance(endpoint, str) and endpoint
    }
    voice_endpoint = voice.get("endpoint") if isinstance(voice.get("endpoint"), str) else None
    voice_model = voice.get("model") if isinstance(voice.get("model"), str) else None
    ollama_base = _ollama_base_for(voice_endpoint)
    ollama = probe_ollama(ollama_base, tool_model=voice_model) if ollama_base else None
    return run_doctor(DoctorEnv(config_text=config_text, servers=servers, ollama=ollama))