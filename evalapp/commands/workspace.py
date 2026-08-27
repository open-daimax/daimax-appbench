"""Workspace management commands."""

import click
from pathlib import Path
from rich.console import Console

from ..workspace.migrator import migrate_workspace

console = Console()


@click.command(name="migrate-workspace")
@click.option(
    "--old-workspace",
    required=True,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="旧工作区路径",
)
@click.option(
    "--new-workspace",
    required=True,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="新工作区路径（将创建）",
)
@click.pass_context
def migrate_workspace_cmd(ctx: click.Context, old_workspace: Path, new_workspace: Path) -> None:
    """将旧工作区迁移到新目录结构。"""
    console.print("[blue]开始迁移工作区...[/blue]")
    console.print(f"  旧: {old_workspace}")
    console.print(f"  新: {new_workspace}")

    stats = migrate_workspace(old_workspace, new_workspace)

    console.print("\n[bold green]迁移完成![/bold green]")
    console.print(f"  成功: {len(stats['migrated_samples'])} 个样本")
    console.print(f"  失败: {len(stats['failed_samples'])} 个样本")

    if stats['failed_samples']:
        console.print("\n[yellow]失败样本:[/yellow]")
        for failed in stats['failed_samples']:
            console.print(f"  - {failed['sample_id']}/{failed['platform']}: {failed['error']}")

    console.print(f"\n[dim]新工作区: {new_workspace}[/dim]")
