"""Artifact-direct 模式的 workspace 准备逻辑。

将用户传入的产物参数（URL/APK/.app/源码目录）转换为评测管线期望的 workspace 目录结构，
使 executor 的现有决策树能正确处理。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import click

from ..platforms import resolve_platform
from ..utils.logging import get_logger
from ..utils.paths import get_project_root
from ..workspace.paths import EXPO_SHARED_DIR, is_expo_platform

logger = get_logger(__name__)


def prepare_artifact_workspace(
    output_dir: Path,
    sample_id: str,
    *,
    url: str | None = None,
    apk: Path | None = None,
    app: Path | None = None,
    project: Path | None = None,
    target_platform: str | None = None,
) -> str:
    """准备 workspace 目录结构，返回 internal_platform。

    根据传入的产物类型，创建 executor 期望的磁盘布局：
    - url → generation.json with h5_url（命中 executor h5_url 分支）
    - apk → .package_installed marker（命中 pre-installed 分支）
    - app → .package_installed marker（命中 pre-installed 分支）
    - project → symlink 源码到 generated_projects/（命中默认 build 路径）

    target_platform 仅在 url / project 模式下生效：
    - url + target_platform="web" → resolve 为 expo_web，写入共享 expo/ 目录
    - project + target_platform → 必须提供，用于确定目标平台与目录结构
    - apk / app 模式隐式确定平台，忽略 target_platform
    """
    sample_dir = output_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    if url:
        internal_platform = resolve_platform(target_platform) if target_platform else "expo_web"
        project_dir = _resolve_project_dir(sample_dir, internal_platform)
        project_dir.mkdir(parents=True, exist_ok=True)
        # 写 generation.json with h5_url（executor 读取此字段命中 h5_url 分支）
        gen_json = sample_dir / "generation.json"
        gen_json.write_text(json.dumps({
            "h5_url": url,
            "generator": "external",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        # 同时写 .h5_url 标记文件作为兜底
        (project_dir / ".h5_url").write_text(url, encoding="utf-8")

    elif apk:
        internal_platform = "expo_android"
        project_dir = _resolve_project_dir(sample_dir, internal_platform)
        project_dir.mkdir(parents=True, exist_ok=True)
        # 写 .package_installed marker
        marker = project_dir / ".package_installed"
        marker.write_text(json.dumps({
            "apk_path": str(apk.resolve()),
            "device_id": None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    elif app:
        internal_platform = "expo_ios"
        project_dir = _resolve_project_dir(sample_dir, internal_platform)
        project_dir.mkdir(parents=True, exist_ok=True)
        # 写 .package_installed marker（executor 对 iOS 同样使用 apk_path 字段）
        marker = project_dir / ".package_installed"
        marker.write_text(json.dumps({
            "apk_path": str(app.resolve()),
            "device_id": None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    elif project:
        if not target_platform:
            raise click.UsageError("--project 模式必须指定 --platform (web/android/ios)")
        internal_platform = resolve_platform(target_platform)
        project_dir = _resolve_project_dir(sample_dir, internal_platform)
        # 创建符号链接或拷贝
        if project_dir.exists():
            shutil.rmtree(project_dir)
        try:
            os.symlink(project.resolve(), project_dir)
        except OSError:
            # 跨分区或权限不足时 fallback 到 copytree
            shutil.copytree(project, project_dir)

    else:
        raise ValueError("必须指定 --url, --apk, --app 或 --project 之一")

    # 写 meta.json
    meta_json = output_dir / "meta.json"
    meta_data: dict[str, Any] = {}
    if meta_json.exists():
        try:
            meta_data = json.loads(meta_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    platforms = set(meta_data.get("platforms", []))
    platforms.add(internal_platform)
    meta_data["platforms"] = sorted(platforms)
    meta_json.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return internal_platform


def discover_sample(sample_id: str) -> tuple[list[Path], Any]:
    """从仓库 dataset/ 目录自动发现样本定义。

    优先搜索 V2，fallback V1。

    Returns:
        (samples_dirs, matched_sample) 元组

    Raises:
        FileNotFoundError: 未找到匹配的样本
    """
    from ..benchset.samples.store import SampleStore

    dataset_root = get_project_root() / "dataset"
    if not dataset_root.is_dir():
        raise FileNotFoundError(
            f"数据集目录不存在: {dataset_root}，请确认在评测仓库根目录运行"
        )

    # 按版本优先级搜索（V2 > V1）
    version_dirs = sorted(
        [d for d in dataset_root.iterdir() if d.is_dir() and d.name.startswith("V")],
        key=lambda d: d.name,
        reverse=True,  # V2 优先
    )

    for version_dir in version_dirs:
        # 遍历版本下的所有分类目录
        for category_dir in sorted(version_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            try:
                store = SampleStore(category_dir)
                sample = store.get(sample_id)
                if sample:
                    return [category_dir], sample
            except Exception:
                continue

    raise FileNotFoundError(
        f"未找到样本 '{sample_id}'，请检查 --sample-id 或使用 --samples-dir 手动指定"
    )


def discover_and_build_tasks(
    sample_ids: list[str],
    internal_platform: str,
) -> tuple[list[Path], list[dict]]:
    """发现样本并构建 sample_platform_tasks 列表。

    Returns:
        (samples_dirs, sample_platform_tasks)
    """
    all_dirs: list[Path] = []
    tasks: list[dict] = []

    for sid in sample_ids:
        dirs, sample = discover_sample(sid)
        for d in dirs:
            if d not in all_dirs:
                all_dirs.append(d)
        tasks.append({
            "sample": sample,
            "platform": internal_platform,
            "end_case": None,
            "priority": None,
        })

    return all_dirs, tasks


def _resolve_project_dir(sample_dir: Path, internal_platform: str) -> Path:
    """解析 generated_projects 下的目标目录。

    Expo 系列平台共享 expo/ 目录，非 Expo 平台使用独立目录。
    """
    base = sample_dir / "generated_projects"
    if is_expo_platform(internal_platform):
        return base / EXPO_SHARED_DIR
    return base / internal_platform
