#!/usr/bin/env python3
"""Generate synthetic classifier training data using KatetoTalker (Bonsai 8B).

Produces 500+ balanced talk/think classification edge cases. Uses patterns
from the existing coarse_grained.csv and generates new examples covering:
- Ambiguous cases (could be talk or think)
- Messages with and without agent name variants
- Rioplatense Spanish variations
- Technical vs casual topics

Output: CSV at data/synthetic/classifier_data.csv
  Format: text,label  (matching coarse_grained.csv format)
"""

import csv
import json
import random
import sys
import time
from pathlib import Path

import requests

API_URL = "http://localhost:11434/v1/chat/completions"
MODEL = "KatetoTalker"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "classifier_data.csv"

SYSTEM_TALK = (
    "Sos un asistente que genera ejemplos de conversacion. "
    "Genera UNA SOLA linea de dialogo. "
    "Debe ser una pregunta o pedido DIRIGIDO a un asistente llamado Kateto. "
    "Usa variantes como: Kateto, Cateto, Teto, Kasane Teto. "
    "Responde SOLO con el texto del dialogo, nada mas. "
    "En español rioplatense, tono natural."
)

SYSTEM_THINK = (
    "Sos un asistente que genera ejemplos de pensamientos en voz alta. "
    "Genera UNA SOLA linea de texto. "
    "Debe ser una reflexion, observacion o comentario interno, "
    "NO dirigido a ningun asistente. "
    "Temas: tecnologia, programacion, vida cotidiana, productividad, frustraciones. "
    "Responde SOLO con el texto, nada mas. "
    "En español rioplatense, tono natural."
)

# Pattern templates for talk examples
TALK_PATTERNS = [
    # Direct questions to agent
    "{name}, {question}",
    "{name}, {action}",
    "{name}, {request}",
    "{greeting}, {name}",
    # Name variants
    "{name}, {question}",
    "{name}, {action}",
    # No-name implicit requests
    "{request_no_name}",
    "{question_no_name}",
]

TALK_NAMES = ["Kateto", "Cateto", "Teto", "Kasane Teto"]

TALK_QUESTIONS = [
    "que framework me recomendas?",
    "como funciona este modulo?",
    "que significa este mensaje?",
    "cual es la mejor practica aca?",
    "que deberia hacer primero?",
    "como lo harias vos?",
    "que enfoque me sugieres?",
    "cual es el siguiente paso?",
    "que me falta para terminar?",
    "donde esta el error?",
    "por que falla el test?",
    "como abordo este problema?",
    "que tan complejo es esto?",
    "que me recomendas para mejorar?",
    "cuanto tiempo calculas que lleva?",
    "que version estamos usando?",
    "cuando termina el sprint?",
    "que es lo mas critico ahora?",
    "cual seria tu consejo?",
    "que ventajas tiene cada opcion?",
]

TALK_ACTIONS = [
    "analizame este codigo.",
    "revisame la logica del algoritmo.",
    "decime si hay errores aca.",
    "explicame la diferencia entre ambos.",
    "resumime la documentacion.",
    "armame un esquema del proyecto.",
    "dame ideas para mejorar el UX.",
    "preparame un informe detallado.",
    "evaluame el rendimiento de esto.",
    "compara las dos opciones.",
    "priorizame estas tareas.",
    "creame una analogia explicativa.",
    "inventame un ejemplo practico.",
    "haceme un analisis rapido.",
    "pasame las conclusiones principales.",
    "organizame las tareas por prioridad.",
    "decime el paso a paso.",
    "explicame con un ejemplo.",
    "sintetizame los puntos clave.",
    "actualizame el estado del proyecto.",
]

TALK_REQUESTS = [
    "necesito tu opinion sobre el diseño.",
    "ayudame a planificar el dia.",
    "me das una mano con esto?",
    "orientame con este diseño.",
    "evaluame esta solucion.",
    "dame lo mas importante de esto.",
    "pasa esto a espanol.",
    "generame un resumen ejecutivo.",
    "escribime un dialogo corto.",
    "armame un cronograma.",
    "resumime lo que hablamos ayer.",
    "recordame que tengo pendiente.",
    "dame ideas para el nombre del proyecto.",
    "explicame el concepto de base.",
    "crea un plan de accion.",
    "decime que hago ahora.",
    "explicame como funciona esto.",
    "hace una lista de tareas pendientes.",
    "condensame toda esta info.",
    "actualiza la documentacion.",
]

TALK_GREETINGS = [
    "che",
    "hola",
    "buenas tardes",
    "hey",
    "buenas",
    "que onda",
]

# No-name variants (implicitly directed at agent)
TALK_QUESTIONS_NO_NAME = [
    "cual es la mejor opcion?",
    "como se configura esto?",
    "que significa este termino?",
    "A o B?",
    "como se usa esta herramienta?",
    "que tarea hago ahora?",
    "cuanto tiempo me queda para terminar?",
    "que versión estamos usando?",
    "que es lo mas urgente?",
]

TALK_REQUESTS_NO_NAME = [
    "dame un resumen del proyecto.",
    "explicame en pocas palabras.",
    "inventame una historia breve.",
    "escribime un poema corto.",
    "escribime un slogan catchy.",
    "escribime un resumen de esto.",
    "genera un resumen ejecutivo.",
    "pasame las conclusiones principales.",
    "escribi un blog sobre lo que dije.",
    "dame ideas para mejorar el UX.",
]

# Pattern templates for think examples
THINK_PATTERNS = [
    # Technical observations
    "Se actualizo el {tech_thing}.",
    "{tech_observation}",
    "No entiendo {tech_frustration}.",
    "Hay que {tech_action}.",
    
    # Casual observations
    "{person} {trait}.",
    "Che {person}, {question_to_person}",
    "Hermano, {question_to_hermano}",
    "Mama, {question_to_mama}",

    # Self-reflection
    "Me estoy {reflection}.",
    "Tengo que {self_action}.",
    "Sera que {doubt}?",
    "Quizas deberia {self_suggestion}.",

    # Work-related
    "{work_observation}",
    "{need_statement}",
    "No olvidar {reminder}.",
    "{sprint_action}"
]

THINK_TECH_THINGS = [
    "el framework",
    "el kernel",
    "el servidor",
    "la libreria",
    "el compilador",
    "la base de datos",
    "el sistema",
    "el paquete",
    "la dependencia",
]

THINK_TECH_OBSERVATIONS = [
    "El build paso todos los tests.",
    "Se cayo el server de staging.",
    "Hay una vulnerabilidad en la dependencia.",
    "El rendimiento empeoro con la ultima version.",
    "La memoria se esta acumulando.",
    "Los logs muestran errores raros.",
    "El deploy a produccion fallo.",
    "La cache se corrompio de nuevo.",
    "El profile reporta cuello de botella en la DB.",
    "Se lleno el disco de /var/log.",
    "La red esta inestable hoy.",
    "El CPU esta al 100% sin razon aparente.",
    "El nuevo release rompio compatibilidad.",
    "Las pruebas de carga no pasan.",
    "El certificado SSL expiro.",
    "La configuracion de CI/CD esta fallando.",
    "El monitoreo muestra latencia alta.",
]

THINK_TECH_FRUSTRATIONS = [
    "por que no compila esto.",
    "por que se rompe todo al mergear.",
    "por que el legado es tan nefasto.",
    "por que nadie documenta nada.",
    "por que hay 10 formas de hacer lo mismo.",
    "por que el codigo ajeno es tan ilegible.",
    "por que siempre explota en produccion.",
    "por que no hay tests para esto.",
    "por que el linter no me deja en paz.",
    "por que las dependencias nunca matchean.",
]

THINK_TECH_ACTIONS = [
    "refactorizar el modulo de auth.",
    "optimizar las queries lentas.",
    "actualizar las dependencias.",
    "revisar los permisos del bucket.",
    "mejorar la covertura de tests.",
    "automatizar los backups.",
    "revisar los logs del servidor.",
    "configurar el CI/CD correctamente.",
    "documentar los endpoints de la API.",
    "revisar la configuracion de seguridad.",
]

THINK_PERSONS = [
    "Juan", "Maria", "Carlos", "Lucia", "Diego", "Ana", "Pedro", "Sofia",
    "Marcos", "Valentina", "Florencia", "Matias", "Paula", "Tomas", "Camila",
    "Gustavo", "Fernando", "Isabella", "Claudia", "Santiago", "Marta", "Roberto",
]

THINK_TRAITS = [
    "siempre rompe el build.",
    "nunca responde los mensajes.",
    "es muy buena explicando conceptos.",
    "siempre entrega antes del deadline.",
    "tiene las mejores ideas.",
    "nunca hace code review.",
    "es muy paciente con los juniors.",
    "siempre quiere refactorizar todo.",
    "es muy eficiente con su tiempo.",
    "siempre complica las soluciones simples.",
    "es muy ordenado con el codigo.",
    "nunca actualiza la documentacion.",
]

THINK_QUESTIONS_TO_PERSON = [
    "como va el trabajo?",
    "viste lo que paso ayer?",
    "que plan para el viernes?",
    "que me decis del partido?",
    "como va tu proyecto personal?",
    "probaste la app nueva?",
    "como te fue con el deploy?",
    "como va la mudanza?",
    "que me recomendas para ver?",
    "cuando venis a visitarme?",
]

THINK_QUESTIONS_TO_HERMANO = [
    "como va todo?",
    "me prestas el cargador?",
    "nos vemos en la cancha?",
    "me pasas la playlist?",
    "como va la huerta?",
    "me ayudarias con el jardin?",
]

THINK_QUESTIONS_TO_MAMA = [
    "como esta el gato?",
    "me pasas la receta del guiso?",
    "me haces las empanadas?",
    "necesito un consejo.",
    "como va todo por casa?",
    "como esta la abuela?",
]

THINK_REFLECTIONS = [
    "sintiendo mas seguro con el codigo.",
    "acostumbrando al ritmo de trabajo.",
    "enfocando en lo importante.",
    "sintiendo que no avanzo lo suficiente.",
    "superando cada dia.",
    "perdiendo en este proyecto.",
    "sintiendo que esto no es para mi.",
    "recuperando la motivacion.",
    "aprendiendo un monton.",
    "sintiendo el peso de las decisiones.",
]

THINK_SELF_ACTIONS = [
    "dejar de procrastinar.",
    "leer la documentacion oficial.",
    "mantener la curiosidad viva.",
    "confiar en mi criterio.",
    "ver el bosque completo.",
    "hacer una pausa y pensar.",
    "pedir ayuda cuando la necesite.",
    "dejar de compararme con otros.",
    "escribir lo que aprendi hoy.",
    "practicar mas seguido.",
]

THINK_DOUBTS = [
    "esto va a funcionar en produccion?",
    "necesito mas memoria para el build?",
    "estoy usando la libreria correcta?",
    "me estoy equivocando de enfoque?",
    "el cliente va a entender lo que hicimos?",
    "esto escala bien?",
    "deberia reescribir todo desde cero?",
    "estoy sobreingenierizando esto?",
]

THINK_SUGGESTIONS = [
    "automatizar los backups.",
    "consultar a alguien con mas experiencia.",
    "usar otro lenguaje para esto.",
    "cambiar de base de datos.",
    "empezar de nuevo con otro enfoque.",
    "hacer una pausa y pensar.",
    "migrar a microservicios.",
    "usar una herramienta diferente.",
    "escribir tests primero.",
    "separar el monolito en modulos.",
]

THINK_WORK_OBSERVATIONS = [
    "El cronograma esta muy ajustado.",
    "Las estimaciones fueron demasiado optimistas.",
    "El equipo esta quemado con este sprint.",
    "Falta comunicacion entre los equipos.",
    "Los requerimientos cambiaron de nuevo.",
    "El cliente no sabe lo que quiere.",
    "La prioridad cambio tres veces hoy.",
    "Nadie se hizo cargo del bug critico.",
    "La documentacion esta desactualizada.",
    "La reunion podria ser un email.",
]

THINK_NEED_STATEMENTS = [
    "Necesito que alguien revise el pipeline de CI.",
    "Necesito que alguien haga el backup urgente.",
    "Necesito que alguien revise los logs de error.",
    "Necesito que alguien actualice la doc tecnica.",
    "Necesito que alguien revise la seguridad.",
    "Necesito que alguien revise mi codigo.",
    "Necesito que alguien haga el testing.",
    "Necesito que alguien revise la API publica.",
    "Necesito que alguien me explique la arquitectura.",
    "Necesito que alguien ayude con la migracion.",
]

THINK_REMINDERS = [
    "hacer el backup del dia.",
    "actualizar el changelog.",
    "enviar el reporte semanal.",
    "revisar los PRs pendientes.",
    "la reunion de las tres.",
    "confirmar con el cliente.",
    "actualizar las dependencias.",
    "committear los cambios locales.",
    "revisar los alerts de monitoreo.",
    "pagar el hosting del server.",
]

THINK_SPRINT_ACTIONS = [
    "Podemos optimizar esta query.",
    "Podemos automatizar este proceso.",
    "Podemos mejorar los tests.",
    "Podemos hacer una reunion rapida.",
    "Podemos mejorar la UX del dashboard.",
    "Necesitamos documentar los endpoints.",
    "Necesitamos hablar del deadline.",
    "Necesitamos mas covertura de tests.",
    "Coordinemos la demo del viernes.",
    "Tengamos la retrospective la semana que viene.",
]

# Ambiguous cases that could go either way
AMBIGUOUS_PAIRS = [
    ("Me ayudarias con esta query?", "talk"),
    ("Alguien me ayuda con esta query?", "think"),
    ("Kateto, explicale a mi cliente que onda.", "talk"),
    ("Hay que explicarle al cliente que onda.", "think"),
    ("Decime si esto esta bien.", "talk"),
    ("Alguien me dice si esto esta bien?", "think"),
    ("Kateto, revisa los logs del servidor.", "talk"),
    ("Hay que revisar los logs del servidor.", "think"),
    ("Che, y si probamos con otra libreria?", "think"),
    ("Teto, que tal si probamos con otra libreria?", "talk"),
    ("Mejor hacerlo de otra forma.", "think"),
    ("Teto, mejor hacerlo de otra forma.", "talk"),
    ("Esto no funciona.", "think"),
    ("Kateto, esto no funciona.", "talk"),
    ("Necesito ayuda con el deploy.", "think"),
    ("Kateto, necesito ayuda con el deploy.", "talk"),
    ("Como hago para optimizar esto?", "think"),
    ("Teto, como hago para optimizar esto?", "talk"),
    ("Alguien sabe que paso con el server?", "think"),
    ("Teto, que paso con el server?", "talk"),
    ("No entiendo por que falla.", "think"),
    ("Cateto, no entiendo por que falla.", "talk"),
    ("Habria que refactorizar esto.", "think"),
    ("Kateto, refactorizame esto.", "talk"),
    ("Donde esta el error?", "think"),
    ("Teto, donde esta el error?", "talk"),
    ("Que tan urgente es esto?", "think"),
    ("Kateto, que tan urgente es esto?", "talk"),
    ("Puedo hacerlo de otra manera?", "think"),
    ("Teto, puedo hacerlo de otra manera?", "talk"),
    ("La API esta dando error.", "think"),
    ("Cateto, la API esta dando error.", "talk"),
    ("El test no pasa, que raro.", "think"),
    ("Teto, el test no pasa, revisalo.", "talk"),
    ("Se me ocurre que podemos usar Redis.", "think"),
    ("Kateto, se te ocurre algo mejor que Redis?", "talk"),
]

# Variations focused on edge cases
EDGE_CASES = [
    # No explicit name but directed
    ("Decime que hago ahora.", "talk"),
    ("Explicame como funciona esto.", "talk"),
    ("Dame un resumen del proyecto.", "talk"),
    ("Inventame un ejemplo.", "talk"),
    ("Cual es la mejor opcion?", "talk"),
    ("Analizame este codigo.", "talk"),
    ("Resumime los cambios.", "talk"),
    ("Evaluame esta solucion.", "talk"),
    ("Armame un esquema.", "talk"),
    ("Priorizame las tareas.", "talk"),
    
    # With name but reflective
    ("Kateto, creo que me equivoque de enfoque.", "talk"),
    ("Teto, estoy trabado con este bug.", "talk"),
    
    # Rioplatense slang
    ("Che, ni idea de como resolver esto.", "think"),
    ("Re complicado todo.", "think"),
    ("Estoy re quemado con este proyecto.", "think"),
    ("Che, que paja tener que debuggear esto.", "think"),
    ("Ni en pedo termino esto hoy.", "think"),
    ("Esto es terrible chino basico.", "think"),
    ("Que cagada, se borro todo.", "think"),
    ("Bueno, fue, lo dejamos para maniana.", "think"),
    ("Dale, mandate con esa solucion.", "think"),
    ("Para mi que esto anda mejor asi.", "think"),
    ("Che, ni cabida, funciono al primer intento.", "think"),
    ("La concha de la lora, se cayo todo.", "think"),
    ("Que garrón la lenta del IDE.", "think"),
    
    # Technical mix
    ("El garbage collector me esta volviendo loco.", "think"),
    ("Esta funcion tiene mas side effects que beneficios.", "think"),
    ("Kateto, el garbage collector me esta volviendo loco.", "talk"),
    ("La recursion me rompe la cabeza.", "think"),
    ("Teto, la recursion me rompe la cabeza.", "talk"),
    ("No se si esto es un bug o una feature.", "think"),
    ("Che, esto es un bug o una feature?", "think"),
    ("Cateto, esto es un bug o una feature?", "talk"),
    ("Si funciona no lo toques.", "think"),
    ("Teto, si funciona no lo toques.", "talk"),
    
    # Mixed intent
    ("Tengo mil cosas por hacer y no se por donde arrancar.", "think"),
    ("Teto, tengo mil cosas, priorizamelas.", "talk"),
    ("No me alcanza el tiempo para nada.", "think"),
    ("No se si esto vale la pena.", "think"),
    ("Kateto, vale la pena seguir con esto?", "talk"),
    ("Esto tiene buena pinta.", "think"),
    ("Teto, esto tiene buena pinta, no?", "talk"),
    ("Que quilombo el codigo este.", "think"),
    ("Cateto, que quilombo este codigo, ayudame.", "talk"),
    ("Me fundi, no entiendo nada.", "think"),
    ("Teto, no entiendo nada, explicalo de nuevo.", "talk"),
    
    # Agent name variations
    ("Kateto, necesito una mano.", "talk"),
    ("Cateto, necesito una mano.", "talk"),
    ("Teto, necesito una mano.", "talk"),
    ("Kasane Teto, necesito una mano.", "talk"),
    ("Kato, necesito una mano.", "talk"),
    ("Cato, dame una mano.", "talk"),
    
    # Context: someone-talking-to-someone vs self-talk
    ("Papa, me ayudarias a armar el mueble?", "think"),
    ("Mama, me cuidas al perro?", "think"),
    ("Hermana, como te va en la facu?", "think"),
    ("Che Juan, como va la mudanza?", "think"),
    ("Claudia, vamos a tomar un cafe?", "think"),
    ("Pedro, ayudame con la configuracion del server.", "think"),
    ("Diego, revisame el PR.", "think"),
    ("Florencia, pasame las metricas.", "think"),
    ("Gustavo, necesito que revises los permisos.", "think"),
    ("Santiago, pasame el diagrama de flujo.", "think"),
]


def generate_talk_example() -> tuple[str, str]:
    """Generate a talk example (directed at assistant)."""
    template = random.choice(TALK_PATTERNS)
    name = random.choice(TALK_NAMES)
    
    format_kwargs = {}
    if "{name}" in template:
        format_kwargs["name"] = name
    if "{question}" in template:
        format_kwargs["question"] = random.choice(TALK_QUESTIONS)
    if "{action}" in template:
        format_kwargs["action"] = random.choice(TALK_ACTIONS)
    if "{request}" in template:
        format_kwargs["request"] = random.choice(TALK_REQUESTS)
    if "{greeting}" in template:
        format_kwargs["greeting"] = random.choice(TALK_GREETINGS)
    if "{request_no_name}" in template:
        format_kwargs["request_no_name"] = random.choice(TALK_REQUESTS_NO_NAME)
    if "{question_no_name}" in template:
        format_kwargs["question_no_name"] = random.choice(TALK_QUESTIONS_NO_NAME)
    
    text = template.format(**format_kwargs)
    # Capitalize first letter
    text = text[0].upper() + text[1:] if text else text
    return text, "talk"


def generate_think_example() -> tuple[str, str]:
    """Generate a think example (self-reflection, observation, not directed)."""
    template = random.choice(THINK_PATTERNS)
    
    format_kwargs = {}
    if "{tech_thing}" in template:
        format_kwargs["tech_thing"] = random.choice(THINK_TECH_THINGS)
    if "{tech_observation}" in template:
        format_kwargs["tech_observation"] = random.choice(THINK_TECH_OBSERVATIONS)
    if "{tech_frustration}" in template:
        format_kwargs["tech_frustration"] = random.choice(THINK_TECH_FRUSTRATIONS)
    if "{tech_action}" in template:
        format_kwargs["tech_action"] = random.choice(THINK_TECH_ACTIONS)
    if "{person}" in template:
        format_kwargs["person"] = random.choice(THINK_PERSONS)
    if "{trait}" in template:
        format_kwargs["trait"] = random.choice(THINK_TRAITS)
    if "{question_to_person}" in template:
        format_kwargs["question_to_person"] = random.choice(THINK_QUESTIONS_TO_PERSON)
    if "{question_to_hermano}" in template:
        format_kwargs["question_to_hermano"] = random.choice(THINK_QUESTIONS_TO_HERMANO)
    if "{question_to_mama}" in template:
        format_kwargs["question_to_mama"] = random.choice(THINK_QUESTIONS_TO_MAMA)
    if "{reflection}" in template:
        format_kwargs["reflection"] = random.choice(THINK_REFLECTIONS)
    if "{self_action}" in template:
        format_kwargs["self_action"] = random.choice(THINK_SELF_ACTIONS)
    if "{doubt}" in template:
        format_kwargs["doubt"] = random.choice(THINK_DOUBTS)
    if "{self_suggestion}" in template:
        format_kwargs["self_suggestion"] = random.choice(THINK_SUGGESTIONS)
    if "{work_observation}" in template:
        format_kwargs["work_observation"] = random.choice(THINK_WORK_OBSERVATIONS)
    if "{need_statement}" in template:
        format_kwargs["need_statement"] = random.choice(THINK_NEED_STATEMENTS)
    if "{reminder}" in template:
        format_kwargs["reminder"] = random.choice(THINK_REMINDERS)
    if "{sprint_action}" in template:
        format_kwargs["sprint_action"] = random.choice(THINK_SPRINT_ACTIONS)
    
    text = template.format(**format_kwargs)
    text = text[0].upper() + text[1:] if text else text
    return text, "think"


def generate_via_api(examples_needed: int) -> list[tuple[str, str]]:
    """Use the LLM to generate diverse examples for talk/think classification."""
    results = []
    half = examples_needed // 2
    
    # Generate talk examples via API
    print(f"\nGenerating {half} talk examples via API...")
    for i in range(half):
        try:
            resp = requests.post(
                API_URL,
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_TALK},
                        {"role": "user",
                         "content": (f"Genera un ejemplo de dialogo donde alguien "
                                     f"le pide algo a Kateto (o Cateto/Teto/Kasane Teto). "
                                     f"Tema: {random.choice(TALK_QUESTIONS + TALK_ACTIONS + TALK_REQUESTS)[:30]}")},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 64,
                    "top_p": 0.95,
                },
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
            if text and len(text) > 5 and len(text) < 200:
                results.append((text, "talk"))
                print(f"  [{i+1}/{half}] Talk: {text[:50]}...")
        except Exception as e:
            print(f"  [ERROR] Talk gen {i}: {e}", file=sys.stderr)
        time.sleep(0.3)
    
    # Generate think examples via API
    print(f"\nGenerating {half} think examples via API...")
    for i in range(half):
        try:
            resp = requests.post(
                API_URL,
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_THINK},
                        {"role": "user",
                         "content": (f"Genera un pensamiento en voz alta, una reflexion "
                                     f"o comentario interno sobre: "
                                     f"{random.choice(['programacion', 'un bug', 'productividad', 'una frustracion tecnica', 'la vida', 'el trabajo en equipo', 'un proyecto'])}")},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 64,
                    "top_p": 0.95,
                },
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
            if text and len(text) > 5 and len(text) < 200:
                results.append((text, "think"))
                print(f"  [{i+1}/{half}] Think: {text[:50]}...")
        except Exception as e:
            print(f"  [ERROR] Think gen {i}: {e}", file=sys.stderr)
        time.sleep(0.3)
    
    return results


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
    print("Classifier Synthetic Data Generator")
    print("=" * 60)

    if not check_model_available():
        print(f"[FATAL] Model '{MODEL}' not available or API not reachable.", file=sys.stderr)
        print(f"  Make sure llama.cpp is running with: {API_URL}", file=sys.stderr)
        sys.exit(1)
    print(f"\n[OK] {MODEL} model available via llama.cpp API\n")

    results: list[tuple[str, str]] = []
    target = random.randint(500, 700)
    
    print(f"Target: {target} examples (balanced talk/think)\n")

    # 1. Generate from predefined templates (fast, guaranteed quality)
    template_target = target // 2
    print(f"[Phase 1] Generating {template_target} examples from templates...")
    for i in range(template_target // 2):
        results.append(generate_talk_example())
        results.append(generate_think_example())

    # 2. Add ambiguous edge cases
    print(f"\n[Phase 2] Adding {len(AMBIGUOUS_PAIRS)} ambiguous edge cases...")
    results.extend(AMBIGUOUS_PAIRS)

    # 3. Add more edge case variations
    print(f"[Phase 3] Adding {len(EDGE_CASES)} edge case variations...")
    for text, label in EDGE_CASES:
        results.append((text, label))

    # 4. Generate additional diverse examples via API
    api_needed = target - len(results)
    if api_needed > 100:
        api_results = generate_via_api(api_needed)
        results.extend(api_results)

    # Shuffle and balance
    random.shuffle(results)
    
    # Ensure no more than 55/45 split (balance)
    talk_count = sum(1 for _, l in results if l == "talk")
    think_count = sum(1 for _, l in results if l == "think")
    
    # If too imbalanced, trim the majority class
    if talk_count > think_count * 1.3:
        talk_items = [(t, l) for t, l in results if l == "talk"]
        think_items = [(t, l) for t, l in results if l == "think"]
        keep_talk = int(think_count * 1.2)
        random.shuffle(talk_items)
        results = talk_items[:keep_talk] + think_items
    elif think_count > talk_count * 1.3:
        talk_items = [(t, l) for t, l in results if l == "talk"]
        think_items = [(t, l) for t, l in results if l == "think"]
        keep_think = int(talk_count * 1.2)
        random.shuffle(think_items)
        results = talk_items + think_items[:keep_think]

    random.shuffle(results)

    # Save CSV
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["text", "label"])
        for text, label in results:
            writer.writerow([text, label])

    # Stats
    final_talk = sum(1 for _, l in results if l == "talk")
    final_think = sum(1 for _, l in results if l == "think")

    print(f"\n{'=' * 60}")
    print(f"Done! Generated {len(results)} classification examples")
    print(f"  Talk:  {final_talk} ({final_talk/len(results)*100:.0f}%)")
    print(f"  Think: {final_think} ({final_think/len(results)*100:.0f}%)")
    print(f"Saved to: {OUTPUT}")
    print(f"{'=' * 60}")

    # Sample output
    print(f"\nSample rows (first 5):")
    with open(OUTPUT, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 6:
                break
            if i == 0:
                print(f"  Header: {line.strip()}")
            else:
                print(f"  {line.strip()}")


if __name__ == "__main__":
    main()
