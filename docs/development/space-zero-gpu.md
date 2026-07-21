# Hugging Face ZeroGPU Space

The repository root is the Space repository. Its README frontmatter points Hugging Face at `space/app.py`; the root `requirements.txt` contains the small Gradio runtime dependency set. The Textual TUI and microphone/audio services are local/operator surfaces, not Space entrypoints.

## Deployment

1. Create or select a Hugging Face Space with the **Gradio** SDK and Python 3.12.
2. Select the **ZeroGPU** hardware option in the Space Settings. CPU Basic is not the supported deployment assumption for this package. The README metadata does not auto-assign hardware.
3. Push this repository, including `README.md`, `requirements.txt`, `space/`, and `kateto/`. The Space starts at `space/app.py`.
4. Wait for the build, then inspect the build/runtime logs. A successful local import does not prove that the account is entitled to host a ZeroGPU Space.

This repository does not contain Hugging Face credentials or a Space repository URL. No deployment, hardware entitlement, or remote revision is claimed here.

## Secrets and provider paths

The first browser action is an explicit provider choice:

- **Bonsai** is the judge path when the Space owner has configured `KATETO_SPACE_MODE=live`, `KATETO_SPACE_BONSAI_ENDPOINT`, `KATETO_SPACE_BONSAI_MODEL`, and an allowlisted model. It does not ask the judge for a key. The endpoint/model are owner configuration, not arbitrary user downloads.
- **BYOK** sends the judge’s OpenRouter key only from the server-side Gradio callback to OpenRouter. The key is session-only: it is not rendered in outputs, events, URLs, logs, or files, and is cleared when the browser session is torn down. A judge must use their own narrowly scoped key and accept OpenRouter’s current terms, model availability, and billing.

Set owner configuration in the Space Settings **Variables and secrets** panel, never in the repository:

```text
KATETO_SPACE_MODE=live
KATETO_SPACE_BONSAI_ENDPOINT=https://<owner-controlled-endpoint>/v1
KATETO_SPACE_BONSAI_MODEL=<allowlisted-model-id>
KATETO_SPACE_BYOK_MODEL=openai/gpt-4o-mini
KATETO_SPACE_ALLOWED_MODELS=openai/gpt-4o-mini
```

If the live Bonsai variables are absent, use the default fixture mode. Do not add an OpenRouter maintainer key: BYOK is intentionally supplied per judge session.

## What the demo means

The default `fixture` mode is deterministic and does not contact a model provider or require a GPU. It demonstrates the real PluginManager event path and renders plans, Jane/Doktor/Conquest actions, workflow progress, plugin/MCP status, and work artifacts. A visible `fixture fallback` label prevents fixture output from being mistaken for live inference.

In `live` mode, only the provider request boundary is wrapped with optional `spaces.GPU`; the whole runtime is not placed in a GPU allocation. ZeroGPU is Gradio-only dynamic allocation, so queueing, daily quota, and account priority can delay or reject live requests. The app bounds calls to a 10-second timeout, 6 requests per 60 seconds per runtime, and 512 output tokens. A provider failure is shown as a degraded notification and does not authorize arbitrary event injection or shell execution.

## Model, provider, and license disclosures

- Fixture output is authored deterministic demo text; it is not a trained model.
- BYOK uses the configured OpenRouter-compatible model, currently defaulting to `openai/gpt-4o-mini`; availability, pricing, terms, and output behavior belong to OpenAI/OpenRouter and can change.
- Bonsai is an optional owner-operated OpenAI-compatible endpoint. The repository does not download or bundle Ternary-Bonsai weights. If a Bonsai model is used, publish its exact model card, revision, and license beside the Space before enabling it; Prism ML’s Ternary-Bonsai cards are Apache-2.0, but endpoint/runtime compatibility remains deployment-specific.
- Gradio, `spaces`, Pydantic, AnyIO, HTTPX, and the other runtime packages retain their upstream licenses. Review their installed-version licenses for redistribution. No model weights, private audio, credentials, or persistent user artifacts are packaged here.

## Public test and teardown

The concise public test is:

```bash
uv run python -c 'from space.app import app; assert app is not None; print("Space import: OK")'
```

For a browser check, launch `uv run python -m space.app` only if a local launcher is added; otherwise use `uv run python -c 'from space.app import app; app.launch()'`, choose **Bonsai**, enter `plan a release`, and confirm a plan plus agent/workflow evidence appears. The local default is fixture mode, so this does not require a secret or provider network call.

When a browser session ends, Gradio invokes the state `delete_callback`; Kateto closes the per-session runtime, disables its plugin, drains pending tasks, and clears the session key. Space storage is ephemeral: plans and artifacts are session evidence, not durable user storage. To stop a remote Space, use its Settings stop/delete controls; do not treat a local process exit as proof of remote teardown.
