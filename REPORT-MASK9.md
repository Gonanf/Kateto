# Reporte MASK-9 — Snapshots de Estado RWKV (S_turn_start + S_barge_in)

## 1. Qué se implementó

Se implementó el subsistema de snapshots y rollback de estado para modelos RWKV-7 en el contexto de turnos conversacionales con corrección de ASR y barge-in de audio.

El estado interno de RWKV-7 se trata como un objeto opaco: el módulo no depende de PyTorch, NumPy ni de ningún runtime específico. La manipulación de estados se delega mediante inyección de dependencias a través del protocolo `StateBackend` (`clone` y `advance`).

## 2. API

Módulo: `kateto.mask.state_snapshots`

### Constantes

- `MIB`: `1024 * 1024` (1048576 bytes).
- `DEFAULT_CORRECTION_WINDOW_MS`: `400.0` ms.
- `DEFAULT_PREFILL_TOKEN_BUDGET`: `5` tokens.
- `DEFAULT_PREFILL_MS_PER_TOKEN`: `0.8` ms/token (presupuesto de 4 ms / 5 tokens).
- `SNAPSHOT_COST_MIB`: `{"0.4B": 3.0, "1.5B": 12.0}` (costo combinado de ambos snapshots por agente).

### Modelos de datos y Excepciones

- `SnapshotStateError(RuntimeError)`: Excepción para violaciones de orden de ciclo de vida (ej. llamar a `begin_response` sin `begin_turn`).
- `MemoryReport(model_label, per_agent_bytes, agents, total_bytes, snapshots_per_agent=2)`: Reporte de consumo de memoria.
- `CorrectionResult(restored, within_window, replayed_tokens, estimated_ms, within_budget)`: Resultado de un intento de corrección de ASR parcial.
- `BargeInResult(state, kept_tokens, dropped_tokens, replayed_tokens)`: Resultado del corte por barge-in y reconstrucción de estado.

### Protocolos y Clases

- `StateBackend(Protocol)`:
  - `clone(state: object) -> object`
  - `advance(state: object, tokens: Sequence[int]) -> object`
- `ListStateBackend`:
  - Implementación trivial con tuplas de enteros para pruebas deterministas sin dependencias externas.
- `TurnSnapshots`:
  - `__init__(backend, *, correction_window_ms=400.0, prefill_token_budget=5, prefill_ms_per_token=0.8)`
  - `begin_turn(state) -> None`: Clona y almacena `S_turn_start`; fija el estado vivo.
  - `prefill_partial(tokens) -> object`: Prefill incremental durante el habla del usuario.
  - `correct_partial(corrected_tokens, *, at_ms) -> CorrectionResult`: Aplica corrección de ASR restaurando `S_turn_start` si `at_ms <= correction_window_ms`.
  - `begin_response() -> None`: Guarda snapshot base de generación para barge-in (`_barge_in_base`).
  - `note_emitted(token, *, audio_start_ms, audio_end_ms) -> object`: Registra ventana de audio del token emitido al TTS y avanza el estado vivo.
  - `barge_in(*, cut_ms) -> BargeInResult`: Reconstruye el estado vivo desde la base de respuesta avanzando únicamente los tokens con `audio_start_ms <= cut_ms`. Idempotente.
  - `state` (property): Retorna el estado vivo.
  - `turn_start` (property): Retorna una copia de `S_turn_start`.
  - `reset() -> None`: Limpia estados y buffers para reuso entre turnos.
- `snapshot_cost(model_label="0.4B", agents=4) -> MemoryReport`: Cálculo de consumo de memoria a partir de constantes del handoff. Lanza `ValueError` ante modelos no reconocidos.

## 3. Garantías

### Garantía de Corrección ASR (`S_turn_start`)

1. Al inicio de cada turno del usuario (`begin_turn`), se preserva un snapshot limpio `S_turn_start` mediante `clone`.
2. Si el reconocedor de voz emite una corrección dentro de la ventana (`at_ms <= 400.0` ms), el estado vivo se descarta y se reconstruye como `clone(S_turn_start) + advance(corrected_tokens)`.
3. Si la corrección llega fuera de la ventana (`at_ms > 400.0` ms), el estado vivo no se modifica y se retorna `within_window=False, restored=False`.
4. El cálculo evalúa `replayed_tokens <= prefill_token_budget` reportando `within_budget` y estimando la latencia en base al presupuesto de `0.8` ms/token, sin truncar tokens si excede el límite.

### Garantía de Interrupción / Barge-in (`S_barge_in`)

1. Cuando el modelo empieza a responder (`begin_response`), se preserva el estado del momento exacto previo a la generación.
2. Ante una interrupción del usuario por detección de VAD (`cut_ms`), el sistema nunca regresa a `S_turn_start` (lo cual causaría amnesia de lo dicho).
3. Se toman únicamente los tokens cuyo audio efectivamente comenzó a reproducirse (`audio_start_ms <= cut_ms`). Los tokens generados que aún no sonaron se descartan.
4. El estado vivo resultante se reconstruye de forma determinista e idempotente: invocar `barge_in` con el mismo `cut_ms` produce idéntico estado y conteos.

## 4. Costo de Memoria

El cálculo incluye los 2 snapshots (`S_turn_start` + `S_barge_in`) por agente:

| Modelo | Por Agente (MiB) | Por Agente (Bytes) | 4 Agentes (MiB) | 4 Agentes (Bytes) | Snapshots / Agente |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **0.4B** | 3.0 MiB | 3,145,728 B | 12.0 MiB | 12,582,912 B | 2 |
| **1.5B** | 12.0 MiB | 12,582,912 B | 48.0 MiB | 50,331,648 B | 2 |

## 5. Límites Explícitos

- Los tiempos en milisegundos (`400.0` ms de ventana, `5` tokens de presupuesto, `0.8` ms/token) corresponden a presupuestos teóricos del handoff de arquitectura (§3.4), no a mediciones empíricas en hardware con el modelo real corriendo.
- El módulo `kateto.mask.state_snapshots` es una implementación desacoplada y deliberadamente no está cableada de forma directa con `kateto/providers/rwkv_rocm.py`.
- No realiza sincronización por reloj de sistema ni concurrencia asíncrona; su lógica es pura y determinista.

## 6. Archivos

- `kateto/mask/__init__.py`: Inicialización del paquete de máscara.
- `kateto/mask/state_snapshots.py`: Implementación de snapshots, ciclo de vida de turnos, presupuesto y backend de prueba.
- `kateto/tests/test_mask_state_snapshots.py`: Suite de 13 pruebas unitarias exhaustivas con formato BDD.
- `REPORT-MASK9.md`: Este reporte.

## 7. Ejecución del Gate

Comando exacto ejecutado:

```bash
PYTHONPATH=$PWD /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin/python -m pytest \
  kateto/tests/test_mask_state_snapshots.py kateto/tests/test_audio_barge_in.py -q
```

Resultado:
- 13 pruebas nuevas en `test_mask_state_snapshots.py`: PASSED
- 22 pruebas preexistentes en `test_audio_barge_in.py`: PASSED
- Total: 35 passed en 11.34s
