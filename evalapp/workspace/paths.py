"""工作区内路径解析辅助函数。

多端 Expo 评测时，同一份源码（generated_projects/expo/）被多个平台共享，
而构建产物、截图、E2E 报告、稳定性日志按平台隔离存放。

核心概念：
- **Expo 共享平台组**：expo_ios / expo_android 共享 "expo" 这个基础平台标识，
  源码只生成一次到 generated_projects/expo/。
- **多 Expo 平台检测**：当工作区的 meta.json 中 platforms 数组包含 2 个及以上
  expo_* 平台时，启用共享模式。
- **向后兼容**：单平台或非 Expo 平台时，路径逻辑与改造前完全一致。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..utils.logging import get_logger

logger = get_logger(__name__)

# 所有以 "expo_" 为前缀的平台标识
EXPO_PLATFORM_PREFIX = "expo_"

# Expo 共享源码的基础目录名（generated_projects/expo/）
EXPO_SHARED_DIR = "expo"

# 已知的 Expo 派生平台 → 共享基础平台映射
EXPO_DERIVED_PLATFORMS = {"expo_ios", "expo_android", "expo_web"}


def is_expo_platform(platform: str) -> bool:
    """判断给定平台是否属于 Expo 系列。"""
    return platform.startswith(EXPO_PLATFORM_PREFIX)


def expo_shared_base(platform: str) -> str | None:
    """返回 Expo 派生平台对应的共享源码目录名。

    - expo_ios / expo_android / expo_web → "expo"
    - 非 Expo 平台 → None
    """
    if platform in EXPO_DERIVED_PLATFORMS:
        return EXPO_SHARED_DIR
    if is_expo_platform(platform):
        # 未知但以 expo_ 开头的平台，也归入共享组
        return EXPO_SHARED_DIR
    return None


def has_multiple_expo_platforms(platforms: list[str]) -> bool:
    """判断平台列表中是否包含 2 个及以上的 Expo 派生平台。"""
    expo_count = sum(1 for p in platforms if is_expo_platform(p))
    return expo_count >= 2


def load_workspace_platforms(workspace_dir: Path) -> list[str]:
    """从工作区的 meta.json 中读取 platforms 数组。"""
    meta_path = workspace_dir / "meta.json"
    if not meta_path.exists():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("platforms", []) or []
    except (json.JSONDecodeError, OSError):
        return []


def is_multi_expo_workspace(workspace_dir: Path) -> bool:
    """判断工作区是否为多 Expo 平台模式。"""
    platforms = load_workspace_platforms(workspace_dir)
    return has_multiple_expo_platforms(platforms)


def resolve_generated_project_dir(
    workspace_dir: Path,
    sample_id: str,
    platform: str,
    *,
    multi_expo: bool | None = None,
) -> Path:
    """解析代码生成的目标目录路径。

    所有 expo_* 平台无条件共享 generated_projects/expo/ 目录（Expo 为一份代码
    三端构建，不论执行计划如何拆分，源码始终放在统一的共享目录）。
    非 Expo 平台沿用 generated_projects/{platform}/ 目录。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
        platform: 目标平台。
        multi_expo: 已废弃，保留参数签名以兼容调用方，内部不再使用。

    Returns:
        源码目录的绝对路径。
    """
    base = workspace_dir / sample_id / "generated_projects"

    if is_expo_platform(platform):
        return base / EXPO_SHARED_DIR  # 始终返回 "expo" 共享目录

    return base / platform


def resolve_build_artifacts_dir(
    workspace_dir: Path,
    sample_id: str,
    platform: str,
) -> Path:
    """解析构建产物目录路径。

    多 Expo 模式：build_artifacts/{platform}/ (如 build_artifacts/expo_ios/)
    单平台模式：直接使用 generated_projects/{platform}/ 内的构建产出

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
        platform: 目标平台。

    Returns:
        构建产物目录的绝对路径。
    """
    sample_dir = workspace_dir / sample_id
    multi_expo = is_multi_expo_workspace(workspace_dir)

    if multi_expo and is_expo_platform(platform):
        return sample_dir / "build_artifacts" / platform
    # 非 Expo 或单平台：不使用独立的 build_artifacts 目录，
    # 构建产物直接在源码目录内（保持向后兼容）
    return sample_dir / "build_artifacts" / platform


def resolve_screenshots_dir(
    workspace_dir: Path,
    sample_id: str,
) -> Path:
    """解析截图目录路径。

    截图统一放在 {sample_id}/screenshots/ 下，文件名按平台区分
    （launch_expo_ios.jpg / launch_expo_android.jpg），不需要按平台建子目录。
    这与现有命名规范 `launch_{platform}.jpg` 完全兼容。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。

    Returns:
        截图目录的绝对路径。
    """
    return workspace_dir / sample_id / "screenshots"


def resolve_e2e_reports_dir(
    workspace_dir: Path,
    sample_id: str,
) -> Path:
    """解析 E2E 报告目录路径。

    E2E 报告统一放在 {sample_id}/e2e_reports/ 下，
    子目录命名已包含平台前缀（如 expo_ios_TC_LAUNCH_xxx/），
    不需要额外建平台子目录。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。

    Returns:
        E2E 报告目录的绝对路径。
    """
    return workspace_dir / sample_id / "e2e_reports"


def resolve_stability_logs_dir(
    workspace_dir: Path,
    sample_id: str,
    platform: str,
) -> Path:
    """解析稳定性日志目录路径。

    多 Expo 模式：stability_logs/{platform}/ (如 stability_logs/expo_ios/)
    单平台模式：stability_logs/{generator}/ (保持向后兼容)

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
        platform: 目标平台。

    Returns:
        稳定性日志目录的绝对路径。
    """
    sample_dir = workspace_dir / sample_id
    multi_expo = is_multi_expo_workspace(workspace_dir)

    if multi_expo and is_expo_platform(platform):
        return sample_dir / "stability_logs" / platform
    # 向后兼容：非 Expo 或单平台模式，使用原有的 {generator}/ 结构
    # 调用方需自行传入 generator_name 作为子目录
    return sample_dir / "stability_logs"
