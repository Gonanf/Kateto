---
id: 135
title: "eot_gate con etapa2=ft fallaba fail-open: el hijo moría por falta de transformers y el 1s de timeout no cubría el cold start"
severity: Alta
status: resolved
component: kateto/plugins/system/eot_gate.py
resolved: 2026-11-08
---

## 135. eot_gate con etapa2=ft fallaba fail-open (hijo sin transformers + cold start)

**Severidad:** Alta
**Componente:** `kateto/plugins/system/eot_gate.py`

### Descripción

Con `[plugin.eot_gate] enabled = true` y `etapa2 = "ft"` (la única etapa servible),
el gate reportaba `available = True` pero **toda clasificación devolvía
`failed_open=True`** (`classifier stdout closed`) y el EOT nunca decidía nada.

### Impacto

El gate es lo que decide `wait | suppress | respond` sobre la transcripción. Fail-open
silencioso = siempre `respond`: el sistema se comporta como si el gate no existiera, y
el único síntoma es un warning en log.

### Causa

Dos causas independientes, ambas tapadas por el fail-open:

1. `clasificador_hibrido.py` importa `transformers`, y el `python3` que el gate usa por
   defecto (el intérprete de Kateto) no lo tiene: el hijo moría en el import
   (`ModuleNotFoundError: No module named 'transformers'`) y `stderr` va a
   `DEVNULL`, así que la causa real nunca aparecía.
2. El child carga el modelo en el arranque: **~5,5 s** medidos hasta la primera respuesta.
   `timeout` por defecto es `1.0 s`, así que la primera clasificación siempre expiraba,
   el gate se reiniciaba y moría tras `MAX_RESTARTS` sin haber clasificado nada.

### Solución aplicada

- `[plugin.eot_gate] python` apunta al venv del repo `kateto-eot2`, que tiene
  `transformers` + `onnxruntime`:
  `/run/media/chaos/secundario/proyectos/kateto-eot2/.venv/bin/python3`.
- `EotClassifierClient.classify_sync()` acepta `timeout=` explícito (sin tocar el
  timeout de turno, que sigue en 1 s).
- `EotGate.initialize()` calienta el hijo una vez al boot
  (`classify_sync("hola", timeout=30.0)` en un thread), así el primer turno real
  clasifica dentro del presupuesto de 1 s.

Verificado: `initialize` 5,2 s (warmup), después `suppress 0.087 s`, `suppress 0.153 s`,
`wait 0.125 s`, todos con `failed_open=False`; `test_eot_gate.py` + `test_eot_partial_hold.py`
17 passed.

### Archivos

`kateto/plugins/system/eot_gate.py`, `~/.config/kateto/config.toml`
