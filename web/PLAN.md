# Kateto Web Sandbox — Plan

## Evaluación de opciones de sandbox

| Opción | Pros | Contras | Veredicto |
|--------|------|---------|-----------|
| **WebContainer (StackBlitz)** | Node.js en browser, zero setup, ideal para frontend demos | No corre Python. Kateto es Python asyncio. No sirve. | ❌ |
| **Pyodide / PyScript** | Python 3.12 en browser via WebAssembly | Sin asyncio completo, sin GPU, sin subprocesos. No puede correr llama.cpp, whisper.cpp, Zonos. | ❌ |
| **CodeSandbox / GitHub Codespaces** | Entorno cloud completo, terminal real, corre stack real | Requiere login. No es sandbox inmediato. Latencia. | ⏸️ Opción para Fase 3 |
| **Cloudflare Workers + DO** | Edge-deployed, sin servidor, escalable | JS/TS only. Podría servir como *simulador* de eventos Kateto, pero no corre el runtime real. | ⏸️ Backend opcional para Fase 2 |
| **Playground custom (WebSocket + fixture)** | Corre Kateto real en modo fixture. Sin dependencias externas. Eventos en tiempo real vía WS. Terminal embebida. | Requiere servidor Python corriendo. No es zero-setup para el visitante. | ✅ **RECOMENDADO MVP** |
| **HuggingFace Spaces / Modal** | Hosting cloud con GPU, soporta Gradio | Costo asociado. Overhead operacional. | ⏸️ Fase 4 - Deploy |

## Recomendación técnica

**MVP: Frontend vanilla (HTML+CSS+JS) + Backend Kateto en modo fixture con WebSocket.**

Razones:

1. **Sin build step.** Vanilla JS elimina la necesidad de Vite, Webpack, npm. Un solo `index.html` + `app.js`. El proyecto Kateto ya usa `uv` como toolchain; agregar Node.js es fricción innecesaria.

2. **Fixture mode existe.** Kateto ya tiene `--fixture` que provee datos deterministas sin servidores externos. Extenderlo para servir WebSocket es trivial.

3. **WebSocket ya está en el stack.** El `McpEventServer` interno usa `fastmcp` que soporta transporte SSE/WebSocket. Solo hay que exponer un puerto HTTP.

4. **Progresión natural:**
   - Hoy: dashboard estático con mock data (standalone)
   - Mañana: conectar a Kateto via WebSocket local
   - Futuro: sandbox server-side con instancias aisladas

## Stack tecnológico propuesto

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| Frontend | HTML5 + CSS3 + Vanilla JS | Zero dependencies, sin build, funciona directo desde filesystem o cualquier static host |
| Backend (sandbox) | FastAPI + WebSocket + Kateto fixture | Python puro, mismo ecosistema que el proyecto, `asyncio` nativo |
| Terminal embebida | xterm.js (opcional, Fase 2) | Para comandos interactivos en la web |
| Deploy frontend | Cloudflare Pages | Gratuito, CDN global, integración con GitHub |
| Deploy backend (opcional) | Fly.io / Railway / Cloudflare Workers (simulador) | Escalado elástico, sin ops |

## Timeline estimado

### Fase 0 — Dashboard informativo (esta iteración)
- [x] `web/index.html` + `web/app.js` — UI con capabilities, voices, event stream
- [x] Mock data para demostración standalone
- [ ] Documentación de setup

**Estimación:** 1 día

### Fase 1 — WebSocket backend
- [ ] Extender `kateto/live.py` para exponer un WebSocket endpoint
- [ ] Puerto configurable via `config.toml` o flag `--web-port`
- [ ] Transmitir eventos del bus al WebSocket
- [ ] Health check endpoint (`GET /health` → status JSON)

**Estimación:** 2-3 días

### Fase 2 — Sandbox interactivo
- [ ] Terminal embebida (xterm.js) para comandos
- [ ] Panel de control de plugins (enable/disable)
- [ ] Selector de voces con estado en vivo
- [ ] Input de texto para simular transcripción

**Estimación:** 3-4 días

### Fase 3 — Demos guiadas
- [ ] Tour interactivo de 5 pasos
- [ ] Scenarios pre-cargados (sprint planning, risk analysis)
- [ ] Botón "Show me what happens" con eventos animados

**Estimación:** 2-3 días

### Fase 4 — Deploy
- [ ] Frontend en Cloudflare Pages
- [ ] Backend en Fly.io o Railway (o Workers simulador)
- [ ] GitHub Actions para CI/CD

**Estimación:** 2 días

**Total estimado:** ~10-13 días hábiles para sandbox completo.

## Cómo probar localmente

```bash
# 1. Abrir el dashboard standalone
open web/index.html

# 2. (Futuro) Iniciar Kateto con WebSocket habilitado
uv run kateto run --web-port 8765

# 3. Abrir con backend
open web/index.html#ws://localhost:8765
```

## Arquitectura (borrador)

```
┌─────────────┐     WebSocket      ┌──────────────────┐
│   Browser   │ ◄──────────────►  │  Kateto Runtime   │
│  index.html │     events:        │                   │
│  app.js     │     TRANSCRIPTION  │  PluginManager    │
│             │     CLASSIFICATION │  VoiceAgents      │
│             │     GENERATE       │  WorkflowEngine   │
│             │     AUDIO_CHUNK    │  (fixture mode)   │
└─────────────┘                    └──────────────────┘
```

El frontend se conecta al runtime via WebSocket. Los eventos del bus se serializan a JSON y se transmiten en vivo.

## Conexión con el MCP server existente

El `McpEventServer` en `kateto/plugins/system/mcp_server.py` ya expone un API vía `fastmcp`. Para el sandbox, en lugar de (o además de) MCP, exponemos un WebSocket directo que:

1. Se suscribe a todos los eventos del bus (`manager.add_event_observer`)
2. Los serializa a JSON y los envía al cliente
3. Recibe comandos del cliente (simular transcripción, ejecutar workflow, etc.)

Esto es más simple que usar MCP para la UI interactiva — MCP queda para integraciones con herramientas externas.
