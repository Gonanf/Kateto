from __future__ import annotations

import argparse
import asyncio  # noqa: ANYIO_OK

from kateto.core import Plugin, PluginManager
from kateto.core.event import GenerateData


class FixtureSubscriber(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.received: list[str | None] = []

    async def on_generate(self, data: GenerateData) -> None:
        self.received.append(data.prompt)


async def run_fixture(mode: str, target: str | None) -> int:
    manager = PluginManager()
    first = FixtureSubscriber("first")
    second = FixtureSubscriber("second")
    await manager.enable_plugin(first)
    await manager.enable_plugin(second)
    try:
        await manager.emit(
            "generate",
            GenerateData(prompt="fixture"),
            source="fixture",
            target=target if mode == "target" else None,
        )
        await manager.wait_for_idle()
        deliveries = len(first.received) + len(second.received)
        manager_alive = all(plugin.enabled for plugin in manager.get_plugins())
        selected_target = target if target is not None else "none"
        print(
            f"TRACE mode={mode} target={selected_target} deliveries={deliveries} "
            f"first={len(first.received)} second={len(second.received)} "
            f"manager_alive={str(manager_alive).lower()}",
        )
        return 0
    finally:
        await manager.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("broadcast", "target"), required=True)
    parser.add_argument("--target")
    arguments = parser.parse_args()
    return asyncio.run(run_fixture(arguments.mode, arguments.target))


if __name__ == "__main__":
    raise SystemExit(main())
