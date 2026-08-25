---
title: Por qué Kateto
description: La filosofía detrás de Kateto y en qué se diferencia del software similar (LangGraph, TEN, LiveKit, agent frameworks).
---

# Por qué Kateto

Kateto no es un chatbot más ni un framework de agentes genérico. Es un **equipo de voces event-driven** para trabajo de proyectos. Esta página explica por qué existe y dónde está el límite con el software similar.

## El problema que resuelve

Un pipeline de conversación fijo (STT → LLM → TTS) sirve para un asistente. Kateto quiere **un equipo**: varias voces con roles (Jane coordina, Doktor planifica, Conquest ejecuta ceremonias ágiles) que deciden *entre ellas* qué hacer, publicando y suscribiendo eventos tipados en un bus. El sistema no tiene un mediador central: el `PluginManager` es a la vez **event bus + lifecycle manager**.

## Comparación con software similar

### LangGraph / grafos de agentes

LangGraph modela el flujo como un **grafo dirigido cableado** (nodos y aristas explícitas). Kateto usa **pub/sub reactivo**: cada plugin tiene su `asyncio.Queue` y suscribe métodos `on_*`; el dispatch lo decide el bus (broadcast, target, capabilities, only_once).

> Son dualmente opuestos en acoplamiento: pub/sub desacoplado vs grafo cableado. Usar LangGraph tiraría la propiedad que justifica a Kateto: que cualquier nodo — input de usuario, cron, workflow, otro agente — pueda ser publisher y subscriber sin re-cablear el grafo.

### TEN Framework (motor de hosting de grafos)

TEN es un **motor de hosting**: runtime de grafo (nodos STT/LLM/TTS/avatar con latencia garantizada, viene con avatar de vtuber). Kateto es un grafo **conceptual** (PluginManager pub/sub).

> No son equivalentes por "ser grafos" — topología ≠ esencia. Si se quisiera un runtime real con latencia garantizada, TEN es donde parar el diseño de Kateto; hoy el pegamento propio alcanza (YAGNI).

### LiveKit (voz en tiempo real)

LiveKit es un framework de **voz en tiempo real**: VAD, turn-detection, barge-in. Su aporte único es `falseInterruptionTimeout` (distinguir interrupción real de un backchannel tipo "ajá").

> Esa capacidad ya está cubierta por el **Interrupt Executor** de Kateto (§3 de SPEC_2): polling event-driven solo cuando alguien habla, con LLM de salida estructurada acotada (`ShouldInterrupt`) y `interject` al mixer concurrente.

### Frameworks de agentes (smolagents, pydantic-ai, OpenCode)

Son herramientas para **que un agente haga tareas** (tool-calling, file system, shell). Kateto las **consume como delegados**: cuando una voz necesita ejecutar, delega a OpenCode/agy/Hermes. Dentro de Kateto, pydantic-ai se usa SOLO para decisiones acotadas (`ShouldInterrupt`, tool calls de acción) — no para creative writing de voces, porque el structured output rompe la generación creativa (verificado en pruebas).

### TEN vs Kateto vs LiveKit — resumen

| | Kateto | TEN | LiveKit |
|---|---|---|---|
| Modelo | Pub/sub (PluginManager) | Grafo cableado | Voz en tiempo real |
| Latencia garantizada | No (diseño) | Sí | Turn-based |
| Avatar/vtuber | Overlay propio | Incluido | No |
| Interrupción consciente | Interrupt Executor | - | falseInterruptionTimeout |

## La filosofía 7P

1. **P1 Libre/BYO** — defaults ONNX+Vulkan, EdgeTTS, modelo pequeño (ternary-bonsai 1.7B). El usuario elige modelos e inferencia.
2. **P2 Linux 1ro** — platformdirs, sin APPDATA/XDG manual.
3. **P3 Divertido/teatro** — voces extremas, nunca bot.
4. **P4 Útil** — asumen información; no preguntan salvo 100% necesario e irresoluble por archivos/tools.
5. **P5 Rubber Ducky** — el acto de explicar debuggea.
6. **P6 Reactivo** — streaming, async; anti-duplicación de plugins; defaults pequeños, calidad opt-in.
7. **P7 Voz 1ro** — mic por defecto, speech-friendly sin markdown, robusto a ASR ruidoso.

## Data plane vs Control plane

Una decisión de diseño central: los tokens de LLM y el PCM de TTS van por **canal directo** (async generator / cola), NUNCA por `emit()` por token. El bus solo transporta `generate`, `speak`, `interrupt`, `idle`, `speaking_state`. Esto mantiene el bus barato y la latencia baja.

## Cómo evoluciona sin romper

- **Hot-reload**: watcher `watchfiles` → `PluginManager.replace_plugin` (disable+swap+enable). No live-patch con `importlib.reload` suelto (deja estado zombie).
- **Worktrees**: cada feature independiente vive en su propio git worktree y se mergea a master secuencialmente después de testear.
- **Coding delegado**: Kateto no escribe su propio código; las voces delegan a agentes de coding (OpenCode, agy) que trabajan en worktrees separados.
