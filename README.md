# Kateto — an event-driven voice team for Work and Productivity

![Jane](public/jane1.svg) ![Doktor](public/doktor1.svg) ![Conquest](public/conquest1.svg)

Kateto is a small, event-driven voice team for project work. Jane orchestrates, Doktor handles planning and backlog work, and Conquest keeps progress moving. The MVP can run entirely with deterministic fixtures, so setup and demo do not require API keys, model weights, microphones, or audio recordings.

Kateto is built for the OpenAI Build Week **Work and Productivity** track. A request becomes observable work: typed events move through the runtime, agents create plans and workflow progress, and connectors can turn the result into backlog/TODO artifacts. The architecture has no custom conversation pipeline: plugins publish and subscribe to events through the PluginManager.

![The Kateto team](public/the_lovers1.svg)

## What to look for in the demo

- **Events:** send typed events, inspect registrations, and see errors as notifications.
- **Agents:** watch Jane, Doktor, and Conquest report input, thinking, talking, and idle states.
- **Plans and work:** inspect global/per-voice workflows, phases, checkpoints, current tasks, backlog, and TODO results.
- **Runtime:** inspect discovered plugins, MCP servers, configuration, sent/received event history, and hot-reload state.
- **Safe fallback:** `--fixture` demonstrates the same event-driven behavior without network services or secrets.

## Setup

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run kateto --help
```

On first use, Kateto copies [`config/defaults/`](config/defaults/) to `$XDG_CONFIG_HOME/kateto` (or `~/.config/kateto` when `XDG_CONFIG_HOME` is unset). To use an isolated config during development:

```bash
XDG_CONFIG_HOME="$(mktemp -d)" uv run kateto config check
```

The default file follows the runtime schema: `[kateto]`, `[plugin.<name>]`, `[voice.<name>]`, `[mcp_servers.<name>]`, and `[cli]`. The CLI allowlist is deliberately restricted to safe, normalized commands. Do not add credentials to `config.toml`; put local secrets in the generated `.env` or `secrets/.env`, which are ignored by version control.

## Fast fixture demo (under 3 minutes)

This is the no-network path used for a reliable recording or review.

1. **0:00–0:20 — preflight**

   ```bash
   uv sync --locked
   XDG_CONFIG_HOME="$(mktemp -d)" uv run kateto config check
   ```

   A provider preflight is optional for the fixture demo: fixture mode supplies transcription, classification, streaming responses, and PCM output without a live server.

2. **0:20–1:05 — conversation loop**

   ```bash
   uv run pytest kateto/tests/test_plugin_manager.py -q
   ```

   This validates typed event dispatch, plugin lifecycle, and bounded runtime history without requiring external services.

3. **1:05–1:35 — live event surface**

   ```bash
   uv run kateto tui --fixture
   ```

   The fixture TUI displays plugin/voice state and the event stream. For an automated capture, use `node script/qa/web-terminal-visual-qa.mjs --title "Kateto TUI" --command "uv run kateto tui --fixture" --input "{Enter}" --evidence-dir .omo/evidence/kateto-mvp/task-14/tui`.

4. **1:35–2:00 — interruption and resume**

   ```bash
   uv run kateto tui --fixture
   ```

   Point out the event stream, statuses, plugin controls, and error notifications in the live TUI.

5. **2:00–2:40 — real work-shaped fixture**

   ```bash
   uv run pytest kateto/tests/test_workflow.py -q
   ```

   This exercises declarative workflow discovery and lifecycle. The complete bounded CLI smoke is tracked separately in [bug 26](docs/bugs/26-smoke-cli-deleted-qa-path.md) until its deleted QA runner path is repaired.

## Provider and audio preflight

Fixture mode is the fallback when external services or hardware are unavailable. Before a live run, confirm each configured HTTP endpoint responds with its provider-specific health route and that the configured audio device is available. Keep endpoint URLs in `config.toml` without embedded credentials; keep keys in `.env`.

Reference clips are required by the live TTS path, but no real or copyrighted clips are checked in. The deterministic voice fixture creates temporary, per-voice placeholder WAV files for its run; it does not change the repository defaults. For a live/configured voice, `reference_audio` or `reference_clip` must be a relative `.wav` path inside that voice's config directory, for example `voices/jane/reference.wav`. If the selected file is missing, the affected voice reports `voice.<name>.<field>` (or its voice name when using the default path) and the event bus stays up. Remediate it by placing an approved local WAV at that exact voice-owned path, or by correcting the configured relative path, then rerun the voice. Never commit the clip.

## Skills

Skills are declarative, non-secret `SKILL.md` files under `skills/<name>/` in the resolved config directory. The defaults include `orchestrator`, `backlog`, `risk-analysis`, and `planning-poker`, matching the voice declarations in `config/defaults/config.toml`. A skill name must be lowercase kebab-case and its document must exist; no implicit discovery or executable skill content is used.

To verify resolution after bootstrap:

```bash
CFG="$(mktemp -d)"
XDG_CONFIG_HOME="$CFG" uv run kateto config check
XDG_CONFIG_HOME="$CFG" uv run python -c 'from kateto.core.config import load_config; from kateto.voices.skills import load_skills; c=load_config(); names=tuple(sorted({n for v in c.settings.voice.values() for n in v.skills})); loaded=load_skills(config_dir=c.paths.config_dir, names=names); assert {s.name for s in loaded} == set(names); print("skills resolved:", ", ".join(names))'
rm -rf "$CFG"
```

For an explicit config directory, call `load_config(config_dir=...)` and `load_skills(config_dir=..., names=...)`; this avoids relying on process-global environment state.

## Troubleshooting

- **`invalid config ...`**: use the setting path in the error. Check TOML types, HTTP(S)-only endpoints, relative asset paths, and the safe CLI allowlist. `uv run python -m kateto.qa.config_fixture --config-dir /tmp/kateto-fixture --mode disallowed-cli` creates a rejection fixture; `--mode malformed` creates a TOML failure fixture.
- **Skill not found**: confirm `skills/<name>/SKILL.md` exists below the resolved config directory and that the name matches the voice declaration exactly.
- **Reference clip missing**: fixture mode supplies temporary per-voice placeholder WAVs. For live/configured use, add an approved local `.wav` at the exact voice-owned path named by the error (or correct `reference_audio`/`reference_clip`); absolute paths, `..`, non-WAV files, and files outside the voice directory are rejected.
- **No provider or microphone**: use `--fixture` commands above. The fixture path is the supported smoke fallback and does not load models or contact external services.
- **Config appears stale**: delete only your user config directory (`$XDG_CONFIG_HOME/kateto` or `~/.config/kateto`) and rerun `kateto config check`; repository defaults remain under `config/defaults/`.

## Safety and repository boundaries

Never commit `.env`, tokens, model weights, private reference audio, generated runtime state, or copyrighted media. The repository defaults contain only non-secret skill instructions and configuration. The full test suite and long acceptance run are separate gates; task-14 validation is limited to clean config bootstrap, skill resolution, and the fixture smoke/runbook surfaces.

## Publishing safely for free

The recommended public deployment is a fixture-first Hugging Face Space on free CPU hardware. Live providers are optional and user-owned: OpenRouter BYOK or a tested local/Ternary-Bonsai classifier, and Edge TTS or Camb.AI for speech. The maintainer key must never be shipped to browsers or shared with anonymous users. ZeroGPU is an experiment rather than the baseline because hosting and quotas depend on the current Hugging Face account tier.

Read the complete [free and safe publishing plan](docs/development/free-publishing-plan.md) and [final MVP assessment](docs/development/final-assessment.md). The latter records what is implemented, what the demo must show, and what remains a deployment caveat.

## Build Week and Codex

This is a solo OpenAI Build Week project in the **Work and Productivity** category. The implementation was developed with Codex and GPT-5.6. The dated commit history is the evidence of incremental work; the final submission must also include the required Codex `/feedback` session ID. The README deliberately separates the reproducible fixture MVP from optional live infrastructure so judges can test the project without rebuilding external model servers.
