# Build Week Requirements

Kateto targets **Work and Productivity**. The public judge path is fixture-first, while live model/audio providers are optional deployment configuration. See [`free-publishing-plan.md`](./free-publishing-plan.md) and [`final-assessment.md`](./final-assessment.md) for the release plan, safety boundaries, and evidence of the work completed.

## Deliverables

1. **Working project** built with Codex (all code written by Codex)
2. **Category**: Work and Productivity
3. **Project description**: what it is and how it works
4. **Demo video**: < 3 minutes, YouTube public, with voiceover explaining:
   - What was built
   - How Codex was used (entire development done with Codex)
   - How GPT-5.6 was used
   - Show: complete conversation loop, live event TUI, voice interruption
5. **Repo link** (share with `testing@devpost.com` and `build-week-event@openai.com`)
6. **README** with setup instructions
7. **Codex /feedback Session ID** where core functionality was built (single session)

## Tracks

- **🌜 Work and Productivity**: tools that make teams faster or more effective — automation, analytics, sales, back-office

## Deadline

**Monday, July 21, 2026, 5:00 PM PT** (8 days from start)

## Team

**Solo**. One person. Scope adjusted to a single developer in 8 days — all development via Codex.

## Demo Strategy (3 min video)

| Segment | Duration | Content |
|---|---|---|
| What is Kateto | 30s | Multi-agent voice assistant where AI agents collaborate for project management |
| Conversation loop | 60s | Talk to Kateto → Jane/Doktor/Conquest respond → visible in TUI → TTS output |
| Live events | 30s | TUI showing plugins, events, bus state in real time |
| Interruption | 20s | Interrupt the system while speaking → instant response |
| Real work | 30s | Doktor creates a task, Conquest updates progress, reflected in the system |
| Codex | 10s | Show everything was built with Codex |

## Evaluation Criteria

| Criterion | Strategy |
|---|---|
| **Technological Implementation** | Plugin broker architecture, async streaming, hot-reload, classifier fine-tuning. Core logic built with Codex. |
| **Design** | Functional vertical slice: complete conversation loop with working TUI and TTS. Not a PoC — a usable product. |
| **Potential Impact** | Voice-driven project management automation. "A team of 4 operates like 8." Concrete use case: daily standup → task breakdown → sprint planning. |
| **Quality of the Idea** | Multi-agent with personality evolution (SOUL). Decentralized coordination via event bus. Each voice = a real team role. |
