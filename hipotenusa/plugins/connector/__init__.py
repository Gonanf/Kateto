def create_plugins(ctx):
    from .cli import CliConnector

    return [CliConnector(settings=ctx.config.settings.cli, working_directory=ctx.config.paths.config_dir)]
