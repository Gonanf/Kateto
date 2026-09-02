from kateto.plugins.game_bridge.game_bridge_plugin import GameBridgePlugin

def create_plugins(ctx):
    settings = ctx.config.settings.plugin.get("game_bridge") if hasattr(ctx.config.settings, "plugin") else None
    return (GameBridgePlugin(settings=settings),)
