---
id: 120
title: "El describe de una captura real supera el timeout de 30 s del cliente MCP: la narración llega tarde y con un error de timeout"
severity: Alta
status: resolved
component: kateto/plugins/system/external_mcp.py
resolved: 2026-09-18
---

## 120. El describe de una captura real supera el timeout de 30 s del cliente MCP: la narración llega tarde y con un error de timeout

**Severidad:** Alta
**Componente:** `kateto/plugins/system/external_mcp.py`, `kateto/plugins/executor/static_vision_plugin.py`

### Descripción

El usuario reportó (textual): "se tomó 4 minutos en empezar, en vez de los 30
segundos que puse. con un error de MCP tool timed out". El job periódico sí
disparaba cada 30 s, pero el describe moría por timeout y la narración se
suprimía (`periodic narration suppressed for jane: no real description
(via=recap)`): el usuario percibía "no se ejecuta", aunque el job corría.

### Impacto

Nadie hablaba nunca: cada tick de 30 s gastaba su describe en un timeout y el
resultado era un recap silenciado. La visión periódica quedaba inútil con
capturas en resolución nativa.

### Causa

Tres capas, todas medidas (no hipótesis):

1. El cliente MCP cortaba a los 30 s, hardcodeado
   (`asyncio.wait_for(..., timeout=30.0)` en `call_tool_result`). Reproducido
   con el cliente real (`ExternalMcpClient` + binario/args del usuario):
   un frame de 8x8 responde en ~10 s, uno de 1920x1080 con texto muere a los
   30.03 s con `{"error": "MCP tool timed out: describe_images"}` (48 chars,
   el texto exacto del log del runtime).
2. El VLM (`LFM2.5-VL-3B`, Q4_K_M) procesa una imagen de pantalla a ~66 tok/s
   de prefill y una sola imagen son ~2350 tokens de visión
   (`n_tokens = 1319, progress = 0.56` en `/var/log/llama-server.log`):
   ~36 s sólo de prefill más la generación. Con 3 frames en la ventana, peor.
   El sidecar manda la captura en resolución nativa.
3. Ningún frame se recomprimía antes de mandar ni se acotaba cuántos iban por
   describe, y el primer tick pagaba además la carga del modelo en frío.

### Solución aplicada

- `call_tool_result` / `call_tool` / `try_call_tool_result` / `try_call_tool`
  aceptan `timeout` por llamada (default 30.0, sin romper a nadie). La visión
  pasa el suyo: `max(vision_timeout, 120)`, logueado en cada llamada al
  sidecar (`sending N frame(s) (... dropped over cap) with timeout Ts`).
  El timeout sigue marcando `is_error=True` (camino del bug 117 intacto).
- Recompresión antes de mandar al sidecar (PIL, sin deps nuevas): ancho
  máximo configurable (`vision_sidecar_max_width`, default 1024, aspecto
  preservado), escalera JPEG q70→55→40 y reducción de escala. El default es
  medido: 1280 px todavía da timeout (30.01 s), 1024 px tarda ~20 s y 896 px
  ~11 s (los tokens van con el área, no con los bytes). Passthrough
  byte-idéntico cuando el frame ya es chico. Lo que no entra en el tope del
  sidecar (~1.5MB) se descarta con log, nunca se manda algo que el sidecar va
  a rechazar.
- `max_frames_per_describe` (default 2, configurable): por describe viajan el
  frame más viejo y el más nuevo de la ventana (lo que muestra el cambio);
  el log del describe informa cuántos se mandaron (`frames=K/N`).
- Prewarm best-effort al arrancar la visión periódica (sólo con opt-in): un
  describe mínimo (imagen 1x1) por el link VLM configurado o el sidecar, con
  10 s de gracia para que `external_mcp.start_all()` termine. Si falla, se
  loguea y no rompe nada (sin error event, sin narración, sin excepción).

**Regresión:** `kateto/tests/test_vision_describe_timeout.py` (9 tests:
timeout configurado con piso / sobre el piso + log, recompresión de
1920x1080 válida y acotada, passthrough de frame chico, cap oldest+newest en
helpers y en el describe real, prewarm best-effort en ambos links y tarea
limpia al habilitar) + `test_call_tool_result_respects_per_call_timeout` en
`test_mcp_is_error.py`.

**Archivos:** `kateto/plugins/system/external_mcp.py`,
`kateto/plugins/executor/static_vision_plugin.py`,
`kateto/tests/test_vision_describe_timeout.py`,
`kateto/tests/test_mcp_is_error.py`,
`kateto/tests/test_vision_describe.py`, `config/defaults/config.toml`,
`docs/src/content/docs/plugins/vision.md`
