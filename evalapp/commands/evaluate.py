"""Evaluation commands.

CLI 层职责：
- Click 参数定义和解析
- 调用 services.evaluation.EvaluationService 完成业务编排
- 输出格式化（Rich console 输出）

业务编排（样本收集、生成器调用、E2E 评测、结果聚合与持久化）已迁移至
``evalapp/services/evaluation.py`` 的 ``EvaluationService``。
"""

from pathlib import Path

import click
from rich.console import Console

from ..config import Config
from ..evaluation.exec_plan.auto_plan import auto_plan_from_dir
from ..evaluation.exec_plan.store import ExecPlanStore
from ..platforms import resolve_platform
from ..services.evaluation import EvaluationService
from ..utils.logging import get_logger
from ..utils.paths import get_project_root

console = Console()
logger = get_logger(__name__)


def do_evaluate(
    workspace, samples_dirs, sample_platform_tasks, generator_name, workers, config,
    auto_uninstall=True, show_browser=False, manifest=None, wait_generate=False,
):
    """核心评测逻辑（薄封装）——委托至 ``EvaluationService.run_evaluation``。

    Args:
        wait_generate: 流水线模式，与 generate 进程并行时按样本等待生成完成。

    Returns:
        (run, dataset_version) 元组；无可评测样本时返回 (None, None)。
    """
    from ..utils.env import EVALAPP_TASK_RUNNER, get_env_flag
    from ..workspace.command_history import track_command

    params = {
        "platforms": sorted({t["platform"] for t in sample_platform_tasks}) if sample_platform_tasks else [],
        "samples": sorted({t["sample"].sample_id for t in sample_platform_tasks}) if sample_platform_tasks else [],
    }

    # 加载或创建 manifest（如果未传入）
    if manifest is None and sample_platform_tasks:
        from ..evaluation.execution_manifest import ExecutionManifest
        try:
            manifest = ExecutionManifest.load_or_create(workspace, sample_platform_tasks)
        except Exception as _me:
            logger.warning("Failed to initialize execution manifest: %s", _me)
            manifest = None

    # Recover stuck running items from previous interrupted runs
    if manifest is not None:
        # 根据当前执行计划的平台过滤，只恢复相关任务；且仅限 evaluate 阶段——
        # 流水线模式下 generate 正在另一进程执行，误恢复会把生成中样本标为失败
        current_platforms = {t["platform"] for t in sample_platform_tasks} if sample_platform_tasks else None
        recovered_count, recovered_items = manifest.recover_stuck_running_items(
            timeout_seconds=1800, platforms=current_platforms, phases={"evaluate"},
        )
        if recovered_count > 0:
            console.print(f"[yellow]⚠ 从上次中断恢复: {recovered_count} 个任务标记为失败，将重新执行[/yellow]")

    def _run():
        return EvaluationService(workspace).run_evaluation(
            samples_dirs=samples_dirs, sample_platform_tasks=sample_platform_tasks,
            generator_name=generator_name, workers=workers, config=config,
            auto_uninstall=auto_uninstall, show_browser=show_browser,
            manifest=manifest, console=console, wait_generate=wait_generate,
        )

    if get_env_flag(EVALAPP_TASK_RUNNER):
        return _run()
    with track_command(workspace, "evaluate", params):
        return _run()


def _print_run_summary(run) -> None:
    """打印评测结果摘要。"""
    s = run.summary
    console.print("\n[bold]样本评测完成[/bold]")
    console.print(f"  Run ID: {run.run_id}")
    console.print(
        f"  总通过率: {s.overall_pass_rate:.0%} "
        f"({s.total_passed}/{s.total_test_cases})"
    )
    if s.top_level_summary:
        tls = s.top_level_summary
        console.print("  [bold]顶层指标:[/bold]")
        console.print(f"    成功率: {tls.get('mean_success_rate', 0):.1f}")
        console.print(f"    功能完整性: {tls.get('mean_quality', 0):.1f}")
        console.print(f"    体验: {tls.get('mean_experience', 0):.1f}")
        console.print(f"    平均耗时: {tls.get('mean_duration_ms', 0)/1000:.1f}s")


@click.command(name="evaluate")
@click.option(
    "--workspace",
    required=False,
    default=None,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="已有工程目录路径（artifact 模式下可省略）",
)
@click.option(
    "--exec-plan",
    "exec_plan_file",
    required=False,
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="执行计划 YAML 文件路径（高级用法，与 --samples-dir 二选一）",
)
@click.option(
    "--samples-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="样本集目录（快捷模式必填，如 ./dataset/V2/beverage 或 ./dataset/V2/）",
)
@click.option("--sample-id", default=None, help="指定样本 ID（已弃用，请使用 --sample-ids）")
@click.option(
    "--sample-ids",
    default=None,
    help="指定样本ID列表，逗号分隔（默认: 执行计划中的全部样本）",
)
@click.option("--platform", type=click.Choice(["web", "android", "ios"], case_sensitive=False), default=None, help="目标平台 (web/android/ios)")
@click.option(
    "--generator",
    "generator_name",
    default=None,
    help="生成器名称（默认: 从工作区目录名推断）",
)
@click.option("--workers", type=int, default=1, show_default=True, help="并发评测线程数")
@click.option("--no-open-report", is_flag=True, help="禁止自动打开浏览器查看报告")
@click.option("--no-uninstall", is_flag=True, help="评测完成后不卸载应用")
@click.option("--show-browser", is_flag=True,
              help="显示浏览器界面（有头模式），默认无头模式")
@click.option("--wait-generate", is_flag=True,
              help="流水线模式：与 generate 进程并行时，按样本等待生成完成后立即投入评测")
@click.option("--url", default=None, help="已部署的 Web 应用 URL（直接评测，无需构建）")
@click.option(
    "--apk",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="预构建 Android APK 文件路径",
)
@click.option(
    "--app",
    "app_path",  # 避免与 Python 内置冲突
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="预构建 iOS .app 路径",
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="源码项目目录（需配合 --platform 指定目标平台）",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="评测结果输出目录（artifact 模式下默认 ./eval_output）",
)
@click.pass_context
def evaluate_cmd(
    ctx: click.Context,
    workspace: Path | None, exec_plan_file: Path | None, samples_dir: Path | None,
    sample_id: str | None, sample_ids: str | None, platform: str | None,
    generator_name: str | None, workers: int,
    no_open_report: bool, no_uninstall: bool, show_browser: bool,
    wait_generate: bool,
    url: str | None, apk: Path | None, app_path: Path | None,
    project_path: Path | None, output_dir: Path | None,
) -> None:
    """评测已有代码（不重新生成）。

    输入已有的 workspace 路径，只执行评测（E2E 测试和打分）。
    要求 workspace/{sample}/generated_projects/{platform}/ 目录已存在。

    支持三种模式：
      1. artifact-direct：直接传入 --url/--apk/--app/--project 产物（无需 workspace）
      2. 高级模式：--workspace + --exec-plan
      3. 快捷模式：--workspace + --samples-dir + --platform
    """
    from ._artifact_prep import prepare_artifact_workspace, discover_and_build_tasks

    config: Config = ctx.obj["config"]

    has_artifact = any([url, apk, app_path, project_path])

    if has_artifact:
        # ===== Artifact-Direct 模式 =====
        if workspace:
            console.print("[red]--url/--apk/--app/--project 与 --workspace 互斥，请选择一种模式[/red]")
            return
        if not sample_id and not sample_ids:
            console.print("[red]artifact 模式必须指定 --sample-id 或 --sample-ids[/red]")
            return

        output = output_dir or Path("./eval_output")
        output.mkdir(parents=True, exist_ok=True)
        workspace = output

        target_ids = [s.strip() for s in (sample_ids or sample_id).split(",") if s.strip()]

        console.print("[bold blue]评测产物[/bold blue]")
        if url:
            console.print(f"  URL: {url}")
        elif apk:
            console.print(f"  APK: {apk}")
        elif app_path:
            console.print(f"  App: {app_path}")
        elif project_path:
            console.print(f"  项目: {project_path}")
        console.print(f"  样本: {', '.join(target_ids)}")
        console.print(f"  输出: {output}\n")

        internal_platform = None
        for sid in target_ids:
            internal_platform = prepare_artifact_workspace(
                output, sid,
                url=url, apk=apk, app=app_path, project=project_path,
                target_platform=platform,
            )

        samples_dirs, sample_platform_tasks = discover_and_build_tasks(
            target_ids, internal_platform
        )

        if not sample_platform_tasks:
            console.print("[red]未找到匹配的测试样本[/red]")
            return

        generator_name = generator_name or "external"

    elif exec_plan_file is not None:
        # ===== 高级模式（Studio/内部）=====
        if not workspace:
            console.print("[red]exec-plan 模式需要 --workspace[/red]")
            return
        generator_name = generator_name or EvaluationService.infer_generator_name(workspace)

        console.print("[bold blue]评测已有代码[/bold blue]")
        console.print(f"  工作区: {workspace}")
        console.print(f"  生成器: {generator_name}")

        if sample_id and not sample_ids:
            console.print("[yellow]--sample-id 已弃用，请使用 --sample-ids 代替（逗号分隔多样本）[/yellow]")
        if sample_id and sample_ids:
            console.print("[yellow]警告: 同时指定了 --sample-id 和 --sample-ids，使用 --sample-ids[/yellow]")

        console.print(f"  执行计划: {exec_plan_file}\n")
        plan_store = ExecPlanStore(exec_plan_file, get_project_root())
        console.print(f"[dim]执行计划: {plan_store.plan_name}[/dim]")

        sample_platform_tasks = EvaluationService.collect_tasks_from_plan(
            plan_store, sample_id=sample_id, sample_ids=sample_ids, platform=resolve_platform(platform) if platform else None,
        )
        if not sample_platform_tasks:
            console.print("[red]未找到匹配的测试样本[/red]")
            return
        samples_dirs = EvaluationService.resolve_samples_dirs(plan_store, samples_dir=samples_dir)

    elif samples_dir is not None:
        # ===== 快捷模式 =====
        if not workspace:
            console.print("[red]快捷模式需要 --workspace[/red]")
            return
        generator_name = generator_name or EvaluationService.infer_generator_name(workspace)

        console.print("[bold blue]评测已有代码[/bold blue]")
        console.print(f"  工作区: {workspace}")
        console.print(f"  生成器: {generator_name}")

        if sample_id and not sample_ids:
            console.print("[yellow]--sample-id 已弃用，请使用 --sample-ids 代替（逗号分隔多样本）[/yellow]")
        if sample_id and sample_ids:
            console.print("[yellow]警告: 同时指定了 --sample-id 和 --sample-ids，使用 --sample-ids[/yellow]")

        if platform is None:
            console.print("[red]快捷模式下必须指定 --platform (web/android/ios)[/red]")
            return
        internal_platform = resolve_platform(platform)
        console.print(f"  样本目录: {samples_dir}")
        console.print(f"  目标平台: {platform} → {internal_platform}\n")
        sample_platform_tasks, samples_dirs = auto_plan_from_dir(
            samples_dir, internal_platform, sample_ids=sample_ids,
        )
        if not sample_platform_tasks:
            console.print("[red]未找到匹配的测试样本[/red]")
            return

    else:
        console.print("[red]请指定评测目标：--url/--apk/--app/--project 或 --workspace + --exec-plan 或 --samples-dir + --platform[/red]")
        return

    if not samples_dirs or not any(d.exists() for d in samples_dirs):
        console.print("[red]无法确定样本集目录，请使用 --samples-dir 指定[/red]")
        return

    run, dataset_version = do_evaluate(
        workspace, samples_dirs, sample_platform_tasks,
        generator_name, workers, config,
        auto_uninstall=not no_uninstall, show_browser=show_browser,
        wait_generate=wait_generate,
    )
    if run is None:
        return

    from .reporting import do_report
    report_dir = do_report(run, workspace, dataset_version, config, no_open_report=no_open_report)
    console.print(f"  V2 输出目录: {report_dir}")
    _print_run_summary(run)


@click.command(name="retest")
@click.option(
    "--workspace",
    required=True,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="工作区路径",
)
@click.option("--sample-id", default=None,
              help="样本ID（单样本模式，与 --platform 配合使用）")
@click.option("--sample-ids", default=None,
              help="样本ID列表，逗号分隔（多样本批量模式，自动推断平台）")
@click.option("--platform", default=None,
              type=click.Choice(["web", "android", "ios"], case_sensitive=False),
              help="目标平台 (web/android/ios)")
@click.option(
    "--exec-plan",
    "exec_plan_file",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="执行计划 YAML 文件路径（多样本模式推荐，用于推断样本集和平台）",
)
@click.option(
    "--samples-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="样本集目录（用于加载样本定义和测试用例，也可由 --exec-plan 推断）",
)
@click.option("--no-open-report", is_flag=True, help="禁止自动打开浏览器查看报告")
@click.option("--no-uninstall", is_flag=True, help="评测完成后不卸载应用")
@click.option("--show-browser", is_flag=True,
              help="显示浏览器界面（有头模式），默认无头模式")
@click.option("--test-case-ids", default=None,
              help="指定重跑的用例ID列表(逗号分隔), 如 TC002 或 TC001,TC003")
@click.pass_context
def retest_cmd(
    ctx: click.Context,
    workspace: Path, sample_id: str | None, sample_ids: str | None,
    platform: str | None, exec_plan_file: Path | None, samples_dir: Path | None,
    no_open_report: bool, no_uninstall: bool, show_browser: bool,
    test_case_ids: str | None,
) -> None:
    """对已有工作区中的指定样本重跑E2E测试，更新 sample_report.json 并重新生成报告。

    支持两种模式：
      1. 单样本模式：--sample-id + --platform
      2. 多样本批量模式：--sample-ids（自动推断平台）
    """
    config: Config = ctx.obj["config"]

    # 解析 test_case_ids
    parsed_test_case_ids: list[str] | None = None
    if test_case_ids:
        if not sample_id or sample_ids:
            console.print("[yellow]警告: --test-case-ids 仅在单样本模式(--sample-id)下生效，已忽略[/yellow]")
        else:
            parsed_test_case_ids = [tc.strip() for tc in test_case_ids.split(",") if tc.strip()]

    if not sample_id and not sample_ids:
        console.print("[red]请指定 --sample-id 或 --sample-ids[/red]")
        return
    if sample_id and not sample_ids and not platform:
        console.print("[red]单样本模式需要同时指定 --platform[/red]")
        return
    if sample_ids and sample_id:
        console.print("[yellow]警告: 同时指定了 --sample-id 和 --sample-ids，使用 --sample-ids[/yellow]")

    internal_platform = resolve_platform(platform) if platform else None

    plan_store = ExecPlanStore(exec_plan_file, get_project_root()) if exec_plan_file else None
    samples_dirs = EvaluationService.resolve_samples_dirs(plan_store, samples_dir=samples_dir)
    if not samples_dirs or not any(d.exists() for d in samples_dirs):
        console.print("[red]无法确定样本集目录，请使用 --samples-dir 或 --exec-plan 指定[/red]")
        return

    generator_name = EvaluationService.infer_generator_name(workspace, default="unknown")

    if sample_ids:
        target_ids = [s.strip() for s in sample_ids.split(",")]
        retest_pairs = EvaluationService.build_retest_pairs(
            workspace, target_ids, plan_store=plan_store,
        )
        if not retest_pairs:
            console.print("[red]未找到匹配的样本-平台组合[/red]")
            return
        console.print("[bold blue]批量重跑E2E测试[/bold blue]")
        console.print(f"  工作区: {workspace}")
        console.print(f"  样本数: {len(target_ids)}")
        console.print(f"  任务数: {len(retest_pairs)}\n")
    else:
        retest_pairs = [(sample_id, internal_platform)]  # type: ignore[arg-type]
        console.print("[bold blue]重跑E2E测试[/bold blue]")
        console.print(f"  工作区: {workspace}")
        console.print(f"  样本: {sample_id}")
        console.print(f"  平台: {platform} → {internal_platform}\n")

    eval_service = EvaluationService(workspace)
    all_results = eval_service.retest_samples(
        retest_pairs, samples_dirs, generator_name, config,
        auto_uninstall=not no_uninstall, show_browser=show_browser,
        console=console, test_case_ids=parsed_test_case_ids,
    )
    if not all_results:
        console.print("[red]没有成功执行的 retest 任务[/red]")
        return

    eval_service.regenerate_retest_report(
        all_results, samples_dirs, generator_name, config,
        no_open_report=no_open_report, console=console,
    )
