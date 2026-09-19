---
id: 129
title: "La narración de visión cae siempre en las mismas fórmulas de reseñador"
severity: Media
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-18
---

## 129. La narración de visión cae siempre en las mismas fórmulas de reseñador

**Severidad:** Media
**Componente:** `kateto/voices/base.py`

### Descripción

Cuando el agente narra lo que ve, dice siempre cosas por el estilo de "Me parece
interesante que…" o "el usuario está aprendiendo…". No es un problema de
vocabulario: prohibir palabras sólo mueve la fórmula de lugar.

### Impacto

La narración suena a crítico amable repetitivo en vez de a la persona; con el
mismo pedido y material parecido, el modelo chico converge siempre al mismo
molde.

### Causa

1. El marco (`frame_look_at_turn`) **pedía una reseña** ("Opiná en 1 o 2
   frases… qué te parece, qué te llama la atención") — el registro de reseñador
   es el que la propia instrucción induce.
2. El material es un caption **neutral y en tercera persona** ("el usuario
   está…"), así que el modelo comenta *sobre el usuario* en vez de **hablarle
   al usuario**.
3. Sin restricción de forma ni memoria de lo dicho, con el mismo pedido y
   material parecido converge siempre al mismo molde.

**Solución aplicada:**

Estructural, sin listas negras de palabras:

1. **El marco pasa de "reseñar" a "reaccionar en voz alta"**: una sola línea
   corta (≤ ~18 palabras), hablándole al usuario en segunda persona sobre el
   **contenido** de la pantalla (lo que dice el OCR), nunca sobre su actividad
   ni nombrándolo en tercera persona. Se mantienen las prohibiciones: no pedir
   instrucciones, no inventar.
2. **Variedad por construcción**: pool de 6 ángulos (queja, pregunta,
   predicción, chiste seco, consejo, dato). Cada narración recibe **un** ángulo
   sorteado con un rng inyectable (`VoiceAgent._narration_rng`), sin repetir el
   de la narración anterior (`pick_narration_angle`). El marco lo dice
   explícito: "Esta vez: <ángulo>".
3. **Memoria de lo dicho**: `VoiceAgent._recent_narrations` (`deque(maxlen=5)`)
   guarda las últimas narraciones (texto final del turno cuando el origen es
   `[look-at …]`); el marco las incluye ("Ya dijiste esto — no repitas ni el
   ángulo ni la forma de arrancar").
4. **Backstop numérico**: si la narración nueva tiene ratio ≥ 0.85 (mismo
   criterio que `_caption_ratio`, fix-111) contra cualquiera de las últimas 3,
   **no se habla**: se loguea y se descarta (`_narration_is_repeat`). En modo
   streaming, las frases de una narración se bufferizan hasta el final del
   turno (es una línea corta: costo cero) para poder descartar antes del audio;
   el turno normal sigue streaming frase a frase sin tocar la latencia.

El marco sigue viviendo en el turno volátil: el prefijo cacheable del prompt
estable no cambió.

**Archivos:** `kateto/voices/base.py`, `kateto/tests/test_vision_narration_variety.py`, `kateto/tests/test_vision_repeat_opinion.py`
