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

**Expected main dependencies** (subject to change during development):
- `asyncio` (stdlib)
- `aiohttp` — HTTP client/server for AI model servers
- `websockets` — real-time communication
- `textual` — TUI framework
- `toml` — config parsing
- `watchdog` — file monitoring for hot-reload
- `pytest` + `pytest-asyncio` — testing
- `openai` — OpenAI SDK (compatible with llama.cpp API)
- `python-dotenv` — secrets management

## Python Version

**Python >= 3.12** required. Pinned via `uv python pin 3.12`.
