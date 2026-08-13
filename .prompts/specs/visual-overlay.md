Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/visual-overlay (rama wt/visual-overlay). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/visual-overlay/docs/specs/2026-08-13-visual-overlay.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/docs/muppet-cutout-spec.md — spec original del usuario (con el detalle de la transformación afín, CSS y mapeo).
3. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §I — contexto.

FEATURE: Visual overlay "muppet cutout" (mandíbula continua por RMS).
- El overlay actual (kateto/plugins/visual_overlay/, HTML + Datastar v1.0.2 servido por kateto/plugins/system/http_server.py: GET /overlay + WS /ws/overlay) conmuta binario entre top.png/mouth.png. Cambiarlo a 2 capas: avatar_head.png (fija) + avatar_jaw.png (móvil), animadas por CSS transforms continuas vía Datastar.
- Backend: calcular RMS del PCM que se reproduce (mixer/player en audio_output): ventana 10-20ms, normalización con umbral de ruido clamp((rms-noise)/(peak-noise),0,1), suavizado EMA α 0.25-0.35. El RMS viaja en el payload del evento audio_output por /ws/overlay: {event:"audio_output", data:{rms, viseme?, is_speaking}}.
- Frontend: contenedor relativo, 2 <img> absolutas (head z-index 2, jaw z-index 1), transform-origin 50% 65%, data-style-transform="translateY(${jawOffsetY}px) rotate(${jawRotation}deg)" (Datastar ya aplica eso reactivo). Mapeo: rms<0.05 → 0/0; factor=clamp((rms-0.05)/0.95,0,1); jawOffsetY=factor×16; jawRotation=factor×4.5.
- Fallback: si no existen avatar_head.png/avatar_jaw.png en config/voices/{name}/, usar el par top.png/mouth.png actual.
- Constraints del usuario: las imágenes son STOCK elegidas/editadas por él (el runtime NO genera ni busca imágenes; solo consume assets de config/voices/{name}/). TTS hoy = EdgeTTS/Boson (Zonos2 después): el RMS se calcula del PCM reproducido, no del provider.

ARCHIVOS CLAVE: kateto/plugins/visual_overlay/ (plugin — verificá si tiene __init__.py con create_plugins; si no, agregarlo), kateto/plugins/system/http_server.py (GET /overlay, allowlist de assets /voices/{name}/{file}, WS /ws/overlay), kateto/plugins/audio_output/player.py (mixer — acá se reproduce el PCM: punto natural para el RMS), kateto/plugins/audio_output/zonos.py, kateto/core/event.py (AudioOutputData u otro contrato de audio_output — NO romper, extender si hace falta). El index.html actual usa Datastar v1.0.2 por CDN y un WS nativo alimenta mergePatch() (NO hay cliente WS propio en Datastar — no inventes data-on-ws-message).

CONVENCIONES:
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla. El plugin necesita enabled=true en config del usuario para activarse (el usuario ya lo tiene o lo pondrá).
- Ponytail: solución MÁS SIMPLE que funcione. No agregues libs de animación ni canvas: CSS transform + Datastar alcanzan. Simplificaciones con `# ponytail: motivo` (o comentario en HTML/CSS).
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Probá el mapeo rms→(offset,rotation) como función pura y el cálculo de RMS (ventana+EMA).

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL (levantar runtime, POST /events/send generate, ver el overlay en el browser — detallá los pasos exactos).
