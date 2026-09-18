# Latencia del LLM de voces: `max_tokens` capado y `thinking` que no llega al proveedor

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`
(HEAD `408015d`). Seguí ahí: ya tiene el venv con deps y un baseline de tests conocido.
**NO commitees**: dejá el diff visible.

## Contexto medido (no hipótesis — usar como intención del fix)
El usuario corre las voces contra FreeLLMAPI (`voice_llm.endpoint = http://127.0.0.1:3001/v1`, `model = "auto"`).
Su log de runtime + la traza del gateway mostraron:
- El streaming funciona: los `[llm-chunk]` llegan escalonados y el TTS arranca en el primer chunk.
- El TTFT se va en el modelo que elige el router (kilo/nvidia/nemotron-3-ultra-550b a 105 s vs
  groq/openai/gpt-oss-120b a 0.8 s). Eso es del pool: **NO se toca acá**.
- `OpenAICompatibleProvider._stream` manda `model/messages/stream/max_tokens/extra_headers` y **nada** de
  reasoning.
- `settings.thinking` sólo saca la capability `Thinking()` de pydantic-ai (`factory.py:177`): aplica al path
  del agente con tools, no al path HTTP de `voice_llm` que el usuario usa.
- El gateway SÍ entiende `reasoning_effort` con valores `none|minimal|low|medium|high` (más alias
  `off|disabled|disable` → `none`), lo normaliza y lo droppea por proveedor cuando no aplica (nunca falla
  el request). Evidencia: `~/proyectos/freellmapi/server/src/lib/sampling-params.ts`
  (`REASONING_EFFORTS`, `EFFORT_ALIASES`, `EXTENDED_SAMPLING_KEYS`).

## Fix 1 — el cap silencioso de `max_tokens`
En `kateto/voices/base.py`, `OpenAICompatibleProvider._stream`:

    max_tokens=min(self.max_tokens or 256, 384) if self.max_tokens else 256

El `max_tokens` de la voz (el usuario tiene 4096) queda en **384** sin avisar.
- Usá el valor configurado tal cual; default 256 sólo cuando no está seteado. Sin cap local: el gateway ya
  clampea por proveedor ("Effective max_tokens is min(requested, provider ceiling)").
- Revisá si el mismo `384` (o un cap equivalente) reaparece en otro path del provider o del agente y unificalo.

## Fix 2 — `thinking=false` tiene que llegar al proveedor
- Nuevo knob por voz `reasoning_effort` (string: `none|minimal|low|medium|high`, aceptando los alias del
  gateway). Leelo de `VoiceSettings` de forma retrocompatible (`getattr`, extra="allow").
- Regla: si `reasoning_effort` está seteado → va tal cual. Si no está seteado y `thinking` es `False` →
  `"none"`. Si `thinking` es `True` → no se manda (que decida el modelo).
- Mandalo por `extra_body={"reasoning_effort": <valor>}` en el `client.chat.completions.create(...)` (el SDK
  rechaza kwargs desconocidos). **Mergeá con el `extra_body` existente, no lo pises.**
- Logueá una vez por spawn a nivel INFO, para que el log pruebe qué va en el cable:
  `[provider] reasoning_effort=... thinking=... model=...`
- No cambies contratos de eventos ni los defaults de las otras voces.

## Fix 3 — config
Documentá el knob en `config/defaults/config.toml` (comentado, al lado de `thinking`) y en la doc de
configuración del sitio si existe esa sección.

## Fix 4 — tests (obligatorios, con el cliente falso que ya usa la suite)
- `max_tokens` configurado en 4096 llega **verbatim** al payload (hoy llegaría 384): test que falle antes del fix.
- `max_tokens` sin configurar → 256.
- `thinking=false` sin `reasoning_effort` → `extra_body["reasoning_effort"] == "none"`.
- `thinking=true` → el campo **no** se manda.
- `reasoning_effort="low"` explícito → se manda `"low"` aunque `thinking` sea false.
- Si el path pydantic-ai con tools también construye requests, un test de que no se rompió.

## Docs
- Dos bugs nuevos con el **siguiente id libre** (verificá el máximo en `docs/src/content/docs/bugs/`):
  (a) "`max_tokens` de la voz capado silenciosamente a 384";
  (b) "`thinking=false` no llega al proveedor (no se manda reasoning_effort)".
- Actualizá la tabla de `known-issues.md` con ambos.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "voice or provider or config"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline de este worktree: **463 passed / 4 failed**
   preexistentes (`test_audio_capture::raw_int16`, `test_prompt_context::session_headers`, 2 de `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Tocar la config del usuario, los contratos de eventos, el gateway freellmapi o el router llama.
- Elegir modelos o cambiar `voice_llm.model` (es decisión del usuario).
- Subagentes/task. Commitear. Inventar verificación.
