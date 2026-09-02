from kateto.core.plugin import Plugin
from typing import Any

class VoyagerTools(Plugin):
    def __init__(self, name="voyager_tools", settings=None):
        super().__init__(name=name, capabilities=("tool",))
        self._active_game = None
        self._active_skills: set[str] = set()
    async def initialize(self):
        pass
    async def on_game_start(self, game: str, skills: list[str]):
        self._active_game = game
        self._active_skills = set(skills)
        for s in skills:
            name = s if s.startswith("voyager_") else f"voyager_{s}"
            if name not in self._manager._tools:
                self._manager.register_tool(name, self._generic, description=f"Voyager {s} (Minecraft mode only)")
    async def _generic(self, **kw):
        tool = kw.get("_tool_name") or "voyager"
        if self._active_game != "minecraft": return f"{tool} only in Minecraft GameMode"
        if tool.replace("voyager_","") not in self._active_skills and tool not in self._active_skills:
            return f"{tool} not enabled for this petition"
        return f"{tool} queued"
