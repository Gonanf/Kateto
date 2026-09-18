# Latencia: el path de pydantic tampoco manda reasoning_effort (y es el que corre)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Estado
Ya se cableó `reasoning_effort` en `OpenAICompatibleProvider` (`voices/base.py`) y en
`OpenAIAgentProvider`/`HermesProvider` (`providers/agent.py`). **Ninguno de esos dos es el camino que corre
en el runtime del usuario**: sus voces van por el **agente de pydantic-ai**
(`_pydantic_agent_loop`), que arma su propio modelo y sus settings en `kateto/voices/factory.py`:

```python
pydantic_agent = Agent(
    model=model,                                   # OpenAIChatModel + OpenAIProvider
    system_prompt=profile.system_prompt,           # (ya corregido: recibe el prompt estable)
    toolsets=[kateto_toolset.toolset],
    capabilities=capabilities,
    model_settings=ModelSettings(max_tokens=settings.max_tokens or 256),   # <-- sin reasoning
)
```

Evidencia del runtime: la línea `[provider] reasoning_effort=... thinking=... model=...` **nunca** aparece
en su log (se loguea sólo desde los otros dos providers), y el primer chunk tardó ~5 s con
`nemotron-3.5-lightning-30b-a3b` contra los **1.85 s** medidos con `reasoning_effort="none"` en la misma
máquina y con un prompt del mismo tamaño. Todas sus voces tienen `thinking = false`, así que la regla
esperada es mandar `"none"`.

## Fix
- En `factory.py`, calcular el esfuerzo con la MISMA función que ya existe
  (`kateto.voices.base::resolve_reasoning_effort`, importála — no dupliques la regla) y pasarlo por
  `extra_body` de `ModelSettings`:
  ```python
  ModelSettings(max_tokens=settings.max_tokens or 256,
                extra_body={"reasoning_effort": effort} if effort else None)
  ```
  `ModelSettings.extra_body` existe en pydantic-ai 2.26 (verificado en el venv:
  `.venv/lib/python3.12/site-packages/pydantic_ai/settings.py` → `extra_body: object`).
- Loguear **una vez** al construir el agente, para que el log lo pruebe:
  `[provider] reasoning_effort={} thinking={} model={} (pydantic)` con el mismo formato que los otros dos
  caminos.
- Si `extra_body` ya se usa para otra cosa en ese modelo/proveedor, mergeá en vez de pisar.
- No cambies `thinking` ni los defaults; la regla ya definida manda: explícito gana; `thinking=False` →
  `"none"`; `thinking=True` → no se manda el campo.

## Tests (obligatorios)
- Con `thinking=False` y sin knob explícito → los `model_settings` del agente llevan
  `extra_body={"reasoning_effort": "none"}`.
- `thinking=True` → **no** aparece la clave (ni un `extra_body` vacío).
- `reasoning_effort="low"` explícito → se manda `low` aunque `thinking` sea False.
- Se loguea una vez con el modelo y el esfuerzo (test del log).
- Los tests existentes de voces/providers siguen verdes.

## Docs
- Completar el bug 110 (`110-thinking-false-no-llega-al-proveedor.md`): ahora son **tres** caminos, y el
  que corre en el runtime es el de pydantic.
- `known-issues.md` si hace falta.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "provider or voice or pydantic"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **493 passed / 3 failed**
   preexistentes (más lo que agreguen fix-102/103; corré la suite y compará contra esos 3 fallos)
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Elegir modelos.
