---
id: 9
title: "List plugins response lost in text_chunk capture"
severity: Baja
status: resolved
component: kateto/voices/base.py, _agent_loop
---

## 9. List plugins response lost in text_chunk capture — ✅ RESUELTO

**Severidad:** Baja
**Componente:** `kateto/voices/base.py`, `_agent_loop`

Cuando Jane responde a un generate con una respuesta larga que incluye `\n` al inicio, el `_emit_chunk` emite un `text_chunk` event. Sin embargo, el chunk solo contiene el contenido de `response.text`, que puede estar vacío o tener solo `\n` cuando el modelo genera una respuesta de tool_call + texto combinado.

**Evidencia:**
```
AGENT_LOOP got response: text='\n' tool_calls=1
AGENT_LOOP got response: text='\nTodos los plugins están habilitados...' tool_calls=0
# Pero el text_chunk capturado está vacío
```

**Causa:** El modelo LLM (Kateto) genera reasoning tokens en `<think>` tags que no se incluyen en `response.text`. El texto visible solo aparece después del tool_call, pero el primer chunk puede estar vacío.

**Impacto:** Respuestas parcialmente perdidas en el TUI. No es un bug crítico pero afecta la experiencia.

**Solución aplicada:** Se agregó `.strip()` al check `if response.text and response.text.strip():` en `_agent_loop()`. Chunks con solo whitespace ya no se emiten.

**Fix:** En `VoiceAgent._agent_loop()`, se agregó `.strip()` al check de texto antes de emitir chunks: `if response.text and response.text.strip():`. Esto evita emitir chunks vacíos o con solo `\n` cuando el modelo genera tool_calls + texto combinado.

**Archivos:** `kateto/voices/base.py`

**Evidencia:** Chunks con solo whitespace ya no se emiten como `text_chunk`.
