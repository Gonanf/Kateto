---
title: SPEC de run mode
description: Arquitectura del runtime — run_mode.py sin dependencias de plugins por nombre (discovery declarativo).
---

# SPEC de run mode

El objetivo del refactor de `run_mode.py` es que el runtime **no dependa de plugins por nombre**: hoy importa por nombre VoiceManager, WorkflowEngine, HttpServer, ExternalMcpManager, McpEventServer y calendar. El target es **discovery declarativo**: los plugins se auto-registran y `run_mode` solo arranca el `PluginManager`.

## Estado

- **Pendiente de refactor.** El doc original `docs/run-mode-SPEC.md` fue eliminado del repo junto con SPEC.md/SPEC_2.md; su contenido se redistribuyó al sitio de docs.
- Ver también: [Runtime headless](/runtime/headless/), [Pipeline de audio](/runtime/pipeline/), [Overlay visual](/runtime/overlay/).
