#!/usr/bin/env python3
"""Generate synthetic Talker training data using KatetoTalker (Bonsai 8B).

Produces 200-500 user→assistant conversation pairs in Gabriel's rioplatense
Spanish style. Uses the existing KatetoTalker model via llama.cpp API.

Output: JSON lines at data/synthetic/talker_data.json
  Format: [{"input": "...", "output": "..."}, ...]
"""

import json
import random
import sys
import time
from pathlib import Path

import requests

API_URL = "http://localhost:11434/v1/chat/completions"
MODEL = "KatetoTalker"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "talker_data.json"

SYSTEM_PROMPT = (
    "Sos Kateto, compañera de programación. Respondé de forma directa, "
    "rioplatense, sincera, como si hablaras con Gabriel. Usá un tono "
    "casual, sin vueltas. No uses markdown ni emojis. "
    "Si te pide una opinion, dala honesta aunque sea controversial. "
    "Si te pide ayuda técnica, respondé clara y concisa."
)

# Seed prompts derived from blog topics, CV, and conversation themes
SEED_TOPICS = [
    # Technical Q&A
    "Por que decis que Android no es FOSS de verdad?",
    "Que opinion tenes de Stack Overflow hoy en dia?",
    "Como harías un backup automatizado de 3 capas?",
    "Que lenguaje recomendas para un proyecto de sistema operativo?",
    "Vale la pena aprender Rust hoy?",
    "Que framework frontend me recomendas para 2026?",
    "Como configurarias Traefik con múltiples servicios?",
    "Que opinas de usar Docker para desarrollo local?",
    "Como manejarías secretos en un proyecto open source?",
    "Que es mejor, SQLite o PostgreSQL para un proyecto chico?",
    "Cuando usarías una base de datos NoSQL?",
    "Que opinion tenes de TypeScript?",
    "Como harías un screen sharing multiplataforma?",
    "Que tan importante es el diseño de APIs REST?",
    "Como implementarías autenticación en una API?",
    "Que es el patrón saga en microservicios?",
    "Vale la pena usar gRPC en vez de REST?",
    "Como optimizarías el rendimiento de una web app?",
    "Que herramientas de CI/CD recomendas?",
    "Como harías un deploy con Cloudflare Workers?",

    # Casual chat / life
    "Che, que tal tu dia?",
    "Como va todo con los proyectos?",
    "Que hiciste el finde?",
    "Estoy re quemado con el laburo.",
    "Que leiste ultimamente?",
    "Viste alguna serie buena?",
    "Como te llevas con la gente de tu equipo?",
    "Que musica escuchas mientras codificas?",
    "Te pasa que a veces no podes dormir pensando en un bug?",
    "Que opinas del home server que quiero armar?",

    # Opinions
    "Que opinas del vibecoding?",
    "Cual es tu postura sobre la IA en la educación?",
    "Que pensas de la moderación en comunidades online?",
    "Que preferis, Android stock o una custom ROM?",
    "Windows o Linux para desarrollo?",
    "Vale la pena el open source o es una utopia?",
    "Que opinion tenes de las startups que meten IA en todo?",
    "Que pensas del bloatware en los celulares?",
    "Cual es el peor software que usaste?",
    "Que te parece Notion comparado con otras herramientas?",
    "Como ves el futuro de las PWAs?",
    "Que pensas del SSD RAID con discos de distinta velocidad?",

    # Explanations
    "Explicame como funciona el bootloader de Windows y por que es tan nefasto.",
    "Por que decis que la metadata de Windows es problematica?",
    "Como funciona Traefik como reverse proxy?",
    "Explicame la diferencia entre GPT y MBR.",
    "Como funciona un kernel de SO a grandes rasgos?",
    "Que es un page fault y como afecta rendimiento?",
    "Explicame como funciona un recolector de basura.",
    "Como funciona el sistema de archivos ext4?",
    "Que es un memory leak y como debuggearlo?",
    "Explicame el modelo OSI en criollo.",

    # Tech troubleshooting
    "No me anda el VPN, que puede ser?",
    "Docker compose me tira error de red, ayuda.",
    "El kernel panic despues de actualizar, que hago?",
    "Se me lleno el /var/log, puedo borrar algo?",
    "La GPU no me da video despues de un golpe, que pruebo?",
    "No me arranca el servidor de Minecraft, que reviso?",
    "La temperatura de la CPU llega a 100 grados, es grave?",
    "Tengo 8GB de RAM menos porque se me murio un stick, me afecta mucho?",
    "El backup no se restaura correctamente, que reviso?",
    "Me hackearon el server, por donde empiezo?",

    # Workflow / productivity
    "Como organizas tu dia de laburo?",
    "Que metologia usas para priorizar tareas?",
    "Como evitas la procrastinacion?",
    "Que herramientas usas para tomar notas?",
    "Como haces code review?",
    "Que estrategia usas para estimar tiempos?",
    "Como documentas tus proyectos?",
    "Que haces cuando te sentas a codificar y no sabes por donde arrancar?",
    "Como manejas el estres con fechas de entrega?",
    "Vale la pena hacer planning semanal?",

    # Deeper / philosophical tech
    "La ingeniería de software es una ingeniería real?",
    "Por que los proyectos de software fracasan tan seguido?",
    "Que es mejor, un codigo perfecto o un codigo que funciona?",
    "Deuda técnica: la pagas hoy o la dejas para despues?",
    "Se puede ser un buen programador sin saber algoritmos?",
    "Que hace a un senior developer?",
    "Son los microservicios siempre la respuesta?",
    "El developer promedio esta sobrevalorado?",
    "Por que hay tantos frameworks y tan poca estandarizacion?",
    "Testing: hasta donde llega el punto optimo?",

    # From CV / personal projects
    "Que aprendiste haciendo A2C, tu lenguaje de programacion?",
    "Gabinator fue dificil de hacer multiplataforma?",
    "Como fue participar en las olimpiadas INET?",
    "Que te llevo a crear KATETO?",
    "Como haces para mantener 30+ repos en GitHub?",
    "Que fue lo mas dificil del proyecto Bombay VGA?",
    "BackShell fue solo por investigacion o lo usaste?",
    "Como ves a futuro ArcTeto?",
    "Que proyecto te dio mas orgullo?",
    "Cual fue tu mayor fracaso tecnico?",

    # Rioplatense flavor
    "Che, todo bien?",
    "Viste lo que paso con X/Twitter?",
    "Que opinas de los que usan WordPress para todo?",
    "Como ves el tema de los aranceles a software importado?",
    "Te copa el desarrollo de videojuegos?",
    "Que framework de CSS te gusta mas?",
    "Tenes mascotas?",
    "Que haces cuando no codeas?",
    "Cual es tu opinión de la inteligencia artificial local vs cloud?",
    "Te parece que los devs jr dependen mucho de la IA?",
]


def generate_response(prompt: str, temperature: float = 0.7) -> str | None:
    """Call llama.cpp API and return the assistant response."""
    try:
        resp = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": 256,
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


def generate_variations(prompt: str, n: int = 3) -> list[str]:
    """Generate multiple response variations for the same prompt."""
    responses = []
    temperatures = [0.5, 0.7, 0.9]
    for i in range(n):
        temp = temperatures[i % len(temperatures)]
        text = generate_response(prompt, temperature=temp)
        if text and len(text) > 10:
            responses.append(text)
    return responses


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
    print("Talker Synthetic Data Generator")
    print("=" * 60)

    # Check API
    if not check_model_available():
        print(f"[FATAL] Model '{MODEL}' not available or API not reachable.", file=sys.stderr)
        print(f"  Make sure llama.cpp is running with: {API_URL}", file=sys.stderr)
        sys.exit(1)
    print(f"\n[OK] {MODEL} model available via llama.cpp API\n")

    random.shuffle(SEED_TOPICS)
    results = []
    errors = 0
    target = random.randint(300, 500)

    print(f"Target: {target} conversation pairs\n")

    for i, topic in enumerate(SEED_TOPICS):
        print(f"[{i+1}/{len(SEED_TOPICS)}] Generating: {topic[:50]}...", end=" ")

        # Generate response for this seed topic
        response = generate_response(topic, temperature=0.7)
        if response and len(response) > 10:
            results.append({"input": topic, "output": response})
            print(f"OK ({len(response)} chars)")
        else:
            errors += 1
            print("FAIL (empty or too short)")
            continue

        # For some topics, generate variations with different temperatures
        if i % 3 == 0 and len(results) < target:
            for j, variant in enumerate(generate_variations(topic, n=2)):
                question = (f"Contame mas sobre eso."
                            if random.random() > 0.5
                            else f"Segui con el tema, me interesa.")
                results.append({"input": f"{topic} - {question}", "output": variant})
                print(f"  → variation {j+1}: OK ({len(variant)} chars)")

        time.sleep(0.8)  # Rate limit

        # Progress check
        if len(results) >= target:
            print(f"\nReached target of {target} examples, stopping early.")
            break

    # Save
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    random.shuffle(results)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Done! Generated {len(results)} conversation pairs")
    print(f"Errors: {errors}")
    print(f"Saved to: {OUTPUT}")
    print(f"{'=' * 60}")

    # Quick stats
    avg_input_len = sum(len(r["input"]) for r in results) / len(results)
    avg_output_len = sum(len(r["output"]) for r in results) / len(results)
    print(f"\nStats:")
    print(f"  Avg input length:  {avg_input_len:.0f} chars")
    print(f"  Avg output length: {avg_output_len:.0f} chars")
    print(f"  File size:         {OUTPUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
