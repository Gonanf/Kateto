# Backlog & Sprint Management

The **Product Owner (Doktor)** manages a **Product Backlog** from which tasks are extracted to start sprints. The backlog is not a fixed singleton — it's an **MCP resource** accessible by all agents via the event system.

## Architecture

The backlog can be implemented as:
- A **dedicated plugin** (`plugin.backlog`) that maintains state and exposes CRUD events
- Or an **MCP resource** with tools to query, add, modify, and delete items

In both cases, the backlog is accessible via MCP for agents and external tools (Codex).

## File Structure

```
Voices/Doktor/backlog/
├── product_backlog.json     # Backlog items (structured format)
├── sprint_board.json        # Active sprint with tasks
├── todo_items.json          # General work items
└── templates/               # Backlog item templates
    ├── user-story.md
    ├── bug-report.md
    └── task-card.md
```

## Backlog Item Schema

| Field | Description |
|---|---|
| `id` | Unique identifier |
| `title` | Short title |
| `description` | Description / story |
| `priority` | Must / Should / Could / Won't (MoSCoW) |
| `status` | Backlog / Ready / In Sprint / Done |
| `estimate` | Story points or estimated time |
| `dependencies` | IDs of items it depends on |
| `created_by` | Who created it (agent or human) |
| `tags` | Labels for filtering |

## PO → Sprint Flow

1. **Doktor** (PO) maintains the prioritized backlog
2. On sprint start, Doktor moves items from backlog to `sprint_board.json`
3. **Conquest** (SM) monitors the sprint and facilitates ceremonies
4. Items are updated via MCP events
5. On sprint completion, Doktor reviews and reprioritizes

## MCP Tools

| Tool | Description |
|---|---|
| `backlog_list` | List items with filters (status, priority) |
| `backlog_add` | Add item to backlog |
| `backlog_update` | Modify item (status, priority, etc.) |
| `backlog_sprint_start` | Move selected items to active sprint |
| `backlog_sprint_status` | View current sprint status |
| `sprint_complete` | Close sprint and archive items |

This allows both agents and humans (via Codex or other tools) to manage the backlog without intermediaries.
