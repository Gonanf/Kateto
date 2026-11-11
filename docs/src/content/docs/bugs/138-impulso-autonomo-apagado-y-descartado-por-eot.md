---
id: 138
title: "Las voces nunca hablaban solas: el impulso estaba apagado en config y, prendido, el EOT gate lo descartaba"
severity: Alta
status: resolved
component: kateto/plugins/system/voice_manager.py, kateto/plugins/system/turn_gate.py, kateto/core/event.py
resolved: 2026-11-08
---

## 138. Las voces nunca hablaban solas (impulso apagado + EOT descartándolo)

**Severidad:** Alta
**Componente:** `kateto/plugins/system/voice_manager.py`, `kateto/plugins/system/turn_gate.py`, `kateto/core/event.py`, `kateto/voices/base.py`

### Descripción

El habla autónoma (una voz que opina sola cada tanto, al azar) no ocurría nunca,
aunque el mecanismo existe desde el commit `00324ee`.

### Impacto

Las 5 voces quedaban mudas hasta que alguien les hablara: se perdía el stream
autónomo para el que existe Hipotenusa.

### Causa

Dos causas encadenadas, y la segunda sólo se ve cuando la primera se arregla:

1. `VoiceManager._impulse_loop` sale en la primera línea si
   `impulse_enabled` no está prendido (`_setting(settings, "impulse_enabled", False)`).
   Esa clave **no existía en `config.toml` ni en el template**, así que el impulso
   quedaba apagado por defecto y no había forma de descubrirlo salvo leyendo el código.
2. El impulso emitía `SpeakRequestData(voice, prompt)` sin `origin`, y `on_speak`
   lo mandaba al TurnGate como `origin="external"`. El EOT gate clasifica ese texto
   como si fuera un turno del usuario y devuelve `SUPPRESS` para un enunciado
   imperativo/aislado (`"Nadie te habló. Mirá lo último que viste…"`), o sea
   `Decision.DISCARD` → la voz nunca generaba. Medido con el gate arreglado (bug 135):
   `"hola, qué tal?"` → `suppress`.

### Solución aplicada

- `SpeakRequestData` ganó `origin: str | None` (mismo vocabulario que
  `GenerateData.origin`), y `on_speak` lo usa en vez de hardcodear `"external"`.
- El impulso emite con `origin="impulse"`.
- `TurnGate.adecide_eot` y `TurnGate.decide` tratan `"impulse"` igual que `"ambient"`
  (habla no pedida): nunca compite con el usuario, no encola, no reclama el turno,
  y **no pasa por el clasificador de EOT**.
- Config: `impulse_enabled/impulse_min/impulse_max/impulse_fresh` en
  `~/.config/kateto/config.toml` (90s–4m, estímulo fresco 10m) y documentadas en
  `config/defaults/config.toml`.

### Verificación observada

Corrida real con `impulse_min="8s"`, `impulse_max="12s"` (para no esperar minutos):

```
voice_manager: impulso, elchacal habla por su cuenta
voice_manager: impulso, elgarca habla por su cuenta
voice_manager: impulso, pagliacci habla por su cuenta
voice_manager: impulso, dionisio habla por su cuenta
voice_manager: impulso, truman habla por su cuenta
```

6 impulsos en ~60 s, cero `narration discarded`, y audio real en el device
(`[piper] synth start`, `[player] played lane=dionisio audio_ms=1621`).
Después se restauró 90 s / 4 m. `pytest test_turn_gate test_eot_gate
test_audio_barge_in test_inter_voice_generate test_dept_scoped_interrupt` → 60 passed.

### Archivos

`kateto/plugins/system/voice_manager.py`, `kateto/plugins/system/turn_gate.py`,
`kateto/core/event.py`, `kateto/voices/base.py`, `~/.config/kateto/config.toml`,
`config/defaults/config.toml`
