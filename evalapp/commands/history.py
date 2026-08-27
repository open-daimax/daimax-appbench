"""执行历史查询命令"""

import json
import logging
import click
from pathlib import Path

logger = logging.getLogger(__name__)


@click.command('history')
@click.option('--workspace', '-w', required=True, type=click.Path(exists=True), help='工作区目录路径')
@click.option('--limit', '-n', default=20, help='显示最近N条记录')
@click.option('--json-output', is_flag=True, help='以JSON格式输出')
def history_cmd(workspace, limit, json_output):
    """查看工作区的执行历史记录"""
    workspace_dir = Path(workspace)
    runs_dir = workspace_dir / "runs"

    if not runs_dir.exists():
        click.echo("该工作区尚无执行历史记录。")
        return

    # 收集所有执行记录
    records = []
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if run_dir.is_dir() and run_dir.name != "latest" and not run_dir.is_symlink():
            record = _parse_run(run_dir)
            if record:
                records.append(record)
        if len(records) >= limit:
            break

    if json_output:
        click.echo(json.dumps(records, indent=2, ensure_ascii=False))
        return

    if not records:
        click.echo("该工作区尚无执行历史记录。")
        return

    # 表格输出
    click.echo(f"{'时间戳':<20} {'阶段':<12} {'状态':<8} {'任务数':<8} {'成功':<6} {'失败':<6}")
    click.echo("-" * 70)
    for r in records:
        status = "完成" if r.get("exit_code") == 0 else ("运行中" if r.get("exit_code") is None else "失败")
        click.echo(
            f"{r['timestamp']:<20} {r['phase']:<12} {status:<8} "
            f"{r.get('total_tasks', '-'):<8} {r.get('succeeded', '-'):<6} {r.get('failed', '-'):<6}"
        )


def _parse_run(run_dir: Path) -> dict | None:
    """解析单个执行记录"""
    record = {"timestamp": run_dir.name, "run_dir": str(run_dir)}

    # 读取 phase
    phase_file = run_dir / "phase"
    if phase_file.exists():
        record["phase"] = phase_file.read_text().strip()
    else:
        record["phase"] = "unknown"

    # 读取 command.json
    cmd_file = run_dir / "command.json"
    if cmd_file.exists():
        try:
            cmd = json.loads(cmd_file.read_text())
            record["command"] = cmd.get("command", "")
            record["started_at"] = cmd.get("started_at", "")
            record["finished_at"] = cmd.get("finished_at")
            record["exit_code"] = cmd.get("exit_code")
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("读取 command.json 失败 (path=%s): %s", cmd_file, e)

    # 读取 result_summary.json
    summary_file = run_dir / "result_summary.json"
    if summary_file.exists():
        try:
            summary = json.loads(summary_file.read_text())
            record["total_tasks"] = summary.get("total_tasks", 0)
            record["succeeded"] = summary.get("succeeded", 0)
            record["failed"] = summary.get("failed", 0)
            record["skipped"] = summary.get("skipped", 0)
            record["samples_affected"] = summary.get("samples_affected", [])
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("读取 result_summary.json 失败 (path=%s): %s", summary_file, e)

    return record
