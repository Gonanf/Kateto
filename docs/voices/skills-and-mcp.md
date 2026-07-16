# Skills & MCP Per Voice

Skills are enabled per voice. MCP access is also per voice, but only through explicit configuration: declared servers are not implicitly available, and an absent voice grant denies access.

## MCP Configuration

Servers are declared globally in `config.toml`:

```toml
[mcp_servers.fixture]
command = "python"
args = ["-m", "example_mcp_server"]

[voice.doktor]
enabled = true
mcp_servers = ["fixture"]
skills = ["backlog", "planning-poker"]
```

The authorization boundary is deny-by-default:

1. The server name must exist under `[mcp_servers.<name>]`.
2. The requesting voice must list that exact name in `voice.<name>.mcp_servers`.
3. Event tools are generated only from currently registered live event receivers.

An undeclared server, an ungranted voice, or a voice with no `mcp_servers` entry is denied. Kateto does not scan installed or running MCP processes, and a voice does not inherit every declared server.

## Skills

**Skills** are reusable knowledge, not executable MCP processes. A skill lives in a directory with markdown instructions that the voice reads and follows.

```text
config/kateto/skills/{skill_name}/
└── SKILL.md
```

Each skill is enabled per voice via `config.toml`; its `SKILL.md` contents are injected into that voice's system prompt at session start. Skills do not grant MCP access.
