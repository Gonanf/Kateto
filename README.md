# Kateto

![Jane](public/jane1.svg) ![Doktor](public/doktor1.svg) ![Conquest](public/conquest1.svg)

## 1. What is Kateto, why was it built, and which category does it target?

Kateto is an event-driven voice team for project work. Instead of putting the
application logic in a fixed conversation pipeline, every component publishes
and receives typed events through the `PluginManager`:

- **Jane** coordinates the project and delegates work.
- **Doktor** turns intent into plans, risks, backlog items, and deliverables.
- **Conquest** facilitates agile execution and keeps progress visible.

![The Kateto team](public/the_lovers1.svg)

Kateto was built to make project coordination observable and actionable. A
spoken request can become a classification, a workflow, a plan, checkpoints,
files, backlog updates, and a spoken response. The TUI exposes the same runtime
state: events, agents, workflows, plugins, MCP servers, errors, and audio
status.

This is a solo OpenAI Build Week project for the **Work and Productivity**
category. The MVP prioritizes a reliable, inspectable event runtime over a
large collection of integrations.

## 2. How to run it

### Dependencies

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Optional for live mode: configured model endpoints, Whisper/classifier
  services, an approved voice reference WAV, a microphone, and an audio output
  device

The fixture runtime needs no API key, model weights, microphone, or external
service. Install the locked dependencies with:

```bash
uv sync --locked
```

Kateto bootstraps user configuration into `$XDG_CONFIG_HOME/kateto`, or
`~/.config/kateto` when `XDG_CONFIG_HOME` is not set. Check it with:

```bash
uv run kateto config check
```

To use an isolated configuration while developing:

```bash
XDG_CONFIG_HOME="$(mktemp -d)" uv run kateto config check
```

### Fixture demo

The deterministic path is the recommended first run:

```bash
uv run kateto tui --fixture
```

It shows the event stream, voice status, workflow state, plugin controls,
notifications, and generated work-shaped output without contacting external
providers.

Other useful commands:

```bash
uv run kateto --help
uv run kateto run
uv run pytest kateto/tests/test_event_routing.py -q
uv run pytest kateto/tests/test_workflow.py -q
```

### Live mode

Live mode reads the resolved user configuration and connects to the configured
providers. Keep credentials in ignored environment/secrets files, never in
`config.toml` or source control. Reference audio must be a local `.wav` inside
the owning voice directory.

The live graph can use HTTP model services for transcription, classification,
and voice generation, plus the configured audio input/output plugins. If those
services or devices are unavailable, use `--fixture` for a reproducible run.

## 3. How I used Codex

All implementation work was done with Codex during Build Week. I used Codex to:

- turn the MVP specification into an execution plan;
- implement the event bus, plugin lifecycle, voice agents, workflows, tools,
  MCP integration, audio plugins, and Textual TUI;
- debug asynchronous failures such as interrupted TTS, stalled tool-call
  responses, and dynamically enabled voices;
- add focused async tests and document each discovered bug;
- prepare the ZeroGPU/Hugging Face publication plan and the judge-facing demo.

The Git history records the incremental implementation and bug-fix work. The
project keeps the fixture path explicit so a reviewer can inspect the core
orchestration without needing private infrastructure.

## 4. Current state

The MVP currently includes:

- a typed, asynchronous event system with broadcast, target, capability, and
  one-time delivery;
- automatic plugin discovery, lifecycle management, hot reload, error
  isolation, and bounded event history;
- Jane, Doktor, and Conquest voice agents with bounded event-based memory,
  project-language instructions, tools, MCP access, and workflow context;
- declarative per-voice workflows with phases, deliverables, checkpoints,
  automatic advancement, and voice delegation;
- dynamic workflow routing through the classifier plugin;
- microphone/VAD, transcription, TTS, PCM playback, interruption handling,
  and audio status events;
- a live Textual TUI with event notifications, plugin switches and history,
  voice/workflow trees, MCP state, JSON event composition, and runtime status;
- fixture implementations and focused async tests for deterministic review.

The project is an MVP, not yet a hosted, unlimited voice service. The complete
test suite still contains repository-drift failures from removed legacy QA
modules, and the old smoke command needs its deleted QA path repaired. These
are tracked in [known issues](docs/known-issues.md). The safe public deployment
strategy is fixture-first Hugging Face ZeroGPU with optional, explicitly
configured live providers; it must not ship a maintainer API key.

## 5. Planned features

- Repair the remaining release validation paths and provide one clean,
  judge-facing smoke command.
- Publish the browser demo on Hugging Face Spaces using the available
  ZeroGPU entitlement, with a clear choice between BYOK and Bonsai at startup.
- Make the live provider adapters more resilient with bounded retries,
  timeouts, quotas, and clearer degraded-runtime diagnostics.
- Expand project artifacts and workflow evolution so agents can safely update
  plans, TODOs, backlog, skills, and voice SOUL/JOURNAL files over time.
- Add more production connectors, including calendar/meeting integrations and
  richer MCP permissions.
- Improve audio device selection, streaming quality, multilingual support, and
  accessibility of the TUI and hosted presentation.
- Increase end-to-end coverage across microphone input, classifier routing,
  workflow delegation, tool calls, TTS interruption, and artifact generation.

For architecture and deployment details, see the [architecture docs](docs/architecture/overview.md),
the [free publishing plan](docs/development/free-publishing-plan.md), and the
[final MVP assessment](docs/development/final-assessment.md).
