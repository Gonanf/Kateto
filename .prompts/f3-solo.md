# Tarea acotada: F3 — Tool de agenda (schedule_event)

Repo: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/

Contexto: ya existe `kateto/plugins/executor/scheduler.py` (SchedulerPlugin) y los contratos `ScheduleRequestData`/`ScheduleResultData`/`ScheduleCancelData` en `kateto/core/event.py`. El SchedulerPlugin escucha `schedule_request` y dispara eventos.

Hacé SOLO esto:
1. En `kateto/voices/tools.py`, agregá un tool builtin `schedule_event` al `VoiceToolExecutor` (seguí el patrón de los BUILTIN_TOOLS existentes). El tool valida args (event_name requerido, delay/interval/cron opcionales, target_voice opcional, dept opcional) y emite `schedule_request` con esos datos. Devuelve el `job_id` (el scheduler responde con `schedule_result`).
2. Agregá el schema del tool en `BUILTIN_TOOLS`.
3. Gate Hermes: agregá `disable_scheduling_tools: bool = False` al executor; cuando está en True, el tool no se registra. En `kateto/voices/factory.py`, en la ruta que usa `conversation_id` (HermesProvider), seteá `disable_scheduling_tools=True` y asegurate de que no se inyecte el cronjob-MCP en `mcp_server_names`.
4. Tests en `kateto/tests/test_tools.py` (o nuevo `test_schedule_tool.py`): el tool emite `schedule_request` con los datos correctos; el flag `disable_scheduling_tools` lo deshabilita.

Usá TDD (pytest-asyncio strict). Commiteá con `feat(voices): tool schedule_event + gate Hermes (F3)`.
Corré `uv run pytest kateto/tests/test_event_bus.py kateto/tests/test_plugin_manager.py kateto/tests/test_config.py kateto/tests/test_tools.py -q` y asegurate de que pasen (ya había 29 passing en core).

No hagas nada más de M2/M3/M4. Solo F3.
