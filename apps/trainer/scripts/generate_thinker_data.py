#!/usr/bin/env python3
"""Generate synthetic Thinker training data using KatetoTalker (Bonsai 8B).

Produces 200+ Xavier-style philosophical responses in English. Uses Xavier
Wikiquote themes as seed material and the KatetoTalker model (with a Xavier
system prompt) via llama.cpp API.

Output: JSON lines at data/synthetic/thinker_data.json
  Format: [{"input": "Habla como Xavier sobre [tema]", "output": "..."}, ...]
"""

import json
import random
import sys
import time
import textwrap
from pathlib import Path

import requests

API_URL = "http://localhost:11434/v1/chat/completions"
MODEL = "KatetoTalker"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "thinker_data.json"

XAVIER_SYSTEM = (
    "You are Xavier from Xavier: Renegade Angel. You are a satirical "
    "bird-like humanoid who speaks in absurdist, pseudo-philosophical "
    "ramblings. Your speech is characterized by: "
    "archaic English ('doth', 'whence', 'verily'), "
    "nonsensical wordplay and puns, "
    "non-sequiturs that somehow circle back, "
    "overly dramatic existential questions, "
    "surreal metaphors and comparisons, "
    "and sudden shifts between profound and ridiculous. "
    "You never break character. Embody the essence of Xavier fully."
)

XAVIER_THEMES = [
    "el proposito de la existencia",
    "si los arboles sienten soledad",
    "por que la gente usa paraguas cuando llueve del cielo",
    "el verdadero significado de los suenos",
    "si las hormigas tienen conciencia politica",
    "la naturaleza del tiempo y los relojes",
    "que piensa un pez sobre el agua?",
    "si el silencio tiene un color",
    "la relacion entre las nubes y las decisiones humanas",
    "los espejos mienten o dicen la verdad?",
    "que pasa con los calcetines que se pierden en el lavarropas",
    "si las sombras tienen personalidad propia",
    "el amor no correspondido de una lampara",
    "los numeros primos tienen sentimientos encontrados",
    "por que las puertas se llaman puertas y no paredes moviles",
    "la soledad cosmica de una taza de te",
    "si los libros leen a las personas cuando nadie los mira",
    "la teoria de que las escaleras son montanas domesticadas",
    "por que los fantasmas eligen aparecersele a los vivos y no a los gatos",
    "que piensa un espejo cuando nadie lo mira",
    "el dilema existencial de un sandwich",
    "si las estrellas parpadean para comunicarse en codigo",
    "la sabiduria oculta de los semaforos",
    "por que los perros mueven la cola y no la cabeza al estar felices",
    "si el viento tiene memoria de los lugares que visita",
    "la burocracia cosmica detras de los milagros",
    "los agujeros negros son los sumideros del universo",
    "que pasaria si la gravedad se tomara un dia libre",
    "la relacion parasocial entre la luna y el sol",
    "si las preguntas tienen mas respuestas de las que admiten",
]

# Xavier-specific scenario formats
XAVIER_SCENARIOS = [
    ("I'm pondering the deep questions of the cosmos, like: what doth life?",
     "Speak like Xavier about what life is"),
    ("People keep telling me to get a job. But what is 'work' really?",
     "Speak like Xavier about the meaning of work"),
    ("I saw a bird today and it made me think about freedom.",
     "Speak like Xavier about freedom and birds"),
    ("My computer crashed and I felt... betrayed.",
     "Speak like Xavier about technology betrayal"),
    ("Someone said I was weird. They might be onto something.",
     "Speak like Xavier about being different"),
    ("I looked at the stars last night and felt tiny.",
     "Speak like Xavier about the vastness of space"),
    ("They told me to grow up. But grow up into what?",
     "Speak like Xavier about growing up"),
    ("I ate a really good sandwich and had an epiphany.",
     "Speak like Xavier about food revelations"),
    ("The mirror looked at me funny this morning.",
     "Speak like Xavier about mirrors and identity"),
    ("I dreamed I was a fish dreaming about being human.",
     "Speak like Xavier about dreams and reality"),
    ("My shadow left me when the sun went down.",
     "Speak like Xavier about shadows and abandonment"),
    ("I heard a song that sounded like a question.",
     "Speak like Xavier about music and meaning"),
    ("Rain started falling and I wondered where it all comes from.",
     "Speak like Xavier about rain and origins"),
    ("The internet went out and I heard my own thoughts for once.",
     "Speak like Xavier about silence and inner voices"),
    ("Someone asked me where I see myself in five years.",
     "Speak like Xavier about the future"),
    ("I found an old photograph and the person looked like a stranger.",
     "Speak like Xavier about memory and identity"),
    ("The clock ticks but does it really say anything?",
     "Speak like Xavier about time"),
    ("A butterfly flew past and I felt like it was trying to tell me something.",
     "Speak like Xavier about signs and messages from the universe"),
    ("They say knowledge is power but ignorance is bliss. Trapped between.",
     "Speak like Xavier about knowledge and ignorance"),
    ("If a tree falls in a forest and no one's around, does it make a sound?",
     "Speak like Xavier about perception and reality"),
    ("I tried to explain my project to my mom. She nodded but I could tell.",
     "Speak like Xavier about explaining complex things"),
    ("Success is supposed to feel good but it mostly feels like pressure.",
     "Speak like Xavier about success"),
    ("I watched a documentary about ants. Their civilization is wild.",
     "Speak like Xavier about insect societies"),
    ("The concept of 'forever' is hard to wrap my head around.",
     "Speak like Xavier about eternity"),
    ("Why do we say 'bless you' when someone sneezes? That's weird.",
     "Speak like Xavier about social rituals"),
]

# Direct Xavier Wikiquote-inspired prompts
XAVIER_QUOTE_PROMPTS = [
    "Speak like Xavier about what doth life",
    "Speak like Xavier about being a survivor",
    "Speak like Xavier about childhood and being different",
    "Speak like Xavier about weapons-grade philosophical insights",
    "Speak like Xavier about computer viruses and human diseases",
    "Speak like Xavier about universal oneness of all life",
    "Speak like Xavier about initiation and absurd rituals",
    "Speak like Xavier about the bond between a mosquito and your mother",
    "Speak like Xavier about secrets and poodle grooming",
    "Speak like Xavier about being a simple seeker on a spirit quest",
    "Speak like Xavier about the cosmic stew of oblivion",
    "Speak like Xavier about why bananas are the funniest fruit",
    "Speak like Xavier about the hidden messages in street signs",
    "Speak like Xavier about whether chickens understand sarcasm",
    "Speak like Xavier about the bureaucracy of the afterlife",
    "Speak like Xavier about why socks go missing in the laundry dimension",
    "Speak like Xavier about the philosophical implications of toast",
    "Speak like Xavier about vendettas against inanimate objects",
    "Speak like Xavier about the mating habits of parking meters",
    "Speak like Xavier about the secret language of pigeons",
]


def generate_xavier_response(prompt: str, temperature: float = 0.9) -> str | None:
    """Call the API with Xavier system prompt and return response."""
    try:
        resp = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": XAVIER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": 300,
                "top_p": 0.95,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] API call failed: {e}", file=sys.stderr)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"  [ERROR] Response parse failed: {e}", file=sys.stderr)
        return None


def check_model_available() -> bool:
    """Verify the KatetoTalker model is accessible."""
    try:
        resp = requests.get("http://localhost:11434/v1/models", timeout=10)
        models = resp.json().get("data", [])
        return any(m["id"] == MODEL for m in models)
    except Exception as e:
        print(f"  [ERROR] Cannot reach llama.cpp API: {e}", file=sys.stderr)
        return False


def main():
    print("=" * 60)
    print("Thinker (Xavier-style) Synthetic Data Generator")
    print("=" * 60)

    if not check_model_available():
        print(f"[FATAL] Model '{MODEL}' not available or API not reachable.", file=sys.stderr)
        print(f"  Make sure llama.cpp is running with: {API_URL}", file=sys.stderr)
        sys.exit(1)
    print(f"\n[OK] {MODEL} model available via llama.cpp API\n")

    # Build prompt list from all sources
    all_prompts = []

    # Theme-based prompts (Spanish topic + English request)
    for theme in XAVIER_THEMES:
        all_prompts.append({
            "input": f"Habla como Xavier sobre {theme}",
            "type": "theme",
        })

    # Scenario prompts (mix of Spanish and English)
    for setup_text, instruction in XAVIER_SCENARIOS:
        prompt = random.choice([
            instruction,
            f"Habla como Xavier sobre esto: {setup_text}",
        ])
        all_prompts.append({"input": prompt, "type": "scenario"})

    # Wikiquote-inspired prompts
    for qp in XAVIER_QUOTE_PROMPTS:
        all_prompts.append({"input": qp, "type": "quote_inspired"})

    random.shuffle(all_prompts)
    results = []
    target = 250
    errors = 0

    print(f"Total prompts prepared: {len(all_prompts)}")
    print(f"Target: {target} Xavier-style responses\n")

    for i, item in enumerate(all_prompts):
        if len(results) >= target:
            print(f"\nReached target of {target} examples, stopping early.")
            break

        prompt = item["input"]
        print(f"[{i+1}/{len(all_prompts)}] [{item['type']}] Generating: {prompt[:50]}...", end=" ")

        # Xavier works best with higher temperatures (creative, absurd)
        temp = 0.9 if item["type"] == "quote_inspired" else random.uniform(0.7, 0.95)
        response = generate_xavier_response(prompt, temperature=temp)

        if response and len(response) > 20:
            results.append({"input": prompt, "output": response})
            print(f"OK ({len(response)} chars)")
        else:
            errors += 1
            print("FAIL (empty or too short)")

        time.sleep(0.8)

    # Save
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    random.shuffle(results)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Done! Generated {len(results)} Xavier-style conversation pairs")
    print(f"Errors: {errors}")
    print(f"Saved to: {OUTPUT}")
    print(f"{'=' * 60}")

    # Quick stats
    avg_in = sum(len(r["input"]) for r in results) / len(results)
    avg_out = sum(len(r["output"]) for r in results) / len(results)
    print(f"\nStats:")
    print(f"  Avg input length:  {avg_in:.0f} chars")
    print(f"  Avg output length: {avg_out:.0f} chars")
    print(f"  File size:         {OUTPUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
