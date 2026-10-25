# REPORT — MASK-10: Durabilidad de la máscara contra fallas de conexión

## 1. Qué se implementó

Se implementó el mecanismo de durabilidad y recuperación para la máscara (`/mask`, `kateto/plugins/visual_overlay/web/mask.html`) ante desconexiones de WebSocket. El sistema almacena en un buffer circular (`TurnJournal`) los frames de audio transmitidos en el broadcast del plugin `VisualOverlayPlugin`, estampando un identificador de secuencia (`seq`) global monótono y un identificador de turno (`turn_id`).

Al desconectarse el socket cliente, el reproductor de audio no se detiene, permitiendo que el audio ya agendado continúe sonando sin interrupción. Al restablecerse la conexión, el cliente solicita mediante un mensaje de control los frames faltantes a partir del último `seq` recibido (`mask_resume`). El servidor responde con el lote retenido (`audio_resume`), el cliente deduplica y reproduce en orden los frames restantes del turno, alcanzando el frame con `final: true` sin intervención del usuario.

## 2. Protocolo

- **Estampado monótono (`seq` y `turn_id`):**
  - `seq`: entero global estrictamente monótono que inicia en 1 y se incrementa en +1 por cada frame de `audio_output`.
  - `turn_id`: entero que inicia en 1 y avanza al siguiente número en el primer frame posterior a uno con `final: true`.

- **Mensajes de control:**
  - **Cliente → Servidor (`type: 'mask_resume'`):**
    ```json
    {
      "type": "mask_resume",
      "after_seq": 7
    }
    ```
    Enviado en `onopen` si `lastSeq > 0`. Solicita todos los frames retenidos posteriores a `after_seq`.
  - **Servidor → Cliente (`event: 'audio_resume'`):**
    ```json
    {
      "event": "audio_resume",
      "type": "resume",
      "after_seq": 7,
      "gap": false,
      "turn_id": 2,
      "frames": [...]
    }
    ```
    Respuesta que contiene los frames retenidos ordenados ascendentemente, indicando si hubo descarte de frames por límites de retención (`gap: true`).

## 3. La métrica

- **Métrica:** `survived_pct`
- **Fórmula:**
  $$\text{survived\_pct} = \begin{cases} 0.0 & \text{si } \text{turns\_started} = 0 \\ \frac{100 \times \text{turns\_survived}}{\text{turns\_started}} & \text{en otro caso (redondeado a 1 decimal)} \end{cases}$$
- **Semántica:** Un turno se considera sobrevivido (`survived`) si se llega a reproducir su frame `final`, haya habido o no caídas durante su emisión. Si el socket se cae y el turno nunca recibe su frame final, cuenta como iniciado pero no sobrevivido.
- **Valor medido:** **100.0%** en la matriz de pruebas unitarias (`test_matriz_de_caidas_sobrevive_100_por_ciento` evaluado para cortes en `outage_at = 1, 2, 3, 4, 5, 6` sobre un turno de 6 frames).

## 4. La guarda

La guarda central de durabilidad radica en que al dispararse `ws.onclose`, el cliente **NO** invoca `player.stop()` ni resetea el avatar. El buffer de audio PCM ya programado en el Web Audio Context continúa su reproducción fluida mientras el socket reintenta la reconexión exponencialmente. Al reabrirse el socket (`onopen`), el cliente emite de inmediato `mask_resume`, el servidor devuelve los frames emitidos durante la caída y el cliente los entrega a `onAudioOutput`, agendándolos en el reproductor antes de que se agote el buffer sonoro.

## 5. Límites explícitos

- El journal es **en memoria**: si el proceso del harness reinicia, se pierde el turno en curso.
- La retención es finita (`512` frames / `4 MiB`): una caída más larga que la ventana pierde frames viejos y `resume` lo reporta con `gap: true`.
- La reanudación garantiza **que los frames se reproducen**, no sincronía muestra-a-muestra (los replayed se agendan al llegar).
- La métrica está medida en la matriz de tests, no con una caída real de red sobre hardware.

## 6. Salida LITERAL de los Gates

### Gate 1 (Python / pytest)
Comando:
`PYTHONPATH=$PWD /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin/python -m pytest kateto/tests/test_mask_turn_durability.py kateto/tests/test_mask_audio_bridge.py kateto/tests/test_mask_page.py kateto/tests/test_mask_state_snapshots.py -q`

Salida:
```
...............................................                          [100%]
=============================== warnings summary ===============================
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:1488: DeprecationWarning: `torch.jit.script` is deprecated. Please switch to `torch.compile` or `torch.export`.
    warnings.warn(

../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:365
../../../../../../home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:365
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/torch/jit/_script.py:365: DeprecationWarning: `torch.jit.script_method` is deprecated. Please switch to `torch.compile` or `torch.export`.
    warnings.warn(

kateto/tests/test_mask_audio_bridge.py::test_end_to_end_websocket_roundtrip
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/websockets/legacy/__init__.py:6: DeprecationWarning: websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html for upgrade instructions
    warnings.warn(  # deprecated in 14.0 - 2024-11-09

kateto/tests/test_mask_audio_bridge.py::test_end_to_end_websocket_roundtrip
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/uvicorn/protocols/websockets/websockets_impl.py:40: UvicornDeprecationWarning: The `websockets` implementation is deprecated, and `--ws websockets` will point at the `websockets-sansio` implementation in a future release. Use `--ws websockets-sansio` or `--ws auto` to switch now.
    warnings.warn(

kateto/tests/test_mask_audio_bridge.py::test_end_to_end_websocket_roundtrip
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/lib/python3.12/site-packages/websockets/legacy/server.py:1178: DeprecationWarning: remove second argument of ws_handler
    warnings.warn("remove second argument of ws_handler", DeprecationWarning)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
47 passed, 10 warnings in 3.94s
```
*(Nota sobre conteo: 29 baseline + 12 tests unitarios + 6 casos parametrizados de `test_matriz_de_caidas_sobrevive_100_por_ciento` = 47 passed).*

### Gate 2 (Node.js / node:test)
Comando:
`node --test kateto/plugins/visual_overlay/web/mask-durability.test.mjs kateto/plugins/visual_overlay/web/kateto-offline.test.mjs kateto/plugins/visual_overlay/web/mask-viseme-bridge.test.mjs`

Salida:
```
▶ reduceOffline
  ✔ reduceOffline: un ws_close incrementa failures y sigue online (4.784422ms)
  ✔ reduceOffline: el tercer ws_close consecutivo entra en offline (0.305379ms)
  ✔ reduceOffline: un ws_open resetea failures y sale de offline (0.25661ms)
  ✔ reduceOffline: no muta el estado de entrada (1.096554ms)
✔ reduceOffline (8.319267ms)
▶ createOfflineShell
  ✔ createOfflineShell: speak usa es-AR y devuelve true (0.370175ms)
  ✔ createOfflineShell: sin speechSynthesis speak devuelve false y no lanza (0.156194ms)
  ✔ createOfflineShell: update marca el badge visible solo en offline (0.331633ms)
✔ createOfflineShell (1.19529ms)
✔ primer frame: play true, lastSeq actualizado (5.323111ms)
✔ frame con seq ya visto no se reproduce (0.287639ms)
✔ salto de seq se reporta como gap y se reproduce igual (0.176223ms)
✔ frame sin seq se reproduce sin dedupear (0.167104ms)
✔ onOpen sin frames previos devuelve null (0.191867ms)
✔ onOpen tras una caida pide mask_resume con after_seq del ultimo frame (0.704893ms)
✔ acceptResume filtra lo ya reproducido y cuenta skipped (0.367787ms)
✔ onClose solo cuenta la caida: no corta el audio (0.150488ms)
✔ metricas: turnos sobrevividos y pct (0.341946ms)
✔ onTurnLost cuenta el turno sin sobrevivir (0.375635ms)
▶ mask-viseme-bridge
  ✔ 1. isVisemeMessage solo true para type:viseme (1.437655ms)
  ✔ 2. applyVisemeMessage aplica los 4 campos y devuelve true (1.144184ms)
  ✔ 3. applyVisemeMessage con type:subtitle no toca el stub (0.225565ms)
  ✔ 4. applyVisemeMessage sin setJawTransform no explota (0.208178ms)
  ✔ 5. interpola: intermedio en el primer frame y converge a -40 (1.896114ms)
  ✔ 6. firstRenderLatencyMs <= 50 con frames de 16ms (0.2502ms)
  ✔ 7. push no-viseme devuelve false y no incrementa pushes (0.161053ms)
  ✔ 8. setEyeOffset se deriva de headOffsetY; sin él no explota (0.283361ms)
  ✔ 9. start() es idempotente y stop() deja de pedir frames (0.21896ms)
  ✔ 10. null/undefined se sanéan a 0 (0.234275ms)
✔ mask-viseme-bridge (8.431677ms)
✔ reloj por defecto = performance.now() (no mezcla con Date.now) (0.326966ms)
ℹ tests 28
ℹ suites 3
ℹ pass 28
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 108.0579
```
*(Nota sobre conteo: 18 baseline + 10 nuevos = 28 tests pass).*
