"""npm registry 可达性检测与自动切换工具。

当评测机网络环境无法访问当前配置的 npm registry（如阿里内网源）
时，自动在项目目录写入 .npmrc 文件切换到公网镜像，避免 npm install
超时失败。

项目级别 .npmrc 仅影响当前项目的依赖安装，不污染全局 npm 配置。
"""

from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

from .logging import get_logger

logger = get_logger(__name__)

# 5 秒超时用于 registry 可达性检测
_REGISTRY_CHECK_TIMEOUT = 5

# fallback registry 顺序：国内镜像优先 → 官方源
FALLBACK_REGISTRIES = [
    "https://registry.npmmirror.com",
    "https://registry.npmjs.org",
]

# .npmrc 文件内容模板
_NPMRC_TEMPLATE = "registry={registry}\n"


def _is_registry_reachable(registry_url: str) -> bool:
    """检测 registry URL 是否可达（HTTP HEAD 请求，超时 5 秒）。"""
    # 确保 URL 以 / 结尾，便于拼接路径
    check_url = registry_url.rstrip("/") + "/"
    try:
        request = urllib.request.Request(check_url, method="HEAD")
        with urllib.request.urlopen(request, timeout=_REGISTRY_CHECK_TIMEOUT) as resp:
            # 任何 2xx/3xx 响应都视为可达
            return 200 <= resp.status < 400
    except Exception:
        return False


def _get_current_registry(project_dir: str | Path | None = None) -> str:
    """获取当前 npm registry 配置。

    如果指定了 project_dir，优先读取项目级别 .npmrc；
    否则读取用户级别和全局级别配置。
    """
    cmd = ["npm", "config", "get", "registry"]
    cwd = str(project_dir) if project_dir else None
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        registry = result.stdout.strip()
        # npm config get registry 可能输出 "undefined" 表示未配置
        if registry and registry != "undefined":
            return registry
    except Exception as exc:
        logger.warning("获取 npm registry 配置失败: %s", exc)

    # 回退到默认值
    return "https://registry.npmjs.org/"


def _find_reachable_fallback() -> str | None:
    """按优先顺序遍历 fallback registries，返回第一个可达的。"""
    for registry in FALLBACK_REGISTRIES:
        if _is_registry_reachable(registry):
            return registry
    return None


def _write_project_npmrc(project_dir: str | Path, registry: str) -> None:
    """在项目目录下写入 .npmrc 文件，设置项目级别 registry。"""
    npmrc_path = Path(project_dir) / ".npmrc"
    content = _NPMRC_TEMPLATE.format(registry=registry)
    npmrc_path.write_text(content, encoding="utf-8")
    logger.info("已写入项目级别 .npmrc: %s → registry=%s", npmrc_path, registry)


def ensure_npm_registry_reachable(project_dir: str | Path) -> None:
    """检测当前 npm registry 是否可达，不可达时在项目目录写入 .npmrc 切换到公网镜像。

    检测流程：
      1. 获取当前 npm registry（考虑项目级别 .npmrc）
      2. 对该 registry 发起 HTTP HEAD 请求（5 秒超时）
      3. 如果不可达，按顺序尝试 fallback registries
      4. 找到可达的 fallback 后，在 project_dir 下写入 .npmrc

    此函数应在执行 ``npm install`` **之前**调用。

    Args:
        project_dir: 项目目录路径，.npmrc 将写入该目录。
    """
    project_dir = Path(project_dir)

    # Step 1: 获取当前 registry
    current_registry = _get_current_registry(project_dir)
    logger.info("当前 npm registry: %s", current_registry)

    # Step 2: 检测可达性
    if _is_registry_reachable(current_registry):
        logger.info("npm registry 可达，无需切换: %s", current_registry)
        return

    logger.warning(
        "npm registry 不可达: %s，尝试切换到公网镜像",
        current_registry,
    )

    # Step 3: 查找可达的 fallback
    fallback = _find_reachable_fallback()
    if fallback is None:
        logger.warning(
            "所有 fallback registries 均不可达，无法自动切换；"
            "npm install 可能失败"
        )
        return

    # Step 4: 写入项目级别 .npmrc
    _write_project_npmrc(project_dir, fallback)
    logger.info("已切换 npm registry: %s → %s", current_registry, fallback)