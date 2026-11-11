def create_plugins(ctx):
    from .backlog import BacklogOwner

    return [BacklogOwner(backlog_path=ctx.config.paths.config_dir / "product_backlog.json")]
