# Improvement harness — {depto}

> Harness² (arXiv 2610.14224): el harness que rodea al modelo (prompts, skills,
> plugins, memoria, guardrails) se edita **sin tocar los pesos**. Cada edición se
> **propone**, se **prueba** sobre la misma tarea, y se **compone** sólo si el
> contraste la sostiene. Este archivo es la memoria de ese bucle: qué se adoptó,
> qué se descartó y con qué evidencia.

Reglas de higiene (si no las cumple, la lección no entra):

1. Toda lección lleva **evidencia**: ruta a `out/harness-probe/<run>/` o cita del log.
2. Un veredicto por edición: `adoptada` / `descartada` / `pendiente`. Nada de "parece mejor".
3. Sin set congelado no hay adopción de prompts: primero `scripts/qa/` (E1 del plan).
4. Nada de números sin fuente (ni latencia, ni F1, ni "% mejor").

## Ediciones adoptadas

| Fecha | Archivo editado | Qué cambió | Evidencia | Veredicto |
|---|---|---|---|---|
| — | — | — | — | — |

## Descartadas (y por qué)

| Fecha | Archivo | Qué se probó | Por qué se descartó |
|---|---|---|---|
| — | — | — | — |

## Cómo se corre

```bash
# 1) proponer: editar SOUL/skill/prompt en un archivo *-nuevo.* al lado del actual
# 2) probar: misma tarea, dos variantes, salidas guardadas
uv run python scripts/harness_probe.py --task "<la tarea real>" --before SOUL.md --after SOUL-nuevo.md
# 3) componer: si el contraste sostiene, mover la edición y registrar la evidencia
uv run python scripts/harness_probe.py --task "<la tarea real>" --before SOUL.md --after SOUL-nuevo.md --record
```

Rollback de SOUL: `SoulSnapshotStore` (snapshot previo a cada escritura).
