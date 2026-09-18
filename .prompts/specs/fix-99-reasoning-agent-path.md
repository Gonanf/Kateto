# El fix de `reasoning_effort` no llega al path que el usuario usa de verdad (agent provider)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## El agujero (verificado con el runtime real, no hipótesis)
El fix anterior cableó `reasoning_effort`/`thinking` en `OpenAICompatibleProvider`
(`kateto/voices/base.py`), pero **las voces del usuario no pasan por ahí**. En
`kateto/voices/factory.py` (línea ~318), después de construir ese provider:

```python
if voice_settings.model and backend != "rwkv" and not str(voice_settings.model).endswith(".pth"):
    ...
    agent_provider = OpenAIAgentProvider(
        model=voice_settings.model, endpoint=..., api_key=...,
        max_tokens=settings.max_tokens or 4096, retries=..., timeout=..., session_headers=...,
    )                                    # <-- sin reasoning_effort ni thinking
    voice.setup_agent(agent_provider=agent_provider, tool_executor=executor)
```

Como `voice_llm.model` está seteado (caso normal) **y** la voz tiene tools/skills/MCP,
la generación la hace `kateto/providers/agent.py::OpenAIAgentProvider` (o `HermesProvider`),
y ahí `_base_kwargs` sólo manda `model`, `max_tokens`, `stream` y `extra_headers`:
**no se manda ningún parámetro de reasoning**.

Evidencia del runtime (log de hoy 13:43, repo en `912931a` = con el fix anterior):
- la request se hizo (`HTTP Request: POST http://127.0.0.1:3001/v1/chat/completions "200 OK"`),
- **no aparece** la línea nueva `[provider] reasoning_effort=... thinking=... model=...` (se loguea
  sólo desde base.py, que en este path nunca corre),
- el primer chunk llegó a los **5.25 s** con `nemotron-3.5-lightning-30b-a3b`, contra **1.85 s**
  medidos con `reasoning_effort="none"` en la misma máquina y mismo tipo de prompt.
- todas las voces tienen `thinking = false`, así que la regla esperada es mandar `"none"` y hoy no se manda.

## Fix
1. `kateto/providers/agent.py`
   - `OpenAIAgentProvider.__init__`: aceptar `reasoning_effort: str | None = None` y
     `thinking: bool | None = None`; guardarlos.
   - `_base_kwargs`: **mergear** `extra_body` (no pisarlo) con
     `reasoning_effort` usando la MISMA regla que ya existe
     (`kateto/voices/base.py::resolve_reasoning_effort` — importala, no dupliques la lógica):
     explícito gana; `thinking=False` → `"none"`; `thinking=True` → no se manda el campo.
     Cuidado: si `effort` es None, no agregues la clave ni un `extra_body` vacío.
   - Loguear una vez por instancia, mismo formato que el otro path:
     `[provider] reasoning_effort={} thinking={} model={}` (con un flag `_reasoning_logged`
     igual que en `base.py`, para no spamear por request).
   - `HermesProvider._base_kwargs` hoy hace `kwargs["extra_body"] = {"conversation_id": ...}` y
     **pisaría** lo de arriba: mergeá ambos (`{"conversation_id": ..., "reasoning_effort": ...}`)
     y tambien pasá/guardá `reasoning_effort`/`thinking` por `__init__`.
2. `kateto/voices/factory.py`: pasar `reasoning_effort=getattr(settings, "reasoning_effort", None)`
   y `thinking=settings.thinking` al construir `OpenAIAgentProvider` **y** `HermesProvider`.

## Tests (obligatorios)
- Con un cliente falso: `chat_with_tools_stream` manda `extra_body={"reasoning_effort": "none"}`
  cuando `thinking=False` y no hay knob explícito.
- `thinking=True` → el campo **no** aparece (ni `extra_body` vacío).
- `reasoning_effort="low"` explícito → se manda `low` aunque `thinking` sea False.
- `HermesProvider`: `extra_body` conserva `conversation_id` **y** suma `reasoning_effort`.
- Que `max_tokens` siga saliendo como hoy (el fix anterior ya lo cubrió: no lo rompas).
- Los tests existentes de `providers/agent` y de voces siguen verdes.

## Docs
- Actualizá el bug 110 (`110-thinking-false-no-llega-al-proveedor.md`): sigue resuelto, pero el
  camino real era el agent provider — agregá esa parte en vez de dejarlo como si ya estuviera todo.
- `known-issues.md` si hace falta.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "provider or agent or voice"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **475 passed / 3 failed** preexistentes
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Duplicar `resolve_reasoning_effort`:
  importala.
