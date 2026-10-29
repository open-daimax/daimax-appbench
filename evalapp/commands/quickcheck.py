"""EvalApp adapters; the synced QuickCheck engine is maintained independently."""
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from ..config import Config
import click
from ..quickcheck.config import Settings
from ..quickcheck import evaluate

@click.command('quickcheck')
@click.option('--url',required=True)
@click.option('--snapshot-id',default=None,help='Reuse a sealed snapshot from the same output workspace.')
@click.option('--name',default=None)
@click.option('--project-id','project_id',default=None)
@click.option('--output',default=None,type=click.Path(),help='Workspace directory (default: workspace_root/quickcheck).')
@click.pass_context
def quickcheck_cmd(ctx: click.Context, url: str, snapshot_id: str | None, name: str | None, project_id: str | None, output: str | Path | None) -> None:
    """Assess mobile and desktop first screens within a bounded budget."""
    config=ctx.obj['config']
    output=output or config.quickcheck_workspace_path
    settings=settings_from_config(config)
    with redirect_stdout(sys.stderr):
        result=evaluate(url,name=name,project_id=project_id,settings=settings,output_dir=output,snapshot_id=snapshot_id)
    click.echo(json.dumps(result,ensure_ascii=False,indent=2))


def settings_from_config(config: Config) -> Settings:
    """Adapt EvalApp configuration without overriding an explicitly selected model."""
    raw=getattr(config,'quickcheck',{}) or {}
    if hasattr(raw,'model_dump'): raw=raw.model_dump()
    raw=dict(raw)
    workflow=raw.pop('workflow','hierarchical')
    if workflow != 'hierarchical':
        raise click.ClickException('QuickCheck supports only the hierarchical workflow.')
    try:
        settings=Settings.model_validate(raw)
    except ValueError as exc:
        raise click.ClickException('Invalid QuickCheck configuration; see docs/QuickCheck.md.') from exc
    primary=getattr(config.models,'quickcheck',None)
    slot=primary if primary is not None and primary.name else config.models.aesthetics
    explicit_name=(raw.get('model') or {}).get('name')
    if not explicit_name and primary is not None and primary.name:
        settings.model.name=primary.name
    elif not settings.model.name:
        settings.model.name=slot.name
    if not settings.model.base_url:
        settings.model.base_url=slot.base_url
    if not settings.model.api_key:
        settings.model.api_key=slot.api_key
    # Interactive reviews have a two-minute end-to-end budget, including queued time.
    settings.deadline_seconds = min(settings.deadline_seconds, 120)
    settings.model_seconds = min(settings.model_seconds, 120)
    settings.readiness_seconds = min(settings.readiness_seconds, 8)
    settings.minimum_observation_seconds = min(settings.minimum_observation_seconds, 4)
    settings.sample_interval_seconds = min(settings.sample_interval_seconds, 1)
    settings.stable_samples = 2
    return settings


@click.command('quickcheck-ui')
@click.option('--host',default=None,help='Bind address (default: loopback).')
@click.option('--port',type=click.IntRange(0,65535),default=None)
@click.option('--output',default=None,type=click.Path(),help='Workspace directory (default: workspace_root/quickcheck).')
@click.option('--workers',type=click.IntRange(1,8),default=None)
@click.option('--max-queued',type=click.IntRange(0,100),default=None)
@click.option('--share-host',default=None,help='Optional LAN interface IP for a shared detection page (no model settings).')
@click.option('--share-port',type=click.IntRange(1,65535),default=None,help='Shared page port (default: local port + 1).')
@click.pass_context
def quickcheck_ui_cmd(ctx: click.Context, host: str | None, port: int | None, output: str | Path | None, workers: int | None, max_queued: int | None, share_host: str | None = None, share_port: int | None = None) -> None:
    """Open the local QuickCheck application review workspace."""
    from ..quickcheck.web import create_server
    config=ctx.obj['config'];settings=settings_from_config(config)
    output=output or config.quickcheck_workspace_path
    raw=getattr(config,'quickcheck',{}) or {}
    if hasattr(raw,'model_dump'):raw=raw.model_dump()
    web=settings.web.model_dump()
    from ..config import get_project_root
    config_path=ctx.obj.get('config_path') or str(get_project_root() / 'evalapp.yaml')
    server=create_server(settings,output,config_path=config_path,host=host or web.get('host','127.0.0.1'),
        port=port if port is not None else web.get('port',8765),
        workers=workers if workers is not None else web.get('workers',5),
        max_queued=max_queued if max_queued is not None else web.get('max_queued',4))
    address=server.server_address
    click.echo(f'QuickCheck workspace: http://{address[0]}:{address[1]}')
    shared_server=None
    lan_host=share_host or web.get('share_host')
    if lan_host:
        import threading
        try:
            shared_server=create_server(settings,output,host=lan_host,port=share_port or web.get('share_port') or address[1]+1,workers=server.store.workers,max_queued=server.store.max_queued,store=server.store,shared=True)
        except Exception:
            server.server_close();server.store.close();raise
        threading.Thread(target=shared_server.serve_forever,daemon=True).start()
        click.echo(f'QuickCheck LAN: http://{lan_host}:{shared_server.server_address[1]}/ (model settings remain local)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if shared_server:
            shared_server.shutdown();shared_server.server_close()
        server.server_close();server.store.close()
