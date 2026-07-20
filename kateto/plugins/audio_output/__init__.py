__all__ = ["AudioOutputPlayer", "CambAudioOutput", "EdgeTTSAudioOutput", "SoundDeviceOutputFactory", "ZonosAudioOutput"]


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
    if name == "CambAudioOutput":
        from .camb import CambAudioOutput
        globals()["CambAudioOutput"] = CambAudioOutput
        return CambAudioOutput
    if name == "EdgeTTSAudioOutput":
        from .edgetts import EdgeTTSAudioOutput
        globals()["EdgeTTSAudioOutput"] = EdgeTTSAudioOutput
        return EdgeTTSAudioOutput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_plugins(ctx):
    from importlib import import_module

    plugins = []
    for name, module_name, attr_name, settings_key in [
        ("audio_output_zonos", "kateto.plugins.audio_output.zonos", "ZonosAudioOutput", "audio_output_zonos"),
        ("audio_output_camb", "kateto.plugins.audio_output.camb", "CambAudioOutput", "audio_output_camb"),
        ("audio_output_edgetts", "kateto.plugins.audio_output.edgetts", "EdgeTTSAudioOutput", "audio_output_edgetts"),
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
        if settings_key in ("audio_output_camb", "audio_output_edgetts"):
            if settings_key == "audio_output_camb":
                key_id, key_lang = "camb_voice_id", "camb_language"
            else:
                key_id, key_lang = "edge_tts_voice", None
            voice_map = {
                name: {key_id: getattr(vs, key_id, None)}
                | ({} if key_lang is None else {key_lang: getattr(vs, key_lang, None)})
                for name, vs in ctx.config.settings.voice.items()
                if getattr(vs, key_id, None) is not None
            }
            plugins.append(cls(settings, voice_map=voice_map))
        else:
            plugins.append(cls(settings))
    return plugins
