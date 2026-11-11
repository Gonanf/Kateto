---
id: 142
title: "EOT gate sobre los logs reales: wait F1 0.21 (repo hermano declara 0.645) y no_response dispara en 88 de 99 turnos completos"
severity: Alta
status: open
component: kateto/plugins/system/eot_gate.py, scripts/qa/build_eot_eval.py
---

## 142. EOT gate medido sobre datos reales

**Severidad:** Alta
**Componente:** `kateto/plugins/system/eot_gate.py` + el repo hermano `kateto-eot2` (`clasificador_hibrido.py`)

### Descripción

El gate de fin de turno (2 etapas: `wait` y `no_response`) se evaluaba con los F1 del
repo hermano. Medido sobre los `turn_end` reales de este runtime, la etapa 1 cae a
menos de un tercio y la etapa 2 suprime casi todos los turnos completos.

### Evidencia (medida 2026-11-10, CPU, sin GPU)

```
$ uv run python scripts/qa/build_eot_eval.py --hours 720 --score
pares: 118  ({'voice_idle': 99, 'next_transcription': 19})
gate real: wait_f1=0.2105 tp=4 fp=15 fn=15 | no_response en wait1=18 wait0=88
referencia del repo hermano: wait F1 0.6452, no_response F1 0.8412
```

- `wait` F1 **0.2105** contra 0.6452 declarado: 15 falsos positivos (marca "seguí hablando"
  en turnos que el usuario ya había cerrado) y 15 falsos negativos sobre 19 positivos reales.
- `no_response` = true en **88 de 99** turnos completos (`wait0`), y en 18 de 19
  incompletos. O sea: si esta cabeza decide, el runtime se queda mudo en ~9 de cada 10
  turnos que el usuario terminó.
- Etiquetas: `closed_by=voice_idle` → turno completo (`wait=0`); `next_transcription` →
  el usuario siguió hablando (`wait=1`); `interrupt` se descarta (input completo, salida
  truncada). Dataset: `out/eot-eval-2026-11.jsonl`.

### Impacto

Cualquier decisión automática apoyada en este gate hereda el sesgo: respuestas
descartadas o esperas espurias. Es coherente con lo reportado en #135 (fail-open) y
#138/#141 (turnos descartados): esos parches no tocan la calibración de las cabezas.

### Causa

Hipótesis, **no confirmada**: `THR1=0.6842` y la cabeza ridge de etapa 2 fueron elegidos
sobre el test set propio del repo hermano, no sobre los transcript rioplatenses cortos del
runtime. Los `.onnx` y `cabeza_etapa2_ft.npz` no registran su distribución de
calibración, así que el desvío no se puede atribuir todavía a un motivo puntual.

**Posible solución:**

1. Recalibrar `THR2` (y `THR1`) sobre `out/eot-eval-*.jsonl` por barrido de umbral,
   eligiendo por F1 de cada etapa — el mismo set que reporta el bug.
2. Antes de recalibrar, subir el set: 118 pares es menos que el criterio de E1 (≥200)
   y 99/118 vienen de `voice_idle`, así que la clase `wait` está subrepresentada.
3. Guardar la versión nueva de la cabeza junto a `THR` y fecha en el repo hermano,
   para no volver a medir sin línea base.

**Archivos:** `scripts/qa/build_eot_eval.py` (nuevo), `out/eot-eval-2026-11.jsonl` (generado),
`/run/media/chaos/secundario/proyectos/kateto-eot2/{clasificador_hibrido.py,cabeza_etapa2_ft.npz}`
