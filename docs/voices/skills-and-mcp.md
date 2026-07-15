# Skills & MCP Per Voice

Each voice can have **MCP servers** and **skills** enabled specifically for it. This allows a voice to have access to tools that others don't, based on its role.

## Voice Configuration (`voice.yaml`)

```yaml
# Voices/Doktor/voice.yaml
mcp_servers:
  - name: "filesystem"
    enabled: true
  - name: "github"
    enabled: true
  - name: "calendar"
    enabled: false

skills:
  - "backlog"
  - "planning-poker"
  - "risk-analysis"
```

```yaml
# Voices/Jane/voice.yaml
mcp_servers:
  - name: "filesystem"
    enabled: true
  - name: "meet"
    enabled: true
  - name: "discord"
    enabled: true

skills:
  - "orchestrator"
  - "interrupt-handler"
```

## Global MCP Plugin

The system has a **global MCP Plugin** that:
1. Scans all available MCP servers (defined in `config.toml`)
2. Exposes them as MCP tools
3. Each voice can enable/disable specific servers in its `voice.yaml`
4. If an MCP server is active in the system, it's added to the available list — the voice decides whether to enable it

```toml
# config.toml
[mcp_servers]
[mcp_servers.filesystem]
command = "uvx"
args = ["mcp-server-filesystem", "/home/chaos/proyectos"]

[mcp_servers.github]
command = "uvx"
args = ["mcp-server-github"]

[mcp_servers.calendar]
command = "python"
args = ["-m", "mcp_server_calendar"]
```

```toml
# Voice config in config.toml
[voice.doktor]
enabled = true
soul = "Voices/Doktor/SOUL.md"
mcp_servers = ["filesystem", "github"]
skills = ["backlog", "planning-poker"]
```

## Skills

**Skills** are reusable abilities that voices can invoke — they are recipes, not code. A skill lives in a directory with markdown instructions that the voice reads and follows, optionally with templates and scripts.

```
config/kateto/skills/{skill_name}/
├── SKILL.md              # What this skill does and how to use it
├── templates/            # Output templates
└── scripts/              # Optional deterministic scripts
```

Unlike MCP servers (external processes) or plugins (event bus participants), skills are **knowledge** — markdown that the LLM ingests as context. A voice uses a skill when a task requires it: "use the backlog skill to create a new task" means the voice reads `skills/backlog/SKILL.md` and follows its instructions.

Each skill:
- Is defined by a `SKILL.md` file with structured instructions
- Can include templates for output formatting
- Can include deterministic scripts for precise operations
- Is enabled/disabled per voice via `config.toml`

When a voice has skills enabled, the contents of each enabled skill's `SKILL.md` are injected into the system prompt at session start.

## Auto-Discovery

If an MCP server is installed and running on the system, the MCP Plugin detects it automatically and adds it to the list of available servers. Each voice then chooses which to enable in its config. If a voice has no `mcp_servers` configured, it inherits all available ones.
