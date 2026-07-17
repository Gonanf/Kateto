from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from openai.types.chat import ChatCompletionToolParam

from kateto.core.config import CliSettings
from kateto.core.manager import PluginManager
from kateto.providers.agent import ToolExecutor


class VoiceToolExecutor:
    def __init__(
        self,
        *,
        config_dir: Path,
        manager: PluginManager | None = None,
        cli_settings: CliSettings | None = None,
        working_directory: Path | None = None,
    ) -> None:
        self._config_dir = config_dir.resolve()
        self._manager = manager
        self._cli_settings = cli_settings
        self._working_directory = (working_directory or config_dir).resolve()

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
            case "send_event":
                return await self._send_event(arguments)
            case "list_events":
                return self._list_events()
            case _:
                return json.dumps({"error": f"unknown tool: {name}"})

    async def _send_event(self, args: dict[str, Any]) -> str:
        manager = self._manager
        if manager is None:
            return json.dumps({"error": "no plugin manager available"})

        event_name = args.get("event_name", "")
        if not event_name:
            return json.dumps({"error": "event_name is required"})

        data = args.get("data", {})
        target = args.get("target")
        wait = args.get("wait", False)

        try:
            registrations = list(manager.get_event_registrations())
            registration = None
            for reg in registrations:
                if reg.name == event_name and reg.receivers:
                    registration = reg
                    break
            if registration is None:
                return json.dumps({"error": f"event '{event_name}' has no receivers"})

            payload = registration.contract.model_validate(data)
            correlation_id = None
            reply_to = None
            if wait and target:
                import uuid
                correlation_id = uuid.uuid4().hex
                reply_to = f"voice/{event_name}/{correlation_id}"

            await manager.emit(
                event_name,
                payload,
                source="voice_agent",
                target=target,
                reply_to=reply_to,
                correlation_id=correlation_id,
            )

            if wait and correlation_id:
                return json.dumps({
                    "status": "dispatched",
                    "event_name": event_name,
                    "correlation_id": correlation_id,
                    "note": "waiting for reply not yet implemented in voice agent",
                })

            return json.dumps({"status": "dispatched", "event_name": event_name})
        except Exception as e:
            return json.dumps({"error": f"failed to dispatch event: {e}"})

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
                        "type": field_info.annotation.__name__ if field_info.annotation else "unknown",
                        "required": field_info.is_required(),
                    }
                events.append({
                    "name": reg.name,
                    "receivers": list(reg.receivers),
                    "fields": fields,
                })
        return json.dumps({"events": events})

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
            "description": "Read the contents of a file. Returns the text content.",
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
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    ),
    ChatCompletionToolParam(
        type="function",
        function={
            "name": "send_event",
            "description": "Dispatch an event through the plugin system. Use list_events first to see available events and their fields. Events include backlog_add, backlog_list, cli_execute, todo_completed, and any other registered event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "The event name to dispatch (e.g. 'backlog_add', 'cli_execute')",
                    },
                    "data": {
                        "type": "object",
                        "description": "The event payload as key-value pairs matching the event's fields",
                    },
                    "target": {
                        "type": "string",
                        "description": "Optional target plugin name to route the event to",
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "Whether to wait for a reply event (default: false)",
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
            "description": "List all available events that can be dispatched, including their fields and receivers.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    ),
)
