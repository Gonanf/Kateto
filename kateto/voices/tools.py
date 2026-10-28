from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_origin

if TYPE_CHECKING:
    from kateto.plugins.system.external_mcp import ExternalMcpManager

from openai.types.chat import ChatCompletionToolParam

from kateto.core.config import CliSettings
from kateto.core.event import ScheduleRequestData, ScheduleType
from kateto.core.manager import PluginManager
from kateto.providers.agent import ToolCall, ToolExecutor

# C0 control chars except tab/newline/cr; JSON escapes are already decoded by json.loads.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_string(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def turn_is_truncated(stop_reason: str | None, tool_calls: tuple[ToolCall, ...]) -> bool:
    """Guard: a truncated turn (stop_reason == "length") must not execute its tool calls."""
    return stop_reason == "length" and bool(tool_calls)


# Tools that close the task (e.g. delegation): no follow-up LLM call when the
# whole batch terminates. Deliberately NOT part of the OpenAI wire schema —
# servers reject unknown function keys.
TERMINAL_TOOLS: frozenset[str] = frozenset({"request_generation"})


def is_terminal_tool(name: str) -> bool:
    return name in TERMINAL_TOOLS


def preflight_tool_arguments(
    parameters: dict[str, Any] | None,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Sanitize strings and validate args against the tool's JSON schema.

    Returns (cleaned_args, None) on success, (None, error_message) on rejection.
    """
    parameters = parameters or {}
    properties: dict[str, Any] = parameters.get("properties") or {}
    required: list[str] = parameters.get("required") or []
    for key in required:
        if key not in arguments:
            return None, f"missing required argument: {key}"
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        stype = (properties.get(key) or {}).get("type")
        if stype == "string":
            if not isinstance(value, str):
                return None, f"argument '{key}' must be a string, got {type(value).__name__}"
            value = sanitize_string(value)
        elif stype == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, f"argument '{key}' must be a number, got {type(value).__name__}"
        elif stype == "boolean":
            if not isinstance(value, bool):
                return None, f"argument '{key}' must be a boolean, got {type(value).__name__}"
        elif stype == "array":
            if not isinstance(value, list):
                return None, f"argument '{key}' must be an array, got {type(value).__name__}"
        elif stype == "object":
            if not isinstance(value, dict):
                return None, f"argument '{key}' must be an object, got {type(value).__name__}"
        cleaned[key] = value
    return cleaned, None


class VoiceToolExecutor:
    def __init__(
        self,
        *,
        config_dir: Path,
        manager: PluginManager | None = None,
        cli_settings: CliSettings | None = None,
        working_directory: Path | None = None,
        external_manager: "ExternalMcpManager | None" = None,
        mcp_server_names: tuple[str, ...] = (),
        voice_name: str = "",
        dept: str = "",
        disable_scheduling_tools: bool = False,
    ) -> None:
        self._config_dir = config_dir.resolve()
        self._manager = manager
        self._cli_settings = cli_settings
        self._working_directory = (working_directory or config_dir).resolve()
        self._external_manager = external_manager
        self._mcp_server_names = mcp_server_names
        self._voice_name = voice_name
        self._dept = dept
        self._disable_scheduling_tools = disable_scheduling_tools

    def set_manager(self, manager: PluginManager) -> None:
        self._manager = manager

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        match name:
            case "run_command":
                return await self._run_command(arguments)
            case "read_file":
                return self._read_file(arguments)
            case "write_file":
                return self._write_file(arguments)
            case "delete_file":
                return self._delete_file(arguments)
            case "send_event":
                return await self._send_event(arguments)
            case "list_events":
                return self._list_events()
            case "enable_plugin":
                return await self._enable_plugin(arguments)
            case "disable_plugin":
                return await self._disable_plugin(arguments)
            case "list_plugins":
                return self._list_plugins()
            case "create_skill":
                return await self._create_skill(arguments)
            case "update_skill":
                return await self._update_skill(arguments)
            case "create_workflow":
                return await self._create_workflow(arguments)
            case "update_workflow":
                return await self._update_workflow(arguments)
            case "update_soul":
                return await self._update_soul(arguments)
            case "request_generation":
                return await self._request_generation(arguments)
            case "schedule_event":
                if self._disable_scheduling_tools:
                    return json.dumps({"error": "scheduling tools are disabled"})
                return await self._schedule_event(arguments)
            case "get_current_time":
                return self._get_current_time()
            case "refine_memory":
                return await self._refine_memory(arguments)
            case _:
                if name.startswith("client_"):
                    manager = self._manager
                    plugin = manager.get_plugin("client_tools") if manager is not None else None
                    call = getattr(plugin, "call", None)
                    if call is not None:
                        return await call(name, arguments)
                    return json.dumps({"error": f"no hay cliente para {name}"})
                if self._external_manager is not None and self._mcp_server_names:
                    result = await self._external_manager.try_call_tool(
                        list(self._mcp_server_names), name, arguments,
                    )
                    if result is not None:
                        return result
                manager = self._manager
                if manager is not None and name in self._event_tool_names():
                    return await self._dispatch_event(name, arguments)
                return json.dumps({"error": f"unknown tool: {name}"})

    def _event_tool_names(self) -> set[str]:
        manager = self._manager
        if manager is None:
            return set()
        return {
            reg.name
            for reg in manager.get_event_registrations()
            if reg.receivers
        }

    async def _dispatch_event(self, event_name: str, data: dict[str, Any], *, target: str | None = None) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})
        try:
            registration = None
            for reg in manager.get_event_registrations():
                if reg.name == event_name and reg.receivers:
                    registration = reg
                    break
            if registration is None:
                return json.dumps({"error": f"event '{event_name}' has no receivers"})
            payload = registration.contract.model_validate(data)
            await manager.emit(event_name, payload, source="voice_agent", target=target)
            return json.dumps({"status": "dispatched", "event_name": event_name})
        except Exception as e:
            return json.dumps({"error": f"failed to dispatch: {e}"})

    async def _send_event(self, args: dict[str, Any]) -> str:
        event_name = args.get("event_name", "")
        if not event_name:
            return json.dumps({"error": "event_name is required"})
        data = args.get("data", {})
        target = args.get("target")
        return await self._dispatch_event(event_name, data, target=target)

    def _list_events(self) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"events": [], "error": "no plugin manager available"})
        events = []
        for reg in manager.get_event_registrations():
            if reg.receivers:
                fields = {}
                for name, field_info in reg.contract.model_fields.items():
                    fields[name] = {
                        "type": getattr(field_info.annotation, "__name__", str(field_info.annotation))
                        if field_info.annotation
                        else "unknown",
                        "required": field_info.is_required(),
                    }
                events.append({
                    "name": reg.name,
                    "receivers": list(reg.receivers),
                    "fields": fields,
                })
        return json.dumps({"events": events})

    async def _enable_plugin(self, args: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})
        name = args.get("name", "")
        if not name:
            return json.dumps({"error": "name is required"})
        try:
            for plugin in manager.get_plugins():
                if plugin.name == name:
                    if plugin.enabled:
                        return json.dumps({"status": "already_enabled", "name": name})
                    await manager.enable_plugin(plugin)
                    return json.dumps({"status": "enabled", "name": name})
            return json.dumps({"error": f"plugin '{name}' not found"})
        except Exception as e:
            return json.dumps({"error": f"failed to enable: {e}"})

    async def _disable_plugin(self, args: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})
        name = args.get("name", "")
        if not name:
            return json.dumps({"error": "name is required"})
        try:
            for plugin in manager.get_plugins():
                if plugin.name == name:
                    if not plugin.enabled:
                        return json.dumps({"status": "already_disabled", "name": name})
                    await manager.disable_plugin(name)
                    return json.dumps({"status": "disabled", "name": name})
            return json.dumps({"error": f"plugin '{name}' not found"})
        except Exception as e:
            return json.dumps({"error": f"failed to disable: {e}"})

    def _list_plugins(self) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"plugins": [], "error": "no plugin manager available"})
        plugins = []
        for plugin in manager.get_plugins():
            plugins.append({
                "name": plugin.name,
                "enabled": plugin.enabled,
                "capabilities": list(plugin.capabilities),
            })
        return json.dumps({"plugins": plugins})

    # ponytail: name validation shared across skill/workflow/soul tools
    @staticmethod
    def _validate_name(name: str) -> None:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*\Z", name):
            raise ValueError(f"invalid name: {name!r}")

    # ponytail: thin wrappers around write_file with path construction + validation.
    #   skip backup, skip event emission, skip confirmation.
    #   add if users actually hit data-loss or need hot-reload notification.
    async def _create_skill(self, args: dict[str, Any]) -> str:
        name = args.get("name", "")
        content = args.get("content", "")
        if not name or content is None:
            return json.dumps({"error": "name and content are required"})
        try:
            self._validate_name(name)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        path = self._config_dir / "skills" / name / "SKILL.md"
        if path.exists():
            return json.dumps({"error": f"skill '{name}' already exists; use update_skill"})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return json.dumps({"status": "created", "name": name, "path": str(path.relative_to(self._config_dir))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _update_skill(self, args: dict[str, Any]) -> str:
        name = args.get("name", "")
        content = args.get("content", "")
        if not name or content is None:
            return json.dumps({"error": "name and content are required"})
        try:
            self._validate_name(name)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        path = self._config_dir / "skills" / name / "SKILL.md"
        if not path.exists():
            return json.dumps({"error": f"skill '{name}' not found; use create_skill"})
        try:
            path.write_text(content, encoding="utf-8")
            return json.dumps({"status": "updated", "name": name, "path": str(path.relative_to(self._config_dir))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _create_workflow(self, args: dict[str, Any]) -> str:
        name = args.get("name", "")
        content = args.get("content", "")
        voice = args.get("voice", "")
        if not name or content is None or not voice:
            return json.dumps({"error": "name, voice, and content are required"})
        try:
            self._validate_name(name)
            self._validate_name(voice)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        path = self._config_dir / "voices" / voice / "workflows" / name / "workflow.py"
        if path.exists():
            return json.dumps({"error": f"workflow '{name}' for voice '{voice}' already exists; use update_workflow"})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return json.dumps({"status": "created", "name": name, "voice": voice, "path": str(path.relative_to(self._config_dir))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _update_workflow(self, args: dict[str, Any]) -> str:
        name = args.get("name", "")
        content = args.get("content", "")
        voice = args.get("voice", "")
        if not name or content is None or not voice:
            return json.dumps({"error": "name, voice, and content are required"})
        try:
            self._validate_name(name)
            self._validate_name(voice)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        path = self._config_dir / "voices" / voice / "workflows" / name / "workflow.py"
        if not path.exists():
            return json.dumps({"error": f"workflow '{name}' for voice '{voice}' not found; use create_workflow"})
        try:
            path.write_text(content, encoding="utf-8")
            return json.dumps({"status": "updated", "name": name, "voice": voice, "path": str(path.relative_to(self._config_dir))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _update_soul(self, args: dict[str, Any]) -> str:
        name = args.get("name", "")
        content = args.get("content", "")
        if not name or content is None:
            return json.dumps({"error": "name and content are required"})
        try:
            self._validate_name(name)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        from kateto.voices.memory import VoiceMemory

        try:
            memory = VoiceMemory.for_voice(config_dir=self._config_dir, voice=name)
            await memory.write_soul(content)
            path = memory.store.path_for("SOUL.md")
            return json.dumps({"status": "updated" if path.exists() else "created", "name": name, "path": str(path.relative_to(self._config_dir))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _request_generation(self, args: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})
        target_voice = args.get("target_voice", "")
        prompt = args.get("prompt", "")
        if not target_voice or not prompt:
            return json.dumps({"error": "target_voice and prompt are required"})
        from kateto.core.event import GenerateRequestData

        request = GenerateRequestData(
            target_voice=target_voice,
            prompt=prompt,
            source_voice=self._voice_name or "voice_agent",
            depth=int(args.get("depth", 0)),
            dept=args.get("dept"),
        )
        try:
            await manager.emit("generate_request", request, source=self._voice_name or "voice_agent")
            return json.dumps({"status": "requested", "target_voice": target_voice, "depth": request.depth})
        except Exception as e:
            return json.dumps({"error": f"failed to request generation: {e}"})

    async def _schedule_event(self, args: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})

        event_name = str(args.get("event_name", ""))
        if not event_name:
            return json.dumps({"error": "event_name is required"})

        schedule_type_str = args.get("schedule_type")
        delay = args.get("delay")
        interval = args.get("interval")
        cron = args.get("cron")
        expression = args.get("expression")

        if schedule_type_str:
            stype = ScheduleType(schedule_type_str)
        elif delay is not None:
            stype = ScheduleType.ONE_SHOT
            expression = f"{delay}s"
        elif interval is not None:
            stype = ScheduleType.INTERVAL
            expression = f"{interval}s"
        elif cron is not None:
            stype = ScheduleType.CRON
            expression = cron
        else:
            stype = ScheduleType.ONE_SHOT
            expression = "0s"

        if expression is None:
            expression = "0s"

        job_id = args.get("job_id") or f"job_{os.urandom(4).hex()}"
        req = ScheduleRequestData(
            schedule_type=stype,
            expression=str(expression),
            event_name=event_name,
            data=args.get("data") or {},
            job_id=job_id,
            target_voice=args.get("target_voice"),
            dept=args.get("dept"),
            jitter_seconds=float(args.get("jitter_seconds", 0)),
            max_fires=args.get("max_fires"),
            active_hours=args.get("active_hours"),
        )
        try:
            await manager.emit("schedule_request", req, source=self._voice_name or "tool_schedule_event")
            return json.dumps({"job_id": job_id, "status": "scheduled", "event_name": event_name})
        except Exception as e:
            return json.dumps({"error": f"failed to schedule event: {e}"})

    async def _run_command(self, args: dict[str, Any]) -> str:
        command = args.get("command", "")
        if not command:
            return json.dumps({"error": "no command provided"})
        try:
            argv = tuple(shlex.split(command, posix=True))
        except ValueError as e:
            return json.dumps({"error": f"malformed command: {e}"})
        if self._cli_settings is not None:
            try:
                from kateto.plugins.connector.cli import normalize_argv
                argv = normalize_argv(command, settings=self._cli_settings, working_directory=self._working_directory)
            except Exception as e:
                return json.dumps({"error": f"command rejected: {e}"})
        executable = shutil.which(argv[0], path=os.defpath)
        if executable is None:
            return json.dumps({"error": f"executable not found: {argv[0]}"})
        process = await asyncio.create_subprocess_exec(
            executable,
            *argv[1:],
            cwd=str(self._working_directory),
            env={"LC_ALL": "C", "PATH": os.defpath},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return json.dumps({"error": "command timed out after 30s"})
        return json.dumps({
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        })

    def _read_file(self, args: dict[str, Any]) -> str:
        path = args.get("path", "")
        if not path:
            return json.dumps({"error": "no path provided"})
        resolved = (self._working_directory / path).resolve()
        if not resolved.is_relative_to(self._working_directory):
            return json.dumps({"error": "path escapes working directory"})
        if not resolved.is_file():
            return json.dumps({"error": f"file not found: {path}"})
        try:
            content = resolved.read_text(encoding="utf-8")
            if len(content) > 50000:
                content = content[:50000] + "\n... (truncated)"
            return json.dumps({"content": content, "path": str(resolved.relative_to(self._working_directory))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _write_file(self, args: dict[str, Any]) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return json.dumps({"error": "no path provided"})
        resolved = (self._working_directory / path).resolve()
        if not resolved.is_relative_to(self._working_directory):
            return json.dumps({"error": "path escapes working directory"})
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return json.dumps({"path": str(resolved.relative_to(self._working_directory)), "bytes_written": len(content.encode("utf-8"))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _delete_file(self, args: dict[str, Any]) -> str:
        path = args.get("path", "")
        if not path:
            return json.dumps({"error": "no path provided"})
        resolved = (self._working_directory / path).resolve()
        if not resolved.is_relative_to(self._working_directory):
            return json.dumps({"error": "path escapes working directory"})
        if not resolved.is_file():
            return json.dumps({"error": f"file not found: {path}"})
        try:
            resolved.unlink()
            return json.dumps({"deleted": str(resolved.relative_to(self._working_directory))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _get_current_time(self) -> str:
        return datetime.now().isoformat()

    async def _refine_memory(self, args: dict[str, Any]) -> str:
        from kateto.voices.ledger import VoiceMemoryLedger

        if not self._dept:
            return json.dumps({"error": "no department configured; cannot refine memory"})
        ledger = VoiceMemoryLedger.for_dept(config_dir=self._config_dir, dept=self._dept)
        try:
            result = await ledger.refine(
                fact=str(args.get("fact", "")),
                category=str(args.get("category", "")),
                evidence=str(args.get("evidence", "")),
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})


_CLIENT_PLUMBING = frozenset({"client_register", "client_tool_request", "tool_result"})


def build_event_tools(manager: PluginManager) -> tuple[ChatCompletionToolParam, ...]:
    tools: list[ChatCompletionToolParam] = []
    for reg in manager.get_event_registrations():
        if not reg.receivers:
            continue
        # client_register / tool_result / client_tool_request son plomeria del
        # telefono: las tools reales (client_*) las aporta el plugin client_tools.
        if reg.name in _CLIENT_PLUMBING:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for field_name, field_info in reg.contract.model_fields.items():
            field_type = "string"
            items: dict[str, str] | None = None
            if field_info.annotation is not None:
                annotation_name = getattr(field_info.annotation, "__name__", str(field_info.annotation))
                if get_origin(field_info.annotation) is list:
                    field_type = "array"
                    items = {"type": "object"}
                elif "bool" in annotation_name:
                    field_type = "boolean"
                elif "int" in annotation_name or "float" in annotation_name:
                    field_type = "number"
                elif "dict" in annotation_name:
                    field_type = "object"
            property_schema: dict[str, Any] = {
                "type": field_type,
                "description": f"Field for {reg.name} event",
            }
            if items is not None:
                property_schema["items"] = items
            properties[field_name] = property_schema
            if field_info.is_required():
                required.append(field_name)
        tools.append(ChatCompletionToolParam(
            type="function",
            function={
                "name": reg.name,
                "description": f"Dispatch {reg.name} event to: {', '.join(reg.receivers)}",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        ))
    return tuple(tools)


def filter_tool_names(
    tools: tuple[ChatCompletionToolParam, ...], excluded: frozenset[str]
) -> tuple[ChatCompletionToolParam, ...]:
    """Devuelve las tools cuyo `function.name` no esta en `excluded`."""
    if not excluded:
        return tools
    filtered: list[ChatCompletionToolParam] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else getattr(tool, "function", None)
        fn_name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        if fn_name not in excluded:
            filtered.append(tool)
    return tuple(filtered)


# Tool loading on demand (pattern `tool_search` de pydantic_ai / Hermes):
# solo ALWAYS_TOOLS viaja al wire con schema completo; el resto llega como
# catalogo `name — description de 1 linea` dentro de search_tools, y el schema
# completo de parametros se revela cuando el modelo lo pide. En logs reales, 4 de
# cada 5 tokens del wire eran esquemas de tools que el turno no llamaba.
ALWAYS_TOOLS: frozenset[str] = frozenset({"get_current_time", "list_events", "send_event"})
SEARCH_TOOLS_NAME = "search_tools"


def one_line(desc: str, limit: int = 110) -> str:
    """Primera oracion de la descripcion, colapsada, limit chars."""
    d = " ".join((desc or "").split())
    parts = re.split(r"(?<=[.!?])\s+", d)
    line = parts[0] if parts else d
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


def stub_tool(tool: ChatCompletionToolParam) -> ChatCompletionToolParam:
    """Wire reducido: name + 1 linea, parameters vacio."""
    fn = tool["function"]
    return ChatCompletionToolParam(
        type="function",
        function={
            "name": fn["name"],
            "description": one_line(fn.get("description", "")),
            "parameters": {"type": "object", "properties": {}},
        },
    )


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^A-Za-z0-9_À-ÿ]+", (text or "").lower())) - {""}


def search_tool_defs(
    queries: list[str],
    tools: tuple[ChatCompletionToolParam, ...],
) -> list[ChatCompletionToolParam]:
    """Busqueda por solapamiento de keywords (algoritmo keywords de pydantic_ai):
    name+description matching los terms de las queries, por score desc."""
    terms = _tokens(" ".join(queries))
    scored: list[tuple[int, str, ChatCompletionToolParam]] = []
    for tool in tools:
        fn = tool["function"]
        name = fn.get("name", "")
        if name == SEARCH_TOOLS_NAME:
            continue
        hits = len(terms & _tokens(f"{name} {fn.get('description', '')}"))
        if hits:
            scored.append((hits, name, tool))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [t for _, _, t in scored]


def build_search_tools_tool(deferred: tuple[ChatCompletionToolParam, ...]) -> ChatCompletionToolParam:
    """Declaracion de `search_tools`: catalogo `name — 1 linea` en la description."""
    lines = []
    for t in deferred:
        fn = stub_tool(t)["function"]
        lines.append(f"- {fn['name']} — {fn['description']}")
    return ChatCompletionToolParam(
        type="function",
        function={
            "name": SEARCH_TOOLS_NAME,
            "description": (
                "Tools diferidas (pedí el esquema con search_tools antes de llamarlas). "
                f"Catálogo nombre — descripción:\n{chr(10).join(lines)}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Search phrases matching tool names or descriptions. "
                            "Each query is tokenized independently; matches are unioned."
                        ),
                    }
                },
                "required": ["queries"],
            },
        },
    )


def build_on_demand_wire(
    tools_full: tuple[ChatCompletionToolParam, ...],
    *,
    revealed: frozenset[str] = frozenset(),
) -> tuple[ChatCompletionToolParam, ...]:
    """Wire on-demand para el path de provider OpenAI manual.

    ALWAYS_TOOLS completas + diferidas reveladas (completas) + `search_tools` con
    catalogo `name — description` de las ocultas. Orden estable: always + revealed
    en orden de tools_full + search_tools al final → prefix cache preservado.
    """
    by_name = {t["function"]["name"]: t for t in tools_full}
    always = [t for n, t in by_name.items() if n in ALWAYS_TOOLS]
    revealed_defs = [t for t in tools_full if t["function"]["name"] in revealed]
    deferred = tuple(
        t for n, t in by_name.items() if n not in ALWAYS_TOOLS and n not in revealed
    )
    return (*always, *revealed_defs, build_search_tools_tool(deferred))


BUILTIN_TOOLS: tuple[ChatCompletionToolParam, ...] = (
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "run_command",
            "description": "Execute a shell command and return its output. Use for git, ls, cat, echo, date, and other CLI tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "read_file",
            "description": "Read the contents of a text file from the working directory and return it. Use to inspect generated documents, plans, notes, or source files before editing. Content longer than 50000 characters is truncated. Paths are relative to the working directory; do not use absolute paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to read",
                    }
                },
                "required": ["path"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "write_file",
            "description": "Create or overwrite a file with the given content. Creates parent directories automatically. Use this to produce any deliverable: markdown documents, plans, reports, notes, or code files. Paths are relative to the working directory; do not use absolute paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the file to create or overwrite (e.g. 'docs/plan.md')",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "delete_file",
            "description": "Delete a file from the working directory. Use when a file is obsolete, incorrect, or should be removed. Paths are relative to the working directory; do not use absolute paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the file to delete",
                    }
                },
                "required": ["path"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "send_event",
            "description": "Dispatch any registered event. Use list_events to see available events. For known events, prefer using the specific tool directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "The event name to dispatch",
                    },
                    "data": {
                        "type": "object",
                        "description": "The event payload as key-value pairs",
                    },
                    "target": {
                        "type": "string",
                        "description": "Optional target plugin name",
                    },
                },
                "required": ["event_name", "data"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "list_events",
            "description": "List all available events with their fields and receivers.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "enable_plugin",
            "description": "Enable a plugin by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Plugin name to enable",
                    }
                },
                "required": ["name"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "disable_plugin",
            "description": "Disable a plugin by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Plugin name to disable",
                    }
                },
                "required": ["name"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "list_plugins",
            "description": "List all plugins with their enabled status and capabilities.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "create_skill",
            "description": "Create a new skill file (SKILL.md) for a voice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name (lowercase-kebab)"},
                    "content": {"type": "string", "description": "Full SKILL.md content"},
                },
                "required": ["name", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "update_skill",
            "description": "Update an existing skill file (SKILL.md).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name"},
                    "content": {"type": "string", "description": "New SKILL.md content"},
                },
                "required": ["name", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "create_workflow",
            "description": "Create a new workflow for a specific voice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name (kebab-case)"},
                    "voice": {"type": "string", "description": "Voice name to attach the workflow to"},
                    "content": {"type": "string", "description": "Full workflow.py content"},
                },
                "required": ["name", "voice", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "update_workflow",
            "description": "Update an existing workflow file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                    "voice": {"type": "string", "description": "Voice name"},
                    "content": {"type": "string", "description": "New workflow.py content"},
                },
                "required": ["name", "voice", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "update_soul",
            "description": "Update a voice's SOUL.md file (creates if missing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Voice name"},
                    "content": {"type": "string", "description": "New SOUL.md content"},
                },
                "required": ["name", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "request_generation",
            "description": "Ask another voice to generate a response. Use when another team member should speak or produce work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_voice": {
                        "type": "string",
                        "description": "The voice to request generation from (e.g. jane, doktor, conquest)",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The task or question for the target voice",
                    },
                    "dept": {
                        "type": "string",
                        "description": "Optional department to route within",
                    },
                },
                "required": ["target_voice", "prompt"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "schedule_event",
            "description": "Schedule a future or recurring event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "Name of the event to fire when scheduled time arrives",
                    },
                    "delay": {
                        "type": "number",
                        "description": "Delay in seconds before firing (one-shot schedule)",
                    },
                    "interval": {
                        "type": "number",
                        "description": "Interval in seconds between firings (recurring schedule)",
                    },
                    "cron": {
                        "type": "string",
                        "description": "Cron expression for scheduled firing (e.g. '*/5 * * * *')",
                    },
                    "target_voice": {
                        "type": "string",
                        "description": "Optional target voice for the scheduled event",
                    },
                    "dept": {
                        "type": "string",
                        "description": "Optional department for routing",
                    },
                },
                "required": ["event_name"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "get_current_time",
            "description": "Return the current local date and time.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "refine_memory",
            "description": (
                "Add, update, or remove a declarative memory in the shared memory ledger for your "
                "department (fun = stream memory; work/management = project memory shared with the "
                "other voices there). The ledger is injected into your system prompt once at session "
                "start, so changes apply from the next session. Categories: facts (confirmed facts "
                "about the user/project), relationships (dynamics between voices), action_patterns "
                "(recurring commands or scripts). To ADD: pass a fact and optional evidence. To "
                "REPLACE an existing entry: pass the new fact and, in evidence, a short unique "
                "substring of the existing fact. To REMOVE: pass fact='' and, in evidence, a short "
                "unique substring of the entry to delete. Hygiene: store declarative facts only, "
                "never progress logs, PR numbers, or 'fixed X' notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The declarative fact to store (empty string to remove)",
                    },
                    "category": {
                        "type": "string",
                        "description": "facts | relationships | action_patterns",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Context/source, or the unique substring of an existing fact to replace/remove",
                    },
                },
                "required": ["fact", "category"],
            },
        },
    ),
)


class KatetoToolset:
    def __init__(
        self,
        executor: VoiceToolExecutor,
        *,
        exclude_names: frozenset[str] = frozenset(),
    ) -> None:
        self._executor = executor
        self._exclude_names = exclude_names
        self._toolset = self._build_toolset()

    def _build_toolset(self) -> Any:
        from pydantic_ai import FunctionToolset
        ts = FunctionToolset()
        for tool_def in BUILTIN_TOOLS:
            function = tool_def["function"]
            name = function["name"]
            if name in self._exclude_names:
                continue
            if name == "schedule_event" and getattr(self._executor, "_disable_scheduling_tools", False):
                continue
            description = function.get("description", "")
            parameters = function.get("parameters") or {"type": "object", "properties": {}}
            # El Agent auto-inyecta ToolSearch: las no-ALWAYS quedan ocultas del
            # wire hasta que search_tools las descubra con su catalogo.
            ts.add_function(
                self._make_tool_func(name),
                name=name,
                description=description,
                defer_loading=name not in ALWAYS_TOOLS,
                prepare=self._make_prepare(name, parameters),
            )
        return ts

    def _make_prepare(self, tool_name: str, parameters: dict[str, Any]) -> Any:
        del tool_name
        # add_function introspects the **kwargs signature, which yields an empty
        # schema; inject the real parameter schema at request time instead.
        def _prepare(ctx: Any, tool_def: Any) -> Any:
            del ctx
            tool_def.parameters_json_schema = parameters
            return tool_def

        return _prepare

    def _make_tool_func(self, tool_name: str) -> Any:
        executor = self._executor

        async def _tool(**kwargs: Any) -> str:
            return await executor.execute(tool_name, kwargs)

        _tool.__name__ = tool_name
        _tool.__qualname__ = f"KatetoToolset.{tool_name}"
        return _tool

    @property
    def toolset(self) -> Any:
        return self._toolset
