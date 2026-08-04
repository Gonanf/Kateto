from __future__ import annotations

from cliff.command import Command

_COMMANDS: dict[str, type[Command]] = {}


def register_command(name: str, command: type[Command]) -> None:
    """Register a command for the Kateto CLI.

    Plugins call this to expose a subcommand (`kateto <name>`) without
    touching the core CLI.
    """
    _COMMANDS[name] = command


def all_commands() -> dict[str, type[Command]]:
    return dict(_COMMANDS)
