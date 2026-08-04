from __future__ import annotations

from cliff.app import App
from cliff.commandmanager import CommandManager

from kateto.cli.registry import all_commands


class KatetoCommandManager(CommandManager):
    """Command manager backed by the internal registry (SPEC §2).

    Uses the internal `kateto.cli.registry` instead of stevedore entry
    points so plugins register commands with `register_command()` without
    packaging plumbing. A stevedore namespace can be layered on later.
    """

    def __init__(self, namespace: str | None = None) -> None:
        super().__init__(namespace=namespace)
        for name, factory in all_commands().items():
            self.add_command(name, factory)


class KatetoApp(App):
    NAME: str = "kateto"
    VERSION: str = "0.1.0"

    def __init__(self) -> None:
        super().__init__(
            description="Kateto event-driven voice team",
            version=self.VERSION,
            command_manager=KatetoCommandManager(),
            deferred_help=True,
        )
