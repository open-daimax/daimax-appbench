"""Reporting commands.

CLI 层职责：
- Click 参数定义和解析
- 调用 services.reporting.ReportService
- 输出格式化（Rich console 输出）

业务编排（截图/打分/HTML/稳定性写入/manifest 过滤/各类回填）已迁移至
``evalapp/services/reporting.py`` 的 ``ReportService`` 与
``evalapp/services/report_backfill.py``。
"""

import json
import webbrowser
from pathlib import Path

import click
from rich.console import Console

from ..config import Config
from ..evaluation.results.reporting import Reporter
from ..utils.json_io import read_json as _read_json
from ..utils.logging import get_logger

console = Console()
logger = get_logger(__name__)


def do_report(
    run,
    workspace_dir,
    dataset_version,
    config,
    *,
    only_export_pairs=None,
    no_open_report=False,
):
    """核心报告生成逻辑 - 供 evaluate/run/retest 调用。

    本函数为 ``ReportService.run_report`` 的薄封装，保留原有签名以维持
    既有调用方（``evaluate_cmd`` / ``run_cmd`` / ``retest_cmd``）的兼容性。

    Args:
        run: EvalRun 对象
        workspace_dir: 输出目录（Path）
        dataset_version: 数据集版本字符串
        config: Config 对象
        only_export_pairs: 可选，set[tuple[str, str]]，限定 export_e2e_reports
            只清理和导出这些 (item_token, platform_token) 对的报告。
            用于 retest 场景避免误删未重测样本的报告。
        no_open_report: 是否禁止自动打开浏览器。

    Returns:
        output_dir: Path - 报告输出目录
    """
    import os  # noqa: F401
    from ..services.reporting import ReportService
    from ..utils.env import EVALAPP_TASK_RUNNER, get_env_flag
    from ..workspace.command_history import track_command

    workspace_dir = Path(workspace_dir)
    params = {"workspace": str(workspace_dir)}

    def _run():
        svc = ReportService(workspace_dir, config)
        return svc.run_report(
            run,
            dataset_version=dataset_version,
            only_export_pairs=only_export_pairs,
            no_open_report=no_open_report,
            console=console,
        )

    if get_env_flag(EVALAPP_TASK_RUNNER):
        return _run()

    with track_command(workspace_dir, "report", params):
        return _run()


@click.command()
@click.option("--run-id", default=None, help="指定 Run ID（默认最新）")
@click.option("--compare", is_flag=True, help="对比模式（生成最新运行 HTML 报告，内置历史对比功能）")
@click.option("--output", "output_file", default=None, help="输出文件路径")
@click.option(
    "--workspace",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="工作区路径（用于重新生成汇总报告，与 --run-id 互斥）",
)
@click.option("--no-open-report", is_flag=True, help="禁止自动打开浏览器查看报告")
@click.pass_context
def report(
    ctx: click.Context,
    run_id: str | None,
    compare: bool,
    output_file: str | None,
    workspace: Path | None,
    no_open_report: bool,
) -> None:
    """生成评测报告（HTML 格式）"""
    config: Config = ctx.obj["config"]

    # Workspace mode：基于工作区现有数据重新生成汇总报告
    if workspace:
        from ..services.report_aggregator import aggregate_report
        from ..services.reporting import ReportService

        console.print("[blue]重新生成工作区汇总报告...[/blue]")
        console.print(f"  工作区: {workspace}")

        # 使用聚合器从样本数据动态聚合报告数据
        report_data = aggregate_report(workspace)
        if report_data is None:
            console.print(
                "[red]未找到任何有效的样本评分数据，无法生成报告[/red]"
            )
            return

        console.print(
            f"  [green]已从 {report_data['summary']['total_prompts']} "
            f"个样本聚合报告数据[/green]"
        )

        svc = ReportService(workspace, config)
        html_path = svc.regenerate_workspace_report(
            no_open_report=no_open_report,
            console=console,
            report_data=report_data,
        )

        if html_path is None:
            console.print("[yellow]workspace 报告重新生成失败[/yellow]")

        console.print("\n[bold green]报告生成完成![/bold green]")
        return

    # 历史评测列表模式：从 workspace 扫描历史评测记录
    workspace_root = config.eval_workspace_path
    if not workspace_root.exists():
        console.print("[red]未找到工作区目录[/red]")
        return

    from evalapp.evaluation.results.models import EvalRun

    # [DEPRECATED since v2.0] run_data.json 扫描机制已废弃，将在 v3.0 移除
    import warnings as _warnings_mod
    _warnings_mod.warn(
        "扫描 run_data.json 列举历史记录的兼容路径已废弃，将在 v3.0 移除。"
        "请迁移到新的 scores_summary.json 格式。",
        DeprecationWarning,
        stacklevel=2,
    )
    console.print(
        "[yellow]⚠️  [DEPRECATED] 正在使用已废弃的 run_data.json 扫描机制，"
        "将在 v3.0 移除。请迁移到 scores_summary.json 格式。[/yellow]"
    )
    logger.warning(
        "[DEPRECATED] 正在扫描旧格式 run_data.json 列举历史记录，"
        "此兼容路径将在 v3.0 移除。请迁移到新的 scores_summary.json 格式。"
    )

    workspace_runs: list[dict] = []
    for ws_dir in sorted(workspace_root.iterdir(), reverse=True):
        run_data_file = ws_dir / "run_data.json"
        if not run_data_file.exists():
            continue
        try:
            data = _read_json(run_data_file)
            workspace_runs.append({
                "run_id": data.get("run_id", ws_dir.name),
                "generator_name": data.get("generator_name", ""),
                "timestamp": data.get("timestamp", ""),
                "total_prompts": data.get("summary", {}).get("total_prompts", 0),
                "overall_pass_rate": data.get("summary", {}).get("overall_pass_rate", 0),
                "workspace_dir": ws_dir,
            })
        except (json.JSONDecodeError, OSError, ValueError):
            continue

    workspace_runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    reporter = Reporter()

    def _load_eval_run(ws_dir: Path) -> EvalRun | None:
        """[DEPRECATED] 从 workspace 目录加载 EvalRun 对象。将在 v3.0 移除。"""
        run_data_file = ws_dir / "run_data.json"
        if not run_data_file.exists():
            return None
        import warnings as _w
        _w.warn(
            "从 run_data.json 加载 EvalRun 的兼容路径已废弃，将在 v3.0 移除。",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "[DEPRECATED] 正在从旧格式 run_data.json 加载 EvalRun，"
            "此兼容路径将在 v3.0 移除: %s", run_data_file,
        )
        try:
            run_raw = _read_json(run_data_file)
            gen_name = run_raw.get("generator_name", "unknown")
            for pr in run_raw.get("prompt_results", []):
                pr.setdefault("prompt_id", pr.get("sample_id", ""))
                pr.setdefault("generator_name", gen_name)
            return EvalRun(**run_raw)
        except Exception:
            return None

    if compare:
        if len(workspace_runs) < 2:
            console.print("[red]至少需要两个评测记录才能进行对比[/red]")
            return
        runs_meta = workspace_runs[:5]
        runs: list[EvalRun] = []
        for meta in runs_meta:
            loaded_run = _load_eval_run(meta["workspace_dir"])
            if loaded_run:
                runs.append(loaded_run)
        if not runs:
            console.print("[red]未能加载任何评测记录[/red]")
            return
        run = runs[0]
        out_path = Path(output_file) if output_file else Path(f"report_{run.run_id}.html")
        reporter.save_html_report(run, out_path.parent)
        default_html = out_path.parent / "report.html"
        if default_html != out_path and default_html.exists():
            default_html.rename(out_path)
        console.print(f"[green]HTML 对比报告已保存到 {out_path}[/green]")
        console.print("[dim]提示：使用浏览器打开报告，通过内置的\"历史对比\"功能对比多个运行[/dim]")
        if not no_open_report and config.report.auto_open:
            html_to_open = out_path if out_path.exists() else (default_html if default_html.exists() else None)
            if html_to_open:
                webbrowser.open(f"file://{html_to_open}")
                console.print("  已在浏览器中打开报告")
    else:
        run = None
        if run_id:
            for wr in workspace_runs:
                if wr["run_id"] == run_id:
                    run = _load_eval_run(wr["workspace_dir"])
                    break
        else:
            if workspace_runs:
                run = _load_eval_run(workspace_runs[0]["workspace_dir"])
        if not run:
            console.print("[red]未找到评测记录[/red]")
            return
        out_path = Path(output_file) if output_file else Path(f"report_{run.run_id}.html")
        reporter.save_html_report(run, out_path.parent)
        default_html = out_path.parent / "report.html"
        if default_html != out_path and default_html.exists():
            default_html.rename(out_path)
        console.print(f"[green]HTML 报告已保存到 {out_path}[/green]")
        if not no_open_report and config.report.auto_open:
            html_to_open = out_path if out_path.exists() else (default_html if default_html.exists() else None)
            if html_to_open:
                webbrowser.open(f"file://{html_to_open}")
                console.print("  已在浏览器中打开报告")
