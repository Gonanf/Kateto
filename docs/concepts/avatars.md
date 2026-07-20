# Visual Design — Avatars (P3 — Demo/Future)

The Kateto voices are represented visually as **unsettling realistic half-masks**.

## Core Concept

Each mask is a **realistic physical object** (porcelain, wood, leather, stone, metal) that covers the upper half of the face. Inside the eye holes, human-sized **eyes are visible** — but the eyes are the same color as the mask, with black/grey sclera (the white part), making it clear something is inside but it's not human.

The effect is **uncanny valley**: the masks look real enough to touch, and the visible eyes suggest a presence inside, but the wrong eye colors reveal inhuman entities wearing them.

## Voices (Agents)

- Each voice has a unique **material and color** matching their personality
- Visible eyes inside the mask's eye holes — same color as mask, black sclera
- Unblinking stare forward
- Material textures: porcelain (Jane), wood (Doktor), cracked porcelain (Conquest), ceramic (Narrador), stone (Susurrante), leather (Drakula), jade (Greedy), obsidian (Informante), cheap porcelain (Germ), painted metal (Business), split wood (Lovers), lacquered wood (Xavier)

See `development/masks-prompts.md` for full SVG generation prompts.

## User

- Red lacquered wooden mask — traditional craft style, glossy
- Large eye holes clearly showing **solid red eyes with black sclera** inside
- **Nutcracker-style hinged jaw** — slightly ajar, revealing mechanical wooden teeth
- Pink blush circles painted on the surface, clearly artificial
- The most unsettling mask of the collection — looks most human, but the solid red eyes with black sclera prove otherwise

## Implementation

Avatars are generated with SVG (via LLM generation or Recraft.ai). Prompts are documented to produce realistic mask textures with visible inner eyes. If time permits:

- **Avatar plugin**: generates and updates SVGs in real time
- **Video overlay**: avatars appear with synchronized subtitles while voices speak. Masks change pose/expression based on state (speaking, listening, thinking)

## Demo Video

Avatars are a central part of the project video. Used for:
- Visually representing which voice is speaking at any moment
- Showing agent ↔ user interaction
- Giving visual identity — unsettling, memorable, unique
