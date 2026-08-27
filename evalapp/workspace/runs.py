"""执行历史管理 - runs/ 目录。

修复要点：
* ``create_run`` / ``finish_run`` 中的 JSON 写入全部改为原子写入（W-05）。
* ``latest`` 符号链接的更新改用 ``atomic_replace_symlink``（``mkstemp`` + symlink
  + ``os.replace``），消除 ``unlink + symlink`` 两步操作之间的 broken-symlink
  时间窗口（W-11）。
* 新增 ``prune_runs`` 工具函数，提供按数量保留最新 N 次的清理策略，避免
  ``runs/`` 目录无限增长（W-08）。
"""
import json
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

from ._safe_io import atomic_replace_symlink, atomic_write_json


def create_run(workspace_dir: Path, phase: str, argv: list[str] = None) -> Path:
    """创建一个新的执行记录目录，返回路径。"""
    workspace_dir = Path(workspace_dir)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = workspace_dir / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    # 写入 phase 文件（小文件，原子语义无关紧要，但保持一致）
    (run_dir / "phase").write_text(phase)

    # 写入 command.json
    command = {
        "command": " ".join(sys.argv) if not argv else " ".join(argv),
        "argv": argv or sys.argv[1:],
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "exit_code": None,
        "environment": {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "hostname": os.uname().nodename
        }
    }
    atomic_write_json(run_dir / "command.json", command)

    # 复制当前 exec_plan.yaml 如果存在
    exec_plan = workspace_dir / "exec_plan.yaml"
    if exec_plan.exists():
        shutil.copy2(exec_plan, run_dir / "exec_plan.yaml")

    # 原子更新 latest 符号链接（避免 broken symlink 时间窗口）
    latest = workspace_dir / "runs" / "latest"
    try:
        atomic_replace_symlink(latest, ts)
    except OSError:
        # 文件系统不支持 symlink（如某些 Windows 共享盘）时降级为忽略
        pass

    return run_dir


def finish_run(run_dir: Path, exit_code: int = 0, result_summary: dict = None):
    """结束一次执行，写入结果（原子写入）并自动清理过期 runs。"""
    run_dir = Path(run_dir)
    cmd_path = run_dir / "command.json"
    if cmd_path.exists():
        cmd = json.loads(cmd_path.read_text())
        cmd["finished_at"] = datetime.now().isoformat()
        cmd["exit_code"] = exit_code
        atomic_write_json(cmd_path, cmd)

    if result_summary:
        atomic_write_json(run_dir / "result_summary.json", result_summary)

    # 运行结束后自动保留最新 50 次 run，防止 runs/ 目录无限增长（W-08）
    # run_dir 结构： {workspace_dir}/runs/{ts}，需两层 .parent 得到工作区
    workspace_dir = run_dir.parent.parent
    try:
        prune_runs(workspace_dir, keep=50)
    except OSError:
        # 清理失败不应影响主流程，静默吞掉仅限于预期的 OSError
        pass


def copy_log_to_run(run_dir: Path, log_path: Path):
    """将执行日志复制到 run 目录"""
    run_dir = Path(run_dir)
    log_path = Path(log_path)
    if log_path and log_path.exists():
        shutil.copy2(log_path, run_dir / "log.txt")


def prune_runs(workspace_dir: Path, keep: int = 50) -> list[Path]:
    """删除工作区下最旧的执行历史，仅保留最新的 ``keep`` 次。

    用于缓解 ``runs/`` 目录无限增长的问题（W-08）。``latest`` 符号链接不会
    被删除（除非它指向被淘汰的目录，此时会被自动跳过保留）。

    Args:
        workspace_dir: 工作区根目录
        keep: 保留最新的多少次执行（按目录名时间戳倒序）。``keep <= 0`` 时
            不做任何清理。

    Returns:
        被删除的 run 目录列表（已不存在的路径）。
    """
    if keep <= 0:
        return []

    runs_dir = Path(workspace_dir) / "runs"
    if not runs_dir.is_dir():
        return []

    # 仅保留以 8 位日期 + 6 位时间命名的目录，跳过 latest symlink 等
    candidates = []
    for entry in runs_dir.iterdir():
        if entry.is_symlink():
            continue
        if not entry.is_dir():
            continue
        name = entry.name
        if len(name) == 15 and name[8] == "_" and name.replace("_", "").isdigit():
            candidates.append(entry)

    # 按目录名（时间戳）倒序，最近的在前
    candidates.sort(key=lambda p: p.name, reverse=True)
    to_remove = candidates[keep:]
    removed: list[Path] = []
    for old in to_remove:
        try:
            shutil.rmtree(old)
            removed.append(old)
        except OSError:
            # 忽略单个删除失败，继续清理其他目录
            continue
    return removed
