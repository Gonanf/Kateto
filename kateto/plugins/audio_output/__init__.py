__all__ = [
    "AudioOutputPlayer",
    "BosonAudioOutput",
    "CambAudioOutput",
    "EdgeTTSAudioOutput",
    "SoundDeviceOutputFactory",
    "ZonosAudioOutput",
]


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
    if name == "BosonAudioOutput":
        from .boson_tts_plugin import BosonAudioOutput
        globals()["BosonAudioOutput"] = BosonAudioOutput
        return BosonAudioOutput
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_plugins(ctx):
    from importlib import import_module

    plugins = []
    for name, module_name, attr_name, settings_key in [
        ("audio_output_zonos", "kateto.plugins.audio_output.zonos", "ZonosAudioOutput", "audio_output_zonos"),
        ("audio_output_camb", "kateto.plugins.audio_output.camb", "CambAudioOutput", "audio_output_camb"),
        ("audio_output_edgetts", "kateto.plugins.audio_output.edgetts", "EdgeTTSAudioOutput", "audio_output_edgetts"),
        ("audio_output_boson", "kateto.plugins.audio_output.boson_tts_plugin", "BosonAudioOutput", "audio_output_boson"),
        ("audio_output_player", "kateto.plugins.audio_output.player", "AudioOutputPlayer", "audio_output_player"),
    ]:
        settings = ctx.config.settings.plugin.get(settings_key)
        if settings is None:
            continue
        try:
            mod = import_module(module_name)
            cls = getattr(mod, attr_name)
        except ModuleNotFoundError:
            continue
        if settings_key in ("audio_output_camb", "audio_output_edgetts", "audio_output_boson"):
            if settings_key == "audio_output_camb":
                key_id, key_lang = "camb_voice_id", "camb_language"
            elif settings_key == "audio_output_edgetts":
                key_id, key_lang = "edge_tts_voice", None
            else:
                key_id, key_lang = "boson_voice", None
            voice_map = {
                name: {key_id: getattr(vs, key_id, None) if getattr(vs, key_id, None) is not None else vs.get(key_id)}
                | ({} if key_lang is None else {key_lang: getattr(vs, key_lang, None) if getattr(vs, key_lang, None) is not None else vs.get(key_lang)})
                for name, vs in ctx.config.settings.voice.items()
                if (getattr(vs, key_id, None) is not None or vs.get(key_id) is not None)
            }
            plugins.append(cls(settings, voice_map=voice_map))
        else:
            plugins.append(cls(settings))
    return plugins
