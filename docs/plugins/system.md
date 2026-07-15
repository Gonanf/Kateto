# System Plugins

## TUI Plugin (P0)

Terminal UI using **Textual** with live visualization of the bus and plugin states.

### Features
- View active/inactive plugins (polls `get_plugins()` / `get_events()`)
- View events in real time
- Enable/disable plugins at runtime
- Send events manually

### Display
```
┌─ Workflows ─────────────────────────────┐
│ Doktor · gestion-proyecto · 🟡 Fase 1/2 │
│   ├ Estado: RUNNING                     │
│   ├ Fase activa: "Planificación"        │
│   ├ Progreso: 3/8 instrucciones         │
│   └ Checkpoints: 2/3 ✓                 │
│                                         │
│ Conquest · review-sprint · 🟢 COMPLETED │
│ Jane · ───────────── · ⚪ INACTIVE      │
└─────────────────────────────────────────┘
```

## MCP Plugin (P0)

Serves a **Model Context Protocol** server that exposes system events (getters and setters) with **auto-detected types and instructions** from the event registry.

### Auto-Detection

When a plugin module is imported, the system:
1. Scans its class for `on_*` methods (events it receives)
2. In `initialize()`, the plugin registers events it can emit (name + data type)
3. The MCP Server uses this registry to dynamically generate:

- **Tools**: Full PluginManager API (`emit`, `enable_plugin`, `disable_plugin`, `get_plugins`, `get_events`). Every registered event is also exposed as an invocable tool.
- **Resources**: Current system state

### Key Tool

`send_event(event_name, data, target, wait=False)` — when `wait=True`, the call blocks until the targeted plugin emits a response event (enables request-response patterns over the async bus).

### Purpose

Allows external AI agents (Codex, Claude, etc.) to communicate with Kateto through the MCP protocol.
