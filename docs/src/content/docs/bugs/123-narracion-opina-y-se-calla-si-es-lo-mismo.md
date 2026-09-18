---
id: 123
title: "Narración de visión: que opine (no que describa literal) y que se calle si la pantalla es la misma"
severity: Alta
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 123. Narración de visión: que opine (no que describa literal) y que se calle si la pantalla es la misma

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/static_vision_plugin.py` (prompt + silencio por repetición), `kateto/voices/base.py` (instrucción de turno)

### Descripción

Pedido del usuario (textual): "Comenta literalmente lo que ve, yo quiero que
opine, y si va a opinar de lo mismo (la imagen es similar o exactamente igual
a lo que ya vio antes) entonces no me sirve."

Tres causas:

1. El prompt al VLM pedía un inventario literal en inglés
   (`Describe what happens across these N screen frames ... One short
   timestamped description.`) — el VLM devolvía una enumeración, sin nada
   opinable.
2. La instrucción de turno del fix-109 (`frame_look_at_turn`) decía "comentá
   lo que ves en 1 o 2 frases" — el modelo repetía el caption.
3. Sin noción de "ya vi esto": el plugin dedupeaba frames dentro de la
   ventana, pero entre ventanas no comparaba nada — con la pantalla quieta
   narraba la misma escena cada 30 s, gastando un VLM por tick.

### Impacto

Narración literal repetida cada 30 s con la pantalla quieta (estudiando):
ruido ambiental + costo VLM por tick sin información nueva.

### Causa

Prompt descriptivo + instrucción de turno descriptiva + ausencia de memoria
entre ventanas periódicas.

### Solución aplicada

1. Prompt al VLM en español que pide material opinable (qué se ve breve +
   qué llama la atención / qué cambió entre primera y última), sin inventar:
   el VLM aporta los hechos, la voz aporta la opinión.
2. Instrucción de turno: opinión/comentario en personaje (qué le parece, qué
   le llama la atención, qué haría o preguntaría), con prohibición explícita
   de repetir la descripción literal. En el idioma configurado (como ya
   estaba).
3. Silencio ante repetición, sólo en el camino periódico:
   - Por imagen: dHash de 64 bits del frame representativo por fuente,
     comparado por distancia de Hamming contra la última ventana narrada.
     Por debajo del umbral (`vision_repeat_hamming_max`, default 6) no se
     llama al VLM/sidecar ni se emite narración (log `info` con los bits).
   - Por texto: si el caption nuevo es casi idéntico al anterior
     (`vision_repeat_text_min_ratio`, default 0.9, `difflib`) no se narra
     (el resultado sí se emite; el `generate` no).
   - El look-at pedido por el usuario siempre contesta, aunque la imagen sea
     la misma; además actualiza la última ventana vista.
4. Observable: el log dice si narró (con el caption), si se calló por imagen
   repetida (hamming numérico) o por caption repetido (similitud numérica).

**Regresión:** `kateto/tests/test_vision_repeat_opinion.py` (6 tests: misma
pantalla calla sin VLM, distinta narra, caption idéntico calla por texto,
pedido siempre contesta, instrucción pide opinión y prohíbe el literal,
prompt en español que pide lo llamativo).

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`,
`kateto/voices/base.py`, `kateto/tests/test_vision_repeat_opinion.py`,
`docs/src/content/docs/plugins/vision.md`
