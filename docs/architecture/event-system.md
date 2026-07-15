# Event System

## Registration

When a plugin is **enabled**, the PluginManager scans all its methods that start with `on_*` and registers them in an internal subscriber dictionary.

Plugins that **emit** events must register them beforehand with name and contract (Pydantic model or dataclass).

```python
# Receiving an event
async def on_transcription(self, data: TranscriptionData):
    ...

# Registering and emitting an event
await self.manager.register_event("transcription", TranscriptionData)
await self.manager.emit("transcription", TranscriptionData(text="..."))
```

## Typed Contracts

Every event has a **contract** defined as a dataclass (by convention, not forcibly frozen). Data travels under that contract for type safety.

## Event Envelope

```python
@dataclass
class EventEnvelope:
    name: str
    data: Any
    source: str               # Plugin name, optionally "plugin/subsource"
    timestamp: datetime       # Set by PluginManager at emit time (non-optional)
    target: str | None = None
    capabilities: list[str] | None = None
    only_once: bool = False
```

### SOURCE

Each event has a `source` field that defaults to the emitting plugin's name. A **subsource** can be added with format `"plugin/subsource"`:

```
"audio_input_mic/stream_1"
"voice_agent/jane"
```

### Timestamps

Every event gets a `datetime.utcnow()` timestamp assigned automatically by the PluginManager at emit time. Not optional. Used for:
- **Debug**: event tracing in TUI, bottleneck detection
- **Agent context**: voices can reason about timing ("this request is 5 minutes old, should have a response by now")
- **Logs**: all events stored with timestamp in bus history

## Self-Delivery OFF by Default

An event does **not** reach the plugin that emitted it (prevents infinite loops). Each plugin can opt in to receive its own events if necessary.

## Capabilities

Each plugin exposes a list of **capabilities** (strings):

```python
class TranscriptionPlugin(AudioProcessor):
    capabilities = ["transcribe", "whisper"]
```

Dispatch can filter to send events only to plugins with certain capabilities.

## Dispatch Filters

Events can use one of the following routing modes (mutually exclusive):

| Mode | Behavior |
|---|---|
| **Broadcast** | No filters — event reaches every subscriber with a matching `on_*` handler |
| **Target** | `target="voice_jane"` — event goes only to that specific plugin by name |
| **Capabilities (AND)** | `capabilities=["voice", "agent"]` — event reaches plugins with ALL listed capabilities. Missing any one → excluded |
| **Only Once** | `only_once=True` — first available subscriber with matching capabilities handles it; no broadcast |

### Targeted Prompting to Voices

A voice can be "interrupted" or "forced to generate" by sending a direct event to its queue with a specific prompt. The target is the voice by name and the event includes the text to process.

## Event Lifecycle

1. Plugin emits event via `emit(event_name, data, ...)`
2. PluginManager determines subscribers (all, filtered by capability, or target)
3. `emit()` is **fire-and-forget**: spawns concurrent tasks for each subscriber and returns immediately
4. **No guaranteed delivery order**. Each subscriber receives the event in its own queue
5. If a subscriber crashes processing the event, the **error is logged** and an **error event** is emitted with the failure context (so TUI, MCP, or other plugins can react)

## Dynamic Pipeline

There is no fixed pipeline. The flow is determined by which plugins are active and how they're configured:

```
Option A: Audio Input → Audio Processor:transcribe
Option B: Audio Input → Audio Processor:diarize → Audio Processor:transcribe
```

Each plugin emits an event and the next in the chain receives it if it has the appropriate capabilities. This allows flexible chaining at the cost of some latency, compensated by:
- Everything is local and async (minimum cost per hop)
- Multiple inputs can coexist
- Performance is sacrificed for modularity, but optimized to keep latency low
