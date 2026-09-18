# Visión: las capturas de pantalla superan el tope del sidecar y nunca se describen

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Evidencia (reproducida a mano contra el sidecar real, no hipotesis)
Hablando directo con `video-rag mcp serve` (MCP por stdio, `describe_images`):

- **Imagen chica (PNG 1x1, data-URL de ~100 bytes)** → funciona perfecto, en 16 s (el VLM se carga la
  primera vez):
  `{"result": {"content": [{"text": "El color rojo.", "type": "text"}]}}`
  ⇒ el endpoint (`http://localhost:11434/v1`) y el modelo por defecto (`LFM2.5-VL-3B`, que sí existe en
  su llama-swap) están bien. **No es un problema de red.**

- **Imagen patológica (PNG 1920x1080 con ruido, data-URL de 5809 KB)** → el sidecar la RECHAZA:
  `isError=True`, texto = `image 0 exceeds ~1.5MB data-URL cap (5948134 bytes)`

- **Imagen realista (documento/escritorio 1920x1080, PNG)** → data-URL de **88-101 KB**: muy por debajo
  del tope. O sea: en 1080p con contenido normal el tope **no** se alcanza; el caso sí aparece con
  resoluciones altas o contenido denso (foto/video/captura 4K).

En el runtime del usuario lo que se sabe con certeza es que el sidecar devolvió **un texto de error de 48
caracteres** y el plugin lo trató como descripción y la voz lo narró. **Cuál fue ese error no está
confirmado**: el plugin sólo loguea la cantidad de caracteres, no el texto (eso lo agrega fix-102).
Este brief es la **red de seguridad** para que un frame grande no vuelva a producir eso, y de paso baja el
costo del VLM (una captura 4K no aporta nada a un caption).

El tope está en el sidecar: `src/mcp.rs` (`MAX_IMAGE_DATA_URL_BYTES`, ~1.5MB por imagen, máx 8 imágenes
por llamada).

## Fix esperado
1. **Antes de mandar cada frame al sidecar, recomprimir/redimensionar para que entre en el tope.**
   En `kateto/plugins/executor/static_vision_plugin.py::_data_url` (y donde se armen los frames):
   - JPEG (o WebP) con calidad razonable y ancho máximo configurable (p.ej. 1280 px, preservando aspecto);
   - objetivo duro: el data-URL base64 resultante < 1.5 MB con margen (apuntá a < 1 MB);
   - si igual no entra, bajar calidad/escala en un segundo intento y, si no, **descartar ese frame**
     avisando en el log (nunca mandar algo que el sidecar va a rechazar).
   - Usá PIL (ya está en las deps de visión del proyecto) o lo que ya use el repo para reencodear; no
     agregues dependencias nuevas.
2. Si el config tiene un tope propio (el plugin ya no lo tiene), dejalo configurable con default sensato;
   el número del sidecar (1.5 MB) tiene que quedar documentado en el comentario.
3. Coordiná con el manejo de `isError` que ya se pidió en el brief fix-102 (un error no es una
   descripción): si el lado del cliente igual manda algo rechazado, no se narra y se loguea el motivo.
4. **Tests**:
   - Un frame sintético grande (p.ej. 1920x1080 con ruido) ⇒ el data-URL que se manda queda por debajo
     del tope y el tamaño del lado servidor no se toca (nada de recortar la imagen a la mitad).
   - La relación de aspecto se preserva y el ancho máximo se respeta.
   - Un frame chico no se agranda ni se reencoda al pedo (que no haya pérdida gratuita).
   - Si el reencode falla, el frame se descarta y se loguea (no explota la narración).
   - Los tests existentes de visión siguen verdes.

## Docs
- Bug nuevo (id siguiente) "capturas de pantalla > tope del sidecar: el describe devuelve error y la voz
  lo narra" con la evidencia de los dos casos (chica OK / grande rechazada).
- `known-issues.md` + `plugins/vision.md` (documentar el tope y el reencode).

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree tras fix-101/102: corré la suite
   y compará contra los 3 fallos preexistentes (`test_audio_capture`, 2× `test_voice_history`)
3. `git diff --stat`
4. Si podés: repetir la prueba contra el sidecar real con un frame ya reencodeado y mostrar que devuelve
   una descripción en vez del error del tope (comando en `/var/tmp/kateto-fix/probar-tope.py` como modelo;
   el binario es `/home/study/.cargo/bin/video-rag` y el config de prueba `/tmp/vr-test/config.toml`).

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Cambiar la resolución de la *captura* por sí
  sola (el ajuste va antes de mandar, no en el capture).
