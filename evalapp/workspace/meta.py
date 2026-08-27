"""工作区元信息管理。

修复要点：
* ``eval_version`` 不再硬编码字符串常量，而是动态读取已安装的 ``evalapp``
  包版本（``importlib.metadata``），版本升级时无需手工同步（W-12）。
* ``meta.json`` 写入改用 ``atomic_write_json`` 保证崩溃安全（W-05）。
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from ._safe_io import atomic_write_json

logger = logging.getLogger(__name__)


def _resolve_eval_version() -> str:
    """读取 evalapp 包版本作为 ``eval_version``。

    读取顺序：
    1. ``importlib.metadata.version('evalapp')`` —— 通过 pip / pyproject.toml 安装时可用
    2. ``evalapp.__version__`` —— 兜底（如果包内显式定义）
    3. 字符串 "unknown" —— 全部失败时的最终降级值

    返回示例：``"0.2.0"``。
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("evalapp")
        except PackageNotFoundError as e:
            logger.debug("evalapp 包未通过 importlib.metadata 发现，回退到下一级: %s", e)
    except ImportError as e:
        logger.debug("importlib.metadata 不可用，回退到 __version__: %s", e)

    try:
        from .. import __version__  # type: ignore
        if isinstance(__version__, str) and __version__:
            return __version__
    except (ImportError, AttributeError):
        # 存在性探测，未定义时静默降级，无需日志
        pass

    return "unknown"


def create_meta(workspace_dir: Path, generator: str, platforms: list[str], dataset: str = None, generator_branch: str = "") -> dict:
    """创建并写入 meta.json"""
    workspace_dir = Path(workspace_dir)
    workspace_name = workspace_dir.name
    # 从目录名解析 timestamp
    ts_match = re.search(r'(\d{8}_\d{6})$', workspace_name)
    created_at = datetime.now().isoformat() if not ts_match else datetime.strptime(ts_match.group(1), '%Y%m%d_%H%M%S').isoformat()

    meta = {
        "workspace_name": workspace_name,
        "generator": generator,
        "generator_branch": generator_branch,
        "platforms": platforms,
        "dataset": dataset,
        "dataset_version": "V2",
        "created_at": created_at,
        "eval_version": _resolve_eval_version(),
    }
    workspace_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(workspace_dir / "meta.json", meta)
    return meta


def load_meta(workspace_dir: Path) -> dict | None:
    """加载 meta.json，不存在返回 None"""
    workspace_dir = Path(workspace_dir)
    meta_path = workspace_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return None
