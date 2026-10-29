"""Atomic JSON persistence, extracted from evalapp.workspace._safe_io (Apache-2.0)."""
import json
import logging
import os
import tempfile
from pathlib import Path
logger = logging.getLogger(__name__)

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
