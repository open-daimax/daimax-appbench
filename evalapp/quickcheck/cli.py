"""CLI adapter. Machine output goes to stdout; diagnostics go to stderr."""
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
import threading
import click
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from . import evaluate, replay_record
from .config import load_config

class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    url: str
    name: str | None = None
    project_id: str | None = Field(None, alias='projectId')

@click.group()
@click.option('--config', 'config_path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_context
def main(ctx, config_path):
    """Standalone first-screen evaluation for Web applications."""
    try:
        config = load_config(config_path)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        # Validation details may contain credentials; do not echo raw exceptions.
        raise click.ClickException('Invalid or unreadable QuickCheck configuration.') from exc
    ctx.obj = {'config': config, 'config_path': config_path or Path.cwd() / 'quickcheck.yaml'}

def emit(result):
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))

@main.command('evaluate')
@click.option('--url')
@click.option('--request', type=click.File('r'), help='JSON request file; use - for stdin.')
@click.option('--name')
@click.option('--project-id')
@click.option('--snapshot-id', help='Rejudge an existing snapshot; calls the model again.')
@click.option('--output', type=click.Path(path_type=Path))
@click.pass_context
def evaluate_cmd(ctx, url, request, name, project_id, snapshot_id, output):
    """Evaluate one URL and write one JSON result to stdout."""
    if (url is None) == (request is None):
        raise click.UsageError('Specify exactly one of --url or --request.')
    if request is not None and (name is not None or project_id is not None):
        raise click.UsageError('Put labels inside the JSON request when using --request.')
    try:
        data = EvaluationRequest.model_validate(json.load(request) if request else
            {'url': url, 'name': name, 'project_id': project_id})
    except (ValueError, TypeError, ValidationError) as exc:
        raise click.UsageError('Request must contain url and optional name/projectId.') from exc
    config = ctx.obj['config']
    try:
        with redirect_stdout(sys.stderr):
            result = evaluate(**data.model_dump(), settings=config.quickcheck,
                              output_dir=output or config.output_dir, snapshot_id=snapshot_id)
    except (ValueError, OSError) as exc:
        raise click.ClickException('Evaluation request or workspace is invalid.') from exc
    emit(result)
    ctx.exit({'completed': 0, 'partial': 2, 'failed': 1}.get(result['status'], 1))

@main.command('replay')
@click.argument('evaluation_id')
@click.option('--output', type=click.Path(path_type=Path))
@click.pass_context
def replay_cmd(ctx, evaluation_id, output):
    """Recompute a saved assessment without browser or model requests."""
    config = ctx.obj['config']
    try:
        result = replay_record(evaluation_id, settings=config.quickcheck,
                               output_dir=output or config.output_dir)
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException('Saved evaluation is missing or invalid.') from exc
    emit(result)
    ctx.exit(0 if result['status'] == 'completed' else 2)

@main.command('serve')
@click.option('--host')
@click.option('--port', type=click.IntRange(0, 65535))
@click.option('--output', type=click.Path(path_type=Path))
@click.option('--workers', type=click.IntRange(1, 8))
@click.option('--max-queued', type=click.IntRange(0, 100))
@click.option('--read-only-config', is_flag=True, help='Disable model configuration writes (for read-only deployments).')
@click.option('--share-host')
@click.option('--share-port', type=click.IntRange(1, 65535))
@click.pass_context
def serve_cmd(ctx, host, port, output, workers, max_queued, read_only_config, share_host, share_port):
    """Start the local demonstration UI and optional LAN entry."""
    from .web import create_server
    config = ctx.obj['config']; settings = config.quickcheck; web = settings.web
    server = create_server(settings, output or config.output_dir,
        host=host or web.host, port=web.port if port is None else port,
        workers=web.workers if workers is None else workers,
        max_queued=web.max_queued if max_queued is None else max_queued,
        config_path=None if read_only_config else ctx.obj['config_path'])
    shared = None
    try:
        lan_host = share_host or web.share_host
        if lan_host:
            shared = create_server(settings, output or config.output_dir,
                host=lan_host, port=share_port or web.share_port or server.server_address[1]+1,
                workers=server.store.workers, max_queued=server.store.max_queued,
                store=server.store, shared=True)
            threading.Thread(target=shared.serve_forever, daemon=True).start()
            click.echo(f'QuickCheck LAN: http://{lan_host}:{shared.server_address[1]}/')
        click.echo(f'QuickCheck: http://{server.server_address[0]}:{server.server_address[1]}/')
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if shared:
            shared.shutdown(); shared.server_close()
        server.server_close(); server.store.close()

if __name__ == '__main__':
    main()
