# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-02
**Commit:** (check `git rev-parse --short HEAD`)
**Branch:** (check `git branch --show-current`)

## OVERVIEW
Kateto — AI agent orchestration platform. Monorepo: Python ML services (classifier, TTS, orchestrator, manager) + Vue frontend (spin-wheel) + protobuf package.

**Stack:** Python 3.13, torch/ROCm, gRPC, Vue 3, Vite, bun, turbo, uv

## STRUCTURE
```
kateto/
├── apps/
│   ├── manager/          # LangChain agent orchestration, SCRUM docs
│   ├── orchestrator/     # Realtime STT (faster-whisper), gRPC server
│   ├── classifier/       # BERT intent classification, training + serving
│   ├── tts/             # Realtime TTS (Coqui), gRPC server
│   ├── spin-wheel/       # Vue 3 + bun frontend, grpc-js client
│   ├── kateto-frontend/  # (empty/skeleton)
│   └── lang_manager/     # (referenced in pyproject.toml, may be empty)
├── packages/
│   ├── protos/           # Protobuf definitions + generated code (Python/TS)
│   └── data/             # (referenced in pyproject.toml, may be empty)
├── docs/
├── turbo.json            # Turbo pipeline: dev depends on protos#gen
├── pyproject.toml       # uv workspace root (Python 3.13, torch/ROCm)
├── package.json          # Bun workspace root (apps/*, packages/*)
└── mempalace.yaml        # Memory palace config (kateto wing)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Agent configs | `apps/manager/data/agents/*.md` | Kateto, Sisyphus, Prometheus, etc. |
| Protobuf schemas | `packages/protos/` | `.proto` files, generated Python/TS code |
| Python entry points | `apps/*/main.py` or `server.py` | orchestrator, tts, manager, classifier |
| Frontend | `apps/spin-wheel/src/` | Vue 3, Tailwind, Lucide icons |
| Build pipeline | `turbo.json`, `apps/*/pyproject.toml` | dev → protos#gen first |
| Agent memory | MemPalace MCP | Wing: `kateto`, rooms: config/apps/docs |

## CODE MAP (Python services)
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| Manager agent | Module | `apps/manager/main.py` | LangChain agent orchestration |
| Orchestrator | Module | `apps/orchestrator/main.py` | STT gRPC server |
| Classifier | Module | `apps/classifier/server.py` | BERT intent classification |
| TTS | Module | `apps/tts/main.py` | TTS gRPC server |
| Agent configs | Markdown | `apps/manager/data/agents/` | Identity + parameter specs |

## CONVENTIONS
- **Python:** uv workspace, `requires-python >=3.13`, pyright with `.venv` at root
- **Frontend:** bun runtime, Vite build, Vue 3, Tailwind CSS
- **Protos:** `turbo gen` task, Python + TypeScript outputs in `packages/protos/*/src/`
- **gRPC:** All Python services use `grpcio>=1.80.0`, frontend uses `@grpc/grpc-js`
- **Hardware:** PyTorch configured for ROCm 7.2 (AMD GPU), not CUDA

## ANTI-PATTERNS (THIS PROJECT)
- **Never use CUDA torch packages** — project uses ROCm (`pytorch-rocm` index)
- **Never bypass `protos#gen`** — turbo `dev` depends on it
- **Never use pip** — uv-only workspace (`uv.lock` committed)
- **Never use npm/yarn** — bun-only (`bun.lock` committed)

## UNIQUE STYLES
- Agent identity files in `apps/manager/data/agents/*.md` use markdown with parameter specs
- `mempalace.yaml` maps rooms to file paths for memory palace MCP
- Classifier has custom BERT training pipeline (`apps/classifier/train.py`)

## COMMANDS
```bash
# Dev (requires protos#gen first)
bun run dev          # turbo run dev

# Python (from root, uv workspace)
uv run apps/manager/main.py
uv run apps/orchestrator/main.py
uv run apps/tts/main.py

# Frontend
cd apps/spin-wheel && bun run dev

# Proto generation (via turbo)
turbo run gen
```

## NOTES
- `lang_manager` and `packages/data` referenced in workspace but may not exist on disk
- `apps/kateto-frontend` exists but appears empty/skeleton
- Large files (>500 lines): check `apps/classifier/` (BERT checkpoint dirs may be large)
- ROCm 7.2 requirement means this runs on AMD GPUs only (not NVIDIA)
