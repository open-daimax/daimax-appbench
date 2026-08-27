"""从本地 dataset/ 目录提取报告页需要的样本集元数据。

Web 控制台通过 ``/api/datasets`` 系列接口取这些信息（样本集分组、中文标题、
需求描述、核心功能、测试用例定义）。这些数据全部来自评测仓的 ``dataset/``
目录，与工作区无关也与后端无关，因此本地报告在生成时直接读文件注入即可。

只注入报告里真实出现过的样本，避免把整个样本集塞进单文件报告。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ....utils.logging import get_logger
from ....utils.paths import get_project_root

logger = get_logger(__name__)

# 测试用例定义里只保留展示需要的字段，其余（page_level/functional_dimension 等）不注入
_TC_FIELDS = ("id", "name", "description", "steps", "expected_result", "priority")


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        logger.debug("读取 %s 失败: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _iter_category_dirs(dataset_root: Path):
    """遍历样本集类别目录，产出 (类别目录, 版本号)。

    目录形如 ``dataset/{V1,V2}/{category}/``；``common/`` 放的是共享模板不是类别。
    """
    for version_dir in sorted(dataset_root.iterdir()):
        if not version_dir.is_dir() or not version_dir.name.upper().startswith("V"):
            continue
        for cat_dir in sorted(version_dir.iterdir()):
            if cat_dir.is_dir() and cat_dir.name != "common":
                yield cat_dir, version_dir.name


def _load_test_case_defs(sample_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """读取 ``test_cases/test_cases_{platform}.json``，按 platform 归档。"""
    tc_dir = sample_dir / "test_cases"
    if not tc_dir.is_dir():
        return {}

    by_platform: dict[str, list[dict[str, Any]]] = {}
    for tc_file in sorted(tc_dir.glob("test_cases_*.json")):
        try:
            data = json.loads(tc_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.debug("读取 %s 失败: %s", tc_file, e)
            continue
        cases = data.get("test_cases") if isinstance(data, dict) else None
        if not isinstance(cases, list):
            continue
        platform = tc_file.stem[len("test_cases_"):] or "default"
        by_platform[platform] = [
            {k: c[k] for k in _TC_FIELDS if k in c}
            for c in cases
            if isinstance(c, dict) and c.get("id")
        ]
    return by_platform


def build_dataset_info(sample_ids: set[str]) -> dict[str, Any]:
    """收集 sample_ids 涉及的样本集元数据。

    返回 ``{"categories": [...], "samples": {...}, "test_cases": {...}}``，
    结构对齐报告页消费方式；dataset/ 缺失时返回空结构（报告页自行降级）。
    """
    empty: dict[str, Any] = {"categories": [], "samples": {}, "test_cases": {}}
    if not sample_ids:
        return empty

    dataset_root = get_project_root() / "dataset"
    if not dataset_root.is_dir():
        logger.debug("dataset 目录不存在: %s", dataset_root)
        return empty

    categories: list[dict[str, Any]] = []
    samples: dict[str, Any] = {}
    test_cases: dict[str, Any] = {}

    for cat_dir, version in _iter_category_dirs(dataset_root):
        index = _load_yaml(cat_dir / "index.yaml") or {}
        listed = [s for s in (index.get("samples_index") or []) if isinstance(s, str)]
        # 无 index.yaml 时退化为按子目录枚举，保证新增样本集也能归组
        if not listed:
            listed = [d.name for d in sorted(cat_dir.iterdir()) if (d / "sample.yaml").is_file()]

        cat_samples: list[dict[str, str]] = []
        for name in listed:
            if name not in sample_ids:
                continue
            meta = _load_yaml(cat_dir / name / "sample.yaml") or {}
            sample_id = meta.get("sample_id") or name
            title = meta.get("title") or sample_id
            cat_samples.append({"sample_id": sample_id, "title": title})
            samples[sample_id] = {
                "title": title,
                "app_type": meta.get("app_type") or "",
                "requirement": meta.get("requirement") or "",
                "core_functions": meta.get("core_functions") or [],
                "constraints": meta.get("constraints") or [],
            }
            defs = _load_test_case_defs(cat_dir / name)
            if defs:
                test_cases[sample_id] = defs

        if cat_samples:
            categories.append({
                "id": cat_dir.name,
                "name": index.get("name") or cat_dir.name,
                "dataset_version": index.get("dataset_version") or version,
                "samples": cat_samples,
            })

    return {"categories": categories, "samples": samples, "test_cases": test_cases}


def build_dataset_info_for_report(report_data: dict) -> dict[str, Any]:
    """按报告数据里出现的样本（含被排除样本）收集样本集元数据。"""
    sample_ids = {
        sr.get("sample_id")
        for sr in report_data.get("sample_results", [])
        if sr.get("sample_id")
    }
    for ex in report_data.get("excluded_samples", []) or []:
        if isinstance(ex, dict) and ex.get("sample_id"):
            sample_ids.add(ex["sample_id"])
    return build_dataset_info(sample_ids)
