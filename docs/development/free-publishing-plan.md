# Free and safe publishing plan

**Decision:** publish Kateto as a public, fixture-first Hugging Face Space and keep live inference provider-agnostic. The public demo must never contain a personal provider key, microphone recording, private reference clip, or unbounded event payload.

This plan is for the OpenAI Build Week **Work and Productivity** submission. It is an execution plan, not a promise that a third-party free tier will remain unchanged.

## Release shape

### 1. Public judge path: Gradio ZeroGPU Space

The deployment target is the ZeroGPU Gradio hardware available in the maintainer’s Hugging Face account. Do not plan around CPU Basic. Ship a small Gradio adapter whose default action launches the bounded fixture runtime and renders its event state, plans, workflow progress, and work artifacts in the browser. The Textual TUI remains the local/operator surface; the Gradio adapter is the judge-facing presentation of the same runtime state.

- Pin Python/dependency versions and build from the lockfile.
- Use Gradio’s Space startup path and a short smoke command before publishing.
- Keep the fixture path GPU-free at the application level so it works even when the shared GPU queue is busy; only decorated inference functions request ZeroGPU.
- Decorate VAD and classifier functions with `@spaces.GPU` only after the fixture path is proven. Do not move the whole runtime into a GPU allocation.
- Treat the Space filesystem as ephemeral. Keep plans and work artifacts in the session/runtime view, and do not promise durable user storage unless a separately verified persistent volume is available.
- Show a clear “fixture / live” label and the current GPU/provider status so judges cannot mistake deterministic output for live inference.

### 2. Optional live path: user-owned providers

Live mode remains a local or explicitly configured deployment. The Space may accept provider settings, but keys belong in Space Secrets or the user’s local `.env`, never in the repository, README examples, browser JavaScript, event payloads, or logs.

| Capability | Default | Optional live provider | Safety boundary |
|---|---|---|---|
| VAD | fixture VAD | a ZeroGPU-decorated inference function | Do not make microphone audio public by default; cap clip length and delete temporary audio after dispatch. |
| Classifier | fixture classifier | OpenRouter free model or a tested Ternary-Bonsai model | Use an allowlisted model ID, low token/output limits, timeout, retry budget, and a per-user rate limit. |
| Voice generation | fixture response | OpenRouter with BYOK, or local/Space-hosted Bonsai where supported | Never proxy the maintainer’s key to anonymous users. BYOK must be entered into a server-side secret/config path. |
| TTS | fixture PCM | Edge TTS without an API key, or Camb.AI with the user’s key | Treat Edge TTS as an online fallback whose availability and terms can change; Camb.AI requires an API key. |

Hugging Face documents that ZeroGPU is Gradio-only, dynamically allocates the GPU to decorated functions, and applies daily quotas and queue priority. The general account rules may differ from this account’s entitlement, so the release checklist must verify that the target Space can actually be created and run under the maintainer’s ZeroGPU plan: <https://huggingface.co/docs/hub/main/en/spaces-zerogpu>.

OpenRouter exposes a model catalog and free variants, but model availability and limits change. Resolve models from the catalog at deployment time and pin a known-good fallback for the demo: <https://openrouter.ai/docs/guides/overview/models>. If BYOK is supported, use a narrowly scoped, expiring key with a spending limit; OpenRouter’s key documentation states that plaintext keys are shown only once: <https://openrouter.ai/docs/api/api-reference/api-keys/create-keys>.

The Ternary-Bonsai idea is technically plausible but must be benchmarked in the target Space. Prism ML publishes Apache-2.0 Ternary-Bonsai model cards, including a 1.7B variant and GGUF variants, but format/runtime compatibility is not the same as a turnkey ZeroGPU service: <https://huggingface.co/prism-ml/Ternary-Bonsai-1.7B-mlx-2bit>, <https://huggingface.co/prism-ml/Ternary-Bonsai-27B-gguf>.

`edge-tts` currently documents an online Microsoft Edge speech service that does not require an API key: <https://github.com/rany2/edge-tts>. It is a convenient no-key fallback, not a guarantee of permanent availability. Camb.AI’s official quickstart requires the API key from its API settings: <https://docs.camb.ai/getting-started/quickstart>.

## Security and privacy gates

1. Keep all secrets in Hugging Face Space Secrets or local ignored files. Add a CI scan for common key prefixes and fail the build if secrets or private audio are tracked.
2. Disable public microphone capture. The judge path uses text/fixture input; live audio is opt-in, visibly indicated, bounded by duration/size, and discarded after the consuming event handlers finish.
3. Apply input limits before inference: maximum UTF-8 bytes, audio duration, workflow name length, event name allowlist, and JSON nesting/depth.
4. Keep tool execution allowlisted. The CLI connector must remain restricted; no user-controlled shell string should be passed through the Space.
5. Do not expose arbitrary event injection from an unauthenticated public endpoint. If a web adapter is added, require a per-session token and accept only the documented demo commands.
6. Emit redacted operational logs. Never log API keys, raw audio, full prompts, private file contents, or untrusted exception payloads.
7. Pin and review third-party licenses. Keep the project license and provider/model licenses visible in the release notes.
8. Add a visible disclaimer that model output can be wrong and that the app is not a substitute for human review of work, calendar, or command actions.

## What the public demo must show

The demo should show the plan and the work, not only a chat bubble:

- the event tab with typed events and errors;
- the Plugins, Voices, Workflows, and MCP tabs populated from the runtime;
- a voice tree showing workflow phases, checkpoints, current task, and status;
- a concrete plan such as a daily stand-up or backlog breakdown;
- the resulting backlog/TODO/workflow artifacts;
- the event trail proving which agent emitted and received each step;
- interruption and recovery;
- the fixture/live provider status and any degraded fallback.

## Execution sequence

1. Freeze the fixture contract and run it locally in a clean config directory.
2. Build the Gradio adapter with fixture as the only default and verify it without network access.
3. Create the target Space using the account’s ZeroGPU Gradio option and confirm a minimal `@spaces.GPU` probe works.
4. Add health, timeout, rate, payload, session cleanup, and secret-scan checks.
5. Test VAD, classifier, LLM, and TTS independently; do not couple their availability into Space startup.
6. Publish the Space and repository, then test from a clean browser/session with no maintainer credentials.
7. Record the exact Space revision, model IDs, provider terms, GPU quota behavior, and smoke output in the release notes.
8. Submit the Build Week entry with an English description, a public YouTube video under three minutes, repository URL, testing instructions, and the Codex `/feedback` session ID. The official `RULES.md` remains the source of truth for eligibility and submission requirements.

## Rollback

If a live provider fails, exceeds quota, changes terms, or exposes unsafe behavior, disable that provider in configuration and leave the fixture Space available. A release is acceptable only when the deterministic path still starts, renders the runtime state, and demonstrates real work artifacts.
