# Reporte: Vigilante del LLM de voz (:8092)

## Archivos creados
1. `scripts/voice-llm-watchdog.py`: Script vigilante en Python stdlib para medir tok/s, evaluar degradación y reiniciar la unit con cooldown.
2. `scripts/systemd/kateto-voice-llm.service`: Copia canónica de la unit agregando `--device Vulkan0` y comentario explicativo de iGPU/dGPU.
3. `scripts/systemd/kateto-voice-llm-watchdog.service`: Unit oneshot de systemd para invocar el vigilante.
4. `scripts/systemd/kateto-voice-llm-watchdog.timer`: Timer de systemd ejecutando el vigilante cada 5 minutos (boot: 3min).
5. `scripts/tests/test_voice_llm_watchdog.py`: Suite de 10 tests unitarios con `unittest` (sin dependencias externas ni red).

## Resultados de pruebas
- Comando: `python3 -m unittest discover -s scripts/tests -v`
- Salida resumida: Ran 10 tests in 0.018s — OK (10/10 tests aprobados exitosamente).

## Criterios no cumplidos
- Ninguno: todos los requerimientos y contratos especificados fueron cumplidos en su totalidad.
