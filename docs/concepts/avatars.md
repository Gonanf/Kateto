# Visual Design — Avatars (P3 — Demo/Future)

The Kateto voices are represented visually as **puppet masks**.

## Voices (Agents)

- Mask **white**, smooth, simple
- Eyes and mouth **black**, no details
- No cheeks or complex expressions
- Minimalist — clearly distinguishable as an agent, not a human

## User

- Same mask but **red**
- With **cheeks** (pink circles on the cheeks)
- **Nutcracker-style** mouth — opens and closes when speaking
- Visually distinct from agents to make clear who is human

## Implementation

Avatars are generated with an AI model specialized in SVG (e.g., an LLM with good SVG generation capabilities). If time permits, they are implemented as:

- **Avatar plugin**: generates and updates SVGs in real time
- **Video overlay**: avatars appear with synchronized subtitles while voices speak. Masks change pose/expression based on state (speaking, listening, thinking)

## Demo Video

Avatars are a central part of the project video. Used for:
- Visually representing which voice is speaking at any moment
- Showing agent ↔ user interaction
- Giving visual identity without complex animation
