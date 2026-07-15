# PluginManager

The **PluginManager** is a singleton that is injected into every plugin during initialization. It is the heart of the system: it handles plugin lifecycle AND event routing (the Event Bus is a concept within the PluginManager, not a separate component).

## API

| Method | Description |
|---|---|
| `register_event(name, contract)` | Register a new event in the bus |
| `emit(event_name, data, source=None, capabilities=None, target=None, only_once=False)` | Emit an event to subscribers (with optional capability filter, target, or only_once flag) |
| `enable_plugin(name)` | Enable a plugin at runtime |
| `disable_plugin(name)` | Disable a plugin at runtime |
| `get_plugins()` | Get logs/status of all plugins |
| `get_events()` | Get logs of emitted events |
| `interrupt(target=None)` | Emit interrupt event (to all or a specific target) |

## Plugin Lifecycle

1. **Load**: Plugin module is imported
2. **Initialize**: Manager singleton and plugin-specific config are injected
3. **Event Registration**: `on_*` methods are scanned and registered as subscribers; plugin registers events it can emit
4. **Enable**: Plugin starts receiving events
5. **Disable**: Plugin unregisters from all events, queue is cleared
6. **Unload**: Plugin is removed from the system (hot-reload)

## Plugin Queue Types

Each plugin has its own `asyncio.Queue`. Processing mode varies by type:

| Mode | Behavior | Examples |
|---|---|---|
| **Streaming** | Process events one-by-one as they arrive, immediately | TTS, Audio Processors |
| **Batch** | Accumulate events in queue, process all together when a specific trigger event arrives | Voice Agents (trigger: `generate`) |

The trigger for batch processing is defined by the plugin or its config.

## Plugin Base Class

```python
class Plugin:
    name: str
    manager: PluginManager
    config: dict
    queue: asyncio.Queue
    capabilities: list[str] = []
    receive_self_events: bool = False

    async def initialize(self): ...
    async def enable(self): ...
    async def disable(self): ...
    async def process_event(self, event): ...  # Internal queue loop
```

## Singleton

The PluginManager is created once at program start and injected into every plugin during initialization. There is exactly one instance.

## Dependencies Between Plugins

Each plugin is completely independent. If a plugin doesn't receive input (because its source is disabled), it simply stays idle. There is no cascading disable.
