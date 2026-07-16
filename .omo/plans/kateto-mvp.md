# kateto-mvp - Work Plan

## TL;DR (For humans)
<!-- Filled last after the detailed plan and review findings. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** A complete Kateto MVP: a working voice conversation loop with three collaborating agents, live terminal visualization, interruption/resume, real backlog/calendar/CLI work capabilities, MCP access, declarative workflows, and setup/demo documentation.

**Why this approach:** Build the event bus, typed contracts, configuration, and safe persistence first, then connect streaming providers and product surfaces around those stable boundaries. External models remain replaceable HTTP services, while fixture services make the full behavior testable without requiring private infrastructure.

**What it will NOT do:** It will not add post-MVP voices or features such as avatars, workspaces, per-voice classification, video/RAG, extra connectors, or imperative workflows. It will not commit secrets, model weights, or reference audio, and it will not permit arbitrary shell execution.

**Effort:** XL
**Risk:** High - the repository is an empty skeleton and the MVP spans audio hardware, external inference services, async cancellation, persistence, TUI, and MCP.
**Decisions to sanity-check:** Python 3.12 target, Pydantic-only event contracts, config-only deny-by-default MCP access, backlog as the single canonical work-item store, and fixture-provider acceptance when external servers are unavailable.

Your next move: run `$start-work` to execute this plan, or request a high-accuracy plan review first. Full execution detail follows below.

---

> TL;DR (machine): XL/high-risk architecture build delivering the complete SPEC.md MVP through dependency-ordered implementation, deterministic fixture tests, live-surface QA, and explicit P1/P2/P3 exclusions.

## Scope
### Must have

- Implement the complete MVP in `SPEC.md:1-384`, starting from the current empty skeleton: uv package, Python 3.12, Pydantic event contracts, singleton PluginManager, plugin lifecycle/queues/filters/error events, config bootstrap, hot-reload, all P0 audio/classifier/interrupt/TTS/player plugins, Jane/Doktor/Conquest, declarative workflows, skills, TODO/backlog, Calendar/Meet/CLI connectors, Textual TUI, MCP server, packaging, README, defaults, tests, demo assets/runbook, and real-surface evidence.
- Preserve async streaming and external-inference boundaries: Python must not load ML models; local/cloud providers are configured HTTP services; audio callbacks never block or dispatch directly.
- Use exact runtime pins from the validated research: `openai==2.45.0`, `mcp==1.28.1`, `textual==8.2.8`, `watchdog==6.0.0`, `httpx==0.28.1`, `sounddevice==0.5.5`; add Pydantic, pytest, pytest-asyncio, and python-dotenv with exact resolved versions in `uv.lock`.
### Must NOT have (guardrails, anti-slop, scope boundaries)

- Do not reduce the MVP to a mock-only demo or omit `audio_input_meet`, TODO executor, CLI connector, workflows, MCP, or any other item explicitly listed in `SPEC.md:98-116` because secondary docs label it differently.
- Do not implement P1/P2/P3 additions: extra voices, VoiceClassifier, avatars, workspaces, VideoRAG, Remotion, Discord/OpenProject, imperative/hybrid workflow scripts, random talk, podcast, or other excluded features in `SPEC.md:375-384`.
- Do not add a central mediator, synchronous blocking path, arbitrary shell execution, implicit MCP process discovery, committed secrets/model weights/reference clips, or compatibility shims for unshipped APIs.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD RED → GREEN → REFACTOR with `uv run pytest`, `pytest-asyncio`, Textual `run_test()`, and fixture HTTP services; live local model servers are an opt-in smoke lane, never the only proof.
- Evidence: `.omo/evidence/kateto-mvp/task-<N>/` with captured command output, JSON event traces, fixture-server logs, TUI screenshots/transcripts, and cleanup receipts. Every todo records one happy and one failure scenario with exact invocation and binary observable.
- Final commands: `uv run pytest`, `uv build`, `uv run kateto --help`, `uv run kateto smoke --fixture`, and `node script/qa/web-terminal-visual-qa.mjs --title "Kateto TUI" --command "uv run kateto tui --fixture" --input "{Enter}" --evidence-dir .omo/evidence/kateto-mvp/final-tui`.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- Wave 1, bootstrap/contracts: 1-4. Sequential dependency gates for Python/dependencies, package layout, event models/dispatch, and config/persistence primitives.
- Wave 2, core runtime and loop: 5-8. Plugin lifecycle/hot reload can proceed beside provider adapters after contracts; voices and audio loop depend on both.
- Wave 3, product capabilities and surfaces: 9-13. Connectors/backlog/workflows/MCP/TUI are parallel after core runtime, with integration wiring after each contract exists.
- Wave 4, delivery and proof: 14-16. Packaging/docs/demo, full end-to-end harness, and final cleanup/verification.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |

| 1 | none | 2-4 | none |
| 2 | 1 | 3-8 | 3,4 |
| 3 | 1-2 | 5-8 | 4 |
| 4 | 1-2 | 5,9-13 | 3 |
| 5 | 3-4 | 6,8,13 | 6,7 |
| 6 | 3-4 | 7,8,13 | 5,7 |
| 7 | 3-4 | 8,13 | 5,6 |
| 8 | 3-6 | 9-13 | 7 |
| 9 | 4-8 | 10,13 | 10,11,12 |
| 10 | 4-8 | 13 | 9,11,12 |
| 11 | 4-8 | 13 | 9,10,12 |
| 12 | 3-8 | 13 | 9,10,11 |
| 13 | 5-12 | 14-16 | none |
| 14 | 1-13 | 15-16 | 15 |
| 15 | 1-13 | 16 | 14 |
| 16 | 14-15 | none | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Bootstrap the uv project and locked runtime
  What to do / Must NOT do: Change `pyproject.toml` to Python >=3.12 with `.python-version` 3.12, add the exact runtime/test dependencies and `kateto` console script, generate `uv.lock`, and create the target package/test directories. Do not add unrequested providers or leave version resolution floating.
  Parallelization: Wave 1 | Blocked by: none | Blocks: 2-4
  References (executor has NO interview context - be exhaustive): `SPEC.md:1-5,276-384`; `pyproject.toml:1-7`; `.python-version:1`; `docs/development/tooling.md:1-36`; `docs/development/tdd.md:1-13`.
  Acceptance criteria (agent-executable): `uv sync --locked` exits 0 on Python 3.12; `uv run python -c 'import kateto'` exits 0; `uv run kateto --help` prints the CLI usage; `uv build` creates a wheel.
  QA scenarios (name the exact tool + invocation): happy `uv run kateto --help` → exit 0 and usage text; failure `uv run python -c 'import sys; assert sys.version_info[:2] == (3, 12)'` → PASS on the pinned interpreter. Evidence `.omo/evidence/kateto-mvp/task-1/`.
  Commit: Y | build(bootstrap): initialize uv package and locked dependencies
- [x] 2. Define Pydantic event contracts and envelope semantics
  What to do / Must NOT do: Implement BaseModel contracts for every MVP event, envelope metadata, timestamps, `source`, `target`, capabilities, `only_once`, `reply_to`, and `correlation_id`; reject malformed payloads. Do not use dataclasses for shipped event payloads.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3-8
  References (executor has NO interview context - be exhaustive): `SPEC.md:35-52,98-116,245-259,375-384`; `docs/architecture/event-system.md:3-103`.
  Acceptance criteria (agent-executable): `uv run pytest kateto/tests/test_event_contracts.py -q` proves valid serialization/deserialization, generated timestamp, and invalid payload rejection; all event models subclass `pydantic.BaseModel`.
  QA scenarios (name the exact tool + invocation): happy `uv run python -m kateto.qa.emit_fixture transcription --text hello` → JSON envelope contains `name`, `source`, `timestamp`; failure same command with missing `text` → nonzero exit and validation error, no event emitted. Evidence `.omo/evidence/kateto-mvp/task-2/`.
  Commit: Y | feat(core): add typed MVP event contracts
- [x] 3. Implement Plugin and PluginManager lifecycle, queues, filters, errors, and singleton access
  What to do / Must NOT do: Implement registration by `on_*`, streaming vs batch queues, enable/disable cleanup, broadcast/target/AND capabilities/deterministic only-once/self-delivery-off, fire-and-forget dispatch, error events, event history, and interrupt routing. Do not create a mediator separate from PluginManager.
  Parallelization: Wave 1 | Blocked by: 1-2 | Blocks: 5-8
  References (executor has NO interview context - be exhaustive): `SPEC.md:29-81`; `docs/architecture/plugin-manager.md:5-60`; `docs/architecture/event-system.md:3-103`.
  Acceptance criteria (agent-executable): `uv run pytest kateto/tests/test_event_bus.py kateto/tests/test_plugin_manager.py -q` covers every dispatch mode, self-delivery, only-once registration order, immediate emit return, plugin crash→error event, lifecycle and queue clearing.
  QA scenarios (name the exact tool + invocation): happy `uv run python -m kateto.qa.bus_fixture --mode broadcast` → two subscribers receive one event; failure `--mode target --target missing` → zero delivery and explicit trace, manager remains running. Evidence `.omo/evidence/kateto-mvp/task-3/`.
  Commit: Y | feat(core): implement plugin manager event bus
- [x] 4. Implement canonical config/bootstrap and safe file primitives
  What to do / Must NOT do: Resolve XDG/APPDATA config paths, copy defaults on first run, normalize `[kateto]`, `[plugin.*]`, `[voice.*]`, `[mcp_servers.*]`, `[cli]`, load `.env`, validate endpoints/assets, and provide per-file asyncio locks plus atomic rename writes. Do not expose secrets in config.toml or permit arbitrary CLI commands.
  Parallelization: Wave 1 | Blocked by: 1-2 | Blocks: 5,9-13
  References (executor has NO interview context - be exhaustive): `SPEC.md:81-97,260-275`; `docs/architecture/config.md:1-81`; `config/defaults/config.toml:1-33`.
  Acceptance criteria (agent-executable): `uv run pytest kateto/tests/test_config.py kateto/tests/test_storage.py -q` proves first-run copy, schema validation, secret exclusion, concurrent atomic writes, and voice path isolation.
  QA scenarios (name the exact tool + invocation): happy `XDG_CONFIG_HOME=$(mktemp -d) uv run kateto config check` → creates config tree and exits 0; failure with `cli.allowlist=['rm']` or malformed TOML → exits nonzero and names the rejected setting. Evidence `.omo/evidence/kateto-mvp/task-4/`.
  Commit: Y | feat(core): add config bootstrap and atomic storage
- [x] 5. Add provider adapters for Whisper, classifier, OpenAI-compatible voice streaming, and Zonos HTTP
  What to do / Must NOT do: Implement lifecycle-managed `httpx.AsyncClient` adapters and streaming parsers for Whisper PCM, mmBERT three-way classification, local llama.cpp Chat Completions/OpenAI Responses, and Zonos sentence PCM; use fixture servers in tests. Do not load models in Python or assume local Responses support.
  Parallelization: Wave 2 | Blocked by: 3-4 | Blocks: 6-8,13 | Can parallelize with: 6,7
  References (executor has NO interview context - be exhaustive): `SPEC.md:98-109,162-188`; `docs/plugins/audio-processor.md:1-26`; `docs/plugins/audio-output.md:1-24`; external API research recorded in draft.
  Acceptance criteria (agent-executable): fixture HTTP tests prove request payloads, streamed chunks, timeout/cancellation, malformed upstream data, and client close; provider endpoints/config are injectable.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/fixture_models.py --scenario stream` → transcription/classification/token/audio chunks logged; failure `--scenario timeout` → bounded timeout event and no leaked client task. Evidence `.omo/evidence/kateto-mvp/task-5/`.
  Commit: Y | feat(inference): add streaming provider adapters
- [x] 6. Implement audio input microphone and Meet capture with VAD/interruption
  What to do / Must NOT do: Implement bounded PortAudio callback queues, 16 kHz mono PCM s16LE, Silero VAD silence segmentation, source tags, configured loopback/Meet device capture, immediate async resume, and `interrupt` on speech during playback. Do not block or perform network/event dispatch in callbacks.
  Parallelization: Wave 2 | Blocked by: 3-5 | Blocks: 7-8,13 | Can parallelize with: 5,7
  References (executor has NO interview context - be exhaustive): `SPEC.md:98-103`; `docs/plugins/audio-input.md:1-66`; `config/defaults/config.toml:8-10`.
  Acceptance criteria (agent-executable): audio fixture tests prove silence boundaries, format, <50ms async resume target, bounded queue behavior, source metadata, and unavailable-device error; real device preflight reports selected mic/loopback.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/audio_fixture.py --source mic --wav fixtures/utterance.wav` → one `audio_chunk` then resumed listener; failure `--source meet --device missing` → actionable startup error and no running capture task. Evidence `.omo/evidence/kateto-mvp/task-6/`.
  Commit: Y | feat(audio): add mic and Meet input plugins
- [x] 7. Implement voices, streaming generation, memory evolution, skills, and relevance self-filtering
  What to do / Must NOT do: Add `VoiceAgent` batch queues, OpenAI-compatible streaming, Jane/Doktor/Conquest behavior, SOUL/JOURNAL/MEMORIES limits and safe writes, declarative skill loading, idle events, reference-clip selection, and defined self-filter outcomes. Do not add extra voices or per-voice classifier.
  Parallelization: Wave 2 | Blocked by: 3-5 | Blocks: 8,9-13 | Can parallelize with: 5,6
  References (executor has NO interview context - be exhaustive): `SPEC.md:118-221`; `docs/voices/overview.md:1-42`; `docs/voices/voice-agent.md:1-67`; `docs/voices/voice-evolution.md:1-40`; `docs/voices/skills-and-mcp.md:1-92`.
  Acceptance criteria (agent-executable): tests prove batch trigger only on `generate`, streamed tokens, `voice_idle`, interrupt cancellation, 500-word SOUL, 50-entry/3000-token JOURNAL, 1000-word MEMORIES, and exactly defined zero/one/multiple response behavior for fixture prompts.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/voice_fixture.py --prompt 'create a backlog task'` → named voice output and `voice_idle`; failure with missing reference WAV → only that voice reports configuration error while bus remains alive. Evidence `.omo/evidence/kateto-mvp/task-7/`.
  Commit: Y | feat(voices): implement MVP voice agents and memory
- [x] 8. Wire classifier, interrupt executor, TODO executor, and complete conversation-loop events
  What to do / Must NOT do: Connect `audio_chunk→transcription→classification`; route EXECUTE to all active P0 voices; implement IGNORE categories, TODO.md creation/update, interrupt cancellation and resume. Do not silently drop errors or route ignored speech to voices.
  Parallelization: Wave 2 | Blocked by: 3-7 | Blocks: 9-13
  References (executor has NO interview context - be exhaustive): `SPEC.md:98-112`; `docs/plugins/executors.md:1-67`.
  Acceptance criteria (agent-executable): integration tests assert exact event sequence and recipients for EXECUTE/IGNORE_SELF_TALK/IGNORE_THIRD_PARTY, TODO detection, interruption during active stream, cancellation of LLM/TTS tasks, and acceptance of the next utterance.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/vertical_slice.py --fixture --prompt 'plan tomorrow standup'` → transcript, EXECUTE, three generate events, streamed response, audio chunks; failure `--prompt 'I am thinking aloud'` → classification ignored and no generate event. Evidence `.omo/evidence/kateto-mvp/task-8/`.
  Commit: Y | feat(pipeline): wire classification, TODOs, and interruption
- [x] 9. Implement canonical backlog plugin, MCP CRUD events, and calendar connector
  What to do / Must NOT do: Make `product_backlog.json` the canonical source, add list/add/update CRUD with filters, lock+atomic writes, MCP-facing events, and Google Calendar OAuth cached-token getter/setter connector with `reply_to`. Do not duplicate backlog storage in MCP or expose tokens.
  Parallelization: Wave 3 | Blocked by: 4-8 | Blocks: 10,13 | Can parallelize with: 10-12
  References (executor has NO interview context - be exhaustive): `SPEC.md:107-112,260-269`; `docs/plugins/connectors.md:1-66`; `docs/voices/backlog.md:1-59`.
  Acceptance criteria (agent-executable): tests prove filters, CRUD validation, concurrent updates without corruption, calendar request/response correlation, token cache path, and connector failure events.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/backlog_fixture.py add --title 'Demo task' --priority Must` → one persisted JSON item; failure two concurrent updates with invalid status → no partial file and error events. Evidence `.omo/evidence/kateto-mvp/task-9/`.
  Commit: Y | feat(work): add backlog and calendar connectors
- [x] 10. Implement restricted CLI connector and TODO/backlog synchronization boundaries
  What to do / Must NOT do: Execute only normalized commands in the config allow-list, capture stdout/stderr as typed reply events, and synchronize completed voice TODO items to the canonical backlog. Do not shell-evaluate strings, expand arbitrary paths, or make TODO.md the canonical backlog.
  Parallelization: Wave 3 | Blocked by: 4-8 | Blocks: 13 | Can parallelize with: 9,11,12
  References (executor has NO interview context - be exhaustive): `SPEC.md:107,260-269`; `config/defaults/config.toml:31-33`; `docs/plugins/connectors.md:1-66`.
  Acceptance criteria (agent-executable): tests prove allow-listed command success, rejected command/path/argument, timeout, output capture, and backlog update event after TODO completion.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/cli_fixture.py --command 'echo kateto'` → exact stdout reply; failure `--command 'rm -rf /tmp/x'` → rejection before process spawn. Evidence `.omo/evidence/kateto-mvp/task-10/`.
  Commit: Y | feat(connector): add restricted CLI and TODO sync
- [x] 11. Implement declarative workflow engine and lifecycle events
  What to do / Must NOT do: Load global/per-voice `workflow.py`, track phases/checkpoints/status, auto-advance on `voice_idle`, emit all lifecycle events, support `workflow_stop`, and hot-reload definitions without imperative scripts. Do not execute shell scripts from workflow phases.
  Parallelization: Wave 3 | Blocked by: 4-8 | Blocks: 13 | Can parallelize with: 9,10,12
  References (executor has NO interview context - be exhaustive): `SPEC.md:222-259`; existing defaults under `config/defaults/voices/*/workflows/`; `docs/voices/workflows.md:1-140`.
  Acceptance criteria (agent-executable): tests prove phase start/complete/checkpoint failure/stop/completion events, auto-advance only after idle and checkpoint success, per-voice/global discovery, and malformed definition rejection.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/workflow_fixture.py --workflow daily-standup --voice Conquest` → ordered lifecycle trace and deliverable path; failure checkpoint false → `workflow_checkpoint_fail` and no next phase. Evidence `.omo/evidence/kateto-mvp/task-11/`.
  Commit: Y | feat(workflow): add declarative workflow engine
- [x] 12. Implement config-declared MCP server with dynamic event-tool schemas and wait semantics
  What to do / Must NOT do: Add FastMCP server, config-only server discovery, explicit per-voice authorization, typed auto-discovered receiver schemas, `send_event(event_name,data,target,wait=False)`, correlation/reply matching, timeout, and cancellation. Do not discover installed/running processes implicitly or grant unconfigured voices all tools.
  Parallelization: Wave 3 | Blocked by: 3-8 | Blocks: 13 | Can parallelize with: 9-11
  References (executor has NO interview context - be exhaustive): `SPEC.md:110-112,371`; `docs/plugins/system.md:1-100`; `docs/voices/skills-and-mcp.md:1-92`.
  Acceptance criteria (agent-executable): MCP tests prove schema generation from registered BaseModels, authorized tool call, denied server/voice, wait correlation success, timeout, cancellation, and error event propagation.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/mcp_fixture.py send_event --event backlog_list --wait` → structured result before timeout; failure `--server undeclared` → authorization error and no subprocess. Evidence `.omo/evidence/kateto-mvp/task-12/`.
  Commit: Y | feat(mcp): expose authorized event bus tools
- [x] 13. Implement Textual TUI, plugin controls, event stream, and hot-reload integration
  What to do / Must NOT do: Build the live plugin/event view from `get_plugins()`/`get_events()`, runtime enable/disable/manual event controls, voice/plugin statuses, and watchdog create/modify/delete handling bridged via `loop.call_soon_threadsafe`, graceful task cancellation and queue clearing. Do not create a second asyncio loop.
  Parallelization: Wave 3 | Blocked by: 5-12 | Blocks: 14-16
  References (executor has NO interview context - be exhaustive): `SPEC.md:61-80,112`; `docs/plugins/system.md:1-100`; `docs/architecture/hot-reload.md:1-34`.
  Acceptance criteria (agent-executable): Textual `run_test()` proves event rendering and controls; reload tests prove task cancellation, queue clearing, module/config replacement, debounce, and no stale subscribers.
  QA scenarios (name the exact tool + invocation): happy `node script/qa/web-terminal-visual-qa.mjs --title 'Kateto TUI' --command 'uv run kateto tui --fixture' --input '{Enter}' --evidence-dir .omo/evidence/kateto-mvp/task-13-tui` → screenshot shows plugin list and live event rows; failure create malformed watched workflow → TUI shows error event while process remains responsive. Evidence `.omo/evidence/kateto-mvp/task-13/`.
  Commit: Y | feat(ui): add Textual dashboard and hot reload
- [x] 14. Complete defaults, assets, README, CLI run modes, and demo runbook
  What to do / Must NOT do: Reconcile `config/defaults/` with the canonical schema, add all enabled MVP SKILL.md files and non-secret reference-clip placeholders/validation instructions, add `README.md` setup/troubleshooting, fixture/live-server preflight, and a <3 minute demo script covering loop/TUI/interruption/work. Do not commit real secrets, model weights, or copyrighted audio.
  Parallelization: Wave 4 | Blocked by: 1-13 | Blocks: 15-16 | Can parallelize with: 15
  References (executor has NO interview context - be exhaustive): `SPEC.md:192-221,276-384`; `config/defaults/config.toml:1-33`; `docs/development/build-week.md:1-80`; `docs/development/tooling.md:1-36`.
  Acceptance criteria (agent-executable): clean temp-config bootstrap succeeds; README commands work from a fresh clone; every configured skill resolves; demo runbook names provider preflight and fallback fixture commands.
  QA scenarios (name the exact tool + invocation): happy `XDG_CONFIG_HOME=$(mktemp -d) uv run kateto smoke --fixture` → exit 0 and documented artifact; failure missing endpoint/clip → startup reports exact path/remediation and does not expose secrets. Evidence `.omo/evidence/kateto-mvp/task-14/`.
  Commit: Y | docs(delivery): add defaults, setup, and demo runbook
- [x] 15. Execute full end-to-end fixture and optional live-provider acceptance gates
  What to do / Must NOT do: Run the complete fixture conversation loop, interruption/resume, TUI visual proof, MCP/backlog work action, workflow lifecycle, and live-server smoke only when health checks pass; collect logs/screenshots/transcripts and teardown every process/temp resource. Do not accept self-reported success or stale logs.
  Parallelization: Wave 4 | Blocked by: 1-14 | Blocks: 16 | Can parallelize with: 14
  References (executor has NO interview context - be exhaustive): `SPEC.md:10-16,98-116`; `docs/development/build-week.md:1-80`; all task acceptance criteria above.
  Acceptance criteria (agent-executable): `uv run pytest` passes; `uv run kateto smoke --fixture` records `audio_chunk`, `transcription`, `EXECUTE`, three `generate`, streamed output, TTS PCM, and idle; interrupt trace proves cancellation and next utterance; MCP action changes backlog JSON atomically; TUI screenshot exists.
  QA scenarios (name the exact tool + invocation): happy `uv run python scripts/qa/acceptance.py --fixture --evidence-dir .omo/evidence/kateto-mvp/task-15` → all named markers PASS; failure `--interrupt-at token:3` → cancellation marker PASS and next input marker PASS; cleanup receipt must show no remaining PID/port/temp dir. Evidence `.omo/evidence/kateto-mvp/task-15/`.
  Commit: Y | test(qa): capture MVP end-to-end acceptance evidence
- [x] 16. Run final quality gates and reconcile scope
  What to do / Must NOT do: Run diagnostics, full tests/build/help, inspect diff against SPEC.md, verify excluded features are absent, redact evidence, and ensure no runtime QA state remains. Do not modify behavior during this verification todo except fixes required by a failed acceptance criterion, which must be recorded and re-tested.
  Parallelization: Wave 4 | Blocked by: 14-15 | Blocks: none
  References (executor has NO interview context - be exhaustive): `SPEC.md:375-384`; `pyproject.toml`; `.python-version`; `.omo/plans/kateto-mvp.md`; all changed files.
  Acceptance criteria (agent-executable): `uv run pytest`, `uv build`, `uv run kateto --help`, and LSP diagnostics exit cleanly; scope audit maps every `SPEC.md` MVP item to an implementation/test/evidence path; `git status --short` contains no generated secrets or QA processes.
  QA scenarios (name the exact tool + invocation): happy run the four final commands and scope audit → all exit 0 with artifacts; failure inject an excluded-feature path into the audit fixture → audit exits nonzero and identifies it. Evidence `.omo/evidence/kateto-mvp/task-16/`.
  Commit: Y | chore(qa): finalize MVP verification and scope audit

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

F1 checks every todo has references, acceptance, happy/failure QA, evidence path, dependency, and commit line. F2 reviews the final diff for async correctness, type safety, error handling, security boundaries, and no suppressed failures. F3 independently runs the fixture vertical slice, interruption, TUI visual QA, and cleanup receipts. F4 compares the implementation map against all P0 rows in `SPEC.md:98-116` and confirms every named P1/P2/P3 exclusion is absent. All lanes must approve.

## Commit strategy

- One Conventional Commit per todo, each kept buildable and testable; no automatic `git commit` is required by this plan unless the executor is explicitly authorized.
- Keep commits in dependency order and append `Plan: .omo/plans/kateto-mvp.md` to final implementation commit messages.

## Success criteria

- `uv sync --locked`, `uv run pytest`, and `uv build` pass on Python 3.12.
- The fixture real-surface command proves the complete audio→transcription→classification→three-voice generation→streamed TTS/player loop and its failure/interrupt/resume path.
- Plugin dispatch, config/bootstrap, atomic persistence, connectors, workflow lifecycle, MCP authorization/wait, TUI controls, and hot reload each have passing happy/failure evidence.
- README/demo runbook supports a fresh setup, and no secrets, models, or excluded post-MVP functionality are committed.
