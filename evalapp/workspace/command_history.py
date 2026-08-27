"""工作区指令历史存储管理。

并发安全设计（修复 W-03 / W-04）：
* 所有 load → modify → save 操作位于 ``file_lock`` 临界区，避免多进程/多线程并发
  写入造成数据丢失。
* command_id 使用 ``cmd_{ts}_{pid}_{uuid4_hex8}`` 格式，叠加进程 PID 和 32-bit
  随机数，把同秒内的碰撞概率降低到 1e-10 量级，覆盖 evalapp.web 多任务并发场景。
* 写入采用 ``atomic_write_json``（写临时文件 + os.replace）保证崩溃时数据不损坏。
"""
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..utils.logging import get_logger
from ._safe_io import atomic_write_json, file_lock

logger = get_logger(__name__)

COMMAND_HISTORY_FILE = "command_history.json"
COMMAND_HISTORY_LOCK = ".command_history.lock"


def _generate_command_id() -> str:
    """生成唯一的 command_id，格式: ``cmd_{timestamp}_{pid}_{uuid8}``。

    旧格式 ``cmd_{ts}_{3 位随机数}`` 在同一秒内有 1/1000 碰撞概率；新格式叠加
    PID 与 uuid4 的前 8 位 hex（约 4.3 亿种），即使数百进程并发也难以撞号。

    保留 ``cmd_`` 前缀和时间戳片段，确保按 command_id 字典序近似按时间排序。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    suffix = uuid.uuid4().hex[:8]
    return f"cmd_{ts}_{pid}_{suffix}"


def _lock_path(workspace_dir: Path) -> Path:
    return Path(workspace_dir) / COMMAND_HISTORY_LOCK


def _load_history(workspace_dir: Path) -> dict:
    """加载 command_history.json，不存在则返回初始结构。

    调用方必须已持有 ``file_lock``，否则不能保证并发一致性。
    """
    workspace_dir = Path(workspace_dir)
    hist_file = workspace_dir / COMMAND_HISTORY_FILE
    if hist_file.exists():
        try:
            return json.loads(hist_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # 文件损坏时记录 warning，并在覆盖前备份到 .bak，保留现场供事后排查
            backup = hist_file.with_suffix(hist_file.suffix + ".bak")
            try:
                shutil.copy2(hist_file, backup)
            except OSError as copy_err:
                logger.warning(
                    "command_history.json corrupted at %s: %s; backup to %s failed: %s",
                    hist_file, exc, backup, copy_err,
                )
            else:
                logger.warning(
                    "command_history.json corrupted at %s: %s; backed up to %s",
                    hist_file, exc, backup,
                )
            # 降级为初始结构，避免阻断后续命令
            return {"workspace_id": workspace_dir.name, "commands": []}
    return {"workspace_id": workspace_dir.name, "commands": []}


def _save_history(workspace_dir: Path, data: dict):
    """原子写入 command_history.json（写临时文件 + rename）。

    并发安全契约：调用方必须已持有 ``file_lock(_lock_path(workspace_dir))``。
    所有 read-modify-write 入口（``append_command`` / ``update_command_status``）
    都已在外层临界区中调用本函数，从而保证 load→modify→save 的原子性。
    本函数本身不再额外加锁，避免在同一进程内嵌套 ``fcntl.flock`` 触发
    ``BlockingIOError`` 重试至 ``TimeoutError``。
    """
    workspace_dir = Path(workspace_dir)
    hist_file = workspace_dir / COMMAND_HISTORY_FILE
    atomic_write_json(hist_file, data)


def append_command(workspace_dir: Path, command_type: str, params: dict, task_id: str = None) -> dict:
    """追加一条新的指令记录，返回该条目。"""
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "command_id": _generate_command_id(),
        "task_id": task_id,
        "type": command_type,
        "status": "running",
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "finished_at": None,
        "duration_ms": None,
        "params": params,
        "result_summary": None,
        "error": None,
    }
    with file_lock(_lock_path(workspace_dir)):
        data = _load_history(workspace_dir)
        data["commands"].append(entry)
        _save_history(workspace_dir, data)
    return entry


def update_command_status(workspace_dir: Path, command_id: str, status: str,
                          result_summary: dict = None, error: str = None):
    """更新指令状态（在文件锁内执行 read-modify-write）。"""
    workspace_dir = Path(workspace_dir)
    with file_lock(_lock_path(workspace_dir)):
        data = _load_history(workspace_dir)
        for cmd in data["commands"]:
            if cmd["command_id"] == command_id:
                cmd["status"] = status
                cmd["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat()
                if cmd["created_at"]:
                    created = datetime.fromisoformat(cmd["created_at"])
                    finished = datetime.fromisoformat(cmd["finished_at"])
                    cmd["duration_ms"] = int((finished - created).total_seconds() * 1000)
                if result_summary:
                    cmd["result_summary"] = result_summary
                if error:
                    cmd["error"] = error[:500]
                break
        _save_history(workspace_dir, data)


def list_commands(workspace_dir: Path) -> list[dict]:
    """读取全部指令序列。"""
    # 读路径无需写锁，但为防止读到部分写入的快照，仍走 lock
    with file_lock(_lock_path(workspace_dir)):
        data = _load_history(workspace_dir)
    return data.get("commands", [])


def get_command(workspace_dir: Path, command_id: str) -> dict | None:
    """查询单条指令。"""
    with file_lock(_lock_path(workspace_dir)):
        data = _load_history(workspace_dir)
    for cmd in data["commands"]:
        if cmd["command_id"] == command_id:
            return cmd
    return None


@contextmanager
def track_command(workspace_dir: Path, command_type: str, params: dict, task_id: str = None):
    """Context manager 封装，自动记录指令开始/完成/失败"""
    entry = append_command(workspace_dir, command_type, params, task_id)
    try:
        yield entry
        update_command_status(workspace_dir, entry["command_id"], "completed")
    except Exception as e:
        update_command_status(workspace_dir, entry["command_id"], "failed", error=str(e))
        raise
