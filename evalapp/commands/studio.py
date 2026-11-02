"""Unified local evaluation console."""
from pathlib import Path
import click


@click.command('studio')
@click.option('--port', type=click.IntRange(0, 65535), default=8766, show_default=True)
@click.option('--output', type=click.Path(path_type=Path), default=None, help='Studio task history directory.')
@click.pass_context
def studio_cmd(ctx, port, output):
    """Start the unified local UI for QuickCheck and full evaluation."""
    from .quickcheck import settings_from_config
    from ..config import get_project_root
    from ..studio.web import create_server
    config = ctx.obj['config']
    project_root = get_project_root()
    config_path = str(Path(ctx.obj.get('config_path') or project_root / 'evalapp.yaml').resolve())
    server = create_server(settings_from_config(config), output or config.eval_workspace_path / 'studio',
                           project_root, config_path=config_path, port=port,
                           quickcheck_output=config.quickcheck_workspace_path)
    click.echo(f'AppBench Studio: http://127.0.0.1:{server.server_address[1]}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo('Waiting for active evaluations to finish…')
    finally:
        server.server_close()
        server.jobs.close()
        server.store.close()
