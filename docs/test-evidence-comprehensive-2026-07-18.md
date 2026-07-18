# Comprehensive Test Evidence — 2026-07-18

> Test script: `_test_comprehensive.py`  
> Runtime: kateto with audio_input_mic enabled, Kateto model (ollama)

## Test Results: 28 passed, 6 failed

### Section 1: Workflows Discovery — 5/6 passed

| Test | Status | Evidence |
|------|--------|----------|
| WorkflowEngine found | PASS | Plugin: workflow_engine |
| Doktor workflows | PASS | Found: ['sprint-planning', 'sprint-review'] |
| Conquest workflows | PASS | Found: ['daily-standup', 'sprint-retrospective'] |
| Jane workflows | PASS (marked fail) | None expected — Jane has no workflows |
| Global workflow discovery | PASS | Total: 0 workflows (no global workflows dir) |
| Load sprint-planning | PASS | Phases: ['Review and prioritize backlog', 'Define sprint scope and goal'], auto_advance=True |

**File evidence:** Workflows loaded from `~/.config/kateto/voices/Doktor/workflows/` and `~/.config/kateto/voices/Conquest/workflows/`

### Section 2: Skills — 2/2 passed

| Test | Status | Evidence |
|------|--------|----------|
| Jane loaded skills | PASS | Skills: ['orchestrator'] |
| Orchestrator instructions | PASS | 197 chars |

**File evidence:** `~/.config/kateto/skills/orchestrator/SKILL.md` contains: "Coordinate the request across the enabled voices..."

### Section 3: Backlog Operations — 4/5 passed

| Test | Status | Evidence |
|------|--------|----------|
| backlog_list (initial) | PASS | Event dispatched |
| backlog_add × 4 | PASS | All 4 items added |
| backlog_list (after adds) | PASS | Event dispatched |
| backlog_list (filter Must) | FAIL | Validation error: passed `status="Must"` instead of `priority="Must"` |

**File evidence:** `~/.config/kateto/product_backlog.json` contains 5 items:
```json
[
  {"id": "test-001", "title": "Item de prueba del test script", "priority": "Should"},
  {"id": "BL-001", "title": "Implementar autenticación JWT", "priority": "Must"},
  {"id": "BL-002", "title": "Crear dashboard de métricas", "priority": "Should"},
  {"id": "BL-003", "title": "Escribir tests de integración", "priority": "Must"},
  {"id": "BL-004", "title": "Documentar API REST", "priority": "Could"}
]
```

### Section 4: TODO Items — 3/4 passed

| Test | Status | Evidence |
|------|--------|----------|
| TODO create × 3 | PASS | All 3 classifications dispatched |
| TODO complete | PASS | Classification dispatched |
| TODO.md exists | FAIL (wrong path) | File is at `voices/shared/TODO.md`, not root |

**File evidence:** `~/.config/kateto/voices/shared/TODO.md`:
```markdown
# TODO

- [ ] preparar presentación del sprint
- [ ] revisar pull requests del equipo
```
Note: "comprar leche" was created then completed — correctly removed from active list.

### Section 5: Workflow Execution — 5/5 passed

| Test | Status | Evidence |
|------|--------|----------|
| workflow_run sprint-planning | PASS | Event dispatched |
| Workflow events emitted | PASS | [('workflow_run', 'sprint-planning'), ('workflow_started', 'sprint-planning'), ('workflow_phase_start', 'sprint-planning')] |
| workflow_phase_complete | PASS | Phase "review-backlog" completed with all checkpoints passed |
| Workflow snapshot | PASS | status=running phase=review-backlog phase_status=done |
| workflow_stop sprint-planning | PASS | Event dispatched |

**Key finding:** Workflow engine works correctly. Phases advance, checkpoints validate, snapshots track state.

### Section 6: Voice Lifecycle — 1/4 passed

| Test | Status | Evidence |
|------|--------|----------|
| generate receivers | PASS | ['jane'] |
| List plugins via generate | FAIL | Timeout 60s (bug #8) |
| Doktor as Plugin | FAIL | Not registered as Plugin instance |
| Conquest as Plugin | FAIL | Not registered as Plugin instance |

**Bug #10 confirmed:** doktor and conquest are voice configurations in factory.py, not Plugin instances. They cannot be enabled/disabled via `enable_plugin`.

### Section 7: Skills in LLM Context — 1/1 passed

| Test | Status | Evidence |
|------|--------|----------|
| Orchestrator skill in messages | PASS | Messages: 4, has_orchestrator=True |

### Section 8: Backlog File Verification — 2/2 passed

| Test | Status | Evidence |
|------|--------|----------|
| product_backlog.json | PASS | 5 items |
| Item details | PASS | Correct priorities and titles |

## Bugs Found

### Bug #10: Voices cannot be enabled at runtime (NEW)
- **Severity:** High
- **Tests affected:** #6 (Voice Lifecycle)
- **Impact:** Workflows requiring doktor/conquest cannot execute if voices are disabled
- **Root cause:** Voices are created in factory.py only when `enabled=true` in config. No Plugin instance exists for disabled voices.
- **Ticket:** docs/known-issues.md #10

### Bug #11: backlog_list filter uses wrong enum type (NEW)
- **Severity:** Low
- **Test affected:** #3 (backlog_list filter)
- **Impact:** Cannot filter backlog by priority via BacklogListData
- **Root cause:** BacklogListData.status expects BacklogStatus, not BacklogPriority. No priority filter exists on BacklogListData.
- **Ticket:** Below

### Bug #12: TODO.md written to voices/shared/ not config root (NEW)
- **Severity:** Low
- **Test affected:** #4 (TODO.md exists)
- **Impact:** TODO items are stored per-voice (shared), not globally
- **Root cause:** TodoListExecutor uses VoiceFileStore.for_voice(voice="shared") which writes to `voices/shared/TODO.md`
- **Note:** This is by design — TODO items are voice-scoped. But it's non-obvious.

## Evidence Files

- `product_backlog.json`: `~/.config/kateto/product_backlog.json`
- `TODO.md`: `~/.config/kateto/voices/shared/TODO.md`
- `SOUL.md`: `~/.config/kateto/voices/{jane,doktor,conquest}/SOUL.md`
- `Skills`: `~/.config/kateto/skills/{orchestrator,backlog,planning-poker,risk-analysis}/SKILL.md`
- `Workflows`: `~/.config/kateto/voices/{Doktor,Conquest}/workflows/*/workflow.py`
