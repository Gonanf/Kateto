---
slug: kateto-mvp
status: plan-written
intent: clear
pending-action: none; plan written at .omo/plans/kateto-mvp.md
approach: Build the complete SPEC.md MVP from the empty skeleton in dependency-ordered waves: packaging/config and Pydantic event contracts first; PluginManager and persistence safety next; the streaming audio/classifier/voice/TTS/interruption loop next; then connectors, workflows, TUI, MCP, hot-reload, demo assets, documentation, and full real-surface verification. Treat SPEC.md as authoritative wherever secondary docs conflict, and make every runtime boundary injectable for deterministic tests.
---

# Draft: kateto-mvp

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
core | Importable uv package with typed event bus, plugin lifecycle, config and safe persistence | active | .omo/evidence/ulw/kateto-mvp/core
audio-loop | Mic/Meet PCM to Whisper to classifier to voice generation to streamed Zonos/player output | active | .omo/evidence/ulw/kateto-mvp/audio-loop
voices-workflows | Jane, Doktor, Conquest, memory files, skills, workflows, TODO/backlog behavior | active | .omo/evidence/ulw/kateto-mvp/voices
integrations-ui | Calendar, Meet/CLI connectors, MCP façade, Textual TUI and hot reload | active | .omo/evidence/ulw/kateto-mvp/integrations
delivery | CLI/package/docs/default config/demo readiness and acceptance evidence | active | .omo/evidence/ulw/kateto-mvp/delivery

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
Python runtime | `requires-python >=3.12`, `.python-version=3.12` | Explicit user choice; aligns SPEC.md/tooling docs | yes
Event contracts | Every event payload and envelope is a Pydantic `BaseModel` | SPEC.md Codex directive is stricter than dataclass examples | yes
Backlog ownership | `product_backlog.json` is owned by a dedicated backlog plugin; MCP tools are a façade over its events | Gives one source of truth while satisfying MCP tool scope | yes
MCP authorization | Only servers declared in config.toml are discoverable; voice access is deny-by-default and explicit | SPEC.md requires config-driven discovery; avoids accidental tool exposure | yes
Request/response | `send_event(wait=True)` carries `correlation_id`, matches `reply_to`, and fails with a bounded timeout/cancellation | Makes wait semantics testable over fire-and-forget dispatch | yes
only_once | Select the first enabled matching subscriber in deterministic registration order; dispatch only to it | Resolves unordered-concurrency ambiguity without adding a mediator | yes
External inference tests | Use injectable HTTP contract fixtures when local servers are absent; live-server tests are an opt-in smoke lane | Keeps TDD deterministic without violating external-inference architecture | yes
Meet capture | Use a configured OS loopback/virtual audio device through the same 16 kHz PCM pipeline; fail startup with an actionable device error if unavailable | `sounddevice` does not provide browser capture itself | yes
Reference clips | Store per-voice WAV clips under the resolved config voice directory; validate format at startup and fail the TTS voice only, not the bus | Clips are required by SPEC.md and are user data | yes

## Findings (cited - path:lines)

- `SPEC.md:1-384` is authoritative and represents the complete MVP; no P1/P2/P3 reduction is permitted.
- `main.py:1-6`, `pyproject.toml:1-7`, and the explorer result show an empty implementation skeleton: no package, tests, scripts, dependencies, or console entrypoint.
- `SPEC.md:29-92`, `docs/architecture/event-system.md:3-103`, and `docs/architecture/plugin-manager.md:5-60` define the broker, typed events, dispatch filters, lifecycle, and config contract.
- `SPEC.md:98-116` defines the required P0 plugins and complete conversation loop; `SPEC.md:118-259` defines voices, memory, skills, and declarative workflows.
- `SPEC.md:260-275` defines CLI allow-list, atomic backlog writes, and voice isolation; `SPEC.md:276-384` defines the target tree, tooling, and exclusions.
- `docs/development/tdd.md:1-109` requires pytest/pytest-asyncio and RED→GREEN→REFACTOR; `docs/development/tooling.md:1-36` requires uv.
- `config/defaults/config.toml:1-33` is the existing default seed but has section/skill gaps identified by Metis.
- Metis review identified 17 plan gaps: Python mismatch, Pydantic-vs-dataclass ambiguity, P0/P1 label conflict, config-only MCP authorization, backlog ownership, wait/only_once semantics, classifier fixture contract, voice self-filter acceptance, Meet capture boundary, exact dependencies, canonical config schema, missing skills, reference clips, workflow ownership, mutable-file locking, executable QA, and dependency order. Each is resolved in the decisions and todos below.

## Decisions (with rationale)

- Follow the user's clarification: `SPEC.md` is the entire MVP. Secondary documents are implementation guidance only; conflicting priority labels do not remove TODO, CLI, Meet, or any other SPEC.md component from scope.
- Build from the empty skeleton in waves, with each implementation todo containing its tests and a real-surface QA command.
- Use Pydantic BaseModel for all event contracts and envelopes; use asyncio queues/tasks for all plugin work; no central mediator beyond PluginManager.
- Keep canonical state stores distinct: backlog JSON is authoritative for work items; per-voice TODO.md is a generated/voice-owned tracking artifact; workflow state is a separate lifecycle record. Cross-store updates flow through typed events.
- Use one long-lived async HTTP client per plugin/provider and adapters for OpenAI-compatible local endpoints. Cloud OpenAI Responses streaming and local llama.cpp Chat Completions are separate adapters.
- Resolve config sections to `[kateto]`, `[plugin.<name>]`, `[voice.<name>]`, `[mcp_servers.<name>]`, and `[cli]`; validate unknown/missing values at startup with actionable errors while preserving existing default seed values after normalization.
- Workflow lifecycle/state belongs to `kateto/core/workflow.py`; all MVP phases are declarative and checkpointed, with hot-reload reloading definitions only after active tasks are cancelled.
- No external credentials, model weights, audio clips, or running model servers are committed. The plan includes fixture servers and preflight checks for live integrations.

## Scope IN

- Complete P0 vertical slice and every component explicitly listed in `SPEC.md:98-116`.
- Three manual voices plus declarative voice discovery, SOUL/JOURNAL/MEMORIES limits, skills, workflows, backlog/TODO, calendar, Meet audio, restricted CLI, TUI, MCP, hot-reload, packaging, README and demo/runbook.
- Deterministic unit/integration tests, fixture HTTP servers, optional live local-server smoke tests, TUI visual terminal evidence, and interruption/resume evidence.

## Scope OUT (Must NOT have)

- No additional voices, VoiceClassifier, avatars, workspaces, VideoRAG, Remotion, Discord/OpenProject connectors, imperative/hybrid workflow scripts, random talk, podcast, or other post-MVP features named in `SPEC.md:375-384`.
- No central mediator, synchronous blocking path, model loading inside Python, arbitrary CLI execution, implicit discovery of installed MCP processes, or secrets/model weights/audio reference clips committed to git.
- No weakening/deleting/skipping tests to obtain green status and no human-only acceptance steps.

## Open questions

- None blocking plan generation. Runtime providers require user-supplied endpoints/credentials/assets; the plan defines validation, fixture substitutes, and explicit failure messages rather than inventing those external resources.

## Approval gate
status: plan-written
approval-recorded: user explicitly approved writing the plan in the latest request
plan-path: .omo/plans/kateto-mvp.md
metis: completed; 17 gaps integrated into decisions and todos
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
