# Workspaces (P3 — Future)

Each **person** and each **project** needs its own isolated context. Instead of mixing SOUL, MEMORIES, JOURNAL, TODO, and Workflows from different contexts in the same directory, the system introduces **workspaces**.

## Structure

```
workspaces/
├── soloto/                       # A person's workspace
│   ├── soul/                     # Voice personality overrides for this context
│   ├── journal/                  # Personal log
│   ├── memories/                 # Long-term memory
│   ├── todo/                     # This person's TODOs
│   └── workflows/                # Workflows created/modified in this context
├── kateto/                       # A project workspace
│   ├── soul/
│   ├── journal/
│   ├── memories/
│   ├── todo/
│   └── workflows/
└── clientes/
    ├── cliente-a/
    └── cliente-b/
```

## Relationship With Voices

**Voices** (roles) are global — `Voices/ProductOwner/`, `Voices/ScrumMaster/` — but at runtime they load their context from the active workspace:

| Component | In Workspace? | Notes |
|---|---|---|
| **SOUL** | Yes | Personality and tone, with per-workspace override |
| **JOURNAL** | Yes | Decision log and events for this workspace |
| **MEMORIES** | Yes | Persistent agent memory for this context |
| **TODO** | Yes | Task lists and objectives for this workspace |
| **Workflows** | Yes | Evolutionary processes agents improve over time |
| **Voices** | Global | Base roles are shared, but can have per-workspace overrides in `soul/` |

## Why Workspaces?

- **Isolation**: workflows and memories of one project don't contaminate another
- **Portability**: a workspace can be shared, cloned, or archived entirely
- **Evolution**: each workspace evolves its own version of workflows, memories, and SOUL without affecting others
- **Multi-client**: the same agent can work for different clients without mixing contexts
