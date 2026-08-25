from .classifier import ClassifierExecutor
from .interrupt import InterruptExecutor
from .scheduler import SchedulerPlugin
from .todo_list import TodoListExecutor
from .workflow_router import WorkflowRouter

__all__ = [
    "ClassifierExecutor",
    "InterruptExecutor",
    "SchedulerPlugin",
    "TodoListExecutor",
    "WorkflowRouter",
]


def create_plugins(ctx):
    from .classifier import ClassifierExecutor
    from .interrupt import InterruptExecutor
    from .todo_list import TodoListExecutor
    from .workflow_router import WorkflowRouter

    plugins = []
    classifier_settings = ctx.config.settings.plugin.get("executor_classifier")
    if classifier_settings is not None:
        plugins.append(ClassifierExecutor(classifier_settings))
    router_settings = ctx.config.settings.plugin.get("executor_workflow_router", classifier_settings)
    if router_settings is not None:
        plugins.append(WorkflowRouter(router_settings))
    interrupt_settings = ctx.config.settings.plugin.get("executor_interrupt")
    if interrupt_settings is None or interrupt_settings.enabled:
        plugins.append(InterruptExecutor())
    todo_settings = ctx.config.settings.plugin.get("executor_todo_list")
    if todo_settings is None or todo_settings.enabled:
        plugins.append(TodoListExecutor(config_dir=ctx.config.paths.config_dir))
    # Scheduler is the autonomy heartbeat: it fires schedule_event jobs and
    # interval triggers (process-audio) on the bus. Always-on like Interrupt.
    scheduler_settings = ctx.config.settings.plugin.get("executor_scheduler")
    if scheduler_settings is None or scheduler_settings.enabled:
        plugins.append(SchedulerPlugin())
    return plugins
