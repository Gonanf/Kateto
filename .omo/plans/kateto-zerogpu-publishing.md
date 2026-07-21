# kateto-zerogpu-publishing - Work Plan

## Objective

Publish a safe Gradio Space on the maintainer's available Hugging Face ZeroGPU entitlement. The browser-facing Space must begin with an explicit provider choice:

1. **BYOK**: the judge supplies their own OpenRouter key in the session, never persisted or exposed to other users.
2. **Bonsai**: the Space uses the configured Ternary-Bonsai path without asking the judge for a key.

Both paths show the same event-derived plans, agent work, workflow progress, and runtime status. Fixture mode remains the deterministic fallback for local development and provider outages.

## Guardrails

- Gradio is the Space surface; the Textual TUI remains a local/operator surface.
- No CPU Basic assumption. GPU work must be isolated behind ZeroGPU-decorated functions.
- Never commit or log API keys, raw audio, private reference clips, prompts containing secrets, or user work artifacts.
- BYOK keys are session-only, redacted from status/events, bounded by timeout/rate/output limits, and discarded on session cleanup.
- Bonsai model identifiers and licenses are explicit configuration, not user-controlled arbitrary downloads.
- No anonymous arbitrary event injection or shell execution.

## TODOs

- [x] 1. Add a Gradio Space adapter and provider-choice gate
  Scope: new `space/` adapter, dependency/config metadata, and tests. Render a first screen with BYOK and Bonsai choices; do not start a runtime or accept prompts until a choice is submitted. BYOK reveals a masked key input and Bonsai reveals no secret field. Add a visible fixture/live/provider status.
  QA: launch the Gradio app locally and assert the initial screen has both choices, BYOK requires a key, Bonsai proceeds without one, and malformed/oversized input is rejected.
  Commit: `feat(space): add ZeroGPU provider selection gate`

- [x] 2. Connect the selected provider to an isolated event-runtime session
  Scope: session factory and adapter seam. Build one bounded runtime per browser session, route prompts through PluginManager events, and expose event history, plans, agent status, workflows, MCP status, and work artifacts as structured Gradio outputs. No global mutable user state.
  QA: two sessions receive independent event histories; session cleanup closes plugins and clears credentials; a provider error becomes an error notification without taking down the Space.
  Commit: `feat(space): expose session runtime state`

- [x] 3. Add ZeroGPU model boundaries and provider safety limits
  Scope: `spaces.GPU` integration for VAD/classifier or the selected Bonsai inference boundary, with fixture fallback. Add model allowlist, request timeout, output/token cap, rate limit, queue/degraded status, and no-key Bonsai path. Keep OpenRouter BYOK server-side and never return the key in any output.
  QA: fixture path runs without GPU; provider calls are bounded; invalid model IDs and quota/provider failures produce typed UI errors; secrets are absent from events/logs.
  Commit: `feat(space): isolate ZeroGPU inference and provider limits`

- [x] 4. Make the Space UI show plans and real agent work
  Scope: Gradio layout and event projection. Show the selected provider, live event timeline, agent statuses, workflow phase/checkpoint/task tree, MCP/plugin status, plan output, and resulting backlog/TODO artifacts. Make the judge-facing path understandable without opening the TUI.
  QA: fixture scenario produces a visible plan, named agent actions, workflow progress, and work artifact; error and interrupted states remain visible.
  Commit: `feat(space): render agent plans and work evidence`

- [x] 5. Package, document, and manually verify the Space
  Scope: Space README/config, deployment instructions, provider/license disclosures, secret setup, public test instructions, and fresh xterm/local Gradio evidence. Do not claim CPU Basic availability.
  QA: clean checkout build, local Gradio launch, browser interaction for both provider choices, ZeroGPU probe, secret scan, and teardown receipt.
  Commit: `docs(space): document ZeroGPU deployment and judge flow`

## Final verification wave

- [x] F1. Provider-choice security audit
- [x] F2. Session isolation and event-state audit
- [x] F3. Real Gradio browser QA on the current build
- [x] F4. ZeroGPU packaging and documentation audit

## Success criteria

- A judge must choose BYOK or Bonsai before any demo interaction starts.
- BYOK never becomes public output, event data, logs, URL state, or persisted file.
- Bonsai works without a key, subject to the configured model/runtime availability.
- The UI visibly shows the plan and real work performed by agents from runtime events.
- The Space runs on the available ZeroGPU Gradio entitlement and has a deterministic fixture fallback.
