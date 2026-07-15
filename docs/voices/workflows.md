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
├── workflow.py       # Phases, instructions, deliverables, checkpoints
├── scripts/          # Executable scripts for imperative phases (P1+)
│   ├── generar_reporte.py
│   ├── procesar_csv.sh
│   └── notify_slack.py
└── templates/        # Reference files, prompts, assets
    ├── informe-semanal.md
    └── checklist.csv
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

## Declarative vs Imperative Phases

### Declarative (instructions) — default
Voice receives instructions as natural language and uses its LLM to interpret and execute. Ideal for tasks requiring reasoning, negotiation, adaptation. This is the MVP mode — all phases are declarative.

### Imperative (scripts) — P1+
Phase executes a shell script from `scripts/`. System runs the command, captures stdout/stderr, result is available for subsequent phases.

```python
{
    "id": "generar-reporte",
    "name": "Generate structured weekly report",
    "run": "python scripts/generar_reporte.py --semana {{context.semana}}"
}
```

**Context available to scripts:**

| Variable | Content |
|---|---|
| `KATETO_WORKFLOW` | Workflow name |
| `KATETO_PHASE_ID` | Current phase ID |
| `KATETO_VOICE` | Voice executing the workflow |
| `KATETO_WORKSPACE` | Active workspace |
| `KATETO_CONTEXT_JSON` | Full context as JSON |
| `KATETO_OUTPUT_DIR` | Directory for outputs |

### Hybrid — P1+
A phase can have **instructions** for the voice to generate content AND a **script** to process it:

```python
{
    "id": "redactar-y-publicar",
    "name": "Write and publish report",
    "instructions": [
        "Analyze sprint progress",
        "Write executive summary",
        "Identify risks and recommendations"
    ],
    "run": "python scripts/estructurar_reporte.py",
    "deliverables": ["reporte-publicado.md"]
}
```

Voice generates analysis → script structures and writes with exact format.

## Workflow Evolution

Workflows are Python files. Both agents and humans can **create, modify, and improve** workflows via hot-reload. A voice can:
- Create a new workflow for a repeated process
- Add phases to an existing workflow
- Adjust instructions based on learning
- Stop a failing workflow and redesign it

Agents evolve their own work processes — not tied to a fixed pipeline.
