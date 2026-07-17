__all__ = ["AudioOutputPlayer", "SoundDeviceOutputFactory", "ZonosAudioOutput"]


def __getattr__(name):
    if name in ("AudioOutputPlayer", "SoundDeviceOutputFactory"):
        from .player import AudioOutputPlayer, SoundDeviceOutputFactory
        globals()["AudioOutputPlayer"] = AudioOutputPlayer
        globals()["SoundDeviceOutputFactory"] = SoundDeviceOutputFactory
        return globals()[name]
    if name == "ZonosAudioOutput":
        from .zonos import ZonosAudioOutput
        globals()["ZonosAudioOutput"] = ZonosAudioOutput
        return ZonosAudioOutput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_plugins(ctx):
    from importlib import import_module

    plugins = []
    for name, module_name, attr_name, settings_key in [
        ("audio_output_zonos", "kateto.plugins.audio_output.zonos", "ZonosAudioOutput", "audio_output_zonos"),
        ("audio_output_player", "kateto.plugins.audio_output.player", "AudioOutputPlayer", "audio_output_player"),
    ]:
        settings = ctx.config.settings.plugin.get(settings_key)
        if settings is None or not settings.enabled:
            continue
        try:
            mod = import_module(module_name)
            cls = getattr(mod, attr_name)
        except ModuleNotFoundError:
            continue
        plugins.append(cls(settings))
    return plugins
