---
id: 141
title: "El EOT gate clasificaba los turnos IA->IA como si fueran del usuario y los descartaba (SUPPRESS)"
severity: Alta
status: resolved
component: kateto/plugins/system/turn_gate.py
resolved: 2026-11-08
---

## 141. Los turnos IA→IA se descartaban en el EOT gate

**Severidad:** Alta
**Componente:** `kateto/plugins/system/turn_gate.py`

### Descripción

Con el pasador de turno IA→IA (clip) andando, varias respuestas entre voces no se
oían: `[voz] turn discarded (followup)` en el log, con el clip encadenándose a medias.

### Impacto

Los clips de dos IAs se cortaban en el segundo turno; el público oía una línea y un
silencio.

### Causa

`adecide_eot` sólo salteaba el clasificador para `origin="ambient"`. Un turno
`followup` (IA→IA) y un `impulse` caían en `gate.aclassify(prompt)`: el clasificador
de fin-de-turno mira ese texto como si lo hubiera dicho el **usuario** de la
conversación y devuelve `SUPPRESS` para cualquier enunciado imperativo o
descontextualizado — y el prompt de clip es exactamente eso ("Contá tu parte del
plan…"). Resultado: `Decision.DISCARD`.

Medido antes del fix: 8 descartes de `followup`/`impulse` en 90 s de corrida.

### Solución aplicada

`adecide_eot` saltea el clasificador para todo lo que no sea turno del usuario:

```python
if origin in ("ambient", "impulse", "followup"):
    return self.decide(voice=voice, prompt=prompt, origin=origin)
```

El EOT gate queda decidindo sólo sobre `origin="external"` (lo que dijo el humano).

### Verificación observada

Misma corrida de clips, después del fix: **0 descartes**, cadenas de 3 turnos
completas (`clip turn 1/3 → 2/3 → 3/3`), voces alternadas, audio real en el device
(`[piper] synth start` + `[player] played`). 41 tests passed (voice_manager_clip,
turn_gate, eot_gate, inter_voice_generate, dept_scoped_interrupt).

### Archivos

`kateto/plugins/system/turn_gate.py`, `kateto/tests/test_voice_manager_clip.py`
