# Final MVP assessment

**Assessment date:** 2026-07-20
**Track:** Work and Productivity
**Project:** Kateto

## Verdict

Kateto is a credible, runnable MVP vertical slice for the track. Its strongest differentiator is the event-oriented team runtime: audio, classification, voices, workflows, tools, TUI state, errors, and hot reload all communicate through the PluginManager. The fixture mode makes the core behavior judgeable without private infrastructure.

The release is not yet a general hosted voice service. Microphone capture, model serving, TTS, provider quotas, and hardware compatibility remain deployment concerns. The safe publication strategy is therefore fixture-first with opt-in live providers, rather than embedding the maintainer’s keys or promising an unlimited free GPU.

## Evidence of work

- Runtime: `kateto/live.py`, `kateto/run_mode.py`, and `kateto/core/manager.py` assemble the event runtime and lifecycle.
- Event contracts: `kateto/core/event.py` defines typed Pydantic payloads and envelopes.
- Work execution: workflow catalog/engine, per-voice workflows, backlog/TODO executors, and MCP runtime state are visible to the TUI.
- Product surface: `kateto/plugins/system/tui.py` exposes events, plugins, voices, workflows, MCPs, configuration, statuses, and notifications.
- Reliability: fixture mode, interruption handling, error events, hot reload, bounded event histories, and focused async tests.
- Development evidence: the dated Git history documents incremental Codex-assisted implementation; the Build Week submission should additionally provide the required `/feedback` session ID.

## Fit against the Build Week criteria

| Criterion | Assessment |
|---|---|
| Technological implementation | Strong: typed event bus, concurrent dispatch, plugin lifecycle, streaming providers, workflow state, and a real TUI. |
| Design | Good for an MVP: the fixture path is reproducible and the TUI explains system state. A hosted web shell is still a packaging layer, not the core product. |
| Potential impact | Strong and specific: a voice team turns stand-ups and project requests into plans, backlog items, workflow progress, and tool actions. |
| Quality of idea | Strong: role-based voices plus event-observable work are more concrete than a generic voice chatbot. |

## Gaps to disclose

- The canonical `SPEC.md` describes the P0 MVP; newer repository documentation also contains post-MVP material. The submission should clearly label what is demonstrated in the video.
- External inference is not guaranteed to be free, available, private, or stable. Provider/model choices belong in deployment configuration.
- The system can create real work and invoke connectors; production deployments need authentication, authorization, audit retention, and human confirmation for consequential actions.
- Third-party voice services and model licenses must be reviewed before commercial redistribution. No private reference clips or credentials should be committed.

## Submission readiness checklist

- [ ] Public repository with license and clean secret scan.
- [ ] Clean fixture smoke run and a judge-facing testing command.
- [ ] TUI capture showing the event trail, agent plan, workflow progress, and real work artifact.
- [ ] Demonstration video is public, in English or has an English translation, contains audio, and is under three minutes.
- [ ] README explains Codex/GPT-5.6 collaboration, product decisions, setup, supported platforms, and fixture/live boundaries.
- [ ] Devpost description selects Work and Productivity and names the actual work outcome.
- [ ] Required Codex `/feedback` session ID is recorded in the submission form.
- [ ] Final dependency/provider/model licenses and terms are checked against the official sources.

Current release blocker: `kateto smoke --fixture` still references the removed `scripts/qa/acceptance.py`; this is tracked as [bug 26](../bugs/26-smoke-cli-deleted-qa-path.md). The focused event-manager and TUI regression tests pass, but the smoke command must be repaired before publishing.

The full `uv run pytest` invocation also has collection failures from removed `kateto.qa`/legacy voice modules. Those existing repository-drift failures must be resolved or explicitly excluded in the judge-facing validation command before release; they are not hidden by the fixture-first plan.

The complete deployment sequence and provider safety controls live in [`free-publishing-plan.md`](./free-publishing-plan.md).
