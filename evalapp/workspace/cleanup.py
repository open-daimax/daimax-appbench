"""工作区清理策略 (W-08)。

``~/eval_app_factory/`` 下的工作区只增不删，38 个样本 × 3 平台可达 1.6GB+。
本模块提供 LRU 风格的工作区清理工具，可按数量上限、时间窗口或磁盘配额清理。
仅在调用方显式触发（CLI ``evalapp cleanup`` 或定时任务）时执行，永远不会自动
删除数据。

主要 API：
* :func:`list_workspaces` —— 枚举给定 base 下所有工作区目录及其元信息（mtime、size）
* :func:`prune_workspaces` —— 按 ``keep_latest`` / ``older_than_days`` 删除旧工作区
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_DIR = Path.home() / "eval_app_factory"


@dataclass
class WorkspaceEntry:
    """单个工作区的概要信息。"""

    path: Path
    mtime: float  # 最近修改时间（epoch）
    size_bytes: int  # 占用磁盘字节数（递归累计，best-effort）

    @property
    def name(self) -> str:
        return self.path.name


def _dir_size(path: Path) -> int:
    """递归累计目录大小（字节），失败时返回 0，不抛异常。"""
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file() and not entry.is_symlink():
                    total += entry.stat().st_size
            except OSError as e:
                logger.debug("_dir_size: stat 子项失败 (path=%s): %s", entry, e)
                continue
    except OSError as e:
        logger.debug("_dir_size: rglob 目录失败 (path=%s): %s", path, e)
    return total


def list_workspaces(base_dir: Path | None = None,
                    *, with_size: bool = False) -> list[WorkspaceEntry]:
    """枚举 ``base_dir`` 下所有工作区目录。

    一个目录被视为工作区当且仅当其包含 ``meta.json``（由 ``create_meta`` 写入）。
    返回结果按 ``mtime`` 倒序（最新在前）。

    Args:
        base_dir: 工作区根，默认 ``~/eval_app_factory/``
        with_size: 是否计算磁盘占用。``False`` 时 ``size_bytes`` 固定为 0，
            可避免遍历海量目录，适合纯计数场景。
    """
    base = Path(base_dir) if base_dir else DEFAULT_BASE_DIR
    if not base.is_dir():
        return []

    entries: list[WorkspaceEntry] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if not (child / "meta.json").exists():
            # 不是工作区（可能是 archive 文件或其他目录），跳过
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        size = _dir_size(child) if with_size else 0
        entries.append(WorkspaceEntry(path=child, mtime=mtime, size_bytes=size))

    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries


def prune_workspaces(
    base_dir: Path | None = None,
    *,
    keep_latest: int | None = None,
    older_than_days: float | None = None,
    dry_run: bool = False,
) -> list[WorkspaceEntry]:
    """删除符合条件的旧工作区。

    至少必须提供 ``keep_latest`` 或 ``older_than_days`` 中的一项。两者都给出时
    取并集（任一条件命中即删除）。

    Args:
        base_dir: 工作区根，默认 ``~/eval_app_factory/``
        keep_latest: 仅保留最新的 N 个工作区（按 mtime）。
        older_than_days: 删除 mtime 早于 ``now - N 天`` 的工作区。
        dry_run: 仅返回计划删除的列表，不真正执行删除。

    Returns:
        被删除（或 ``dry_run`` 时计划删除）的 ``WorkspaceEntry`` 列表。
    """
    if keep_latest is None and older_than_days is None:
        raise ValueError(
            "prune_workspaces requires keep_latest or older_than_days"
        )

    entries = list_workspaces(base_dir)
    if not entries:
        return []

    to_remove: list[WorkspaceEntry] = []

    # 按 keep_latest 选出超额条目（已按 mtime 倒序）
    if keep_latest is not None and keep_latest >= 0:
        to_remove.extend(entries[keep_latest:])

    # 按 older_than_days 选出过期条目
    if older_than_days is not None and older_than_days > 0:
        cutoff = time.time() - older_than_days * 86400
        for entry in entries:
            if entry.mtime < cutoff and entry not in to_remove:
                to_remove.append(entry)

    if dry_run:
        for entry in to_remove:
            logger.info("[dry-run] would remove workspace: %s", entry.path)
        return to_remove

    removed: list[WorkspaceEntry] = []
    for entry in to_remove:
        try:
            shutil.rmtree(entry.path)
            removed.append(entry)
            logger.info("Removed old workspace: %s", entry.path)
        except OSError as exc:
            logger.warning("Failed to remove workspace %s: %s", entry.path, exc)
    return removed
