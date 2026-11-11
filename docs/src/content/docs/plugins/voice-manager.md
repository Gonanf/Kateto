---
title: Voice Manager
description: Voice Manager — documentación de Hipotenusa.
---

# VoiceManager

Routes classifier output to the appropriate voice plugin.

## Purpose

The VoiceManager (`hipotenusa/plugins/system/voice_manager.py`) sits between the classifier and voice agents. Instead of the classifier broadcasting `generate` to all voices, it targets `voice_manager`, which picks ONE voice and emits `speak` to it.

This solves three problems:
- Multiple voices responding simultaneously
- All voices saying the same thing
- Serial TTS sounding identical

## Routing Logic

1. Receives `generate` event from classifier (EXECUTE intent)
2. Filters voice pool by **enabled status** and **capabilities** declared in `VoiceProfile`
3. Picks ONE voice via **weighted random** (configurable in `config.toml`)
4. Emits `speak(target=chosen_voice)` to the selected voice
5. Tracks `speaking_state` via voice_status and voice_idle events

## Configuration

```toml
[plugin.voice_manager]
enabled = true
voice_probabilities = { jane = 0.7, doktor = 0.15, conquest = 0.1 }
```

## Capabilities

Each voice declares capabilities in its `VoiceProfile`:

| Voice | Capabilities |
|-------|-------------|
| jane | orchestration, coordination, general |
| doktor | planning, backlog, risk |
| conquest | agile, ceremonies, process |

The VoiceManager uses these for eligibility filtering. A voice without capabilities matching the input is excluded from the pool.

## Events

| Event | Direction | Purpose |
|-------|-----------|---------|
| `generate` | inbound | Classifier sends intent to route |
| `speak` | outbound | Selected voice receives speak request |
| `speaking_state` | outbound | Broadcasts who is currently speaking |
| `voice_status` | inbound | Tracks voice state changes |
| `voice_idle` | inbound | Tracks when voices finish |
| `voice_enable` | inbound | Enable/disable voices dynamically |

## Interjection (clip IA→IA)

Cuando una voz termina de hablar (`voice_idle` con texto), el VoiceManager puede
pasarle el turno a **otra** voz para que le conteste. El turno rodado vive en
`speak` con `origin="followup"`; el EOT gate no lo clasifica (ver bug 141).

Reglas (todas baratas, ninguna requiere al LLM):

| Knob | Default | Qué decide |
|------|---------|------------|
| `interject_enabled` | `false` | prende el pasador |
| `interject_chance` | `0.55` | probabilidad por turno |
| `interject_max_turns` | `3` | largo de la cadena; al llegar, se corta sola |
| `interject_cooldown` | `6s` | respiro mínimo entre clips |
| `voice_probabilities` | `{}` | peso por voz; si no hay, usa `speak_frequency`/roles |

El par se elige excluyendo al que habló, ponderado por `voice_probabilities`.
El clip nunca arranca sin línea previa, ni sin par, ni con clip apagado.
El habla real del usuario (`on_transcription`) cancela la cadena abierta.

### Prompts: lo que aprendimos midiendo

`_CLIP_PROMPT` **no lleva prohibiciones**. "No repitas lo que dijo" hace que un
modelo chico repita esa frase literal; `no describas la escena`, idem. Todo en
positivo: contexto + semilla + twist + "contestale a {otro} por su nombre, una
sola frase de seis a doce palabras".

Semillas rotan con un **cursor monótono** (`_seed_cursor`), no per-cadena: al
reiniciar en 0, dos cadenas distintas arrancan con la misma semilla y el modelo
escupía la misma frase. `_CLIP_TWISTS` meten un constraint al azar (un objeto de
la casa, un número, una palabra del barrio, un insulto, una hora) para romper la
convergencia verbatim.

Medido con `model=auto` (gpt-oss-120b), 3 corridas de ~110 s, cadencia agresiva
(impulso 7-10 s, chance 1.0, cooldown 1 s):

| Métrica | Resultado |
|---------|-----------|
| cadenas | 21-28 por corrida, 0 descartes, 0 errores 502 |
| largo de línea | 12,2-14,4 palabras (max 18, min 3) |
| dirigidas al par | 22/29 y 31/37 pares (~76 %) |
| duplicadas verbatim | 2-4 de ~40 líneas, casi todas del impulso |

**Piso de modelo:** con LFM3-1.7B y Qwen3.8-2B el mismo prompt filtra las
instrucciones ("Ahora diré qué me provocó…", "I am a voice assistant", inglés
mezclado). El prompt no es el problema: con ~100B rinde. Si algún día Hipotenusa
corre local chico, el clip necesita un modelo ≥8B con buen castellano.

El impulso (`_IMPULSE_PROMPT`) **no es una orden, es una frase de situación**:
`base.py` mete el prompt como mensaje `role="user"`, así que un imperativo
("Decí qué te provoca, en seis a doce palabras") lo lee como algo que le dijo el
humano y el modelo de 120B lo repetía tal cual, palabra por palabra, en el
micrófono. Ahora es:

```
En la sala hay silencio desde hace un rato. Lo último que se oyó fue «…».
¿Qué te provoca eso?
```

La última línea de la sala sale de `_last_line` (lo que dijo cualquier voz): da
material concreto en vez de pedirle que invente de la nada. Medido con
`chance=0` e impulso 8-12 s: ya no repite el pedido, habla de eso
("El silencio me habla de una puerta que no cierra bien").


