# Voice Evolution — SOUL, JOURNAL, MEMORIES

Agents **read** their SOUL, MEMORIES, and JOURNAL as part of their context, and can **modify their own SOUL** at the end of a session.

## SOUL.md

The system prompt — defines personality, role, behavior rules.

| Property | Value |
|---|---|
| **Max size** | 500 words |
| **When rewritten** | After 5 minutes of system idle |
| **How** | Agent reads current SOUL + JOURNAL + MEMORIES, rewrites it preserving core identity while incorporating new experiences |

## JOURNAL.md

Stream of consciousness — thoughts, decisions, observations.

| Property | Value |
|---|---|
| **Strategy** | Append-only |
| **Max size** | Sliding window: 50 entries or 3000 tokens (whichever hits first) |
| **When written** | During or after tasks |
| **Pruning** | Oldest entries dropped when window fills |

## MEMORIES.md

Long-term recall — what the agent should remember.

| Property | Value |
|---|---|
| **Max size** | 1000 words |
| **Management** | Agent decides what to add and what to prune when limit is reached |

## When SOUL Updates

At the end of a session (system stops or agent idle for a period), the LLM modifies its own SOUL via MCP — the agent calls an MCP tool to read/write the files.
