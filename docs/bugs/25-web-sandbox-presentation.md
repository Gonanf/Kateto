---
id: 25
title: "Web sandbox: presentación interactiva del sistema Kateto"
severity: Media
status: resolved
component: web/ (nuevo)
resolved: 2026-07-19
---

## 25. Web sandbox: presentación interactiva del sistema Kateto

**Severidad:** Media
**Componente:** `web/` (nuevo directorio propuesto)

### Descripción

Preparar una presentación del sistema Kateto en la web con un sandbox interactivo donde los visitantes puedan:
- Ver el sistema funcionando en vivo
- Interactuar con las voces (Jane, Doktor, Conquest)
- Explorar la arquitectura de plugins y eventos
- Probar comandos y ver respuestas en tiempo real

### Investigación

**Opciones para el sandbox:**

1. **WebContainer (StackBlitz)** — Corre Node.js en el browser via WebAssembly. Ideal para demos de frontend, pero Kateto es Python asyncio. No corre Python nativamente.

2. **Pyodide / Pyodide + WebWorker** — Python en el browser via WebAssembly. Corre 3.12. Limitaciones: sin asyncio completo, sin acceso a GPU/audio, sin subprocesos. No sirve para el stack real (llama.cpp, whisper.cpp, Zonos).

3. **CodeSandbox / GitHub Codespaces** — Entorno cloud completo con terminal. Corre el stack real. El usuario necesita login. No es "sandbox inmediato".

4. **Cloudflare Workers + Durable Objects** — Para una versión demo liviana. Limitado a JS/TS. Podría servir para un "simulador" de eventos pero no corre el stack real.

5. **Playground web custom (RECOMENDADO):**
   - Backend: servidor Python asyncio corriendo Kateto en modo fixture
   - Frontend: Web UI vanilla HTML+CSS+JS (sin build step)
   - WebSocket para streaming de eventos en tiempo real
   - Terminal embebida (xterm.js) en Fase 2
   - **Opción más viable — implementada parcialmente**

6. **Modal / RunPod / HuggingFace Spaces** — Hosting cloud del stack completo. Spaces soporta Gradio, Modal tiene GPUs. Costo asociado.

**Recomendación para MVP: Opción 5 (Playground custom) corriendo Kateto en modo fixture.**

**Stack tecnológico validado:**
- Frontend: HTML5 + CSS3 + Vanilla JS — zero dependencies, sin build
- Backend sandbox: FastAPI + WebSocket + Kateto fixture (Python puro)
- Deploy: Cloudflare Pages (frontend) + Fly.io/Railway (backend opcional)
- Terminal: xterm.js (Fase 2)

### Plan ejecutado

**Fase 0 — Dashboard informativo (COMPLETADA):**
- `web/index.html` — Dashboard interactivo con logo, capabilities grid, voices, event stream y CTA
- `web/app.js` — Vanilla JS con soporte WebSocket + fallback a mock data para standalone
- `web/PLAN.md` — Evaluación de opciones, stack, timeline, arquitectura propuesta

### Plan propuesto

1. **Fase 1 — WebSocket backend:**
   - Extender `kateto/live.py` para exponer WebSocket endpoint
   - Puerto configurable via `config.toml` o flag `--web-port`
   - Transmitir eventos del bus al WebSocket
   - Health check endpoint (`GET /health`)

2. **Fase 2 — Sandbox interactivo:**
   - Terminal embebida con xterm.js
   - Panel de control de plugins (enable/disable)
   - Selector de voces con estado en vivo
   - Input de texto para simular transcripción

3. **Fase 3 — Demos guiadas:**
   - Tour interactivo de 5 pasos
   - Scenarios pre-cargados (sprint planning con Conquest, risk analysis con Doktor)
   - Botón "Show me what happens" que dispara eventos animados

4. **Fase 4 — Deploy:**
   - Cloudflare Pages (frontend)
   - Opciones backend: Cloudflare Workers (simulador) o servidor dedicado (stack real)

### Solución aplicada

1. Creado `web/` en la raíz del proyecto
2. Desarrollado `web/index.html` + `web/app.js` — dashboard standalone con mock data
3. Documentadas todas las opciones de sandbox en `web/PLAN.md` con pros/cons y timeline
4. El frontend soporta detección automática: con meta tag `kateto-ws` se conecta vía WebSocket; sin él funciona en modo standalone con eventos mock

**Archivos:** `web/index.html`, `web/app.js`, `web/PLAN.md`
