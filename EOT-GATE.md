# EOT-GATE — puerta híbrida de fin de turno (fail-open)

`EotGate` clasifica el texto ya transcripto (wait→QUEUE+hold,
no_response→DISCARD, respond→EXECUTE). Todo error (timeout, proceso
muerto, JSON roto) devuelve RESPOND = el corte `turn_silence_timeout`
de hoy. Nunca lanza al bus, nunca toca audio_input/audio_processor.

## Activar / desactivar

```toml
[plugin.eot_gate]
enabled = true   # false (default) = decide() sync de hoy, sin cambios
```

`EOT_ETAPA2=base|ft` (default base). Requiere el script hermano
`kateto-eot2/clasificador_hibrido.py`; si falta, fail-open.

## Salidas reales (CPU, `/tmp/opencode/eot_real_run.json`)

- `eh... quiero decir que` → wait=true (0.986>thr 0.684), no_resp=true (−0.057>−0.198)
- `mmm` → wait=false (0.629<0.684), no_resp=true (0.774>−0.198)
- `hola, ¿me escuchás?` → wait=false (0.038), no_resp=true (0.650)
- `ajá, seguí` → wait=true (0.754), no_resp=true (0.973)

## Base vs ft (F1 de REPORTE-HIBRIDO.md, latencias medidas aquí)

| variante | F1 reporte | p50 e2e reporte | p50 medido | p95 medido |
|---|---|---|---|---|
| base (a) | 0.8261 @ ~106ms | 2 forwards | 51.3ms | 78.4ms |
| ft (c, elegida) | 0.8412 @ ~44ms | 1 forward | 54.4ms | 57.9ms |

Caveat: la base medida es head-swap de un solo forward (estilo a2,
F1 0.671 en test), NO la (a) real de 2 forwards — comparación honesta
de cabezas a igualdad de cómputo; por eso los p50 salen casi iguales.

## Transcripción provisional

Hold a nivel texto en `TurnGate._eot_pending` (merge con el turno
siguiente, 0 costo whisper extra por diseño). redux-light-engine NO
adoptado (documentado con número: 0).

## Qué NO verifiqué

Runtime live, turnos reales de micrófono, GPU, ni p95 bajo carga
(medición en CPU, máquina no en reposo pleno).
