# Tooling

## Project Manager: `uv`

Everything uses **uv**. No pip, no poetry, no conda, no manual virtualenv.

| Command | Purpose |
|---|---|
| `uv sync` | Install dependencies |
| `uv add <package>` | Add dependency |
| `uv remove <package>` | Remove dependency |
| `uv run <script>` | Run script in project environment |
| `uv run pytest` | Run tests |
| `uv run kateto` | Start the system |
| `uv build` | Build the package |
| `uv publish` | Publish to PyPI (future) |
| `uv python pin 3.12` | Pin Python version |

## Dependencies

Declared in `pyproject.toml` using `[project]` with `requires-python = ">=3.12"`.

**Main dependencies** (from `pyproject.toml`):
- `anyio` — async compatibility layer
- `edge-tts` — Microsoft Edge TTS (free, no API key)
- `fastapi` — HTTP server for external integrations
- `httpx` — async HTTP client
- `mcp` — Model Context Protocol server
- `numpy` — audio buffer manipulation
- `openai` — OpenAI-compatible LLM API
- `pydantic` — data validation
- `pydantic-ai` — structured tool-calling for voice agents
- `python-dotenv` — secrets management
- `silero-vad` — voice activity detection
- `sounddevice` — cross-platform audio capture/playback
- `textual` — TUI framework
- `torch` — Silero VAD runtime
- `uvicorn` — ASGI server for FastAPI

## Python Version

**Python >= 3.12** required. Pinned via `uv python pin 3.12`.
