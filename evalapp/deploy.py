"""Deployment health check / repair / info subcommands.

Provides ``evalapp deploy`` commands for post-install environment maintenance.
This complements the first-time bootstrap script at ``deploy/deploy.sh``:

- ``evalapp deploy check``  — diagnose current installation, generator CLIs,
  runtime dependencies (Node/JDK/adb/Xcode) and generator artifact directories.
- ``evalapp deploy repair`` — idempotently fix what is safely fixable: create
  missing generator artifact dirs, re-install missing generator CLIs, reinstall the
  evalapp package itself in its current environment.
- ``evalapp deploy info``   — print where evalapp/python live, PATH hints.

The repair command only *reports* (not auto-installs) heavyweight runtime
dependencies (JDK / Android SDK / Xcode) to avoid polluting the host.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import click
from rich.console import Console
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

RUNTIME_TOOLS: list[tuple[str, str]] = [
    ("node", "Node.js，UI 测试依赖"),
    ("java", "JDK，Android 构建依赖"),
    ("adb", "Android SDK platform-tools"),
]

MACOS_EXTRA: list[tuple[str, str]] = [
    ("xcodebuild", "Xcode，iOS 评测依赖"),
]

GENERATOR_CLIS: dict[str, str] = {
    "claude": "claude",
}


@dataclass
class CheckResult:
    ok_items: list[str] = field(default_factory=list)
    warn_items: list[str] = field(default_factory=list)
    fail_items: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None: self.ok_items.append(msg)
    def warn(self, msg: str) -> None: self.warn_items.append(msg)
    def fail(self, msg: str) -> None: self.fail_items.append(msg)

    @property
    def healthy(self) -> bool:
        return not self.fail_items


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _version_of(cmd: str) -> str:
    path = _which(cmd)
    if not path:
        return "(not found)"
    try:
        out = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0] if text else path
    except Exception:
        return path


def _platform_name() -> str:
    s = platform.system()
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(s, s.lower())


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def run_check(generators: Iterable[str]) -> CheckResult:
    r = CheckResult()

    # Python
    pyver = sys.version_info
    if pyver >= (3, 10):
        r.ok(f"Python {pyver.major}.{pyver.minor}.{pyver.micro} ({sys.executable})")
    else:
        r.fail(f"Python 版本过低: {pyver.major}.{pyver.minor} (需要 >= 3.10)")

    # evalapp itself
    evalapp_path = _which("evalapp")
    if evalapp_path:
        r.ok(f"evalapp 入口: {evalapp_path}")
    else:
        r.warn("PATH 中未找到 evalapp 命令（当前进程已通过模块调用运行）")

    # Generator CLIs
    for g in generators:
        bin_name = GENERATOR_CLIS.get(g, g)
        if _which(bin_name):
            r.ok(f"生成系统 {g}: {_version_of(bin_name)}")
        else:
            r.warn(f"生成系统 {g} 未安装（缺少 {bin_name}）")

    # Runtime tools
    tools = list(RUNTIME_TOOLS)
    if _platform_name() == "macos":
        tools += MACOS_EXTRA
    for cmd, desc in tools:
        if _which(cmd):
            r.ok(f"运行时 {cmd}: 可用")
        else:
            r.warn(f"运行时 {cmd} 不可用（{desc}）")

    return r


def print_check(r: CheckResult) -> None:
    table = Table(title="evalapp 部署健康检查", show_lines=False)
    table.add_column("级别", style="bold", width=6)
    table.add_column("项目")
    for msg in r.ok_items:
        table.add_row("[green]OK[/green]", msg)
    for msg in r.warn_items:
        table.add_row("[yellow]WARN[/yellow]", msg)
    for msg in r.fail_items:
        table.add_row("[red]FAIL[/red]", msg)
    console.print(table)

    total = len(r.ok_items) + len(r.warn_items) + len(r.fail_items)
    console.print(
        f"\n[bold]汇总[/bold]: "
        f"[green]OK={len(r.ok_items)}[/green]  "
        f"[yellow]WARN={len(r.warn_items)}[/yellow]  "
        f"[red]FAIL={len(r.fail_items)}[/red]  "
        f"(共 {total} 项)"
    )


def run_repair(
    generators: Iterable[str],
    dry_run: bool,
    reinstall_self: bool,
) -> CheckResult:
    """Attempt idempotent fixes. Returns a CheckResult summarizing actions."""
    r = CheckResult()

    # 1. Report missing generator CLIs (evalapp does not manage their installation)
    for g in generators:
        bin_name = GENERATOR_CLIS.get(g, g)
        if not _which(bin_name):
            r.warn(f"生成系统 {g} 缺失，且 evalapp 不代管其安装，请手工处理")

    # 2. Optionally reinstall evalapp into current environment (editable)
    if reinstall_self:
        project_root = _locate_project_root()
        if project_root is None:
            r.warn("未定位到 pyproject.toml，跳过 evalapp 自身重装")
        else:
            cmd = [sys.executable, "-m", "pip", "install", "-e", str(project_root)]
            if dry_run:
                r.warn(f"[dry-run] 将执行: {' '.join(cmd)}")
            else:
                rc = subprocess.run(cmd).returncode
                if rc == 0:
                    r.ok(f"evalapp 已在当前 Python 中重新 editable 安装: {project_root}")
                else:
                    r.fail("evalapp editable 重装失败")

    # 3. Runtime tools: never auto-install, only report
    tools = list(RUNTIME_TOOLS)
    if _platform_name() == "macos":
        tools += MACOS_EXTRA
    for cmd, desc in tools:
        if not _which(cmd):
            r.warn(f"运行时 {cmd} 缺失（{desc}），请手工安装")

    return r


def _locate_project_root() -> Path | None:
    """Walk up from this file to find the directory containing pyproject.toml."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def print_info() -> None:
    table = Table(title="evalapp 部署信息", show_lines=False)
    table.add_column("项", style="cyan")
    table.add_column("值")

    table.add_row("OS", _platform_name())
    table.add_row("Python", f"{sys.version.split()[0]} ({sys.executable})")
    table.add_row("evalapp 入口", _which("evalapp") or "(PATH 中未找到)")
    table.add_row("项目根目录", str(_locate_project_root() or "(未检测到)"))

    # Where entry-point scripts would be installed
    scripts_dir = Path(sys.executable).parent
    table.add_row("脚本目录", str(scripts_dir))

    # PATH hint
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    local_bin = str(Path.home() / ".local" / "bin")
    table.add_row(
        "~/.local/bin 在 PATH",
        "是" if local_bin in path_entries else "否（建议加入）",
    )

    console.print(table)


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------

def _get_default_generators() -> list[str]:
    """Read default generators from config; empty list if not configured."""
    try:
        from .config import get_config
        cfg = get_config()
        gen = cfg.default_generator
        return [gen] if gen else []
    except Exception:
        return []


DEFAULT_GENERATORS: list[str] = []  # Resolved at runtime via _get_default_generators()


@click.group(name="deploy")
def deploy_group() -> None:
    """evalapp 部署健康检查与修复（首次安装请使用 deploy/deploy.sh）。"""


@deploy_group.command(name="info")
def deploy_info() -> None:
    """打印当前部署信息（Python、入口、脚本目录、PATH）。"""
    print_info()


@deploy_group.command(name="check")
@click.option(
    "--generators", default=None, show_default=False,
    help="要检查的生成系统（逗号分隔），空则使用 default_generator 配置",
)
def deploy_check(generators: str | None) -> None:
    """检查 evalapp 部署健康度与依赖可用性。"""
    if generators:
        gens = [g.strip() for g in generators.split(",") if g.strip()]
    else:
        gens = _get_default_generators()
    r = run_check(gens)
    print_check(r)
    if not r.healthy:
        sys.exit(1)


@deploy_group.command(name="repair")
@click.option(
    "--generators", default=None, show_default=False,
    help="要修复的生成系统（逗号分隔），空则使用 default_generator 配置",
)
@click.option(
    "--dry-run", is_flag=True, help="仅展示将要执行的动作，不实际修改",
)
@click.option(
    "--reinstall-self", is_flag=True,
    help="在当前 Python 环境中以 editable 模式重新安装 evalapp",
)
def deploy_repair(generators: str | None, dry_run: bool, reinstall_self: bool) -> None:
    """幂等修复：装生成系统 CLI、可选重装 evalapp。"""
    if generators:
        gens = [g.strip() for g in generators.split(",") if g.strip()]
    else:
        gens = _get_default_generators()
    r = run_repair(gens, dry_run=dry_run, reinstall_self=reinstall_self)
    print_check(r)
    if not r.healthy:
        sys.exit(1)
