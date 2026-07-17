from .classifier import ClassifierExecutor
from .interrupt import InterruptExecutor
from .todo_list import TodoListExecutor

__all__ = ["ClassifierExecutor", "InterruptExecutor", "TodoListExecutor"]


def create_plugins(ctx):
    from .classifier import ClassifierExecutor
    from .interrupt import InterruptExecutor
    from .todo_list import TodoListExecutor

    plugins = []
    classifier_settings = ctx.config.settings.plugin.get("executor_classifier")
    if classifier_settings is not None and classifier_settings.enabled:
        plugins.append(ClassifierExecutor(classifier_settings))
    interrupt_settings = ctx.config.settings.plugin.get("executor_interrupt")
    if interrupt_settings is None or interrupt_settings.enabled:
        plugins.append(InterruptExecutor())
    todo_settings = ctx.config.settings.plugin.get("executor_todo_list")
    if todo_settings is None or todo_settings.enabled:
        plugins.append(TodoListExecutor(config_dir=ctx.config.paths.config_dir))
    return plugins
