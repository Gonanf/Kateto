---
id: 77
title: "OpenAI-compatible API Server: interfaz HTTP /v1/chat/completions sobre el bus de eventos nativo de Kateto"
severity: Media
status: resolved
component: kateto/plugins/system/openai_server.py
resolved: 2026-08-31
---

## 77. OpenAI-compatible API Server: interfaz HTTP /v1/chat/completions sobre el bus de eventos nativo de Kateto

**Severidad:** Media  
**Componente:** [`kateto/plugins/system/openai_server.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/system/openai_server.py), [`kateto/plugins/system/http_server.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/system/http_server.py)

### Descripción

Se implementó una capa de compatibilidad con la API de OpenAI (`/v1/models`, `/v1/chat/completions`, `/v1/completions`) que permite a clientes externos (Open WebUI, LibreChat, SillyTavern, Cursor, extensiones o scripts de juegos en Unity/Godot) interactuar con las voces de Kateto usando los SDKs oficiales de OpenAI, preservando simultáneamente la arquitectura interna basada en eventos y plugins.

### Funcionamiento

1. **Mapeo de modelos a voces:** El campo `model` en la petición (`"jane"`, `"doktor"`, `"conquest"`, `"whisperer"`) selecciona la voz destinataria de Kateto.
2. **Propagación nativa por el Bus de Eventos:**
   - La petición entrante emite un evento `generate` hacia `PluginManager`.
   - Se preservan intactos el carácter [`SOUL.md`](file:///home/chaos/.config/kateto/voices/jane/SOUL.md), la memoria, las herramientas (*tools*) y el turn-gating de la voz.
   - Los avatares del overlay visual reaccionan a los visemas en tiempo real y el TTS reproduce o transmite audio simultáneamente.
3. **Streaming SSE (`stream: true`):** Emite fragmentos Server-Sent Events en formato estándar `chat.completion.chunk` a medida que llegan los eventos `text_chunk`, finalizando con `data: [DONE]`.
4. **Modo síncrono (`stream: false`):** Acumula los fragmentos y devuelve el objeto JSON `chat.completion` con conteo estimado de tokens de uso.

**Archivos:** `kateto/plugins/system/openai_server.py`, `kateto/plugins/system/http_server.py`, `kateto/tests/test_openai_server.py`
