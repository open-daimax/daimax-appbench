"""工作区安全 I/O 工具：原子写入、文件锁、原子 symlink 替换。

本模块统一提供工作区模块的并发安全与崩溃安全能力，被
``command_history``、``sample_data``、``report_data``、``runs`` 等共享。

设计要点：
* ``atomic_write_text``：写临时文件后 ``os.replace`` 重命名，保证写入要么完全成功
  要么完全不可见，避免崩溃导致 JSON 文件损坏。
* ``file_lock``：跨平台进程间互斥锁。优先 ``fcntl.flock``（POSIX），降级
  ``msvcrt.locking``（Windows），最终降级为基于临时锁文件 ``O_EXCL`` 的自旋互斥，
  保证三种环境下都能提供进程级互斥能力，且零第三方依赖。
* ``atomic_replace_symlink``：先创建临时 symlink，再用 ``os.replace`` 替换，规避
  ``unlink + symlink`` 之间的 broken-symlink 时间窗口。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_HAS_FCNTL = False
_HAS_MSVCRT = False

try:  # POSIX (macOS / Linux)
    import fcntl  # type: ignore
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - 非 POSIX 平台
    pass

try:  # Windows
    import msvcrt  # type: ignore
    _HAS_MSVCRT = True
except ImportError:  # pragma: no cover - 非 Windows 平台
    pass


# 文件锁自旋重试的指数退避参数：初始 1ms，每次翻倍，上限 50ms。
# 提供低竞争下的快速获锁，同时避免高并发下 CPU 热轮询。
_LOCK_BACKOFF_INITIAL = 0.001
_LOCK_BACKOFF_MAX = 0.05


def _next_backoff(current: float) -> float:
    """计算下一轮退避间隔：翻倍但不超过 ``_LOCK_BACKOFF_MAX``。"""
    return min(current * 2, _LOCK_BACKOFF_MAX)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """原子写入文本：先写到同目录下的临时文件，成功后 ``os.replace`` 重命名。

    满足两个崩溃安全要求：
    1. 写入中途进程崩溃时，目标文件保持原内容（不会出现半截文件）。
    2. 临时文件位于同一目录，``os.replace`` 在 POSIX/NTFS 上为原子操作。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件位于同一父目录，确保 rename 跨设备不会触发 EXDEV
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as _e:
                # 部分文件系统不支持 fsync（如 tmpfs），忽略即可
                logger.debug("fsync not supported on this filesystem: %s", _e)
        os.replace(tmp_name, path)
    except Exception:
        # 任何失败都尝试清理临时文件，避免遗留垃圾
        try:
            os.unlink(tmp_name)
        except OSError as _e:
            logger.debug("_safe_io best-effort cleanup of tmp file failed: %s", _e)
        raise


def atomic_write_json(path: Path, data, *, indent: int = 2,
                      ensure_ascii: bool = False) -> None:
    """原子写入 JSON，封装 ``json.dumps`` + ``atomic_write_text``。"""
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=str)
    atomic_write_text(path, text)


@contextmanager
def file_lock(lock_path: Path, *, timeout: float = 30.0) -> Iterator[None]:
    """跨平台跨进程文件锁。

    用法::

        with file_lock(workspace / ".command_history.lock"):
            # 临界区
            ...

    Args:
        lock_path: 锁文件路径，会被自动创建。
        timeout: 等待锁的秒数上限，超时抛 ``TimeoutError``。

    Notes:
        * POSIX 平台优先使用 ``fcntl.flock`` 实现真正的进程级建议锁；
        * Windows 平台使用 ``msvcrt.locking`` 锁定首字节实现互斥；
        * 二者均不可用时，回退到基于 ``O_CREAT | O_EXCL`` 的临时锁文件
          自旋互斥，保证至少进程间的弱互斥能力；
        * fcntl/msvcrt 路径下锁文件不会被删除，避免和并发请求竞争创建/删除。
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if _HAS_FCNTL:
        yield from _fcntl_lock(lock_path, timeout)
        return

    if _HAS_MSVCRT:
        yield from _msvcrt_lock(lock_path, timeout)
        return

    # 最后兜底：基于 O_CREAT|O_EXCL 的自旋互斥
    yield from _spinfile_lock(lock_path, timeout)


def _fcntl_lock(lock_path: Path, timeout: float) -> Iterator[None]:
    """POSIX: 基于 ``fcntl.flock`` 的非阻塞自旋实现（指数退避）。"""
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        backoff = _LOCK_BACKOFF_INITIAL
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring file lock: {lock_path}"
                    )
                time.sleep(backoff)
                backoff = _next_backoff(backoff)
        yield
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError as _e:
                logger.debug("fcntl.flock LOCK_UN best-effort failed: %s", _e)
        try:
            os.close(fd)
        except OSError as _e:
            logger.debug("close lock fd best-effort failed: %s", _e)


def _msvcrt_lock(lock_path: Path, timeout: float) -> Iterator[None]:  # pragma: no cover - Windows only
    """Windows: 基于 ``msvcrt.locking`` 锁定首字节的非阻塞自旋实现。"""
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    # 确保首字节存在以便 locking 调用
    try:
        if os.fstat(fd).st_size < 1:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
    except OSError as _e:
        logger.debug("msvcrt lock prepare failed: %s", _e)

    acquired = False
    try:
        deadline = time.monotonic() + timeout
        backoff = _LOCK_BACKOFF_INITIAL
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                acquired = True
                break
            except (IOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring file lock: {lock_path}"
                    )
                time.sleep(backoff)
                backoff = _next_backoff(backoff)
        yield
    finally:
        if acquired:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            except OSError as _e:
                logger.debug("msvcrt unlock best-effort failed: %s", _e)
        try:
            os.close(fd)
        except OSError as _e:
            logger.debug("close lock fd best-effort failed: %s", _e)


def _spinfile_lock(lock_path: Path, timeout: float) -> Iterator[None]:
    """无 fcntl/msvcrt 时的兜底：基于 ``O_CREAT|O_EXCL`` 自旋创建锁文件。

    虽不如内核级 advisory lock 严格，但在不支持原生锁的环境下仍能为多进程
    提供基本互斥能力（同一台机器、同一锁路径内）。
    """
    sentinel = lock_path.with_suffix(lock_path.suffix + ".pid")
    deadline = time.monotonic() + timeout
    backoff = _LOCK_BACKOFF_INITIAL
    fd = -1
    while True:
        try:
            fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            except OSError as _e:
                logger.debug("spinfile lock pid write best-effort failed: %s", _e)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out acquiring file lock: {lock_path}"
                )
            time.sleep(backoff)
            backoff = _next_backoff(backoff)
    try:
        yield
    finally:
        try:
            if fd != -1:
                os.close(fd)
        except OSError as _e:
            logger.debug("close spinfile lock fd best-effort failed: %s", _e)
        try:
            os.unlink(sentinel)
        except OSError as _e:
            logger.debug("unlink spinfile lock sentinel best-effort failed: %s", _e)


def atomic_replace_symlink(link_path: Path, target: str) -> None:
    """原子替换 symlink：先创建临时 symlink，再 ``os.replace`` 重命名。

    避免 ``unlink + symlink`` 在两次系统调用之间出现 broken-symlink 的时间窗口。

    Args:
        link_path: 期望的 symlink 路径
        target: symlink 指向的相对/绝对路径（保持字符串以便支持相对 target）
    """
    link_path = Path(link_path)
    link_path.parent.mkdir(parents=True, exist_ok=True)

    # 同目录创建临时 symlink，避免跨设备 rename
    parent = link_path.parent
    # 使用唯一临时名
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{link_path.name}.",
        suffix=".lnktmp",
        dir=str(parent),
    )
    # mkstemp 会创建一个真实文件，需要先删除再 symlink_to
    os.close(fd)
    try:
        os.unlink(tmp_name)
    except OSError as _e:
        logger.debug("atomic symlink tmp pre-unlink best-effort failed: %s", _e)

    try:
        os.symlink(target, tmp_name)
        os.replace(tmp_name, link_path)
    except Exception:
        # 失败时清理临时 symlink
        try:
            os.unlink(tmp_name)
        except OSError as _e:
            logger.debug("atomic symlink tmp cleanup best-effort failed: %s", _e)
        raise
