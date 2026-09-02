---
id: 74
title: "Bate debate: solapamiento prematuro de oradores por delay estático y voces en tercera persona o eco textual"
severity: Alta
status: resolved
component: kateto/plugins/bate_debate/orchestrator.py
resolved: 2026-08-31
---

## 74. Bate debate: solapamiento prematuro de oradores por delay estático y voces en tercera persona o eco textual

**Severidad:** Alta  
**Componente:** [`kateto/plugins/bate_debate/orchestrator.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/bate_debate/orchestrator.py)

### Descripción

1. En modo debate, el orador siguiente comenzaba a hablar antes de que el orador anterior terminara de reproducir su audio por los parlantes (`audio_output_player`).
2. Algunas voces hablaban de sí mismas en tercera persona (e.g. *"Whisperer cometió un grave error al asumir..."* o *"Tengo que defender la postura de..."*).
3. Los oradores repetían argumentos anteriores o, en el caso del rebate de objeciones, repetían palabra por palabra la objeción del adversario en vez de contestarla, provocando que el TTS reprodujera el mismo texto dos veces seguidas.

### Causa

- **Desincronización de audio:** La función `_wait_for_turn` calculaba una duración con una tasa irreal de 240 WPM y le restaba el tiempo transcurrido desde `started_at`. Dado que `started_at` se registraba antes de la inferencia LLM, el tiempo de prefill/generación consumía toda la duración estimada, provocando un tiempo de espera de 0 segundos e interrumpiendo el habla activa.
- **Sin posturas asignadas:** No se asignaban posturas antagónicas a los debatientes, lo que causaba consenso y que los modelos parafrasearan los mismos argumentos.
- **Instrucciones ambiguas en prompts:** Los prompts decían *"Da tu argumento como X"* o incluían el texto de la objeción en comillas (`"{objection_text}"`), provocando que los modelos pequeños lo completaran como eco en tercera persona.

### Solución aplicada

1. **Sincronización real con `AudioOutputPlayer`:** Se reemplazó el cálculo estático por `_wait_for_speech_finish`, que consulta el estado real `player._playing` del hardware de audio (esperando hasta que termine de reproducir en sounddevice) más el delay configurado.
2. **Asignación formal de posturas:** Se definen posturas explícitas (Afirmativa / Opositora / Crítica) para cada debatiente, impidiendo el consenso o la copia mutua.
3. **Instrucciones estrictas de primera persona y anti-eco:**
   - Prohibición explícita de hablar en tercera persona o decir frases meta (*"Tengo que defender..."*).
   - Inclusión de un verificador anti-eco (`_is_echo`) que detecta si el modelo repite la objeción y la sustituye automáticamente por una defensa auténtica en primera persona.

**Archivos:** `kateto/plugins/bate_debate/orchestrator.py`, `kateto/tests/test_bate_debate.py`
