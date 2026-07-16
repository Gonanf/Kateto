# Workflows

Workflows are **instructions given to a voice** to execute a process step by step. They are not autonomous code — they are directives the voice receives as prompts and must fulfill, phase by phase.

## Workflow Locations

| Location | Purpose |
|---|---|
| `config/kateto/workflows/{name}/` | **Global workflows** shared across voices (daily standup, sprint review) |
| `config/kateto/voices/{voice}/workflows/{name}/` | **Per-voice workflows** specific to an agent's role |

Global workflows can be assigned to any voice at runtime. Per-voice workflows are available only to that agent.

## Structure

```
config/kateto/voices/{voice}/workflows/{workflow_name}/
└── workflow.py       # Literal phases, instructions, deliverables, checkpoints
```

## Format

```python
name = "sprint-planning"
description = "Plan and organize a sprint from the backlog"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "review-backlog",
        "name": "Review and prioritize backlog",
        "instructions": [
            "Review all items in the product backlog",
            "Prioritize using MoSCoW (Must/Should/Could/Won't)",
            "Identify items ready for the sprint"
        ],
        "deliverables": ["prioritized-backlog.md"],
        "calls_skills": ["backlog"],
        "calls_voices": [],
        "checkpoints": [
            "All items have a priority assigned",
            "Ready items are clearly identified"
        ]
    }
]
```

## Lifecycle

```
INACTIVE → RUNNING (phase 1) → RUNNING (phase 2) → ... → COMPLETED
                │                    │
                │                    └── (if voice aborts) → STOPPED
                └── (if system aborts) → STOPPED
```

1. **Start**: `workflow_run` event sent to target voice
2. **Active phase**: Voice receives instructions + deliverables for current phase as prompt
3. **Auto-advance**: On idle (no new events after completing phase), system advances to next phase
4. **Checkpoints**: Verified before advancing. If any fails, workflow pauses
5. **Completed**: Last phase passes checkpoints → workflow marked COMPLETED
6. **Stopped**: Voice can stop via `workflow_stop` → marked STOPPED

## Lifecycle Events

| Event | When | Payload |
|---|---|---|
| `workflow_started` | Workflow begins | workflow, voice, context, timestamp |
| `workflow_phase_start` | Phase begins | workflow, phase_id, voice, timestamp |
| `workflow_phase_complete` | Phase finishes | workflow, phase_id, voice, deliverables, timestamp |
| `workflow_checkpoint_fail` | Checkpoint fails | workflow, phase_id, checkpoint, voice, timestamp |
| `workflow_completed` | Completed successfully | workflow, voice, timestamp |
| `workflow_stopped` | Stopped | workflow, voice, reason, timestamp |

All voices listen to these events, keeping the system informed of what each agent is doing.

## Declarative phases only

Every phase is declarative: the voice receives literal natural-language instructions and produces the listed deliverables. Workflow definitions are parsed as data and never imported or executed. A phase containing a `run` command, imports, calls, or other executable content is rejected at the definition boundary.

## Workflow Evolution

Workflows are Python files. Both agents and humans can **create, modify, and improve** workflows via hot-reload. A voice can:
- Create a new workflow for a repeated process
- Add phases to an existing workflow
- Adjust instructions based on learning
- Stop a failing workflow and redesign it

Agents evolve their own work processes — not tied to a fixed pipeline.
